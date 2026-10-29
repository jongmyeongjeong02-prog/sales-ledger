"""Preview-only weekly and daily briefing contracts."""
import csv
from datetime import date
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from briefing import build_weekly, build_daily, render_weekly, render_daily
from ledger import LEDGER_FIELDS, write_rows


def quote(no, qdate, amount, *, order='', sale='', status='진행중', sent='0', asked=''):
    row = dict.fromkeys(LEDGER_FIELDS, '')
    row.update(quote_no=no, customer='가상고객', quote_date=qdate, quote_amount=str(amount),
               status=status, order_date=order, order_amount=str(amount) if order else '',
               invoice_date=sale, invoice_amount=str(amount) if sale else '',
               alert_count=sent, loss_prompted_at=asked)
    return row


class BriefingTest(unittest.TestCase):
    def test_monday_uses_previous_monday_sunday_and_pending_stage_boundaries(self):
        rows = [quote('Q1', '2026-09-27', 1_000_000, order='2026-10-19', status='수주완'),
                quote('Q2', '2026-10-20', 2_000_000, order='2026-10-25', sale='2026-10-25', status='매출완'),
                quote('Q3', '2026-08-26', 3_000_000),  # 61 days, loss target
                quote('Q4', '2026-09-26', 4_000_000),  # 30 days, needs check
                quote('Q5', '2026-09-27', 5_000_000),  # 29 days, submitted
                quote('Q6', '2026-10-27', 6_000_000)] # future quote excluded
        data = build_weekly(rows, date(2026, 10, 26))
        self.assertEqual((data['from'], data['to']), ('2026-10-19', '2026-10-25'))
        self.assertEqual(data['orders'], {'count': 2, 'amount': 3_000_000})
        self.assertEqual(data['sales'], {'count': 1, 'amount': 2_000_000})
        self.assertEqual(data['pending']['amount'], 12_000_000)
        self.assertEqual([len(data['pending'][s]) for s in ('submitted', 'check', 'loss_target')], [1, 1, 1])
        text = render_weekly(data)
        self.assertIn('수주: 2건 · 3.0 백만원', text)
        self.assertIn('매출: 1건 · 2.0 백만원', text)
        self.assertIn('발주서 미수령 견적: 3건 · 12.0 백만원', text)
        self.assertIn('Q4 / 가상고객 / 4.0 백만원 / 견적 후 30일', text)
        self.assertIn('Q3 / 가상고객 / 3.0 백만원 / 견적 후 61일', text)
        self.assertIn('"실주 JJM○○"', text)

    def test_daily_pending_flags_only_once_and_never_marks_rows_in_preview(self):
        rows = [quote('Q1', '2026-09-27', 1_000_000),   # 31 days on 10/28
                quote('Q2', '2026-08-28', 2_000_000),   # 61 days on 10/28
                quote('Q3', '2026-08-01', 3_000_000, sent='1', asked='2026-10-01'),
                quote('Q4', '2026-08-01', 4_000_000, status='수주완', order='2026-08-15')]
        before = [dict(r) for r in rows]
        data = build_daily(rows, date(2026, 10, 28))
        self.assertEqual({x['quote_no'] for x in data['alert']}, {'Q1'})
        self.assertEqual({x['quote_no'] for x in data['loss_question']}, {'Q2'})
        self.assertTrue(all(30 < x['elapsed'] <= 60 for x in data['alert']))
        self.assertTrue(all(x['elapsed'] > 60 for x in data['loss_question']))
        self.assertIn('실주 처리할까요?', render_daily(data))
        self.assertEqual(rows, before)
        for row in rows[:2]:
            row['alert_count'] = '1'
        rows[1]['loss_prompted_at'] = '2026-10-28'
        self.assertIn('새 알림 없음', render_daily(build_daily(rows, date(2026, 10, 29))))

    def test_manual_weekend_reports_work_and_keep_csv_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / 'ledger.csv'
            write_rows(ledger, LEDGER_FIELDS, [quote('Q1', '2026-09-27', 1_000_000)])
            original = ledger.read_bytes()
            base = [sys.executable, str(ROOT / 'scripts/briefing.py'), '--ledger', str(ledger)]
            ok = subprocess.run(base + ['--mode', 'daily', '--as-of', '2026-10-28'], text=True, capture_output=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn('Q1', ok.stdout)
            for mode in ('weekly', 'daily'):
                weekend = subprocess.run(base + ['--mode', mode, '--as-of', '2026-10-31'],
                                         text=True, capture_output=True)
                self.assertEqual(weekend.returncode, 0, weekend.stderr)
                self.assertIn('[주간 보고] 2026-10-19~2026-10-25' if mode == 'weekly'
                              else '[일일 현황] 2026-10-31', weekend.stdout)
            self.assertEqual(ledger.read_bytes(), original)

    def test_assumed_sent_through_oct_28_preview_nov_5_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / 'ledger.csv'
            with (ROOT / 'demo/expected_ledger.csv').open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                if row['status'] == '진행중':
                    row.update(alert_count='0', loss_prompted_at='')
            write_rows(ledger, LEDGER_FIELDS, rows)
            original = ledger.read_bytes()
            base = [sys.executable, str(ROOT / 'scripts/briefing.py'), '--ledger', str(ledger),
                    '--mode', 'daily', '--as-of', '2026-11-05', '--assume-sent-through', '2026-10-28']
            result = subprocess.run(base, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('JJM20260905-B', result.stdout)
            self.assertIn('실주 처리할까요?', result.stdout)
            self.assertNotIn('JJM20260405-A', result.stdout)
            self.assertNotIn('확인필요 알림', result.stdout)
            self.assertEqual(ledger.read_bytes(), original)

if __name__ == '__main__':
    unittest.main()
