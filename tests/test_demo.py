"""Deterministic fictional demo artifacts; never touches project data/."""
import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_demo.py"


class DemoTest(unittest.TestCase):
    def generate(self, root):
        result = subprocess.run([sys.executable, str(SCRIPT), "--out-dir", str(root)],
                                capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with (root / "answer_key.csv").open(encoding="utf-8-sig", newline="") as f:
            answer = list(csv.DictReader(f))
        with (root / "expected_ledger.csv").open(encoding="utf-8-sig", newline="") as f:
            ledger = list(csv.DictReader(f))
        return answer, ledger

    def test_document_counts_money_dates_and_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            answer, ledger = self.generate(out)
            quotes = [r for r in answer if r["document_type"] == "quote"]
            orders = [r for r in answer if r["document_type"] == "order" and r["expected_result"] == "connected"]
            invoices = [r for r in answer if r["document_type"] == "invoice"]
            exceptions = [r for r in answer if r["expected_result"] in ("unlinked", "mismatch")]
            self.assertEqual((len(quotes), len(orders), len(exceptions)), (40, 32, 2))
            self.assertEqual(len(ledger), 40)
            self.assertEqual({r["expected_result"] for r in exceptions}, {"unlinked", "mismatch"})
            self.assertTrue(all(r["po_no"].startswith("PO-VIRTUAL-") for r in exceptions))
            self.assertEqual(len({r["customer"] for r in quotes}), 12)
            self.assertTrue(all((out / "pdfs" / r["filename"]).read_bytes().startswith(b"%PDF-") for r in answer))
            self.assertEqual(len(list((out / "pdfs").glob("*.pdf"))), len(answer))
            months = defaultdict(list)
            catalog = defaultdict(set)
            for row in quotes:
                month = row["document_date"][:7]
                months[month].append(int(row["supply_amount"]))
                self.assertRegex(row["quote_no"], r"^JJM2026\d{4}-[A-Z]$")
                self.assertTrue(10_000_000 <= int(row["supply_amount"]) <= 200_000_000)
                items = json.loads(row["items_json"])
                self.assertTrue(2 <= len(items) <= 7)
                self.assertEqual(sum(i["amount"] for i in items), int(row["supply_amount"]))
                for item in items:
                    catalog[item["model"]].add((item["unit_price"], item["product_code"]))
                    self.assertEqual(item["unit_price"] % 1000, 0)
            self.assertEqual(sorted(months), [f"2026-{m:02d}" for m in range(4, 11)])
            self.assertTrue(all(len(values) >= 4 and 400_000_000 <= sum(values) <= 1_000_000_000 for values in months.values()))
            self.assertEqual(len({sum(v) for v in months.values()}), 7)
            self.assertEqual(len(catalog), 7)
            self.assertTrue(all(len(values) == 1 for values in catalog.values()))
            self.assertTrue(all(r["document_date"] <= "2026-10-27" for r in quotes))
            self.assertTrue(all(r["document_date"] < "2026-10-27" for r in orders + invoices))
            self.assertEqual(len({r["quote_no"] for r in invoices}), len(invoices))
            self.assertTrue(all(int(r["vat"]) == int(r["supply_amount"]) // 10 for r in invoices))
            self.assertTrue(all(int(r["total"]) == int(r["supply_amount"]) + int(r["vat"]) for r in invoices))
            unorder = [r for r in ledger if r["status"] in ("진행중", "실주")]
            self.assertEqual(len(unorder), 8)
            self.assertEqual(Counter(r["quote_date"][:7] for r in unorder if r["status"] == "진행중"),
                             Counter({"2026-04": 1, "2026-05": 1, "2026-07": 1, "2026-08": 1, "2026-09": 2, "2026-10": 2}))
            self.assertTrue(all(r["status"] == "진행중" and r["lost_date"] == "" and "자동 실주" not in r["memo"]
                                for r in unorder))
            self.assertEqual(sum(bool(r["loss_prompted_at"]) for r in unorder), 4)
            self.assertTrue(all(r["loss_prompted_at"] == "2026-10-31" for r in unorder
                                if date.fromisoformat(r["quote_date"]) + timedelta(days=60) < date(2026, 10, 31)))
            self.assertTrue(all(r["alert_count"] == "1" for r in unorder if r["quote_date"] < "2026-10-01"))
            self.assertTrue(all(r["alert_count"] == "0" for r in unorder if r["quote_date"].startswith("2026-10")))
            self.assertTrue(all(r["status"] == "매출완" for r in ledger if r["quote_no"] in {x["quote_no"] for x in invoices}))

    def test_repeat_generation_is_byte_identical_and_public_safe(self):
        self.assertIsNotNone(re.search(rb"\b\d{3}-\d{3,4}-\d{4}\b", b"000-1234-5678"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.generate(out)
            first = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).digest()
                     for p in out.rglob("*") if p.is_file()}
            self.generate(out)
            second = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).digest()
                      for p in out.rglob("*") if p.is_file()}
            self.assertEqual(first, second)
            for p in out.rglob("*"):
                if p.is_file():
                    self.assertFalse(any(secret.encode() in p.read_bytes() for secret in (
                        "실제고객", "실제회사", "031)", "ImagePrinter", "NOT REGISTERED")), p)
                    self.assertIsNone(re.search(rb"\b\d{3}-\d{3,4}-\d{4}\b", p.read_bytes()), p)
    def test_answer_key_replays_to_expected_ledger_in_isolated_dir(self):
        live = ROOT / "data" / "ledger.csv"
        live_before = live.read_bytes() if live.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo"
            answer, expected = self.generate(out)
            data = Path(tmp) / "isolated-data"
            input_path = Path(tmp) / "input.json"

            def cli(command, payload=None, as_of=None):
                args = [sys.executable, str(ROOT / "scripts" / "ledger.py"), "--data-dir", str(data)]
                if as_of:
                    args += ["--as-of", as_of]
                args.append(command)
                if payload is not None:
                    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    args.append(str(input_path))
                result = subprocess.run(args, capture_output=True, text=True)
                return result

            for row in (r for r in answer if r["document_type"] == "quote"):
                items = json.loads(row["items_json"])
                payload = {"quote_no": row["quote_no"], "quote_date": row["document_date"],
                           "customer": row["customer"], "customer_contact": "", "contact_title": "",
                           "sales_rep": "가상영업 담당", "quote_amount": int(row["supply_amount"]),
                           "items": [dict(i, remark="SET-01") for i in items]}
                result = cli("add-quote", payload)
                self.assertEqual(result.returncode, 0, result.stdout)
            for row in (r for r in answer if r["document_type"] == "order"):
                items = json.loads(row["items_json"])
                payload = {"quote_no": row["quote_no"], "received_date": row["document_date"],
                           "po_no": row["po_no"], "order_amount": int(row["supply_amount"]),
                           "order_vat": int(row["vat"]), "order_total": int(row["total"]),
                           "items": [{"model": i["model"], "qty": i["qty"],
                                      "unit_price": i["unit_price"]} for i in items]}
                if "도장회신" in row["filename"]:
                    payload["stamped_quote"] = True
                result = cli("add-order", payload)
                self.assertEqual(result.returncode == 0, row["expected_result"] == "connected", result.stdout)
            for row in (r for r in answer if r["document_type"] == "invoice"):
                payload = {"quote_no": row["quote_no"], "invoice_date": row["document_date"],
                           "invoice_amount": int(row["supply_amount"]), "invoice_vat": int(row["vat"]),
                           "invoice_total": int(row["total"])}
                result = cli("add-invoice", payload)
                self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(cli("advance", as_of="2026-10-31").returncode, 0)
            with (data / "ledger.csv").open(encoding="utf-8-sig", newline="") as f:
                actual = {r["quote_no"]: r for r in csv.DictReader(f)}
            self.assertEqual(len(actual), len(expected))
            for row in expected:
                found = actual[row["quote_no"]]
                for field in ("customer", "customer_contact", "contact_title", "sales_rep",
                              "quote_date", "quote_amount", "status", "order_date", "order_amount",
                              "order_vat", "order_total", "invoice_date", "invoice_amount",
                              "invoice_vat", "invoice_total", "lost_date", "memo", "alert_count",
                              "loss_prompted_at", "next_alert_date"):
                    self.assertEqual(found[field], str(row[field]), (row["quote_no"], field))
            self.assertEqual(live.read_bytes() if live.exists() else None, live_before)


if __name__ == "__main__":
    unittest.main()
