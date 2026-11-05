import unittest
from datetime import date
from services.task_service import rank_tasks, make_briefing, with_ids

class TaskTest(unittest.TestCase):
    def setUp(self):
        self.tasks = with_ids([
            {'title':'데이터 분석', 'owner':'김 대리', 'due_date':'2026-11-06', 'importance':5, 'is_dependency':True},
            {'title':'FAQ 정리', 'owner':'박 과장', 'due_date':'2026-11-09', 'importance':3, 'is_dependency':False},
            {'title':'날짜 미정', 'owner':'김 대리', 'due_date':None, 'importance':2, 'is_dependency':False},
        ])

    def test_priority_and_deadline(self):
        ranked = rank_tasks(self.tasks, date(2026,11,4))
        self.assertEqual(ranked[0]['title'], '데이터 분석')
        self.assertEqual(ranked[0]['priority_score'], 95)
        self.assertEqual(ranked[0]['days_left'], 2)

    def test_done_excluded_from_briefing(self):
        self.tasks[0]['status']='완료'
        report = make_briefing(self.tasks, '김 대리', date(2026,11,4))
        self.assertIn('남은 업무는 **1건**', report)
        self.assertNotIn('**데이터 분석**', report)

    def test_missing_date(self):
        ranked = rank_tasks(self.tasks, date(2026,11,4))
        unknown = next(t for t in ranked if t['title']=='날짜 미정')
        self.assertEqual(unknown['urgency_status'], '마감일 확인 필요')

if __name__ == '__main__':
    unittest.main()
