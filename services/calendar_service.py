"""에이블 캘린더: 직접 등록한 일정과 회의에서 추출한 마감일 통합."""
import calendar
from collections import Counter
from datetime import date, datetime
from html import escape
from uuid import uuid4

MAX_EVENTS = 200


def validate_event(event):
    if not isinstance(event, dict):
        raise ValueError('일정 형식이 올바르지 않습니다.')
    title = event.get('title', '')
    day = event.get('date', '')
    time = event.get('time', '')
    note = event.get('note', '')
    event_id = event.get('id', '')
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError('일정 제목은 1~120자여야 합니다.')
    if not isinstance(day, str):
        raise ValueError('일정 날짜가 올바르지 않습니다.')
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ValueError('일정 날짜는 YYYY-MM-DD 형식이어야 합니다.')
    if time:
        if not isinstance(time, str):
            raise ValueError('시간 형식이 올바르지 않습니다.')
        try:
            datetime.strptime(time, '%H:%M')
        except ValueError:
            raise ValueError('시간은 HH:MM 형식이어야 합니다.')
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError('일정 메모는 2,000자 이하여야 합니다.')
    if not isinstance(event_id, str) or len(event_id) > 64:
        raise ValueError('일정 ID가 올바르지 않습니다.')
    return {'id': event_id or uuid4().hex, 'title': title.strip(), 'date': day,
            'time': time or '', 'note': note}


def save_event(events, event):
    clean = validate_event(event)
    result = [dict(x) for x in events if x.get('id') != clean['id']]
    if len(result) >= MAX_EVENTS:
        raise ValueError('직접 등록 일정은 최대 200건까지 저장할 수 있습니다.')
    result.append(clean)
    return sorted(result, key=lambda x: (x['date'], x['time'], x['title']))


def deadline_entries(records, current_analysis=None, current_tasks=None, active_id=None):
    """기록된 회의 업무와 현재 활성 회의의 마감일을 중복 없이 가져옵니다."""
    source = {}
    for record in records:
        source[record['id']] = (record.get('title','회의'), record.get('tasks',[]))
    if active_id and current_analysis is not None and current_tasks is not None:
        source[active_id] = (current_analysis.get('meeting_title','회의'), current_tasks)
    result = []
    for meeting_id, (meeting_title, tasks) in source.items():
        for index, task in enumerate(tasks):
            day = task.get('due_date')
            try:
                date.fromisoformat(day)
            except (ValueError, TypeError):
                continue
            result.append({'date':day, 'title':str(task.get('title','업무')),
                'kind':'deadline','status':task.get('status','미시작'),
                'meeting':meeting_title,'owner':task.get('owner',''),
                'id':f"{meeting_id}:{task.get('id',index)}"})
    return result


def entries_for_day(events, deadlines, selected):
    day = selected.isoformat() if isinstance(selected,date) else selected
    manual = [dict(x,kind='event') for x in events if x['date'] == day]
    tasks = [x for x in deadlines if x['date'] == day]
    return sorted(manual + tasks, key=lambda x:(x.get('time',''),x['title']))


def month_html(year, month, events, deadlines, today=None):
    """가벼운 비대화형 월간 달력. 세부 날짜는 Streamlit date_input으로 선택."""
    today = today or date.today()
    counts = Counter(x['date'] for x in events)
    due_counts = Counter(x['date'] for x in deadlines if x.get('status') != '완료')
    rows = calendar.Calendar(firstweekday=6).monthdatescalendar(year,month)
    output = ['<div class="aivle-calendar"><table><thead><tr>']
    for name in ['일','월','화','수','목','금','토']:
        output.append(f'<th>{name}</th>')
    output.append('</tr></thead><tbody>')
    for week in rows:
        output.append('<tr>')
        for day in week:
            iso = day.isoformat()
            classes = 'other' if day.month != month else ''
            if day == today:classes += ' today'
            dots = []
            if counts[iso]: dots.append(f'<span class="event-dot">일정 {counts[iso]}</span>')
            if due_counts[iso]: dots.append(f'<span class="task-dot">마감 {due_counts[iso]}</span>')
            output.append(f'<td class="{classes}"><div class="day-number">{day.day}</div>{"".join(dots)}</td>')
        output.append('</tr>')
    output.append('</tbody></table></div>')
    return ''.join(output)
