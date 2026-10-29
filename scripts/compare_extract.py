#!/usr/bin/env python3
"""Compare blind JSON PDF extractions to the fictional answer key; never alter CSV."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ITEM_FIELDS = ("model", "part_no", "product_code", "qty", "unit_price", "amount")
BASIC_FIELDS = ("document_type", "quote_no", "customer", "document_date", "supply_amount")


def value(raw):
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return str(raw)
    return str(raw).strip().replace(",", "") if isinstance(raw, (str, int, float)) else str(raw)


def compare(answer_key, extracted_dir, pdf_dir):
    with answer_key.open(encoding="utf-8-sig", newline="") as handle:
        answers = list(csv.DictReader(handle))
    by_filename = {r["filename"]: r for r in answers}
    if len(by_filename) != len(answers):
        raise ValueError("정답표의 파일명이 중복됩니다")
    pdf_names = {p.name for p in pdf_dir.glob("*.pdf")}
    extracted_paths = {}
    for path in extracted_dir.glob("*.json"):
        filename = path.name[:-5] if path.name.endswith(".pdf.json") else path.stem + ".pdf"
        if filename in extracted_paths:
            raise ValueError(f"추출 JSON 중복: {filename}")
        extracted_paths[filename] = path
    extracted_names = set(extracted_paths)
    missing = sorted(pdf_names - extracted_names)
    extra = sorted(extracted_names - pdf_names)
    key_only = sorted(set(by_filename) - pdf_names)
    pdf_only = sorted(pdf_names - set(by_filename))
    counts = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    mismatches = []
    exact = defaultdict(lambda: [0, 0])
    limitations = {"filename_routing": 0, "unverified_receipt": 0,
                   "invoice_items_unverified": 0}

    def check(kind, filename, field, expected, actual):
        stats = counts[kind][field]
        stats[1] += 1
        if value(expected) == value(actual):
            stats[0] += 1
            return True
        mismatches.append({"filename": filename, "field": field, "expected": expected, "actual": actual})
        return False

    for filename in sorted(pdf_names & set(by_filename)):
        row = by_filename[filename]
        kind = row["document_type"]
        exact[kind][1] += 1
        extraction_path = extracted_paths.get(filename)
        if extraction_path is None:
            mismatches.append({"filename": filename, "field": "document", "expected": "PDF 추출 JSON", "actual": None})
            # Every applicable field counts as missing; never inflate accuracy by skipping a failed PDF.
            extracted = {}
        else:
            try:
                extracted = json.loads(extraction_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                extracted = {}
                mismatches.append({"filename": filename, "field": "JSON 형식", "expected": "유효", "actual": str(exc)})
            if not isinstance(extracted, dict):
                extracted = {}
        source = extracted.get("source") or {}
        if isinstance(source, dict):
            limitations["filename_routing"] += "filename" in str(source.get("quote_no", "")).lower()
            limitations["unverified_receipt"] += "independent receipt date not recorded" in str(source.get("document_date", ""))
        if kind == "invoice" and not extracted.get("items"):
            limitations["invoice_items_unverified"] += 1
        before = len(mismatches)
        fields: list[str] = list(BASIC_FIELDS)
        if kind in ("order", "invoice"):
            fields += ["vat", "total"]
        if kind == "order":
            fields.append("po_no")
        # A signed quote reply displays only supply amount; VAT and total are computed later by ledger.py.
        if "도장회신" in filename:
            fields = [f for f in fields if f not in ("vat", "total")]
        for field in fields:
            check(kind, filename, field, row.get(field), extracted.get(field))
        if kind in ("quote", "order"):
            expected_items = json.loads(row["items_json"] or "[]")
            actual_items = extracted.get("items")
            if not isinstance(actual_items, list):
                actual_items = []
            check(kind, filename, "items.count", len(expected_items), len(actual_items))
            for n, item in enumerate(expected_items):
                got = actual_items[n] if n < len(actual_items) and isinstance(actual_items[n], dict) else {}
                for field in ITEM_FIELDS:
                    label = ("customer_item_code" if kind == "order" and "도장회신" not in filename
                             and field == "product_code" else field)
                    actual = got.get(label)
                    # One aggregate per field, detailed mismatches identify the line.
                    stats = counts[kind]["items." + label]
                    stats[1] += 1
                    if value(item.get(field)) == value(actual):
                        stats[0] += 1
                    else:
                        mismatches.append({"filename": filename, "field": f"items[{n + 1}].{label}",
                                           "expected": item.get(field), "actual": actual})
        if len(mismatches) == before:
            exact[kind][0] += 1
    return {"pdf_count": len(pdf_names), "answer_count": len(answers),
            "extracted_count": len(extracted_names), "missing": missing, "extra": extra,
            "key_only": key_only, "pdf_only": pdf_only, "counts": counts,
            "exact": exact, "mismatches": mismatches, "limitations": limitations}


def safe(raw):
    return json.dumps(raw, ensure_ascii=False).replace("|", "\\|").replace("\n", " ")


def markdown(result):
    counts = result["counts"]
    matched = sum(v[0] for fields in counts.values() for v in fields.values())
    compared = sum(v[1] for fields in counts.values() for v in fields.values())
    pct = lambda n, d: f"{n / d * 100:.2f}%" if d else "N/A"
    lines = ["# 가상 PDF 추출 정확도 검증", "", "정답표는 추출 단계에서 사용하지 않았으며, 비교 시에만 읽었습니다.",
             "", f"- PDF: {result['pdf_count']}개 / 정답 행: {result['answer_count']}개 / 추출 JSON: {result['extracted_count']}개",
             f"- 전체 필드 일치율: **{pct(matched, compared)}** ({matched}/{compared})",
             f"- 완전일치 문서: **{sum(x[0] for x in result['exact'].values())}/{sum(x[1] for x in result['exact'].values())}**",
             "- 견적서는 VAT·총계 미표시, 도장 회신 견적서는 VAT·총계 미표시: 문서에 없는 계산값을 정확도 분모에서 제외합니다.",
             "", "## 검증 한계 (불일치가 아닌 문서상 미기재)", "",
             f"- 견적번호 파일명 연결: {result['limitations']['filename_routing']}건 — PDF 본문 번호 검증이 아니라 담당자 전달 정보 역할의 파일명으로 연결했습니다.",
             f"- 발주서 별도 수신일 미표시: {result['limitations']['unverified_receipt']}건 — 문서의 작성/발주일을 비교했으며 실제 수신일 증명은 아닙니다.",
             f"- 계산서 품목별 수량 미표시: {result['limitations']['invoice_items_unverified']}건 — 품목 수량 일치는 평가하지 않았습니다.",
             "", "## 문서 종류·항목별 일치율", "", "| 종류 | 항목 | 일치/대상 | 일치율 |", "|---|---|---:|---:|"]
    for kind in ("quote", "order", "invoice"):
        for field, (yes, total) in sorted(counts[kind].items()):
            lines.append(f"| {kind} | {field} | {yes}/{total} | {pct(yes, total)} |")
        yes, total = result["exact"][kind]
        lines.append(f"| {kind} | **문서 완전일치** | {yes}/{total} | {pct(yes, total)} |")
    lines += ["", "## 파일 범위", ""]
    for label, key in (("미추출 PDF", "missing"), ("초과 JSON", "extra"),
                       ("정답표에만 있는 파일", "key_only"), ("정답표에 없는 PDF", "pdf_only")):
        items = result[key]
        lines.append(f"- {label}: {len(items)}" + (" — " + ", ".join(f"`{x}`" for x in items) if items else ""))
    lines += ["", "## 틀린 항목 목록", "", "| 파일 | 항목 | 정답 | 추출 |", "|---|---|---|---|"]
    if not result["mismatches"]:
        lines.append("| — | 없음 | — | — |")
    for issue in result["mismatches"]:
        lines.append("| " + " | ".join(safe(issue[x]) for x in ("filename", "field", "expected", "actual")) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-key", type=Path, default=ROOT / "demo" / "answer_key.csv")
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "demo" / "pdfs")
    parser.add_argument("--extracted-dir", type=Path, default=ROOT / "demo" / "extracted")
    parser.add_argument("--output", type=Path, default=ROOT / "demo" / "reports" / "verify_extract.md")
    args = parser.parse_args()
    try:
        report = compare(args.answer_key, args.extracted_dir, args.pdf_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown(report), encoding="utf-8")
        print(f"PDF {report['pdf_count']} / JSON {report['extracted_count']} / 불일치 {len(report['mismatches'])}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
