"""회의록 텍스트 + 화이트보드 이미지 통합 분석."""
import base64
import json
from datetime import date

from prompts.system_prompts import MEETING_INSTRUCTIONS

ANALYSIS_SCHEMA = {
    'type': 'object',
    'properties': {
        'meeting_title': {'type': 'string'},
        'meeting_date': {'type': ['string', 'null']},
        'summary': {'type': 'string'},
        'decisions': {'type': 'array', 'items': {'type': 'string'}},
        'pending': {'type': 'array', 'items': {'type': 'string'}},
        'conflicts': {'type': 'array', 'items': {'type': 'string'}},
        'tasks': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'owner': {'type': 'string'},
                'description': {'type': 'string'},
                'due_date': {'type': ['string', 'null']},
                'importance': {'type': 'integer'},
                'is_dependency': {'type': 'boolean'},
                'source_notes': {'type': 'string'},
            },
            'required': ['title', 'owner', 'description', 'due_date', 'importance', 'is_dependency', 'source_notes'],
            'additionalProperties': False,
        }},
    },
    'required': ['meeting_title', 'meeting_date', 'summary', 'decisions', 'pending', 'conflicts', 'tasks'],
    'additionalProperties': False,
}


def analyze_meeting(client, model, meeting_text='', image_bytes=None, image_mime=None):
    """TXT·회의 음성 전사·화이트보드를 선택적으로 함께 분석합니다."""
    if not (meeting_text or '').strip() and not image_bytes:
        raise ValueError('회의록, 회의 녹음 또는 화이트보드 중 한 가지 이상 필요합니다.')
    content = [{'type': 'input_text', 'text': (
        f'오늘 날짜: {date.today().isoformat()}\n'
        '아래 회의록/녹음 전사와 화이트보드 자료를 종합 분석하세요. '
        '녹음 전사에는 음성 인식 오류가 있을 수 있으니 불확실한 내용은 표시하세요. '
        '날짜와 담당 업무는 반드시 자료에 근거하세요.\n\n'
        '[회의 자료 원문]\n' + (meeting_text or '(텍스트 없음)')
    )}]
    if image_bytes:
        if image_mime not in ('image/png', 'image/jpeg'):
            raise ValueError('화이트보드 이미지는 PNG 또는 JPG만 지원합니다.')
        encoded = base64.b64encode(image_bytes).decode('ascii')
        content.append({'type': 'input_image',
                        'image_url': f'data:{image_mime};base64,{encoded}', 'detail': 'high'})
    response = client.responses.create(
        model=model,
        instructions=MEETING_INSTRUCTIONS,
        input=[{'role': 'user', 'content': content}],
        text={'format': {'type': 'json_schema', 'name': 'meeting_analysis', 'schema': ANALYSIS_SCHEMA, 'strict': True}},
        max_output_tokens=4500,
    )
    if not response.output_text:
        raise ValueError('AI 분석 결과가 비어 있습니다. 다시 시도해 주세요.')
    result = json.loads(response.output_text)
    for task in result['tasks']:
        task['importance'] = max(1, min(5, int(task['importance'])))
        task['status'] = '미시작'
    return result


def build_meeting_report(analysis, tasks):
    lines = [
        f"# {analysis.get('meeting_title') or '최종 통합 회의록'}",
        f"**회의일:** {analysis.get('meeting_date') or '미상'}", '',
        '## 핵심 요약', analysis.get('summary', ''), '',
        '## 확정된 결정사항',
        *[f'- {x}' for x in analysis.get('decisions', [])], '',
        '## 검토 중인 사항',
        *[f'- {x}' for x in analysis.get('pending', [])], '',
        '## 담당자별 업무',
    ]
    for task in tasks:
        lines += [
            f"- **{task['owner']}** — {task['title']} (마감: {task.get('due_date') or '미정'}, 상태: {task.get('status', '미시작')})",
            f"  - {task.get('description', '')}",
            f"  - 근거: {task.get('source_notes', '')}",
        ]
    lines += ['', '## 자료 간 차이 / 확인 필요 사항']
    lines += [f'- {x}' for x in analysis.get('conflicts', [])] or ['- AI가 탐지한 차이 없음 (원문 확인 권장)']
    lines += ['', '> 중요도와 선행 작업 여부는 AI 추정치이며, 확인되지 않은 일정은 미정으로 표시합니다.']
    return '\n'.join(lines)
