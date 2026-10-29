"""Preview/apply alerts against isolated fictional CSVs only."""
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "alerts.py"
EXPECTED = ROOT / "demo" / "expected_ledger.csv"


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "ledger.csv"
        with EXPECTED.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            self.fields = reader.fieldnames
            assert self.fields is not None
            self.expected = list(reader)
        self.before = [dict(r) for r in self.expected]
        for row in self.before:
            if row["status"] == "진행중":
                row.update(alert_count="0", loss_prompted_at="", next_alert_date=(
                    date.fromisoformat(row["quote_date"]) + timedelta(days=31)).isoformat())
        self.save(self.before)

    def save(self, rows):
        with self.ledger.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, self.fields)
            writer.writeheader()
            writer.writerows(rows)

    def run_cmd(self, as_of="2026-10-31", apply=False):
        cmd = [sys.executable, str(SCRIPT), "--ledger", str(self.ledger), "--as-of", as_of]
        if apply:
            cmd.append("--apply")
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_expected_targets_are_previewed_without_writing(self):
        original = self.ledger.read_bytes()
        live = ROOT / "data" / "ledger.csv"
        live_before = live.read_bytes() if live.exists() else None
        result = self.run_cmd()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["as_of"], "2026-10-31")
        self.assertFalse(payload["applied"])
        self.assertEqual({x["quote_no"] for x in payload["alert_targets"]},
                         {x["quote_no"] for x in self.expected if x["status"] == "진행중" and x["alert_count"] == "1" and
                          (date(2026, 10, 31) - date.fromisoformat(x["quote_date"])).days <= 60})
        self.assertEqual({x["quote_no"] for x in payload["loss_question_targets"]},
                         {x["quote_no"] for x in self.expected if x["status"] == "진행중" and x["loss_prompted_at"]})
        self.assertNotIn("auto_lost_targets", payload)
        self.assertEqual((len(payload["alert_targets"]), len(payload["loss_question_targets"])), (2, 4))
        self.assertTrue(set(x["quote_no"] for x in payload["alert_targets"]).isdisjoint(
                        x["quote_no"] for x in payload["loss_question_targets"]))
        self.assertEqual(self.ledger.read_bytes(), original)
        self.assertEqual(live.read_bytes() if live.exists() else None, live_before)

    def test_apply_matches_expected_and_is_idempotent(self):
        result = self.run_cmd(apply=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["applied"])
        with self.ledger.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for actual, expected in zip(rows, self.expected):
            for field in ("quote_no", "status", "alert_count", "lost_date", "memo", "next_alert_date", "loss_prompted_at"):
                self.assertEqual(actual[field], expected[field], (actual["quote_no"], field))
        after = self.ledger.read_bytes()
        again = self.run_cmd(apply=True)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.ledger.read_bytes(), after)
        self.assertEqual(len(json.loads(again.stdout)["alert_targets"]), 0)
        self.assertEqual(len(json.loads(again.stdout)["loss_question_targets"]), 0)

    def test_strict_day_boundaries_and_order_exclusion(self):
        row = dict(self.before[0], quote_date="2026-09-01", status="진행중", alert_count="0", lost_date="", memo="")
        self.save([row])
        self.assertEqual(len(json.loads(self.run_cmd("2026-10-01").stdout)["alert_targets"]), 0)
        self.assertEqual(len(json.loads(self.run_cmd("2026-10-02").stdout)["alert_targets"]), 1)
        self.assertEqual(len(json.loads(self.run_cmd("2026-10-31").stdout)["loss_question_targets"]), 0)
        self.assertEqual(len(json.loads(self.run_cmd("2026-11-01").stdout)["loss_question_targets"]), 1)
        row["status"] = "수주완"
        self.save([row])
        self.assertEqual(len(json.loads(self.run_cmd("2026-11-01").stdout)["loss_question_targets"]), 0)

    def test_skipped_run_marks_both_notices_once_without_losing_quote(self):
        row = dict(self.before[0], quote_date="2026-09-01", status="진행중", alert_count="0",
                   loss_prompted_at="", lost_date="", memo="가상 요청")
        self.save([row])
        result = json.loads(self.run_cmd("2026-11-01", apply=True).stdout)
        self.assertEqual(len(result["alert_targets"]), 0)
        self.assertEqual(len(result["loss_question_targets"]), 1)
        self.assertIn("실주 처리할까요?", str(result["loss_question_targets"]))
        with self.ledger.open(encoding="utf-8-sig", newline="") as f:
            saved = list(csv.DictReader(f))[0]
        self.assertEqual((saved["status"], saved["lost_date"], saved["memo"], saved["alert_count"], saved["loss_prompted_at"]),
                         ("진행중", "", "가상 요청", "1", "2026-11-01"))
        self.assertEqual(json.loads(self.run_cmd("2026-11-02", apply=True).stdout)["loss_question_targets"], [])

    def test_cover_legacy_and_monday_reported_items_idempotently(self):
        cmd = [sys.executable, str(SCRIPT), '--ledger', str(self.ledger),
               '--as-of', '2026-10-28', '--cover']
        original = self.ledger.read_bytes()
        preview = subprocess.run(cmd, text=True, capture_output=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(self.ledger.read_bytes(), original)
        result = subprocess.run(cmd + ['--apply'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.ledger.open(encoding='utf-8-sig', newline='') as f:
            marked = {r['quote_no']: r for r in csv.DictReader(f)}
        for row in self.before:
            current = marked[row['quote_no']]
            self.assertEqual(current['status'], row['status'])
            if row['status'] != '진행중':
                continue
            days = (date(2026, 10, 28) - date.fromisoformat(row['quote_date'])).days
            if days >= 30:
                self.assertEqual(current['alert_count'], '1')
            if days > 60:
                self.assertEqual(current['loss_prompted_at'], '2026-10-28')
        after = self.ledger.read_bytes()
        subprocess.run(cmd + ['--apply'], check=True, capture_output=True)
        self.assertEqual(self.ledger.read_bytes(), after)

    def test_monday_cover_includes_day_30_but_not_day_29_or_future(self):
        sample = [dict(self.before[0], quote_no=f'Q{n}', quote_date=qdate,
                       status='진행중', alert_count='0', loss_prompted_at='')
                  for n, qdate in enumerate(('2026-09-26', '2026-09-27', '2026-08-26'), 1)]
        self.save(sample)
        cmd = [sys.executable, str(SCRIPT), '--ledger', str(self.ledger), '--as-of',
               '2026-10-26', '--cover', '--apply']
        subprocess.run(cmd, check=True, capture_output=True)
        with self.ledger.open(encoding='utf-8-sig', newline='') as f:
            by_no = {r['quote_no']: r for r in csv.DictReader(f)}
        self.assertEqual((by_no['Q1']['alert_count'], by_no['Q2']['alert_count'],
                          by_no['Q3']['alert_count'], by_no['Q3']['loss_prompted_at']),
                         ('1', '0', '1', '2026-10-26'))
        tuesday = json.loads(self.run_cmd('2026-10-27').stdout)
        self.assertNotIn('Q1', {a['quote_no'] for a in tuesday['alert_targets']})
        self.assertNotIn('Q3', {a['quote_no'] for a in tuesday['loss_question_targets']})


if __name__ == "__main__":
    unittest.main()
