"""AI가 추출한 업무에 일관된 점수를 계산하는 순수 Python 로직."""
from datetime import date
import hashlib

STATUSES = ['미시작', '진행 중', '완료']


def with_ids(tasks):
    result = []
    for i, task in enumerate(tasks):
        item = dict(task)
        value = f"{i}|{item.get('owner', '')}|{item.get('title', '')}"
        item['id'] = hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]
        item['status'] = '미시작'
        result.append(item)
    return result


def rank_tasks(tasks, today=None):
    today = today or date.today()
    ranked = []
    for raw in tasks:
        task = dict(raw)
        try:
            days = (date.fromisoformat(task['due_date']) - today).days if task.get('due_date') else None
        except (TypeError, ValueError):
            days = None
        if days is None:
            urgency, label = 0, '마감일 확인 필요'
        elif days < 0:
            urgency, label = 60, '기한 초과'
        elif days == 0:
            urgency, label = 60, '오늘 마감'
        elif days <= 2:
            urgency, label = 55, '마감 임박'
        elif days <= 5:
            urgency, label = 40, '이번 주 우선'
        elif days <= 7:
            urgency, label = 25, '준비 필요'
        else:
            urgency, label = 10, '여유 있음'
        importance = max(1, min(5, int(task.get('importance', 3))))
        score = urgency + importance * 5 + (15 if task.get('is_dependency') else 0)
        task.update(days_left=days, urgency_status=label, priority_score=score)
        ranked.append(task)
    return sorted(ranked, key=lambda x: (x.get('status') == '완료', -x['priority_score'], x.get('due_date') or '9999-12-31'))


def personal_tasks(tasks, owner):
    normalized = owner.replace(' ', '')
    return [t for t in tasks if normalized in t.get('owner', '').replace(' ', '')]


def make_briefing(tasks, owner, today=None):
    today = today or date.today()
    my_tasks = personal_tasks(rank_tasks(tasks, today), owner)
    active = [t for t in my_tasks if t.get('status') != '완료']
    lines = [f'# {today.isoformat()} 오늘 할 일 브리핑', '',
             f'**{owner}님**, 남은 업무는 **{len(active)}건**, 완료한 업무는 **{len(my_tasks)-len(active)}건**입니다.', '',
             '## 최우선 업무 TOP 3']
    if not active:
        lines.append('- 현재 미완료 업무가 없습니다. 할당된 업무나 담당자 이름을 확인해 주세요.')
    for i, task in enumerate(active[:3], 1):
        days = task['days_left']
        remaining = '마감 미정' if days is None else ('기한 초과' if days < 0 else ('오늘 마감' if days == 0 else f'D-{days}'))
        lines.append(f"{i}. **{task['title']}** — {remaining} / {task['priority_score']}점 / {task['status']}")
        lines.append(f"   - 추천: {task.get('description') or '업무 착수와 진행 상황을 확인하세요.'}")
    lines.extend(['', '## 참고', '- 중요도 및 의존성은 AI 추정, 우선순위 점수는 Python 규칙 계산 결과입니다.',
                  '- 실제 완료 여부와 마감일은 사용자가 확인 후 수정해 주세요.'])
    return '\n'.join(lines)
