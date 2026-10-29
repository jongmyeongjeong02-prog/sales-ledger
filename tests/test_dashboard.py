"""Offline dashboard numbers, security, CLI and period boundaries."""
from datetime import date
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from ledger import LEDGER_FIELDS, ITEM_FIELDS, write_rows
from report import aggregate


def row(quote_no, customer, quote_date, quote_amount, order_date='', order_amount='',
        invoice_date='', invoice_amount='', status='진행중'):
    data = dict.fromkeys(LEDGER_FIELDS, '')
    data.update(quote_no=quote_no, customer=customer, quote_date=quote_date,
                quote_amount=str(quote_amount), status=status,
                order_date=order_date, order_amount=str(order_amount) if order_date else '',
                order_vat='0' if order_date else '', order_total=str(order_amount) if order_date else '',
                invoice_date=invoice_date, invoice_amount=str(invoice_amount) if invoice_date else '',
                invoice_vat='0' if invoice_date else '', invoice_total=str(invoice_amount) if invoice_date else '')
    return data


class DashboardTest(unittest.TestCase):
    def setUp(self):
        from dashboard import build_view, render_html
        self.build_view = build_view
        self.render_html = render_html
        self.rows = [row('Q1', '가상고객가', '2026-04-01', 10_000_000, '2026-04-20', 10_000_000,
                         '2026-06-01', 10_000_000, '매출완'),
                     row('Q2', '가상고객나', '2026-09-01', 5_000_000),
                     row('Q3', '가상고객가', '2026-09-02', 3_000_000, '2026-10-03', 3_000_000,
                         status='수주완')]
        self.items = [dict(quote_no='Q1', line_no='1', model='A1', part_no='ZYX')]

    def view(self, day='2026-10-02'):
        ref = date.fromisoformat(day)
        report = aggregate(self.rows, self.items, ref)
        return self.build_view(report, self.rows, self.items, ref)

    def test_view_uses_report_totals_and_fills_months(self):
        view = self.view()
        self.assertEqual(view['report'], aggregate(self.rows, self.items, date(2026, 10, 2)))
        self.assertEqual([m['month'] for m in view['months']],
                         [f'2026-{month:02d}' for month in range(4, 11)])
        self.assertEqual(view['summary']['month_orders'], 0)  # Q3 is dated tomorrow
        self.assertEqual(view['summary']['month_sales'], 0)
        self.assertEqual(view['summary']['quote_amount'], 18_000_000)
        self.assertEqual(view['summary']['ordered_amount'], 10_000_000)
        self.assertEqual(view['summary']['forecast_count'], 1)
        self.assertEqual(view['summary']['forecast_amount'], 5_000_000)
        self.assertEqual(view['summary']['needs_check'], 1)
        self.assertEqual(view['months'][0]['orders'], next(x for x in view['report']['orders_by_month']
                                                          if x['month'] == '2026-04'))
        self.assertEqual(view['top_customers'][0]['orders']['supply_amount'], 10_000_000)
        self.assertEqual(view['leads'][0]['average_days'], view['report']['lead_by_model'][0]['average_days'])
        self.assertEqual(view['leads'][0]['label'], 'A1 ZYX')
        self.assertEqual(view['leads'][0]['recent'][0]['customer'], '가상고객가')
        self.assertEqual(view['month_details']['2026-04']['orders'][0]['quote_no'], 'Q1')
        self.assertEqual(view['month_details']['2026-10']['orders'], [])

    def test_inclusive_day_30_and_empty_csv(self):
        self.assertEqual(self.view('2026-10-01')['summary']['needs_check'], 1)
        self.assertEqual(self.view('2026-10-02')['summary']['needs_check'], 1)
        empty = self.build_view(aggregate([], [], date(2026, 10, 31)), [], [], date(2026, 10, 31))
        self.assertEqual(empty['summary']['conversion_percent'], 0)
        self.assertEqual(len(empty['months']), 7)
        self.assertEqual(empty['forecast'], [])

    def test_month_drilldown_keeps_report_order_from_older_quote(self):
        self.rows.append(row('Q0', '가상과거고객', '2026-03-25', 2_000_000,
                             '2026-04-05', 2_000_000, status='수주완'))
        view = self.view()
        april = next(m for m in view['months'] if m['month'] == '2026-04')
        self.assertEqual(april['orders']['count'], 2)
        self.assertEqual({r['quote_no'] for r in view['month_details']['2026-04']['orders']}, {'Q0', 'Q1'})

    def test_order_rate_uses_same_quote_cohort_in_numerator_and_denominator(self):
        self.rows.append(row('Q0', '가상과거고객', '2026-03-25', 10_000_000,
                             '2026-04-05', 10_000_000, status='수주완'))
        view = self.view()
        self.assertEqual(view['report']['orders_by_month'][0]['supply_amount'], 20_000_000)
        self.assertEqual(view['summary']['quote_amount'], 18_000_000)
        self.assertEqual(view['summary']['ordered_amount'], 10_000_000)
        self.assertEqual(view['summary']['conversion_percent'], 55.6)

    def test_lead_detail_ignores_quote_after_cutoff_like_report(self):
        self.rows.append(row('QF', '가상미래고객', '2026-11-01', 1_000_000,
                             '2026-05-01', 1_000_000, '2026-06-02', 1_000_000, '매출완'))
        self.items.append(dict(quote_no='QF', line_no='1', model='A1', part_no='ZYX'))
        view = self.view()
        self.assertEqual(view['report']['lead_by_model'][0]['count'], 1)
        self.assertEqual([r['quote_no'] for r in view['leads'][0]['recent']], ['Q1'])

    def test_million_won_uses_conventional_one_decimal_rounding(self):
        from dashboard import millions
        self.assertEqual(millions(666_650_000), '666.7')
        self.assertEqual(millions(0), '0.0')

    def test_html_is_offline_safe_responsive_and_contains_same_json(self):
        self.rows[0]['customer'] = '가상</script><img src=x onerror=alert(1)>'
        view = self.view()
        markup = self.render_html(view)
        self.assertIn('name="viewport"', markup)
        self.assertRegex(markup, r'@media\s*\(max-width:\s*640px\)')
        self.assertNotIn('src="http', markup)
        self.assertNotIn('href="http', markup)
        self.assertNotIn('</script><img', markup)
        self.assertNotIn('<img src=x', markup)
        self.assertIn('data-month="2026-04"', markup)
        self.assertIn('data-model="A1"', markup)
        match = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', markup, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1))['report'], view['report'])

    def test_monthly_detail_table_exposes_report_count_vat_and_total(self):
        markup = self.render_html(self.view())
        self.assertIn('월별 금액 상세', markup)
        self.assertIn('<th>VAT</th><th>총계</th>', markup)
        self.assertIn('<td>2026-04</td><td>수주</td><td>1</td>', markup)
        self.assertIn('10.0</td><td class="number">0.0</td><td class="number">10.0', markup)

    def test_cohort_counts_and_forecast_thresholds(self):
        self.rows = [row('A', '가', '2026-10-02', 1_000_000),
                     row('B', '나', '2026-09-01', 2_000_000),
                     row('C', '다', '2026-08-31', 3_000_000),
                     row('D', '라', '2026-08-30', 4_000_000),
                     row('E', '마', '2026-09-01', 5_000_000,
                         '2026-10-01', 5_000_000, status='수주완')]
        view = self.view('2026-10-31')
        self.assertEqual(view['summary']['quote_count'], 5)
        self.assertEqual(view['summary']['ordered_count'], 1)
        self.assertEqual(view['summary']['forecast_stages'], {'submitted': 1, 'check': 1, 'loss_target': 2})
        day_30 = self.view('2026-10-01')
        self.assertEqual(next(r for r in day_30['forecast'] if r['quote_no'] == 'B')['stage'], 'check')
        self.assertEqual(view['forecast'][2]['elapsed_days'], 60)
        self.assertEqual(view['forecast'][1]['elapsed_days'], 61)
        self.assertEqual([(r['quote_no'], r['stage'], r['loss_target_date']) for r in view['forecast']],
                         [('D', 'loss_target', '2026-10-30'), ('C', 'loss_target', '2026-10-31'),
                          ('B', 'check', '2026-11-01'), ('A', 'submitted', '2026-12-02')])
        markup = self.render_html(view)
        self.assertIn('견적 중 수주액 5.0 / 견적액 15.0 백만원', markup)
        self.assertIn('발주 1건 / 견적 5건', markup)
        self.assertIn('(견적제출 1 + 확인필요 1 + 실주대상 2)', markup)
        self.assertIn('실주대상 기준일', markup)
        self.assertNotIn('자동 실주 예정일', markup)

    def test_month_customer_ranking_uses_order_events_only(self):
        self.rows.extend([row('Q0', '가상과거고객', '2026-03-25', 20_000_000,
                              '2026-04-05', 20_000_000, status='수주완'),
                          row('Q4', '가상고객나', '2026-09-01', 8_000_000,
                              '2026-09-20', 8_000_000, status='수주완'),
                          row('Q5', '가상미래', '2026-11-01', 90_000_000,
                              '2026-04-01', 90_000_000, status='수주완')])
        view = self.view('2026-10-02')
        self.assertEqual([(c['customer'], c['orders']['supply_amount']) for c in view['customers_by_month']['2026-04']],
                         [('가상과거고객', 20_000_000), ('가상고객가', 10_000_000)])
        self.assertEqual(view['customers_by_month']['2026-09'][0]['customer'], '가상고객나')
        self.assertEqual(view['customers_by_month']['2026-10'], [])
        self.assertEqual(view['top_customers'][0]['customer'], '가상과거고객')

    def test_chart_layout_and_interactive_contract(self):
        markup = self.render_html(self.view())
        self.assertIn('<div class="eyebrow">수주·매출대장</div>', markup)
        self.assertNotIn('SALES LEDGER / OFFLINE VIEW', markup)
        self.assertRegex(markup, r'\.bar-pair\{[^}]*grid-template-columns:repeat\(2,')
        self.assertRegex(markup, r'\.chart\{[^}]*display:flex')
        self.assertIn('aria-pressed="false"', markup)
        self.assertIn('선택 ', markup)
        self.assertIn('합계 ', markup)
        self.assertIn('pointerenter', markup)
        self.assertIn('pointerdown', markup)
        self.assertIn('keydown', markup)
        self.assertIn('<details class="monthly-detail">', markup)
        self.assertIn('id="month-title">월 막대를 선택해 주세요', markup)
        self.assertRegex(markup, r'\.kpi \.sub\{[^}]*white-space:nowrap')
        self.assertRegex(markup, r'class="bar-value" style="bottom:calc\(100% \+ 4px\)">10</span>')
        self.assertIn('style="height:100%"', markup)
        self.assertIn('id="customer-list"', markup)

    def test_only_graph_presentation_has_spaced_months_bare_bars_and_thick_customer_bars(self):
        markup = self.render_html(self.view())
        match = re.search(r'<style>(.*?)</style>', markup, re.S)
        self.assertIsNotNone(match)
        assert match is not None
        style = match.group(1)
        self.assertRegex(style, r'\.chart\{[^}]*gap:20px;[^}]*padding:42px 26px 3px 2px')
        self.assertRegex(style, r'\.bar-pair\{[^}]*gap:0;')
        self.assertRegex(style, r'\.bar-track\{[^}]*background:transparent')
        self.assertRegex(style, r'\.customer-meter\{[^}]*height:10px;background:transparent')
        self.assertRegex(style, r'\.customers li\{[^}]*align-items:center')

    def test_cli_writes_named_html_without_touching_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp = Path(temp)
            ledger, items = tmp / 'ledger.csv', tmp / 'items.csv'
            write_rows(ledger, LEDGER_FIELDS, self.rows)
            write_rows(items, ITEM_FIELDS, self.items)
            original = (ledger.read_bytes(), items.read_bytes())
            call = subprocess.run([sys.executable, str(ROOT / 'scripts/dashboard.py'), '--as-of', '2026-10-02',
                                   '--ledger', str(ledger), '--items', str(items), '--out-dir', str(tmp)],
                                  capture_output=True, text=True)
            self.assertEqual(call.returncode, 0, call.stderr)
            output = tmp / 'dashboard_20261002.html'
            self.assertTrue(output.is_file())
            self.assertEqual((ledger.read_bytes(), items.read_bytes()), original)
            markup = output.read_text(encoding='utf-8')
            blob = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', markup, re.S)
            report_call = subprocess.run([sys.executable, str(ROOT / 'scripts/report.py'), '--as-of', '2026-10-02',
                                          '--ledger', str(ledger), '--items', str(items)],
                                         capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(blob.group(1))['report'], json.loads(report_call.stdout))


if __name__ == '__main__':
    unittest.main()
