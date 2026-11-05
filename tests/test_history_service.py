import unittest
from services.history_service import make_record, export_backup, import_backup, upsert_record

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {'meeting_title': '고객센터 회의', 'meeting_date': '2026-11-04', 'summary': '요약'}
        self.tasks = [{'id':'task1','title':'자료 분석','status':'미시작'}]

    def test_archive_restore(self):
        rec = make_record(self.analysis, self.tasks, '녹음 전사')
        self.assertEqual(rec['title'], '고객센터 회의')
        self.assertEqual(rec['transcript'], '녹음 전사')
        backup = export_backup([rec], [{'role':'user','content':'업무는?'}, {'role':'assistant','content':'분석 업무'}])
        records, chats = import_backup(backup.encode('utf-8'))
        self.assertEqual(len(records),1)
        self.assertEqual(len(chats),2)

    def test_upsert_keeps_original_date(self):
        rec = make_record(self.analysis,self.tasks)
        later = make_record(self.analysis,[{'id':'task1','status':'완료'}], record_id=rec['id'])
        records=upsert_record([rec], later, preserve_created=True)
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['saved_at'], rec['saved_at'])
        self.assertEqual(records[0]['tasks'][0]['status'],'완료')

    def test_invalid_backup_rejected(self):
        with self.assertRaises(ValueError):
            import_backup(b'{"records":[]}')

if __name__ == '__main__':
    unittest.main()
