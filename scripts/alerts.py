#!/usr/bin/env python3
"""Preview pending quote notices; mark them sent only with --apply.

No Slack/customer message is sent. A separate human-reviewed process may send
one alert and one loss question after reading this JSON. Defaults to data/ledger.csv.
"""
import argparse
import json
from pathlib import Path
import sys

from ledger import LEDGER_FIELDS, Rejected, advance_rows, cover_reported_rows, day, read_rows, write_rows

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="기준일 YYYY-MM-DD")
    parser.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger.csv")
    parser.add_argument("--apply", action="store_true", help="명시적으로 대장에 반영")
    parser.add_argument("--cover", action="store_true", help="이미 보고했거나 초기 누적분인 구간을 보낸 것으로 기록")
    args = parser.parse_args()
    try:
        reference = day(args.as_of, "기준일")
        if args.apply and (ROOT / "demo") in args.ledger.resolve().parents:
            raise Rejected("demo/ 예상 대장은 변경할 수 없습니다")
        rows = read_rows(args.ledger)
        actions = cover_reported_rows(rows, reference) if args.cover else advance_rows(rows, reference)
        if args.apply and actions:
            write_rows(args.ledger, LEDGER_FIELDS, rows)
        result = {
            "as_of": reference.isoformat(), "applied": args.apply,
            "alert_targets": [x for x in actions if x["kind"] == "alert"],
            "loss_question_targets": [x for x in actions if x["kind"] == "loss_question"],
            "covered_targets": actions if args.cover else [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, Rejected, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
