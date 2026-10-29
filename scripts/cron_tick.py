#!/usr/bin/env python3
"""One weekday cron report; reconcile only confirmed prior deliveries."""
import argparse
from contextlib import closing
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import warnings
from zoneinfo import ZoneInfo

from briefing import build_daily, build_weekly, render_daily, render_weekly
from ledger import LEDGER_FIELDS, day, read_rows, write_rows

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo('Asia/Seoul')
LOCAL_BLOCKLIST = ROOT / 'config/blocklist.local.txt'


def require_fictional(rows, ledger, items, blocklist_path=LOCAL_BLOCKLIST):
    if not rows or not items.is_file():
        raise ValueError('가상 대장과 품목 파일이 없습니다. 공유하지 않습니다.')
    if any(not r['customer'].startswith('가상') or not r['sales_rep'].startswith('가상')
           or r['customer_contact'] or r['contact_title'] for r in rows):
        raise ValueError('가상 데이터만 확인되지 않아 공유하지 않습니다.')
    if not blocklist_path.is_file():
        warnings.warn('차단 목록 파일이 없어 문자열 검사를 건너뜁니다.', RuntimeWarning, stacklevel=2)
        return
    terms = [line.strip() for line in blocklist_path.read_text(encoding='utf-8-sig').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    for path in (ledger, items):
        text = path.read_text(encoding='utf-8-sig')
        if any(term in text for term in terms):
            raise ValueError('공유 금지 문자열이 있어 공유하지 않습니다.')


def delivered_days(job_id, db):
    if not db.exists():
        return set()
    with closing(sqlite3.connect(db)) as connection:
        receipts = connection.execute(
            "SELECT scheduled_instant FROM executions WHERE job_id=? AND status='completed' "
            "AND delivery_outcome='delivered'", (job_id,)).fetchall()
    return {datetime.fromisoformat(stamp).astimezone(KST).date().isoformat()
            for (stamp,) in receipts if stamp}


def reconcile(job_id, ledger, manifests, db, today):
    """After a successful cron delivery, persist only IDs in its saved report."""
    delivered = delivered_days(job_id, db)
    changed = 0
    for path in sorted(manifests.glob('cron_manifest_????????.json')):
        payload = json.loads(path.read_text(encoding='utf-8'))
        ref = day(payload['date'], '발송일')
        if payload['job_id'] != job_id or ref >= today or ref.isoformat() not in delivered:
            continue
        rows = read_rows(ledger)
        by_no = {r['quote_no']: r for r in rows}
        dirty = False
        for quote_no in set(payload['alert']) | set(payload['loss_question']):
            row = by_no.get(quote_no)
            if row is None or row['status'] != '진행중' or day(row['quote_date'], '견적일') > ref:
                continue
            row_changed = False
            if int(row['alert_count'] or 0) == 0:
                row.update(alert_count='1', next_alert_date='', updated_at=ref.isoformat())
                row_changed = True
            if quote_no in payload['loss_question'] and not row.get('loss_prompted_at'):
                row.update(loss_prompted_at=ref.isoformat(), updated_at=ref.isoformat())
                row_changed = True
            if row_changed:
                changed += 1
                dirty = True
        if dirty:
            write_rows(ledger, LEDGER_FIELDS, rows)
        path.rename(path.with_name(path.stem + '.done.json'))
    return changed


def prepare(job_id, reference, ledger, items, manifests):
    if reference.weekday() > 4:
        raise ValueError('평일 예약만 실행합니다')
    rows = read_rows(ledger)
    require_fictional(rows, ledger, items)
    mode = 'weekly' if reference.weekday() == 0 else 'daily'
    result = build_weekly(rows, reference) if mode == 'weekly' else build_daily(rows, reference)
    body = render_weekly(result) if mode == 'weekly' else render_daily(result)
    manifests.mkdir(parents=True, exist_ok=True)
    output = subprocess.run([sys.executable, str(ROOT / 'scripts/dashboard.py'),
                             '--as-of', reference.isoformat(), '--ledger', str(ledger),
                             '--items', str(items), '--out-dir', str(manifests)],
                            text=True, capture_output=True, check=True)
    html = Path(output.stdout.strip())
    if not html.is_file() or not html.resolve().is_relative_to(manifests.resolve()):
        raise ValueError('대시보드 HTML 생성 실패')
    if mode == 'weekly':
        pending = result['pending']
        alerts = [r['quote_no'] for r in pending['check'] + pending['loss_target']]
        loss = [r['quote_no'] for r in pending['loss_target']]
    else:
        alerts = [r['quote_no'] for r in result['alert']]
        loss = [r['quote_no'] for r in result['loss_question']]
    manifest = manifests / f"cron_manifest_{reference:%Y%m%d}.json"
    if manifest.exists():
        raise ValueError('같은 날의 발송 대기 기록이 이미 있습니다. 중복 발송을 막습니다.')
    manifest.write_text(json.dumps({'job_id': job_id, 'date': reference.isoformat(),
                                    'alert': alerts, 'loss_question': loss}, ensure_ascii=False),
                        encoding='utf-8')
    return '담당자님,\n' + body + '\nMEDIA:' + str(html.resolve())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--ledger', type=Path, default=ROOT / 'data/ledger.csv')
    parser.add_argument('--items', type=Path, default=ROOT / 'data/items.csv')
    parser.add_argument('--manifests', type=Path, default=ROOT / 'reports')
    parser.add_argument('--executions-db', type=Path, required=True)
    args = parser.parse_args()
    today = datetime.now(KST).date()
    try:
        require_fictional(read_rows(args.ledger), args.ledger, args.items)
        reconcile(args.job_id, args.ledger, args.manifests, args.executions_db, today)
        print(prepare(args.job_id, today, args.ledger, args.items, args.manifests))
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        print(f'예약 보고 중단: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
