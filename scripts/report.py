#!/usr/bin/env python3
"""Read-only, as-of JSON aggregates of orders, invoices and actual lead time."""
import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import sys

from ledger import Rejected, day, read_rows

ROOT = Path(__file__).resolve().parents[1]


def bucket():
    return {"count": 0, "supply_amount": 0, "vat": 0, "total": 0}


def add(bucket_row, row, prefix):
    bucket_row["count"] += 1
    bucket_row["supply_amount"] += int(row[prefix + "_amount"])
    bucket_row["vat"] += int(row[prefix + "_vat"])
    bucket_row["total"] += int(row[prefix + "_total"])


def aggregate(ledger_rows, item_rows, reference):
    """Treat dates, not status labels, as evidence of an event by the cutoff."""
    quotes = {}
    orders, sales = defaultdict(bucket), defaultdict(bucket)
    customers = {}
    for row in ledger_rows:
        quote_date = day(row["quote_date"], "견적일")
        if quote_date > reference:
            continue
        quote_no = row["quote_no"]
        if quote_no in quotes:
            raise Rejected(f"견적번호 중복: {quote_no}")
        quotes[quote_no] = row
        name = row["customer"]
        if name not in customers:
            customers[name] = {"customer": name, "quote_count": 0, "quote_amount": 0,
                               "orders": bucket(), "sales": bucket()}
        customers[name]["quote_count"] += 1
        customers[name]["quote_amount"] += int(row["quote_amount"])
        for prefix, field, groups, ckey in (("order", "order_date", orders, "orders"),
                                            ("invoice", "invoice_date", sales, "sales")):
            if row[field] and day(row[field], field) <= reference:
                add(groups[row[field][:7]], row, prefix)
                add(customers[name][ckey], row, prefix)
    leads = defaultdict(list)
    for item in item_rows:
        row = quotes.get(item["quote_no"])
        if not row or not row["order_date"] or not row["invoice_date"]:
            continue
        order_date = day(row["order_date"], "수주일")
        invoice_date = day(row["invoice_date"], "매출일")
        if invoice_date > reference or order_date > reference:
            continue
        days = (invoice_date - order_date).days
        if days < 0:
            raise Rejected(f"납기일이 수주일보다 빠릅니다: {row['quote_no']}")
        leads[item["model"]].append((invoice_date.isoformat(), row["quote_no"], days))
    lead_by_model = []
    for model, values in sorted(leads.items()):
        durations = [entry[2] for entry in values]
        recent = max(values)
        lead_by_model.append({"model": model, "count": len(values),
                              "average_days": round(sum(durations) / len(values), 2),
                              "min_days": min(durations), "max_days": max(durations),
                              "latest_days": recent[2], "latest_date": recent[0]})
    return {"as_of": reference.isoformat(),
            "orders_by_month": [dict(month=m, **values) for m, values in sorted(orders.items())],
            "sales_by_month": [dict(month=m, **values) for m, values in sorted(sales.items())],
            "lead_by_model": lead_by_model,
            "customers": [customers[name] for name in sorted(customers)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="기준일 YYYY-MM-DD")
    parser.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger.csv")
    parser.add_argument("--items", type=Path, default=ROOT / "data" / "items.csv")
    args = parser.parse_args()
    try:
        result = aggregate(read_rows(args.ledger), read_rows(args.items), day(args.as_of, "기준일"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Rejected, OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
