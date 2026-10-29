#!/usr/bin/env python3
"""Build deterministic, entirely fictional sales-ledger demo PDFs and answer keys.

Requires reportlab (see requirements-demo.txt) and a Korean TTF font. The
source template is used for layout inspiration only; no source PDF is embedded.
"""
import argparse
import calendar
import csv
from datetime import date, timedelta
import json
import os
from pathlib import Path
import random

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ledger import LEDGER_FIELDS

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261031
AS_OF = date(2026, 10, 31)
CUTOFF = date(2026, 10, 27)
CATALOG = (
    ("A1", "ZYX", "VIRT-1001", 14_500_000),
    ("B2", "YXW", "VIRT-1002", 12_750_000),
    ("C3", "XWV", "VIRT-1003", 9_800_000),
    ("D4", "WVU", "VIRT-1004", 8_200_000),
    ("E5", "VUT", "VIRT-1005", 6_600_000),
    ("F6", "UTS", "VIRT-1006", 4_500_000),
    ("G7", "TSR", "VIRT-1007", 3_200_000),
)
CUSTOMERS = tuple(f"가상{word}기어연구소{i:02d}" for i, word in enumerate(
    ("청록", "노을", "은하", "새벽", "구름", "바람", "해솔", "별빛", "푸른", "달빛", "봄결", "여울"), 1))
ANSWER_FIELDS = "filename document_type quote_no customer document_date supply_amount vat total po_no items_json expected_result".split()
WIDTH, HEIGHT = A4


def font_path():
    path = os.environ.get("DEMO_KOREAN_FONT") or str(ROOT / "assets" / "fonts" / "DemoLedgerKR-Regular.ttf")
    if Path(path).is_file():
        return path
    raise SystemExit("Korean TTF font missing: restore assets/fonts/DemoLedgerKR-Regular.ttf")


def text(c, x, y, value, size=10, font="DemoKR"):
    c.setFillColorRGB(0.1, 0.15, 0.2)
    c.setFont(font, size)
    c.drawString(x, y, str(value))


def right(c, x, y, value, size=10):
    c.setFont("DemoKR", size)
    c.drawRightString(x, y, str(value))


def box(c, x, y, w, h, color=(0.25, 0.32, 0.4)):
    c.setStrokeColorRGB(*color)
    c.rect(x, y, w, h)


def pdf(path, title, draw):
    c = canvas.Canvas(str(path), pagesize=A4, pageCompression=1, invariant=1)
    c.setTitle(title)
    c.setAuthor("가상 데이터 시연")
    draw(c)
    c.showPage()
    c.save()


def table(c, items, y, variant=0):
    # All three variants retain the same semantic fields; headings and frames vary.
    left, right_edge = 42, WIDTH - 42
    xcols = (47, 78, 219, 291, 335, 410, 515)
    header = ("NO", "품명", "규격", "수량", "상품코드", "단가", "공급가액")
    if variant == 2:
        header = ("NO", "품목명", "규격", "수량", "품목코드", "단가", "금액")
    c.setFillColorRGB(0.91, 0.94, 0.96)
    c.rect(left, y - 8, right_edge - left, 23, fill=1, stroke=0)
    c.setStrokeColorRGB(0.3, 0.35, 0.4)
    c.line(left, y - 8, right_edge, y - 8)
    for x, label in zip(xcols, header):
        text(c, x, y, label, 8)
    for n, item in enumerate(items, 1):
        yy = y - 25 - (n - 1) * 22
        fields = (n, item["model"], item["part_no"], item["qty"],
                  item["product_code"], f"{item['unit_price']:,}", f"{item['amount']:,}")
        for x, value in zip(xcols, fields):
            text(c, x, yy, value, 8)
        c.setStrokeColorRGB(0.78, 0.8, 0.83)
        c.line(left, yy - 7, right_edge, yy - 7)
    return y - 35 - len(items) * 22


def quote_pdf(path, quote, stamped=False, received=None):
    """Recreate the supplied quote's grid/sections, never embed its original PDF."""
    def draw(c):
        c.setStrokeColorRGB(0.08, 0.08, 0.08)
        c.setLineWidth(0.7)
        text(c, 245, 760, "見  積  書", 19)
        c.line(213, 751, 368, 751)
        right(c, 565, 763, f"No. {quote['quote_no']}", 9)
        right(c, 565, 744, quote["quote_date"], 9)
        text(c, 32, 701, f"{quote['customer']} 담당자님 貴下", 10)
        text(c, 32, 680, "하기와 같이 견적을 제출합니다.", 9)
        text(c, 365, 682, "당사", 12)
        text(c, 365, 662, "가상 문서 · 연락처 없음", 8)
        text(c, 49, 660, "1.납품일정 : 발주 후 3개월", 9)
        text(c, 49, 642, "2.지불조건 : 납입 후 익월 말 현금 결제", 9)
        text(c, 49, 624, "3.인도조건 : 지정장소", 9)
        c.line(30, 609, 565, 609)
        text(c, 170, 590, f"일금 : {quote['amount']:,}원 정", 10)
        text(c, 415, 590, "(￦) - 부가세별도", 8)
        left, right_edge = 30, 565
        top, header_bottom, spec_bottom, table_bottom, footer_bottom = 578, 556, 534, 270, 194
        box(c, left, footer_bottom, right_edge - left, top - footer_bottom)
        c.setFillColorRGB(0.88, 0.88, 0.88)
        c.rect(left, header_bottom, right_edge-left, top-header_bottom, fill=1, stroke=0)
        c.setFillColorRGB(0.91, 0.94, 0.86)
        c.rect(415, footer_bottom, right_edge-415, table_bottom-footer_bottom, fill=1, stroke=0)
        for xx in (54, 325, 365, 415, 482):
            c.line(xx, table_bottom, xx, top)
        c.line(415, footer_bottom, 415, table_bottom)
        for yy in (header_bottom, spec_bottom, table_bottom):
            c.line(left, yy, right_edge, yy)
        for xx, title in ((37, "NO"), (173, "품    명"), (334, "수량"),
                          (372, "상품코드"), (437, "단가"), (505, "공급가액")):
            text(c, xx, 563, title, 8)
        text(c, 164, 541, quote["remark"], 9)
        for n, item in enumerate(quote["items"], 1):
            yy = spec_bottom - n * 22
            for xx, val in ((37, n), (65, f"{item['model']} {item['part_no']}"),
                            (337, item["qty"]), (369, item["product_code"]),
                            (426, f"{item['unit_price']:,}"), (489, f"{item['amount']:,}")):
                text(c, xx, yy + 7, val, 8)
            c.setStrokeColorRGB(0.75, 0.75, 0.75)
            c.line(left, yy, right_edge, yy)
        text(c, 35, 249, "* 담당 : 가상영업 담당", 8)
        text(c, 35, 233, "* 견적유효기간 : 작성 후 30일", 8)
        text(c, 35, 217, "* 발주 후 주문 취소 시 발주 금액의 30% 위약금이 발생합니다.", 7)
        text(c, 35, 202, "* 모든 당사 제품의 사양은 본 견적을 기준으로 합니다.", 7)
        text(c, 430, 225, "합 계", 9)
        right(c, 558, 225, f"￦{quote['amount']:,}", 10)
        if stamped:
            assert received is not None
            c.setStrokeColorRGB(0.75, 0.12, 0.16)
            c.setLineWidth(2)
            c.circle(515, 678, 26)
            c.setFillColorRGB(0.75, 0.12, 0.16)
            c.setFont("DemoKR", 9)
            c.drawCentredString(515, 682, "가상")
            c.drawCentredString(515, 668, "발주")
            text(c, 35, 171, f"팩스 수신일: {received.isoformat()} · 도장 회신 견적서", 9)
    pdf(path, quote["quote_no"] + (" 발주 확인" if stamped else " 견적서"), draw)


def order_pdf(path, quote, received, variant, exception=""):
    amount = quote["amount"]
    items = [dict(i) for i in quote["items"]]
    if variant == 3:
        for item in items:
            item["product_code"] = "C-" + item["product_code"]
    if exception == "mismatch":
        items[0]["qty"] += 1
        items[0]["amount"] += items[0]["unit_price"]
        amount += items[0]["unit_price"]
    vat = amount // 10
    order_no = f"PO-VIRTUAL-{quote['quote_no'][-9:]}"

    def draw(c):
        if variant == 1:
            box(c, 38, 104, 519, 660)
            text(c, 241, 729, "발 주 서", 23)
            text(c, 50, 697, f"발주번호: {order_no}", 10)
            text(c, 300, 697, f"발주일자: {received.isoformat()}", 10)
            text(c, 50, 676, f"발주처: {quote['customer']}", 10)
            text(c, 300, 676, "공급처: 당사", 10)
            text(c, 50, 655, "납품요청일: 발주 후 3개월", 10)
            text(c, 50, 634, f"연결: {quote['quote_no'] if not exception else '담당자 전달 기준'}", 9)
            y = table(c, items, 606, variant)
        elif variant == 2:
            text(c, 44, 766, "발 주 서", 23)
            box(c, 403, 707, 147, 56)
            text(c, 415, 743, "작성   검토   승인", 8)
            text(c, 44, 726, f"PO No. {order_no}", 11)
            text(c, 44, 697, f"상호: {quote['customer']}     수신: 당사", 10)
            text(c, 44, 676, f"작성일: {received.isoformat()}    납기: 발주 후 3개월", 10)
            text(c, 44, 649, "아래 품목을 주문합니다.", 9)
            y = table(c, items, 622, variant)
        else:
            text(c, 235, 777, "발 주 서", 23)
            box(c, 42, 630, 510, 126)
            text(c, 54, 731, f"발주일자: {received.isoformat()}       발주번호: {order_no}", 10)
            text(c, 54, 705, f"발주자: {quote['customer']}       공급처: 당사", 10)
            text(c, 54, 679, "요청 납기: 발주 후 3개월", 10)
            text(c, 54, 652, f"견적 연결: {quote['quote_no'] if not exception else '별도 확인'}", 9)
            y = table(c, items, 602, variant)
        right(c, 549, y - 12, f"공급가액 {amount:,}원", 10)
        right(c, 549, y - 32, f"부가세 {vat:,}원", 10)
        right(c, 549, y - 52, f"총액 {amount + vat:,}원", 11)
        text(c, 47, 89, "고객사 확인 · 연락처는 가상 문서에 포함하지 않음", 8)
    pdf(path, order_no + " 발주서", draw)
    return amount, vat, items, order_no


def invoice_pdf(path, quote, issue_date):
    amount = quote["amount"]
    vat = amount // 10
    approval = "DEMO-" + quote["quote_no"].replace("JJM", "")

    def draw(c):
        text(c, 172, 770, "계산서 발행확인서", 20)
        box(c, 45, 472, 505, 260)
        for idx, (label, value) in enumerate((
            ("발행일", issue_date.isoformat()), ("승인번호", approval),
            ("공급자", "가상제작상사"), ("공급받는자", quote["customer"]),
            ("공급가액", f"{amount:,}원"), ("세액", f"{vat:,}원"),
            ("합계", f"{amount + vat:,}원"))):
            text(c, 62, 698 - idx * 32, label, 11)
            text(c, 210, 698 - idx * 32, value, 11)
            c.line(48, 685 - idx * 32, 547, 685 - idx * 32)
        text(c, 48, 425, f"연결 견적번호: {quote['quote_no']}", 10)
    pdf(path, approval + " 발행확인서", draw)


def add_months(value, months):
    year, month = value.year + (value.month - 1 + months) // 12, (value.month - 1 + months) % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def make_quotes(rng):
    result = []
    for month in range(4, 11):
        days = (1, 2, 3, 20, 27) if month == 10 else ((5, 5, 12, 18, 24) if month == 9 else (5, 5, 12, 18, 24, 27))
        # Draw a full month's independent quotes until the whole-month invariant holds.
        for _ in range(10000):
            picks = []
            for idx, day_no in enumerate(days):
                while True:
                    chosen = rng.sample(CATALOG, rng.randint(3, 6))
                    items = [dict(line_no=j + 1, model=model, part_no=part, product_code=code,
                                  qty=(qty := rng.randint(1, 8)), unit_price=price, amount=qty * price)
                             for j, (model, part, code, price) in enumerate(chosen)]
                    amount = sum(x["amount"] for x in items)
                    if 10_000_000 <= amount <= 200_000_000:
                        break
                when = date(2026, month, day_no)
                suffix = "B" if idx == 1 and day_no == days[0] else "A"
                quote_no = f"JJM{when:%Y%m%d}-{suffix}"
                picks.append(dict(quote_no=quote_no, quote_date=when.isoformat(),
                                  customer=rng.choice(CUSTOMERS), amount=amount, items=items,
                                  remark="예비품 견적서" if rng.random() < .2 else f"SET-{rng.randint(1, 24):02d}"))
            total = sum(q["amount"] for q in picks)
            if 400_000_000 <= total <= 1_000_000_000:
                result.extend(picks)
                break
        else:
            raise RuntimeError(f"cannot satisfy month {month} amount bounds")
    assert len(result) == len({q["quote_no"] for q in result}) == 40
    return result


def csv_write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def answer(filename, kind, quote, when, amount, vat, items, result, po_no=""):
    return dict(filename=filename, document_type=kind, quote_no=quote["quote_no"],
                customer=quote["customer"], document_date=when.isoformat(),
                supply_amount=amount, vat=vat, total=amount + vat, po_no=po_no,
                items_json=json.dumps(items, ensure_ascii=False, separators=(",", ":")), expected_result=result)


def build(out):
    pdfs = out / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)
    prior_key = out / "answer_key.csv"
    if prior_key.exists():
        with prior_key.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = row.get("filename", "")
                if name and Path(name).name == name and name.endswith(".pdf"):
                    (pdfs / name).unlink(missing_ok=True)
    rng = random.Random(SEED)
    quotes = make_quotes(rng)
    # Exactly 20% are un-ordered: four old loss questions, two September alerts, two October in progress.
    unorder = {(4, 0), (5, 1), (7, 2), (8, 3), (9, 1), (9, 4), (10, 3), (10, 4)}
    rows, expected = [], []
    months = {}
    mismatch_quote = next(q for q in quotes if q["quote_date"][:7] == "2026-09" and q["quote_date"].endswith("05") and q["quote_no"].endswith("-B"))
    for q in quotes:
        month = int(q["quote_date"][5:7])
        idx = months.get(month, 0)
        months[month] = idx + 1
        quote_day = date.fromisoformat(q["quote_date"])
        qname = q["quote_no"] + "_견적서.pdf"
        quote_pdf(pdfs / qname, q)
        rows.append(answer(qname, "quote", q, quote_day, q["amount"], 0, q["items"], "registered"))
        record = {key: "" for key in LEDGER_FIELDS}
        record.update(quote_no=q["quote_no"], customer=q["customer"], customer_contact="",
                      contact_title="", sales_rep="가상영업 담당", quote_date=q["quote_date"],
                      quote_amount=q["amount"], alert_count="0", status="진행중", updated_at=q["quote_date"])
        if (month, idx) in unorder:
            if quote_day + timedelta(days=30) < AS_OF:
                record.update(alert_count="1", updated_at=AS_OF.isoformat())
            if quote_day + timedelta(days=60) < AS_OF:
                record.update(loss_prompted_at=AS_OF.isoformat(), updated_at=AS_OF.isoformat())
            if record["alert_count"] == "0":
                record["next_alert_date"] = (quote_day + timedelta(days=31)).isoformat()
        else:
            offsets = [n for n in range(3, 26) if quote_day + timedelta(days=n) < CUTOFF]
            received = quote_day + timedelta(days=rng.choice(offsets))
            variant = (idx % 4) + 1
            if variant == 4:
                name = q["quote_no"] + "_도장회신견적서.pdf"
                quote_pdf(pdfs / name, q, stamped=True, received=received)
                amount, vat, order_items, order_no = q["amount"], q["amount"] // 10, q["items"], ""
            else:
                name = q["quote_no"] + f"_발주서_양식{variant}.pdf"
                amount, vat, order_items, order_no = order_pdf(pdfs / name, q, received, variant)
            rows.append(answer(name, "order", q, received, amount, vat, order_items, "connected", order_no))
            record.update(status="수주완", order_date=received.isoformat(), po_no=order_no,
                          order_amount=amount, order_vat=vat, order_total=amount + vat,
                          updated_at=received.isoformat())
            eligible = [m for m in (1, 2, 3) if add_months(received, m) < CUTOFF]
            if eligible:
                issue = add_months(received, rng.choice(eligible))
                iname = q["quote_no"] + "_계산서발행확인서.pdf"
                invoice_pdf(pdfs / iname, q, issue)
                rows.append(answer(iname, "invoice", q, issue, amount, vat, q["items"], "issued"))
                record.update(status="매출완", invoice_date=issue.isoformat(),
                              invoice_amount=amount, invoice_vat=vat, invoice_total=amount + vat,
                              updated_at=issue.isoformat())
        expected.append(record)
    # Exceptions are additional POs, NOT counted among the 32 accepted orders.
    source = quotes[2]
    exception_date = date(2026, 9, 17)
    name = "견적번호없음_발주서.pdf"
    amount, vat, items, po_no = order_pdf(pdfs / name, source, exception_date, 1, "unlinked")
    row = answer(name, "order", source, exception_date, amount, vat, items, "unlinked", po_no)
    row["quote_no"] = ""
    rows.append(row)
    name = mismatch_quote["quote_no"] + "_발주서_수량차이.pdf"
    amount, vat, items, po_no = order_pdf(pdfs / name, mismatch_quote, date(2026, 9, 15), 3, "mismatch")
    rows.append(answer(name, "order", mismatch_quote, date(2026, 9, 15), amount, vat, items, "mismatch", po_no))
    csv_write(out / "answer_key.csv", ANSWER_FIELDS, rows)
    csv_write(out / "expected_ledger.csv", LEDGER_FIELDS, expected)
    print(f"generated {len(quotes)} quotes, {len([r for r in rows if r['document_type']=='order' and r['expected_result']=='connected'])} connected orders, {len([r for r in rows if r['document_type']=='invoice'])} invoices, 2 exception POs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "demo")
    args = parser.parse_args()
    pdfmetrics.registerFont(TTFont("DemoKR", font_path()))
    build(args.out_dir)


if __name__ == "__main__":
    main()
