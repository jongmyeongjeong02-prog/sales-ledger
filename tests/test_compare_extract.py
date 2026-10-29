"""Independent comparator tests with miniature artificial keys and extraction JSONs."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_extract.py"
FIELDS = "filename document_type quote_no customer document_date supply_amount vat total po_no items_json expected_result".split()


class CompareExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pdfs, self.extracted = root / "pdfs", root / "extracted"
        self.pdfs.mkdir()
        self.extracted.mkdir()
        self.key, self.output = root / "answer_key.csv", root / "verify.md"
        quote = dict(filename="alpha.pdf", document_type="quote", quote_no="JJM20261001-A",
                     customer="가상회사", document_date="2026-10-01", supply_amount="10000",
                     vat="0", total="10000", po_no="", expected_result="registered",
                     items_json=json.dumps([dict(model="A1", part_no="ZYX", product_code="VIRT-1",
                                                 qty=2, unit_price=5000, amount=10000)]))
        order = dict(filename="beta.pdf", document_type="order", quote_no="JJM20261001-A",
                     customer="가상회사", document_date="2026-10-05", supply_amount="10000",
                     vat="1000", total="11000", po_no="PO-1", expected_result="connected",
                     items_json=quote["items_json"])
        self.rows = [quote, order]
        for row in self.rows:
            (self.pdfs / row["filename"]).write_bytes(b"%PDF-test")
        with self.key.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(self.rows)

    def write_extracted(self, name, **fields):
        (self.extracted / (name + ".json")).write_text(json.dumps({"filename": name, **fields}), encoding="utf-8")

    def run_cmd(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--answer-key", str(self.key),
                               "--pdf-dir", str(self.pdfs), "--extracted-dir", str(self.extracted),
                               "--output", str(self.output)], capture_output=True, text=True)

    def test_reports_per_type_field_accuracy_and_mismatches(self):
        self.write_extracted("alpha.pdf", document_type="quote", quote_no="JJM20261001-A",
                             customer="가상회사", document_date="2026-10-01", supply_amount=10000,
                             items=[dict(model="A1", part_no="ZYX", product_code="VIRT-1",
                                         qty=2, unit_price=5000, amount=10000)])
        self.write_extracted("beta.pdf", document_type="order", quote_no="JJM20261001-A",
                             customer=None, document_date="2026-10-05", supply_amount=10000,
                             vat=1000, total=11000, po_no="PO-1",
                             source={"quote_no": "filename routing only; no quote number on page",
                                     "document_date": "PO date on PDF; independent receipt date not recorded"},
                             items=[dict(model="A1", part_no="ZYX", customer_item_code="VIRT-1",
                                         qty=3, unit_price=5000, amount=10000)])
        result = self.run_cmd()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.output.read_text(encoding="utf-8")
        self.assertIn("quote", text)
        self.assertIn("order", text)
        self.assertIn("items.qty", text)
        self.assertIn("beta.pdf", text)
        self.assertIn("customer", text)
        self.assertIn("92.59%", text)  # 25 of 27 comparable fields
        self.assertIn("100.00%", text)
        self.assertIn("0.00%", text)
        self.assertIn("파일명 연결: 1건", text)
        self.assertIn("별도 수신일 미표시: 1건", text)

    def test_missing_and_extra_json_are_reported_not_silently_ignored(self):
        self.write_extracted("alpha.pdf", document_type="quote", quote_no="JJM20261001-A")
        self.write_extracted("ghost.pdf", document_type="order")
        result = self.run_cmd()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.output.read_text(encoding="utf-8")
        self.assertIn("beta.pdf", text)
        self.assertIn("ghost.pdf", text)
        self.assertIn("미추출", text)
        self.assertIn("초과", text)

    def test_stem_named_json_files_are_paired_with_pdf(self):
        self.write_extracted("alpha.pdf", document_type="quote", quote_no="JJM20261001-A")
        source = self.extracted / "alpha.pdf.json"
        source.rename(self.extracted / "alpha.json")
        result = self.run_cmd()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.output.read_text(encoding="utf-8")
        self.assertIn("추출 JSON: 1개", text)
        self.assertIn("미추출 PDF: 1", text)  # beta only
        self.assertNotIn("초과 JSON: 1", text)


if __name__ == "__main__":
    unittest.main()
