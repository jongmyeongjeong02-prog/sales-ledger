#!/usr/bin/env python3
"""JSON-to-CSV sales ledger. All writes require prior human review of JSON."""
import argparse
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import sys

LEDGER_FIELDS = "quote_no customer customer_contact contact_title sales_rep quote_date quote_amount status po_no order_date order_amount order_vat order_total invoice_date invoice_amount invoice_vat invoice_total next_alert_date alert_count loss_prompted_at lost_date memo updated_at".split()
ITEM_FIELDS = "quote_no line_no model part_no product_code customer_item_code remark qty unit_price amount order_date delivery_date lead_days".split()


class Rejected(Exception):
    pass


def required(value, label):
    if value is None or str(value).strip() == "":
        raise Rejected(f"{label} 확인 필요: 기록하지 않았습니다")
    return value


def day(value, label):
    value = required(value, label)
    try:
        parsed = date.fromisoformat(str(value))
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except ValueError:
        raise Rejected(f"{label}은 YYYY-MM-DD 날짜여야 합니다") from None


def integer(value, label, minimum=0):
    required(value, label)
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < minimum:
        raise Rejected(f"{label}은 {minimum} 이상의 정수여야 합니다")
    return int(value)


def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if path.name == "ledger.csv":
        for row in rows:
            row.setdefault("loss_prompted_at", "")
    return rows


def write_rows(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def next_alert(quote_date, reference):
    return (quote_date + timedelta(days=31)).isoformat()


def check_items(items, label):
    if not isinstance(items, list) or not items:
        raise Rejected(f"{label} 품목 확인 필요: 기록하지 않았습니다")
    for item in items:
        required(item.get("model"), "모델명")
        integer(item.get("qty"), "수량", 1)
        integer(item.get("unit_price"), "단가")


def differences(base_amount, base_items, supplied, amount_key, require_items=False):
    diffs = []
    amount = integer(supplied.get(amount_key), "금액")
    if amount != int(base_amount):
        diffs.append(f"금액: 견적 {base_amount} / 입력 {amount}")
    incoming = supplied.get("items")
    if require_items or incoming is not None:
        check_items(incoming, "입력")
        # Customer item codes differ; match by model, qty and unit price (including repeated lines).
        from collections import Counter
        base = Counter((i["model"], int(i["qty"]), int(i["unit_price"])) for i in base_items)
        other = Counter((i["model"], int(i["qty"]), int(i["unit_price"])) for i in incoming)
        if base != other:
            diffs.append(f"품목/수량/단가: 견적 {sorted(base.elements())} / 입력 {sorted(other.elements())}")
    return diffs


def check_totals(payload, prefix):
    amount = integer(payload.get(prefix + "_amount"), "공급가액")
    vat = integer(payload.get(prefix + "_vat"), "VAT")
    total = integer(payload.get(prefix + "_total"), "총계")
    if amount + vat != total:
        raise Rejected(f"금액 합계 불일치: {amount} + {vat} != {total}")


def advance_rows(rows, reference):
    """Mark pending notices in memory; never infer a loss without instruction."""
    actions = []
    for row in rows:
        if row["status"] != "진행중":
            continue
        quote_date = day(row["quote_date"], "견적일")
        elapsed = (reference - quote_date).days
        if elapsed > 60:
            if not row.get("loss_prompted_at"):
                # The 30-day reminder is obsolete; never show both stages.
                row.update(alert_count="1", next_alert_date="", loss_prompted_at=reference.isoformat(),
                           updated_at=reference.isoformat())
                actions.append({"kind": "loss_question", "quote_no": row["quote_no"],
                                "due_date": (quote_date + timedelta(days=61)).isoformat(),
                                "question": "실주 처리할까요?"})
        elif 30 < elapsed <= 60 and int(row["alert_count"] or 0) == 0:
            row.update(alert_count="1", next_alert_date="", updated_at=reference.isoformat())
            actions.append({"kind": "alert", "quote_no": row["quote_no"],
                            "due_date": (quote_date + timedelta(days=31)).isoformat()})
    return actions


def cover_reported_rows(rows, reference):
    """In memory, record stages already listed in a report or explicitly baselined."""
    covered = []
    for row in rows:
        if row["status"] != "진행중":
            continue
        elapsed = (reference - day(row["quote_date"], "견적일")).days
        if elapsed < 30:
            continue
        if int(row["alert_count"] or 0) == 0:
            row.update(alert_count="1", next_alert_date="", updated_at=reference.isoformat())
            covered.append({"kind": "alert", "quote_no": row["quote_no"]})
        if elapsed > 60 and not row.get("loss_prompted_at"):
            row.update(loss_prompted_at=reference.isoformat(), updated_at=reference.isoformat())
            covered.append({"kind": "loss_question", "quote_no": row["quote_no"]})
    return covered


def operate(command, payload, data_dir, as_of=None):
    lp, ip = data_dir / "ledger.csv", data_dir / "items.csv"
    if command != "show" and (Path(__file__).resolve().parents[1] / "demo") in lp.resolve().parents:
        raise Rejected("demo/ 예상 대장은 변경할 수 없습니다")
    ledger, items = read_rows(lp), read_rows(ip)
    if command == "show":
        selected = [r for r in ledger if not payload.get("quote_no") or r["quote_no"] == payload["quote_no"]]
        print(json.dumps({"ledger": selected, "items": [i for i in items if i["quote_no"] in {r["quote_no"] for r in selected}]}, ensure_ascii=False, indent=2))
        return
    if command == "advance":
        reference = day(as_of, "기준일(--as-of)")
        actions = advance_rows(ledger, reference)
        for action in actions:
            print(f"{'실주 처리할까요?' if action['kind'] == 'loss_question' else '유효기간 만료'}: {action['quote_no']}")
        if actions:
            write_rows(lp, LEDGER_FIELDS, ledger)
        return
    if command == "lost-all":
        reference = day(as_of, "기준일(--as-of)")
        targets = [row for row in ledger if row["status"] == "진행중" and
                   reference > day(row["quote_date"], "견적일") + timedelta(days=60)]
        for row in targets:
            row.update(status="실주", lost_date=reference.isoformat(), next_alert_date="",
                       updated_at=reference.isoformat())
            print(f"기록: {row['quote_no']} 실주")
        if targets:
            write_rows(lp, LEDGER_FIELDS, ledger)
        return
    quote_no = payload.get("quote_no")
    if not isinstance(quote_no, str) or not quote_no.strip():
        raise Rejected("미연결: 견적번호 확인 필요; 기록하지 않았습니다")
    existing = next((r for r in ledger if r["quote_no"] == quote_no), None)
    if command == "add-quote":
        if existing:
            raise Rejected(f"중복 견적번호 {quote_no}: 기록하지 않았습니다")
        quote_date = day(payload.get("quote_date"), "견적일")
        for key in ("customer", "sales_rep"):
            required(payload.get(key), key)
        quote_amount = integer(payload.get("quote_amount"), "견적금액")
        incoming = payload.get("items")
        check_items(incoming, "견적")
        if sum(integer(i.get("amount"), "품목 공급가액") for i in incoming) != quote_amount or any(
            integer(i["qty"], "수량") * integer(i["unit_price"], "단가") != integer(i["amount"], "품목 공급가액") for i in incoming
        ):
            raise Rejected("견적 금액/품목 합계 불일치: 기록하지 않았습니다")
        lines = [str(required(i.get("line_no"), "품목 번호")) for i in incoming]
        if len(set(lines)) != len(lines):
            raise Rejected("품목 번호 중복: 기록하지 않았습니다")
        today = date.today().isoformat()
        row = {key: "" for key in LEDGER_FIELDS}
        row.update({key: payload[key] for key in ("customer", "customer_contact", "contact_title", "sales_rep")})
        row.update(quote_no=quote_no, quote_date=quote_date.isoformat(), quote_amount=str(quote_amount),
                   status="진행중", next_alert_date=(quote_date + timedelta(days=31)).isoformat(),
                   alert_count="0", memo=payload.get("memo", ""), updated_at=today)
        new_items = []
        for i in incoming:
            item = {key: "" for key in ITEM_FIELDS}
            item.update({key: i.get(key, "") for key in ("line_no", "model", "part_no", "product_code", "remark", "qty", "unit_price", "amount")})
            item["quote_no"] = quote_no
            new_items.append(item)
        write_rows(ip, ITEM_FIELDS, items + new_items)
        write_rows(lp, LEDGER_FIELDS, ledger + [row])
        print(f"등록: {quote_no} 진행중")
        return
    if not existing:
        raise Rejected(f"미연결: 대장에 없는 견적번호 {quote_no}; 기록하지 않았습니다")
    related = [i for i in items if i["quote_no"] == quote_no]
    transitions = {"add-order": "진행중", "add-invoice": "수주완", "lost": "진행중", "reopen": "실주"}
    if existing["status"] != transitions[command]:
        raise Rejected(f"상태 전환 불가: 현재 {existing['status']}, 요청 {command}; 기록하지 않았습니다")
    today = date.today().isoformat()
    if command == "add-order":
        stamped = payload.get("stamped_quote") is True
        if stamped:
            if payload.get("po_no") not in (None, ""):
                raise Rejected("도장 회신 견적서는 발주번호를 빈칸으로 기록합니다")
        else:
            required(payload.get("po_no"), "발주번호")
        order_date = day(payload.get("received_date"), "발주서 전달일/확정 수주일")
        if stamped:
            amount = integer(payload.get("order_amount"), "공급가액")
            vat = amount // 10
            total = amount + vat
            if payload.get("order_vat") not in (None, "") and integer(payload["order_vat"], "VAT") != vat:
                raise Rejected(f"VAT 차이: 입력 {payload['order_vat']} / 계산 {vat}; 기록하지 않았습니다")
            if payload.get("order_total") not in (None, "") and integer(payload["order_total"], "총계") != total:
                raise Rejected(f"총계 차이: 입력 {payload['order_total']} / 계산 {total}; 기록하지 않았습니다")
        else:
            check_totals(payload, "order")
            vat, total = integer(payload["order_vat"], "VAT"), integer(payload["order_total"], "총계")
        diffs = differences(existing["quote_amount"], related, payload, "order_amount", True)
        if diffs:
            raise Rejected("차이 확인 필요 (기록하지 않음): " + "; ".join(diffs))
        memo_append = payload.get("memo_append", "")
        if not isinstance(memo_append, str):
            raise Rejected("메모는 문자열이어야 합니다: 기록하지 않았습니다")
        from collections import defaultdict
        codes = defaultdict(list)
        for i in payload["items"]:
            codes[(i["model"], int(i["qty"]), int(i["unit_price"]))].append(i.get("customer_item_code", ""))
        for i in related:
            i["customer_item_code"] = codes[(i["model"], int(i["qty"]), int(i["unit_price"]))].pop()
            i["order_date"] = order_date.isoformat()
        existing.update(po_no="" if stamped else payload["po_no"], order_date=order_date.isoformat(),
                        order_amount=payload["order_amount"], order_vat=vat,
                        order_total=total, status="수주완", next_alert_date="")
        if memo_append:
            existing["memo"] = "\n".join(x for x in (existing["memo"], memo_append) if x)
    elif command == "add-invoice":
        invoice_date = day(payload.get("invoice_date"), "계산서 발행일")
        order_date = day(existing["order_date"], "수주일")
        if invoice_date < order_date:
            raise Rejected("계산서 발행일이 수주일보다 빠릅니다: 기록하지 않았습니다")
        check_totals(payload, "invoice")
        diffs = differences(existing["quote_amount"], related, payload, "invoice_amount")
        if int(payload["invoice_amount"]) != int(existing["order_amount"]):
            diffs.append(f"금액: 발주 {existing['order_amount']} / 계산서 {payload['invoice_amount']}")
        for key, label in (("vat", "VAT"), ("total", "총계")):
            if int(payload[f"invoice_{key}"]) != int(existing[f"order_{key}"]):
                diffs.append(f"{label}: 발주 {existing[f'order_{key}']} / 계산서 {payload[f'invoice_{key}']}")
        if diffs:
            raise Rejected("차이 확인 필요 (기록하지 않음): " + "; ".join(diffs))
        for i in related:
            i["delivery_date"] = invoice_date.isoformat()
            i["lead_days"] = (invoice_date - order_date).days
        existing.update(invoice_date=invoice_date.isoformat(), invoice_amount=payload["invoice_amount"],
                        invoice_vat=payload["invoice_vat"], invoice_total=payload["invoice_total"], status="매출완")
    elif command == "lost":
        existing.update(status="실주", lost_date=day(payload.get("lost_date"), "실주일").isoformat(), next_alert_date="")
    elif command == "reopen":
        reference = day(payload.get("reopen_date"), "재진행일")
        existing.update(status="진행중", lost_date="", next_alert_date=(
            next_alert(day(existing["quote_date"], "견적일"), reference)
            if int(existing["alert_count"] or 0) == 0 else ""))
    existing["updated_at"] = today
    if command in ("add-order", "add-invoice"):
        write_rows(ip, ITEM_FIELDS, items)
    write_rows(lp, LEDGER_FIELDS, ledger)
    print(f"기록: {quote_no} {existing['status']}")


def main():
    parser = argparse.ArgumentParser(description="확인된 JSON을 CSV 대장에 기록")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--as-of", help="advance/lost-all 기준일 YYYY-MM-DD")
    parser.add_argument("command", choices=("add-quote", "add-order", "add-invoice", "lost", "lost-all", "reopen", "show", "advance"))
    parser.add_argument("input", nargs="?", type=Path, help="확인된 JSON 파일 (show는 생략 가능)")
    args = parser.parse_args()
    if args.command in ("advance", "lost-all") and not args.as_of:
        parser.error(f"{args.command}는 --as-of YYYY-MM-DD가 필요합니다")
    if args.command in ("advance", "lost-all") and args.input:
        parser.error(f"{args.command}는 JSON 입력을 받지 않습니다")
    if args.command not in ("show", "advance", "lost-all") and not args.input:
        parser.error("JSON 입력 파일이 필요합니다")
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig")) if args.input else {}
        if not isinstance(payload, dict):
            raise Rejected("JSON 객체가 필요합니다")
        operate(args.command, payload, args.data_dir, args.as_of)
    except (Rejected, OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stdout)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
