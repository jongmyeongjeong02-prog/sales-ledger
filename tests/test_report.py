"""Independent aggregate oracle from expected ledger and fictional item answer rows."""
import csv
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "report.py"
LEDGER = ROOT / "demo" / "expected_ledger.csv"
ANSWER = ROOT / "demo" / "answer_key.csv"


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.items = Path(self.tmp.name) / "items.csv"
        with LEDGER.open(encoding="utf-8-sig", newline="") as f:
            self.rows = list(csv.DictReader(f))
        with ANSWER.open(encoding="utf-8-sig", newline="") as f:
            self.answers = list(csv.DictReader(f))
        quote_items = [dict(quote_no=r["quote_no"], model=i["model"], line_no=i["line_no"])
                       for r in self.answers if r["document_type"] == "quote"
                       for i in json.loads(r["items_json"])]
        with self.items.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, ["quote_no", "line_no", "model"])
            writer.writeheader()
            writer.writerows(quote_items)

    def run_cmd(self, as_of="2026-10-31"):
        return subprocess.run([sys.executable, str(SCRIPT), "--as-of", as_of,
                               "--ledger", str(LEDGER), "--items", str(self.items)],
                              text=True, capture_output=True)

    def test_monthly_customer_and_lead_match_independent_expected_calculation(self):
        before = LEDGER.read_bytes(), self.items.read_bytes()
        live = ROOT / "data" / "ledger.csv"
        live_before = live.read_bytes() if live.exists() else None
        result = self.run_cmd()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["as_of"], "2026-10-31")
        for prefix, key, when in (("order", "orders_by_month", "order_date"),
                                  ("invoice", "sales_by_month", "invoice_date")):
            groups = defaultdict(list)
            for row in self.rows:
                if row[when]:
                    groups[row[when][:7]].append(row)
            actual = {r["month"]: r for r in report[key]}
            self.assertEqual(set(actual), set(groups))
            for month, group in groups.items():
                expected = {"count": len(group),
                            "supply_amount": sum(int(r[prefix + "_amount"]) for r in group),
                            "vat": sum(int(r[prefix + "_vat"]) for r in group),
                            "total": sum(int(r[prefix + "_total"]) for r in group)}
                self.assertEqual({k: actual[month][k] - v for k, v in expected.items()},
                                 dict.fromkeys(expected, 0), (month, prefix))
        customer = defaultdict(list)
        for row in self.rows:
            customer[row["customer"]].append(row)
        actual_customers = {r["customer"]: r for r in report["customers"]}
        self.assertEqual(set(actual_customers), set(customer))
        for name, group in customer.items():
            c = actual_customers[name]
            self.assertEqual(c["quote_count"], len(group))
            self.assertEqual(c["quote_amount"], sum(int(r["quote_amount"]) for r in group))
            for prefix, label in (("order", "orders"), ("invoice", "sales")):
                selected = [r for r in group if r[prefix + "_date"]]
                self.assertEqual(c[label]["count"], len(selected))
                self.assertEqual(c[label]["supply_amount"], sum(int(r[prefix + "_amount"]) for r in selected))
                self.assertEqual(c[label]["vat"], sum(int(r[prefix + "_vat"]) for r in selected))
                self.assertEqual(c[label]["total"], sum(int(r[prefix + "_total"]) for r in selected))
        by_no = {r["quote_no"]: r for r in self.rows}
        expected_lead = defaultdict(list)
        with self.items.open(encoding="utf-8-sig", newline="") as f:
            for item in csv.DictReader(f):
                r = by_no[item["quote_no"]]
                if r["invoice_date"]:
                    days = (date.fromisoformat(r["invoice_date"]) - date.fromisoformat(r["order_date"])).days
                    expected_lead[item["model"]].append((r["invoice_date"], r["quote_no"], days))
        actual_lead = {r["model"]: r for r in report["lead_by_model"]}
        self.assertEqual(set(actual_lead), set(expected_lead))
        for model, values in expected_lead.items():
            actual = actual_lead[model]
            durations = [v[2] for v in values]
            self.assertEqual(actual["count"], len(values))
            self.assertEqual(actual["average_days"] - round(sum(durations) / len(values), 2), 0)
            self.assertEqual(actual["min_days"] - min(durations), 0)
            self.assertEqual(actual["max_days"] - max(durations), 0)
            self.assertEqual(actual["latest_days"] - max(values)[2], 0)
        self.assertEqual((LEDGER.read_bytes(), self.items.read_bytes()), before)
        self.assertEqual(live.read_bytes() if live.exists() else None, live_before)

    def test_as_of_filters_future_events_without_mutating_csv(self):
        out = self.run_cmd("2026-06-01")
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout)
        self.assertTrue(all(r["month"] <= "2026-06" for r in payload["orders_by_month"] + payload["sales_by_month"]))
        self.assertEqual(sum(r["count"] for r in payload["sales_by_month"]), 0)
        self.assertEqual(payload["lead_by_model"], [])
        self.assertEqual(sum(r["quote_count"] for r in payload["customers"]),
                         sum(r["quote_date"] <= "2026-06-01" for r in self.rows))


if __name__ == "__main__":
    unittest.main()
