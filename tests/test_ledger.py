"""CLI integration tests with fictitious data only."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ledger.py"
FIXTURES = Path(__file__).parent / "fixtures"


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"

    def run_cmd(self, command, fixture=None, changes=None, as_of=None):
        if fixture:
            payload = json.loads((FIXTURES / f"{fixture}.json").read_text(encoding="utf-8"))
            payload.update(changes or {})
            path = Path(self.tmp.name) / "input.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        else:
            path = None
        args = [sys.executable, str(SCRIPT), "--data-dir", str(self.data)]
        if as_of:
            args.extend(["--as-of", as_of])
        args.append(command)
        if path:
            args.append(str(path))
        return subprocess.run(args, text=True, capture_output=True)

    def rows(self, name):
        with (self.data / name).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def test_quote_order_invoice_and_bom(self):
        self.assertEqual(self.run_cmd("add-quote", "quote").returncode, 0)
        self.assertEqual((self.data / "ledger.csv").read_bytes()[:3], b"\xef\xbb\xbf")
        self.assertEqual((self.data / "items.csv").read_bytes()[:3], b"\xef\xbb\xbf")
        self.assertEqual(self.rows("ledger.csv")[0]["status"], "진행중")
        self.assertEqual(self.rows("ledger.csv")[0]["next_alert_date"], "2026-10-02")
        self.assertEqual(self.run_cmd("add-order", "order").returncode, 0)
        order = self.rows("ledger.csv")[0]
        self.assertEqual((order["status"], order["order_date"], order["next_alert_date"]), ("수주완", "2026-09-10", ""))
        self.assertEqual(self.rows("items.csv")[0]["customer_item_code"], "C-VIRTUAL-1")
        self.assertEqual(self.run_cmd("add-invoice", "invoice").returncode, 0)
        invoice = self.rows("ledger.csv")[0]
        self.assertEqual((invoice["status"], invoice["invoice_date"]), ("매출완", "2026-09-20"))
        self.assertEqual((self.rows("items.csv")[0]["delivery_date"], self.rows("items.csv")[0]["lead_days"]), ("2026-09-20", "10"))
        self.assertIn("매출완", self.run_cmd("show", "quote").stdout)

    def test_duplicate_quote_does_not_change_files(self):
        self.run_cmd("add-quote", "quote")
        before = [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")]
        result = self.run_cmd("add-quote", "quote")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("중복", result.stdout + result.stderr)
        self.assertEqual(before, [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")])

    def test_unlinked_missing_or_unknown_quote_does_not_create_ledger(self):
        for command, fixture in (("add-quote", "quote"), ("add-order", "order"), ("add-invoice", "invoice")):
            for quote_no in (("",) if command == "add-quote" else ("", "JJM20990101-Z")):
                result = self.run_cmd(command, fixture, {"quote_no": quote_no})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("미연결", result.stdout + result.stderr)
                self.assertFalse((self.data / "ledger.csv").exists())

    def test_order_mismatch_shows_amount_and_quantity_without_write(self):
        self.run_cmd("add-quote", "quote")
        before = [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")]
        result = self.run_cmd("add-order", "order", {"order_amount": 300000, "order_total": 320000,
            "items": [{"model": "ABC-100", "qty": 3, "unit_price": 100000}]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("200000", result.stdout)
        self.assertIn("300000", result.stdout)
        self.assertIn("수량", result.stdout)
        self.assertEqual(before, [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")])

    def test_invoice_mismatch_shows_amount_and_quantity_without_write(self):
        self.run_cmd("add-quote", "quote")
        self.run_cmd("add-order", "order")
        before = [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")]
        result = self.run_cmd("add-invoice", "invoice", {"invoice_amount": 300000, "invoice_total": 320000,
            "items": [{"model": "ABC-100", "qty": 3, "unit_price": 100000}]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("금액", result.stdout)
        self.assertIn("수량", result.stdout)
        self.assertEqual(before, [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")])

    def test_lost_then_reopen_preserves_quote_and_alerts(self):
        self.run_cmd("add-quote", "quote")
        self.assertEqual(self.run_cmd("lost", "quote", {"lost_date": "2026-09-05"}).returncode, 0)
        lost = self.rows("ledger.csv")[0]
        self.assertEqual((lost["status"], lost["next_alert_date"], lost["quote_amount"]), ("실주", "", "200000"))
        self.assertEqual(self.run_cmd("reopen", "quote", {"reopen_date": "2026-11-05"}).returncode, 0)
        reopened = self.rows("ledger.csv")[0]
        self.assertEqual((reopened["status"], reopened["lost_date"], reopened["next_alert_date"]), ("진행중", "", "2026-10-02"))

    def test_invalid_transition_and_incomplete_order_do_not_write(self):
        self.run_cmd("add-quote", "quote")
        self.assertNotEqual(self.run_cmd("add-invoice", "invoice").returncode, 0)
        self.assertNotEqual(self.run_cmd("add-order", "order", {"received_date": ""}).returncode, 0)
        self.assertEqual(self.rows("ledger.csv")[0]["status"], "진행중")
        self.assertEqual(self.rows("items.csv")[0]["order_date"], "")

    def test_stamped_quote_without_po_computes_vat_and_appends_memo(self):
        self.assertEqual(self.run_cmd("add-quote", "quote", {"memo": "E.U: 가상공장"}).returncode, 0)
        payload = {"stamped_quote": True, "po_no": "", "received_date": "2026-09-02",
                   "order_vat": None, "order_total": None,
                   "memo_append": "고객 수기 요청: ABC-100 ret量 3mm"}
        self.assertEqual(self.run_cmd("add-order", "order", payload).returncode, 0)
        row = self.rows("ledger.csv")[0]
        self.assertEqual((row["po_no"], row["order_date"], row["order_vat"], row["order_total"]),
                         ("", "2026-09-02", "20000", "220000"))
        self.assertEqual(row["status"], "수주완")
        self.assertEqual(row["memo"], "E.U: 가상공장\n고객 수기 요청: ABC-100 ret量 3mm")
        self.assertEqual(self.rows("items.csv")[0]["order_date"], "2026-09-02")

    def test_stamped_quote_vat_truncates_fractional_won(self):
        item = {"line_no": 1, "model": "ABC-100", "part_no": "ABC-100-X1-KR",
                "product_code": "VIRTUAL-1", "remark": "예비품", "qty": 1,
                "unit_price": 200001, "amount": 200001}
        self.assertEqual(self.run_cmd("add-quote", "quote", {"quote_amount": 200001, "items": [item]}).returncode, 0)
        result = self.run_cmd("add-order", "order", {"stamped_quote": True, "po_no": "",
            "order_amount": 200001, "received_date": "2026-09-02", "order_vat": None,
            "order_total": None, "items": [{"model": "ABC-100", "qty": 1, "unit_price": 200001}]})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.rows("ledger.csv")[0]["order_vat"], self.rows("ledger.csv")[0]["order_total"]),
                         ("20000", "220001"))

    def test_unstamped_order_with_blank_po_is_rejected(self):
        self.run_cmd("add-quote", "quote")
        before = [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")]
        result = self.run_cmd("add-order", "order", {"po_no": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")])

    def test_invoice_vat_mismatch_is_rejected_without_write(self):
        self.run_cmd("add-quote", "quote")
        self.run_cmd("add-order", "order")
        before = [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")]
        result = self.run_cmd("add-invoice", "invoice", {"invoice_vat": 25000, "invoice_total": 225000})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VAT", result.stdout)
        self.assertEqual(before, [(self.data / n).read_bytes() for n in ("ledger.csv", "items.csv")])

    def test_anonymous_demo_contact_is_allowed(self):
        result = self.run_cmd("add-quote", "quote", {"customer_contact": "", "contact_title": ""})
        self.assertEqual(result.returncode, 0, result.stdout)
        row = self.rows("ledger.csv")[0]
        self.assertEqual((row["customer_contact"], row["contact_title"]), ("", ""))

    def test_as_of_alert_once_strictly_after_day_30(self):
        self.run_cmd("add-quote", "quote")
        self.assertNotIn("유효기간 만료", self.run_cmd("advance", as_of="2026-10-01").stdout)
        first = self.run_cmd("advance", as_of="2026-10-02")
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertIn("JJM20260901-D", first.stdout)
        self.assertIn("유효기간 만료", first.stdout)
        self.assertEqual(self.rows("ledger.csv")[0]["alert_count"], "1")
        self.assertEqual(self.rows("ledger.csv")[0]["next_alert_date"], "")
        self.assertNotIn("유효기간 만료", self.run_cmd("advance", as_of="2026-10-31").stdout)

    def test_as_of_loss_question_after_day_60_preserves_quote_and_memo(self):
        self.run_cmd("add-quote", "quote", {"memo": "가상 요청"})
        self.run_cmd("advance", as_of="2026-10-31")
        self.assertEqual(self.rows("ledger.csv")[0]["status"], "진행중")
        result = self.run_cmd("advance", as_of="2026-11-01")
        self.assertEqual(result.returncode, 0, result.stdout)
        row = self.rows("ledger.csv")[0]
        self.assertEqual((row["status"], row["lost_date"], row["memo"], row["next_alert_date"], row["loss_prompted_at"]),
                         ("진행중", "", "가상 요청", "", "2026-11-01"))
        self.assertEqual(row["quote_amount"], "200000")
        self.assertIn("실주 처리할까요?", result.stdout)
        self.assertEqual(self.run_cmd("advance", as_of="2026-11-02").stdout.count("실주 처리할까요?"), 0)

    def test_lost_all_requires_explicit_as_of_and_targets_only_overdue_open_quotes(self):
        self.run_cmd("add-quote", "quote", {"memo": "가상 요청"})
        before = (self.data / "ledger.csv").read_bytes()
        self.assertNotEqual(self.run_cmd("lost-all").returncode, 0)
        self.assertEqual((self.data / "ledger.csv").read_bytes(), before)
        self.assertEqual(self.run_cmd("lost-all", as_of="2026-10-31").returncode, 0)
        self.assertEqual((self.data / "ledger.csv").read_bytes(), before)
        result = self.run_cmd("lost-all", as_of="2026-11-01")
        self.assertEqual(result.returncode, 0, result.stdout)
        row = self.rows("ledger.csv")[0]
        self.assertEqual((row["status"], row["lost_date"], row["memo"]),
                         ("실주", "2026-11-01", "가상 요청"))
        after = (self.data / "ledger.csv").read_bytes()
        self.assertEqual(self.run_cmd("lost-all", as_of="2026-11-02").returncode, 0)
        self.assertEqual((self.data / "ledger.csv").read_bytes(), after)

    def test_legacy_ledger_without_prompt_column_is_upgraded_on_write(self):
        self.run_cmd("add-quote", "quote")
        path = self.data / "ledger.csv"
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames is not None
            fields = [field for field in reader.fieldnames if field != "loss_prompted_at"]
            rows = list(reader)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        result = self.run_cmd("advance", as_of="2026-11-01")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.rows("ledger.csv")[0]["loss_prompted_at"], "2026-11-01")

    def test_reopen_keeps_one_time_loss_question_stamp(self):
        self.run_cmd("add-quote", "quote")
        self.run_cmd("advance", as_of="2026-11-01")
        self.run_cmd("lost", "quote", {"lost_date": "2026-11-02"})
        self.run_cmd("reopen", "quote", {"reopen_date": "2026-11-03"})
        row = self.rows("ledger.csv")[0]
        self.assertEqual((row["status"], row["loss_prompted_at"], row["alert_count"]),
                         ("진행중", "2026-11-01", "1"))
        self.assertNotIn("실주 처리할까요?", self.run_cmd("advance", as_of="2026-11-04").stdout)

    def test_demo_directory_rejects_loss_writes(self):
        args = [sys.executable, str(SCRIPT), "--data-dir", str(ROOT / "demo"),
                "--as-of", "2026-11-01", "lost-all"]
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("demo/", result.stdout)

    def test_lost_all_excludes_ordered_and_existing_lost_quotes(self):
        self.run_cmd("add-quote", "quote")
        self.run_cmd("add-quote", "quote", {"quote_no": "JJM20260901-E"})
        self.run_cmd("add-quote", "quote", {"quote_no": "JJM20260901-F"})
        self.run_cmd("lost", "quote", {"quote_no": "JJM20260901-E", "lost_date": "2026-09-10"})
        self.run_cmd("add-order", "order", {"quote_no": "JJM20260901-F"})
        self.assertEqual(self.run_cmd("lost-all", as_of="2026-11-01").returncode, 0)
        rows = {r["quote_no"]: r for r in self.rows("ledger.csv")}
        self.assertEqual(rows["JJM20260901-D"]["lost_date"], "2026-11-01")
        self.assertEqual((rows["JJM20260901-E"]["status"], rows["JJM20260901-E"]["lost_date"]), ("실주", "2026-09-10"))
        self.assertEqual(rows["JJM20260901-F"]["status"], "수주완")

    def test_manual_lost_and_ordered_quotes_excluded_from_advance(self):
        self.run_cmd("add-quote", "quote")
        self.run_cmd("lost", "quote", {"lost_date": "2026-09-12"})
        self.assertNotIn("자동 실주", self.run_cmd("advance", as_of="2026-11-02").stdout)
        self.assertEqual(self.rows("ledger.csv")[0]["lost_date"], "2026-09-12")
        self.run_cmd("reopen", "quote", {"reopen_date": "2026-09-13"})
        self.run_cmd("add-order", "order")
        self.assertNotIn("유효기간 만료", self.run_cmd("advance", as_of="2026-11-02").stdout)
        self.assertEqual(self.rows("ledger.csv")[0]["status"], "수주완")


if __name__ == "__main__":
    unittest.main()
