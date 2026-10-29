#!/usr/bin/env python3
"""Read-only Korean Slack briefing preview; never sends or marks notices."""
import argparse
from datetime import date, timedelta
from pathlib import Path
import sys

from dashboard import millions
from ledger import Rejected, advance_rows, cover_reported_rows, day, read_rows

ROOT = Path(__file__).resolve().parents[1]


def pending_rows(rows, reference):
    """Open quotes known by the cutoff; a later order/loss is not backdated."""
    current = []
    for row in rows:
        quoted = day(row['quote_date'], '견적일')
        if quoted > reference:
            continue
        if row['order_date'] and day(row['order_date'], '수주일') <= reference:
            continue
        if row['lost_date'] and day(row['lost_date'], '실주일') <= reference:
            continue
        # A lost row with no dated loss cannot be reconstructed historically.
        if row['status'] == '실주' and not row['lost_date']:
            continue
        elapsed = (reference - quoted).days
        stage = 'submitted' if elapsed < 30 else 'check' if elapsed <= 60 else 'loss_target'
        current.append({'quote_no': row['quote_no'], 'customer': row['customer'],
                        'amount': int(row['quote_amount']), 'elapsed': elapsed,
                        'stage': stage})
    return sorted(current, key=lambda x: (-x['elapsed'], x['quote_no']))


def build_weekly(rows, reference):
    start = reference - timedelta(days=reference.weekday() + 7)
    end = start + timedelta(days=6)
    buckets = {}
    for key, field, amount_field in (('orders', 'order_date', 'order_amount'),
                                      ('sales', 'invoice_date', 'invoice_amount')):
        selected = [r for r in rows if r[field] and
                    start <= day(r[field], field) <= end and
                    day(r['quote_date'], '견적일') <= reference]
        buckets[key] = {'count': len(selected), 'amount': sum(int(r[amount_field]) for r in selected)}
    pending = pending_rows(rows, reference)
    return {'as_of': reference.isoformat(), 'from': start.isoformat(), 'to': end.isoformat(),
            **buckets, 'pending': {'count': len(pending), 'amount': sum(r['amount'] for r in pending),
                                   **{stage: [r for r in pending if r['stage'] == stage]
                                      for stage in ('submitted', 'check', 'loss_target')}}}


def build_daily(rows, reference):
    # advance_rows only mutates these copies. Unsent older items are catch-up
    # notices on the first run, not falsely described as crossing today.
    actions = advance_rows([dict(r) for r in rows], reference)
    by_no = {r['quote_no']: r for r in rows}
    def entries(kind):
        found = []
        for action in actions:
            if action['kind'] != kind:
                continue
            row = by_no[action['quote_no']]
            found.append({'quote_no': row['quote_no'], 'customer': row['customer'],
                          'amount': int(row['quote_amount']),
                          'elapsed': (reference - day(row['quote_date'], '견적일')).days,
                          'due_date': action['due_date']})
        return sorted(found, key=lambda r: (-r['elapsed'], r['quote_no']))
    return {'as_of': reference.isoformat(), 'alert': entries('alert'),
            'loss_question': entries('loss_question')}


def detail(row):
    return f"{row['quote_no']} / {row['customer']} / {millions(row['amount'])} 백만원 / 견적 후 {row['elapsed']}일"


def render_weekly(data):
    p = data['pending']
    lines = [f"[주간 보고] {data['from']}~{data['to']} (기준일 {data['as_of']})",
             f"1. 수주: {data['orders']['count']}건 · {millions(data['orders']['amount'])} 백만원 (수주일 기준)",
             f"2. 매출: {data['sales']['count']}건 · {millions(data['sales']['amount'])} 백만원 (계산서 발행일 기준)",
             f"3. 발주서 미수령 견적: {p['count']}건 · {millions(p['amount'])} 백만원",
             f"  ◦ 견적제출 {len(p['submitted'])}건 (30일 미만)",
             f"  ◦ 확인필요 {len(p['check'])}건 → 고객 진행 상황 확인 필요"]
    lines.extend('    - ' + detail(r) for r in p['check'])
    lines.append(f"  ◦ 실주대상 {len(p['loss_target'])}건 → 실주 처리 시 \"실주 JJM○○\"로 답해 주세요")
    lines.extend('    - ' + detail(r) for r in p['loss_target'])
    return '\n'.join(lines)


def render_daily(data):
    lines = [f"[일일 현황] {data['as_of']}"]
    if not data['alert'] and not data['loss_question']:
        return '\n'.join(lines + ['새 알림 없음'])
    if data['alert']:
        lines.append(f"미발송 확인필요 알림 {len(data['alert'])}건 → 고객 진행 상황 확인 필요")
        lines.extend('- ' + detail(r) for r in data['alert'])
    if data['loss_question']:
        lines.append(f"미발송 실주대상 질문 {len(data['loss_question'])}건 → 실주 처리할까요?")
        lines.extend('- ' + detail(r) for r in data['loss_question'])
        lines.append('처리 지시: "실주 JJM○○" 또는 "실주대상 모두 실주". 답변 전에는 진행중으로 유지합니다.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=('weekly', 'daily'))
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--ledger', type=Path, default=ROOT / 'data/ledger.csv')
    parser.add_argument('--assume-sent-through', help='미리보기 전용: 이 날짜까지 누적 건을 발송 처리한 것으로 가정')
    args = parser.parse_args()
    try:
        reference = day(args.as_of, '기준일')
        rows = read_rows(args.ledger)
        if args.assume_sent_through:
            assumed = day(args.assume_sent_through, '가정한 발송일')
            if assumed > reference:
                raise Rejected('가정한 발송일은 기준일 이후일 수 없습니다')
            rows = [dict(r) for r in rows]
            cover_reported_rows(rows, assumed)
        print(render_weekly(build_weekly(rows, reference)) if args.mode == 'weekly'
              else render_daily(build_daily(rows, reference)))
    except (OSError, Rejected, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
