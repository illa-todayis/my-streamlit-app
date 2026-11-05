"""세션별 회의 기록 보관과 JSON 백업·복원. 서버에는 영구 저장하지 않습니다."""
import copy
import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

MAX_RECORDS = 50
MAX_IMPORT_BYTES = 4_000_000


def make_record(analysis, tasks, transcript='', record_id=None):
    if not isinstance(analysis, dict) or not isinstance(tasks, list):
        raise ValueError('회의 분석 데이터 형식이 올바르지 않습니다.')
    return {
        'id': record_id or uuid4().hex,
        'title': str(analysis.get('meeting_title') or '제목 없는 회의')[:200],
        'meeting_date': analysis.get('meeting_date'),
        'saved_at': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds'),
        'analysis': copy.deepcopy(analysis),
        'tasks': copy.deepcopy(tasks),
        'transcript': str(transcript or '')[:200000],
    }


def upsert_record(records, record, preserve_created=False):
    records = copy.deepcopy(records)
    for index, previous in enumerate(records):
        if previous['id'] == record['id']:
            if preserve_created:
                record['saved_at'] = previous['saved_at']
            records[index] = copy.deepcopy(record)
            return records[-MAX_RECORDS:]
    records.append(copy.deepcopy(record))
    return records[-MAX_RECORDS:]


def export_backup(records, messages, events=None):
    payload = {'format': 'aivle_meeting_archive', 'version': 1,
               'records': records[-MAX_RECORDS:], 'messages': messages[-20:],
               'calendar_events': (events or [])[:200]}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_backup(data, include_events=False):
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMPORT_BYTES:
        raise ValueError('4MB 이하의 유효한 JSON 백업을 선택해 주세요.')
    payload = json.loads(data.decode('utf-8-sig'))
    if not isinstance(payload, dict) or payload.get('format') != 'aivle_meeting_archive' or payload.get('version') != 1:
        raise ValueError('에이블 회의 백업 형식이 아닙니다.')
    records = payload.get('records', [])
    messages = payload.get('messages', [])
    if not isinstance(records, list) or not isinstance(messages, list) or len(records) > MAX_RECORDS or len(messages) > 20:
        raise ValueError('기록 건수가 허용 범위를 초과했습니다.')
    clean_records = []
    for record in records:
        if not isinstance(record, dict) or not all(key in record for key in ('id','title','saved_at','analysis','tasks')):
            raise ValueError('회의 기록의 필수 항목이 누락되었습니다.')
        if not isinstance(record['analysis'], dict) or not isinstance(record['tasks'], list):
            raise ValueError('회의 기록의 자료 형식이 올바르지 않습니다.')
        if not isinstance(record['id'], str) or len(record['id']) > 64 or not isinstance(record['title'], str):
            raise ValueError('회의 기록 식별자가 유효하지 않습니다.')
        if not isinstance(record['saved_at'], str) or len(record['saved_at']) > 50:
            raise ValueError('회의 날짜 형식이 잘못되었습니다.')
        clean_records.append(copy.deepcopy(record))
    clean_messages = []
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('user','assistant') or not isinstance(message.get('content'), str):
            raise ValueError('대화 기록 형식이 올바르지 않습니다.')
        clean_messages.append({'role': message['role'], 'content': message['content'][:10000]})
    from services.calendar_service import validate_event
    event_items = payload.get('calendar_events', [])
    if not isinstance(event_items, list) or len(event_items) > 200:
        raise ValueError('일정 기록 건수가 허용 범위를 초과했습니다.')
    clean_events = [validate_event(event) for event in event_items]
    if len({x['id'] for x in clean_events}) != len(clean_events):
        raise ValueError('중복된 일정 ID가 있습니다.')
    if include_events:
        return clean_records, clean_messages, clean_events
    return clean_records, clean_messages
