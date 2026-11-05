import unittest
from datetime import date
from services.calendar_service import save_event, deadline_entries, entries_for_day, month_html
from services.history_service import export_backup, import_backup

class CalendarTests(unittest.TestCase):
    def test_save_edit_and_duplicates(self):
        ev = save_event([], {'title':'고객 인터뷰','date':'2026-11-06','time':'09:30','note':'2층'})
        self.assertEqual(len(ev),1)
        new = save_event(ev,dict(ev[0], title='고객 인터뷰 수정'))
        self.assertEqual(len(new),1)
        self.assertEqual(new[0]['title'],'고객 인터뷰 수정')
        with self.assertRaises(ValueError):
            save_event(new, {'title':'','date':'2026-11-06'})
        with self.assertRaises(ValueError):
            save_event(new, {'title':'예시','date':'2026-11-35'})

    def test_deadlines_dedup_active_and_archived(self):
        analysis = {'meeting_title':'킥오프'}
        tasks=[{'id':'a','title':'고객 분석','due_date':'2026-11-06','owner':'김 대리','status':'미시작'}]
        archived=[{'id':'one','title':'킥오프','tasks':[dict(tasks[0],status='미시작')]}]
        due=deadline_entries(archived, analysis,[dict(tasks[0],status='완료')], 'one')
        self.assertEqual(len(due),1)
        self.assertEqual(due[0]['status'],'완료')
        events=save_event([],{'title':'미팅','date':'2026-11-06'})
        self.assertEqual(len(entries_for_day(events,due,date(2026,11,6))),2)
        self.assertIn('일정 1',month_html(2026,11,events,due,date(2026,11,4)))

    def test_backup_roundtrip_and_old_compat(self):
        events=save_event([] ,{'title':'직접 등록','date':'2026-11-09'})
        data=export_backup([],[],events).encode()
        archive, messages, restored=import_backup(data, include_events=True)
        self.assertEqual(len(restored),1)
        self.assertEqual(restored[0]['title'],'직접 등록')
        old=export_backup([],[]).encode()
        self.assertEqual(import_backup(old,include_events=True)[2],[])
        self.assertEqual(len(import_backup(data)),2)

if __name__=='__main__':
    unittest.main()
