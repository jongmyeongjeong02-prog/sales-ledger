"""Scheduled briefing delivery/reconciliation contracts, without Slack sends."""
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cron_tick import reconcile, prepare
from ledger import LEDGER_FIELDS, read_rows, write_rows


def quote(number, quoted, *, stage='진행중'):
    row = dict.fromkeys(LEDGER_FIELDS, '')
    row.update(quote_no=number, customer='가상고객', sales_rep='가상영업 담당',
               quote_date=quoted, quote_amount='1000000', status=stage,
               alert_count='0', next_alert_date='')
    return row


class CronTickTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.ledger = self.base / 'ledger.csv'
        self.manifests = self.base / 'reports'
        self.manifests.mkdir()
        self.db = self.base / 'executions.db'
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('CREATE TABLE executions (job_id TEXT, status TEXT, delivery_outcome TEXT, scheduled_instant TEXT)')
            connection.commit()
        self.rows = [quote('Q30', '2026-10-03'), quote('Q60', '2026-08-29')]
        write_rows(self.ledger, LEDGER_FIELDS, self.rows)

    def receipt(self, outcome='delivered', when='2026-11-02T08:30:00+09:00'):
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('INSERT INTO executions VALUES (?,?,?,?)', ('job-1', 'completed', outcome, when))
            connection.commit()

    def test_delivered_monday_stages_mark_once_before_tuesday_preview(self):
        self.manifests.joinpath('cron_manifest_20261102.json').write_text(json.dumps({
            'date': '2026-11-02', 'job_id': 'job-1', 'alert': ['Q30', 'Q60'],
            'loss_question': ['Q60']}), encoding='utf-8')
        self.receipt()
        changed = reconcile('job-1', self.ledger, self.manifests, self.db, date(2026, 11, 3))
        self.assertEqual(changed, 2)
        by_no = {r['quote_no']: r for r in read_rows(self.ledger)}
        self.assertEqual(by_no['Q30']['alert_count'], '1')
        self.assertEqual(by_no['Q60']['loss_prompted_at'], '2026-11-02')
        self.assertEqual(by_no['Q60']['status'], '진행중')
        before = self.ledger.read_bytes()
        self.assertEqual(reconcile('job-1', self.ledger, self.manifests, self.db, date(2026, 11, 4)), 0)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_failed_delivery_does_not_change_csv(self):
        self.manifests.joinpath('cron_manifest_20261102.json').write_text(json.dumps({
            'date': '2026-11-02', 'job_id': 'job-1', 'alert': ['Q30'],
            'loss_question': ['Q60']}), encoding='utf-8')
        self.receipt(outcome='failed')
        original = self.ledger.read_bytes()
        self.assertEqual(reconcile('job-1', self.ledger, self.manifests, self.db, date(2026, 11, 3)), 0)
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_prepare_does_not_mark_before_delivery_and_emits_html_attachment(self):
        # Dashboard only uses Python stdlib and accepts empty items for a fixture.
        items = self.base / 'items.csv'
        items.write_text('quote_no,model,order_date,delivery_date\n', encoding='utf-8')
        original = self.ledger.read_bytes()
        message = prepare('job-1', date(2026, 11, 2), self.ledger, items, self.manifests)
        self.assertIn('[주간 보고]', message)
        self.assertIn('MEDIA:', message)
        self.assertTrue(self.manifests.joinpath('cron_manifest_20261102.json').exists())
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_real_customer_prevents_any_report_or_manifest(self):
        from cron_tick import require_fictional
        rows = read_rows(self.ledger)
        rows[0]['customer'] = '실제회사'
        write_rows(self.ledger, LEDGER_FIELDS, rows)
        items = self.base / 'items.csv'
        items.write_text('quote_no,model\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '가상 데이터'):
            require_fictional(read_rows(self.ledger), self.ledger, items)
        self.assertEqual(list(self.manifests.glob('cron_manifest_*.json')), [])

    def test_local_blocklist_rejects_fictional_marker_in_ledger_or_items(self):
        from cron_tick import require_fictional
        blocklist = self.base / 'blocklist.local.txt'
        blocklist.write_text('가상금지어\n', encoding='utf-8')
        items = self.base / 'items.csv'
        items.write_text('quote_no,model\nQ30,가상모델\n', encoding='utf-8')
        rows = read_rows(self.ledger)
        rows[0]['memo'] = '가상금지어'
        write_rows(self.ledger, LEDGER_FIELDS, rows)
        with self.assertRaisesRegex(ValueError, '공유 금지 문자열'):
            require_fictional(read_rows(self.ledger), self.ledger, items, blocklist)
        rows[0]['memo'] = ''
        write_rows(self.ledger, LEDGER_FIELDS, rows)
        items.write_text('quote_no,model\nQ30,가상금지어\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '공유 금지 문자열'):
            require_fictional(read_rows(self.ledger), self.ledger, items, blocklist)

    def test_missing_local_blocklist_warns_and_skips_only_that_check(self):
        from cron_tick import require_fictional
        import warnings
        rows = read_rows(self.ledger)
        rows[0]['memo'] = '가상금지어'
        write_rows(self.ledger, LEDGER_FIELDS, rows)
        items = self.base / 'items.csv'
        items.write_text('quote_no,model\n', encoding='utf-8')
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            require_fictional(read_rows(self.ledger), self.ledger, items,
                              self.base / 'missing-blocklist.local.txt')
        self.assertEqual(len(seen), 1)
        self.assertIn('차단 목록 파일', str(seen[0].message))

if __name__ == '__main__':
    unittest.main()
