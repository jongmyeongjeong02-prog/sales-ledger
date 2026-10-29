#!/usr/bin/env python3
"""Render report.py's read-only aggregates as one offline HTML dashboard."""
import argparse
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import json
from pathlib import Path
import sys

from ledger import Rejected, day, read_rows
from report import ROOT, aggregate, bucket

START = date(2026, 4, 1)


def millions(won):
    value = (Decimal(int(won)) / Decimal(1_000_000)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    return f'{value:,.1f}'


def build_view(report_data, ledger_rows, item_rows, reference):
    """Keep report.py totals untouched; derive only presentation/drilldown rows."""
    order_months = {r['month']: r for r in report_data['orders_by_month']}
    sale_months = {r['month']: r for r in report_data['sales_by_month']}
    months = []
    cursor = START
    while cursor <= reference:
        key = cursor.strftime('%Y-%m')
        months.append({'month': key, 'orders': order_months.get(key, bucket()),
                       'sales': sale_months.get(key, bucket())})
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    visible = {r['month'] for r in months}
    month_details = {key: {'orders': [], 'sales': []} for key in visible}
    rows_by_key = {r['quote_no']: r for r in ledger_rows}
    for row in ledger_rows:
        if row['quote_date'] > reference.isoformat():
            continue
        for field, kind, amount_key in (('order_date', 'orders', 'order_amount'),
                                        ('invoice_date', 'sales', 'invoice_amount')):
            value = row[field]
            if value and value <= reference.isoformat() and value[:7] in month_details:
                month_details[value[:7]][kind].append({
                    'quote_no': row['quote_no'], 'customer': row['customer'],
                    'amount': int(row[amount_key]), 'status': row['status']})
    for group in month_details.values():
        for entries in group.values():
            entries.sort(key=lambda x: x['quote_no'])
    # Match report.aggregate's event criteria; include orders from older quotes,
    # exclude future quotes/events, and retain the report-period customer ranking.
    customers_by_month = {}
    for key in visible:
        totals = {}
        for row in ledger_rows:
            if (row['quote_date'] > reference.isoformat() or not row['order_date']
                    or row['order_date'] > reference.isoformat() or row['order_date'][:7] != key):
                continue
            name = row['customer']
            entry = totals.setdefault(name, {'customer': name, 'orders': bucket()})
            entry['orders']['count'] += 1
            for field, source in (('supply_amount', 'order_amount'), ('vat', 'order_vat'), ('total', 'order_total')):
                entry['orders'][field] += int(row[source])
        customers_by_month[key] = sorted(totals.values(),
                                         key=lambda c: (-c['orders']['supply_amount'], c['customer']))[:5]
    forecast = []
    for row in ledger_rows:
        if row['status'] != '진행중' or not (START.isoformat() <= row['quote_date'] <= reference.isoformat()):
            continue
        quote_date = day(row['quote_date'], '견적일')
        elapsed = (reference - quote_date).days
        forecast.append({'quote_no': row['quote_no'], 'customer': row['customer'],
                         'quote_date': row['quote_date'], 'elapsed_days': elapsed,
                         'amount': int(row['quote_amount']), 'stage': ('loss_target' if elapsed > 60 else
                         'check' if elapsed >= 30 else 'submitted'), 'needs_check': 30 <= elapsed <= 60,
                         'loss_target_date': (quote_date + timedelta(days=61)).isoformat()})
    forecast.sort(key=lambda x: (-x['elapsed_days'], x['quote_no']))
    leads = []
    for stats in report_data['lead_by_model']:
        model = stats['model']
        eligible = []
        parts = set()
        for item in item_rows:
            if item['model'] != model:
                continue
            row = rows_by_key.get(item['quote_no'])
            if (not row or row['quote_date'] > reference.isoformat() or not row['order_date']
                    or not row['invoice_date'] or row['order_date'] > reference.isoformat()
                    or row['invoice_date'] > reference.isoformat()):
                continue
            parts.add(item.get('part_no', ''))
            eligible.append({'quote_no': row['quote_no'], 'customer': row['customer'],
                             'order_date': row['order_date'], 'invoice_date': row['invoice_date'],
                             'days': (day(row['invoice_date'], '매출일') - day(row['order_date'], '수주일')).days})
        eligible.sort(key=lambda x: (x['invoice_date'], x['quote_no']), reverse=True)
        leads.append({**stats, 'label': f"{model} {', '.join(sorted(p for p in parts if p))}".strip(),
                      'recent': eligible[:5]})
    quotes = [r for r in ledger_rows if START.isoformat() <= r['quote_date'] <= reference.isoformat()]
    quote_amount = sum(int(r['quote_amount']) for r in quotes)
    ordered_amount = sum(int(r['order_amount']) for r in quotes
                         if r['order_date'] and r['order_date'] <= reference.isoformat())
    current = months[-1] if months else {'orders': bucket(), 'sales': bucket()}
    top_customers = sorted((c for c in report_data['customers'] if c['orders']['count']),
                           key=lambda c: (-c['orders']['supply_amount'], c['customer']))[:5]
    summary = {'month_orders': current['orders']['supply_amount'],
               'month_sales': current['sales']['supply_amount'],
               'quote_amount': quote_amount, 'ordered_amount': ordered_amount,
               'quote_count': len(quotes),
               'ordered_count': sum(bool(r['order_date'] and r['order_date'] <= reference.isoformat()) for r in quotes),
               'conversion_percent': round(100 * ordered_amount / quote_amount, 1) if quote_amount else 0,
               'forecast_count': len(forecast), 'forecast_amount': sum(r['amount'] for r in forecast),
               'needs_check': sum(r['needs_check'] for r in forecast),
               'forecast_stages': {stage: sum(r['stage'] == stage for r in forecast)
                                   for stage in ('submitted', 'check', 'loss_target')}}
    return {'as_of': reference.isoformat(), 'report': report_data, 'months': months,
            'month_details': month_details, 'top_customers': top_customers,
            'customers_by_month': customers_by_month,
            'forecast': forecast, 'leads': leads, 'summary': summary}


def render_html(view):
    e = lambda value: escape(str(value), quote=True)
    s = view['summary']
    months = view['months']
    maximum = max((max(m['orders']['supply_amount'], m['sales']['supply_amount']) for m in months), default=0) or 1
    chart_rows = []
    for month in months:
        key = month['month']
        bars = []
        for kind, label in (('orders', '수주'), ('sales', '매출')):
            amount = month[kind]['supply_amount']
            height = min(100, round(amount / maximum * 100, 2))
            bars.append(f'<button class="bar-line {kind}" type="button" data-month="{e(key)}" '
                        f'data-kind="{kind}" aria-pressed="false" aria-label="{e(key)} {label} {millions(amount)}백만원 보기">'
                        f'<span class="bar-track"><span class="bar-fill" style="height:{height}%"></span>'
                        f'<span class="bar-value" style="bottom:calc({height}% + 4px)">'
                        f'{int((Decimal(amount) / Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))}'
                        f'</span></span></button>')
        chart_rows.append(f'<div class="chart-row"><div class="bar-pair">{"".join(bars)}</div>'
                          f'<span class="month-label">{e(key[5:])}월</span></div>')
    monthly_table = ''.join(
        f'<tr><td>{e(month["month"])}</td><td>{label}</td><td>{month[kind]["count"]}</td>'
        f'<td class="number">{millions(month[kind]["supply_amount"])}</td>'
        f'<td class="number">{millions(month[kind]["vat"])}</td>'
        f'<td class="number">{millions(month[kind]["total"])}</td></tr>'
        for month in months for kind, label in (('orders', '수주'), ('sales', '매출')))
    top_max = max((c['orders']['supply_amount'] for c in view['top_customers']), default=0) or 1
    customers = ''.join(
        f'<li><span class="customer-name">{e(c["customer"])}</span>'
        f'<span class="customer-meter"><span style="width:{min(100,round(c["orders"]["supply_amount"]/top_max*100,2))}%"></span></span>'
        f'<strong>{millions(c["orders"]["supply_amount"])} <small>백만원</small></strong></li>'
        for c in view['top_customers']) or '<li class="empty">수주 내역이 없습니다.</li>'
    forecast = ''.join(
        f'<tr><td class="mono">{e(r["quote_no"])}</td><td>{e(r["customer"])}</td>'
        f'<td class="mono">{e(r["quote_date"])}</td>'
        f'<td>{r["elapsed_days"]}일 {"<strong class=\"tag loss-target\">실주대상</strong>" if r["stage"] == "loss_target" else "<span class=\"tag danger\">확인필요</span>" if r["stage"] == "check" else ""}</td>'
        f'<td class="number">{millions(r["amount"])}</td><td class="mono">{e(r["loss_target_date"])}</td></tr>'
        for r in view['forecast']) or '<tr><td colspan="6" class="empty">진행중 견적이 없습니다.</td></tr>'
    lead_buttons = ''.join(
        f'<button type="button" class="lead-button" data-model="{e(r["model"])}" aria-pressed="false">'
        f'<span>{e(r["label"])}</span><strong>{r["average_days"]:.1f}<small>일</small></strong></button>'
        for r in view['leads']) or '<p class="empty">완료된 납기 자료가 없습니다.</p>'
    # JSON inside a script element must escape closing-tag delimiters even for inert application/json.
    blob = json.dumps(view, ensure_ascii=False, separators=(',', ':')).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    style = '''
:root{--bg:#f4f3ef;--paper:#fff;--ink:#192927;--muted:#5f706c;--line:#d8dfdb;--order:#087e72;--sale:#d17a40;--danger:#b63832;--soft:#e8f1ed}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;font-size:14px;line-height:1.45}
main{max-width:1600px;margin:auto;padding:28px 34px 70px}header{display:flex;align-items:flex-end;justify-content:space-between;padding-bottom:20px;border-bottom:2px solid var(--ink);gap:16px}
.eyebrow{font-weight:700;letter-spacing:.15em;font-size:11px;color:var(--order)}h1{font-size:28px;letter-spacing:-.045em;margin:4px 0 0}h2{font-size:20px;letter-spacing:-.035em;margin:0}h3{font-size:15px;margin:0}.asof{text-align:right;color:var(--muted)}.asof strong{display:block;color:var(--ink);font-size:16px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:22px 0 30px}.kpi{background:var(--paper);border:1px solid var(--line);padding:19px 17px;min-height:125px;min-width:0}.kpi .label{font-size:15px;color:var(--muted);font-weight:700}.kpi .value{font-size:27px;font-weight:750;letter-spacing:-.05em;margin-top:14px;white-space:nowrap}.kpi small{font-size:13px;letter-spacing:0;color:var(--muted);font-weight:500}.kpi .sub{color:var(--muted);font-size:13px;margin-top:5px;white-space:nowrap;letter-spacing:-.035em}.kpi.forecast-kpi{background:#e8f1ed}.kpi.forecast-kpi .sub b{color:var(--danger)}
section{margin-top:30px}.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:14px}.section-note{color:var(--muted);font-size:12px}.main-grid{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(280px,1fr);gap:24px}.main-grid section{min-width:0}.panel{background:var(--paper);border:1px solid var(--line);padding:20px;min-width:0}.legend{display:flex;gap:16px;color:var(--muted);font-size:12px}.legend span:before{content:"";display:inline-block;width:8px;height:8px;margin-right:6px;background:var(--order)}.legend span.sale-key:before{background:var(--sale)}
.chart{display:flex;align-items:stretch;gap:20px;overflow-x:auto;padding:42px 26px 3px 2px;min-height:220px}.chart-row{flex:1 0 65px;min-width:0;display:flex;flex-direction:column;align-items:stretch;gap:7px}.month-label{font-weight:700;color:var(--muted);font-size:12px;text-align:center}.bar-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;height:170px;align-items:end}.bar-line{display:flex;flex-direction:column;justify-content:flex-end;align-items:stretch;border:0;background:transparent;padding:0;min-width:0;height:100%;cursor:pointer;text-align:center;color:var(--ink)}.bar-track{display:flex;position:relative;align-items:flex-end;flex:1;width:100%;background:transparent}.bar-fill{display:block;width:100%;background:var(--order);min-height:0}.sales .bar-fill{background:var(--sale)}.bar-value{position:absolute;left:0;width:100%;font-variant-numeric:tabular-nums;font-size:15px;font-weight:800;line-height:1.1}.bar-line:hover .bar-fill,.bar-line[aria-pressed=true] .bar-fill{outline:2px solid var(--ink);outline-offset:1px}.bar-line:focus-visible,.lead-button:focus-visible,.detail-list button:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.drill{border-top:1px solid var(--line);margin-top:18px;padding-top:17px;min-height:114px}.drill-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.drill-head strong{font-size:14px}.drill-head span{color:var(--muted);font-size:12px}.detail-list{list-style:none;padding:0;margin:10px 0 0}.detail-list li{border-top:1px solid #edf0ee}.detail-list li:first-child{border-top:0}.detail-list button{display:grid;grid-template-columns:1fr 1.3fr auto auto;gap:9px;align-items:center;width:100%;padding:9px 4px;border:0;background:transparent;text-align:left;color:inherit;cursor:pointer;touch-action:pan-y}.detail-list button[aria-pressed=true]{background:var(--soft)}.detail-list .amount{text-align:right;font-weight:700;white-space:nowrap}.detail-list .state{font-size:11px;color:var(--muted)}.mono{font-variant-numeric:tabular-nums;font-family:Consolas,"Malgun Gothic",monospace;font-size:12px}.empty{color:var(--muted);padding:12px 0}
.monthly-detail{border-top:1px solid var(--line);margin-top:10px}.monthly-detail summary{cursor:pointer;display:flex;align-items:center;min-height:44px;color:var(--order);font-weight:700}.monthly-detail summary:focus-visible{outline:3px solid var(--ink)}.monthly-detail table{min-width:580px}
.customers{list-style:none;margin:0;padding:0}.customers li{display:grid;grid-template-columns:minmax(105px,1fr) minmax(36px,.8fr) auto;align-items:center;gap:12px;border-top:1px solid #edf0ee;padding:13px 0}.customers li:first-child{border-top:0}.customer-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.customer-meter{height:10px;background:transparent}.customer-meter span{display:block;height:100%;background:var(--order)}.customers strong{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}.customers small{font-weight:400;color:var(--muted)}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;text-align:left;min-width:790px}th{font-size:11px;color:var(--muted);letter-spacing:.02em;font-weight:700;border-bottom:1px solid var(--ink);padding:10px 8px}td{padding:12px 8px;border-bottom:1px solid var(--line)}td.number,th.number{text-align:right;font-variant-numeric:tabular-nums}.tag{display:inline-block;font-size:10px;font-weight:700;border-radius:3px;padding:2px 5px;white-space:nowrap}.danger{background:#fae9e7;color:var(--danger)}.loss-target{background:#243d38;color:#fff;font-weight:800}
.lead-layout{display:grid;grid-template-columns:minmax(215px,.7fr) minmax(0,1.3fr);gap:18px}.lead-list{display:grid;gap:6px;align-content:start}.lead-button{display:flex;align-items:center;justify-content:space-between;width:100%;min-height:48px;padding:10px 13px;border:1px solid var(--line);background:var(--paper);text-align:left;cursor:pointer;color:var(--ink)}.lead-button:hover,.lead-button[aria-pressed=true]{background:var(--soft);border-color:var(--order)}.lead-button strong{font-variant-numeric:tabular-nums;white-space:nowrap}.lead-button small{font-weight:400;color:var(--muted);margin-left:3px}.lead-detail{min-width:0}.statline{display:flex;flex-wrap:wrap;gap:10px;color:var(--muted);font-size:12px;margin:8px 0 4px}.statline b{color:var(--ink)}.lead-detail table{min-width:620px}footer{border-top:1px solid var(--line);color:var(--muted);font-size:11px;margin-top:38px;padding-top:14px}
@media (max-width:1250px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:900px){.main-grid{grid-template-columns:1fr}.lead-layout{grid-template-columns:1fr}.lead-list{grid-template-columns:repeat(2,1fr)}}
@media (max-width:640px){main{padding:18px 15px 48px}header{align-items:flex-start}h1{font-size:22px}.asof strong{font-size:12px}.kpis{gap:7px;margin:18px 0 22px}.kpi{min-height:113px;padding:13px 11px}.kpi .label{font-size:13px}.kpi .value{font-size:21px;white-space:normal}.kpi .sub{font-size:11px;white-space:normal}h2{font-size:18px}.section-head{align-items:flex-start;flex-direction:column;gap:3px}.panel{padding:14px}.main-grid{gap:8px}.detail-list button{grid-template-columns:1fr auto;gap:4px}.detail-list .state{grid-column:2}.detail-list .customer{grid-column:1}.lead-list{grid-template-columns:1fr 1fr}.lead-button{font-size:12px;padding:9px}.customers li{grid-template-columns:minmax(90px,1fr) minmax(25px,.5fr) auto;gap:7px;font-size:12px}.chart-row{flex-basis:55px}.bar-value{font-size:13px}}
@media print{body{background:#fff}main{max-width:none}.kpi,.panel{break-inside:avoid}button{color:inherit}}
'''
    script = '''
const DATA=JSON.parse(document.getElementById('dashboard-data').textContent);
const fmt=(n)=> (n/1000000).toLocaleString('ko-KR',{minimumFractionDigits:1,maximumFractionDigits:1});
function cell(tr,value,klass){const td=document.createElement('td');td.textContent=value;if(klass)td.className=klass;tr.appendChild(td)}
let activeMonth=null, activeKind=null, selectedRows=new Set(), dragging=false, mouseHandled=false;
function showCustomers(month){
  const rows=month===null?DATA.top_customers:DATA.customers_by_month[month]||[];
  const list=document.getElementById('customer-list');list.replaceChildren();
  document.getElementById('customer-title').textContent=month===null?'고객사별 수주 상위 5곳':month+' 고객사별 수주 상위 5곳';
  if(!rows.length){const li=document.createElement('li');li.className='empty';li.textContent='수주 내역이 없습니다.';list.appendChild(li);return}
  const max=Math.max(...rows.map(c=>c.orders.supply_amount),1);
  rows.forEach(c=>{const li=document.createElement('li'),name=document.createElement('span'),meter=document.createElement('span'),fill=document.createElement('span'),amount=document.createElement('strong');
    name.className='customer-name';name.textContent=c.customer;meter.className='customer-meter';fill.style.width=(100*c.orders.supply_amount/max)+'%';meter.appendChild(fill);
    amount.textContent=fmt(c.orders.supply_amount)+' 백만원';li.append(name,meter,amount);list.appendChild(li)})
}
function updateSelection(){
  const rows=activeMonth===null?[]:DATA.month_details[activeMonth]?.[activeKind]||[];
  document.querySelectorAll('#month-list button').forEach(b=>b.setAttribute('aria-pressed',String(selectedRows.has(Number(b.dataset.index)))));
  document.getElementById('month-selection').textContent='선택 '+selectedRows.size+'건 · 합계 '+fmt(rows.reduce((sum,r,i)=>sum+(selectedRows.has(i)?r.amount:0),0))+' 백만원';
}
function selectRow(index,force=false){
  if(force)selectedRows.add(index);else if(selectedRows.has(index))selectedRows.delete(index);else selectedRows.add(index);
  updateSelection();
}
function showMonth(month,kind){
  if(activeMonth===month&&activeKind===kind){month=null;kind=null}
  activeMonth=month;activeKind=kind;selectedRows.clear();
  document.querySelectorAll('.bar-line').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.month===month&&b.dataset.kind===kind)));
  document.getElementById('month-title').textContent=month===null?'월 막대를 선택해 주세요':month+' '+(kind==='orders'?'수주':'매출')+' 건 목록';
  const rows=month===null?[]:DATA.month_details[month]?.[kind]||[];
  document.getElementById('month-count').textContent=month===null?'건별 목록':rows.length+'건 · 공급가액 (백만원)';
  const list=document.getElementById('month-list');list.replaceChildren();
  if(month!==null&&!rows.length){const li=document.createElement('li');li.className='empty';li.textContent='해당 월에 기록된 건이 없습니다.';list.appendChild(li)}
  rows.forEach((r,i)=>{const li=document.createElement('li'),button=document.createElement('button');button.type='button';button.dataset.index=i;button.setAttribute('aria-pressed','false');button.setAttribute('aria-label',r.quote_no+' '+r.customer+' '+fmt(r.amount)+' 백만원 선택');
    ['quote_no','customer','amount','status'].forEach(key=>{const span=document.createElement('span');span.textContent=key==='amount'?fmt(r.amount):r[key];span.className=key==='quote_no'?'mono':key==='amount'?'amount':key==='status'?'state':'customer';button.appendChild(span)});li.appendChild(button);list.appendChild(li)});
  updateSelection();showCustomers(month);
}
function showLead(model){
  const row=DATA.leads.find(x=>x.model===model);if(!row)return;
  document.querySelectorAll('.lead-button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.model===model)));
  document.getElementById('lead-title').textContent=row.label+' · 최근 납기';
  document.getElementById('lead-stats').textContent='평균 '+row.average_days.toFixed(1)+'일  /  최소 '+row.min_days+'일  /  최대 '+row.max_days+'일';
  const body=document.getElementById('lead-body');body.replaceChildren();
  row.recent.forEach(r=>{const tr=document.createElement('tr');cell(tr,r.quote_no,'mono');cell(tr,r.customer);cell(tr,r.order_date,'mono');cell(tr,r.invoice_date,'mono');cell(tr,r.days+'일');body.appendChild(tr)})
}
document.addEventListener('pointerdown',ev=>{
  const row=ev.target.closest('#month-list button');
  if(row&&ev.pointerType==='mouse'&&ev.button===0){dragging=true;mouseHandled=true;selectRow(Number(row.dataset.index));ev.preventDefault()}
});
document.addEventListener('pointerenter',ev=>{
  const row=ev.target.closest('#month-list button');
  if(dragging&&row)selectRow(Number(row.dataset.index),true);
},true);
document.addEventListener('pointerup',()=>{dragging=false;setTimeout(()=>{mouseHandled=false},0)});
document.addEventListener('click',ev=>{
  const row=ev.target.closest('#month-list button');
  if(row){if(mouseHandled){mouseHandled=false;return}selectRow(Number(row.dataset.index));return}
  const b=ev.target.closest('button[data-month],button[data-model]');if(!b)return;
  if(b.dataset.month)showMonth(b.dataset.month,b.dataset.kind);else showLead(b.dataset.model)
});
// Native button keydown for Enter/Space dispatches click and toggles aria-pressed.
const first=DATA.leads[0];if(first)showLead(first.model);
'''
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>수주·매출 현황 | {e(view['as_of'])}</title><style>{style}</style></head><body><main>
<header><div><div class="eyebrow">수주·매출대장</div><h1>수주·매출 현황</h1></div><div class="asof">조회 기준일<strong>{e(view['as_of'])}</strong></div></header>
<div class="kpis" aria-label="핵심 지표">
<div class="kpi"><div class="label">이번 달 수주</div><div class="value">{millions(s['month_orders'])}<small> 백만원</small></div><div class="sub">수주일 기준 · 공급가액</div></div>
<div class="kpi"><div class="label">이번 달 매출</div><div class="value">{millions(s['month_sales'])}<small> 백만원</small></div><div class="sub">계산서일 기준 · 공급가액</div></div>
<div class="kpi"><div class="label">수주율</div><div class="value">{s['conversion_percent']:.1f}<small> %</small></div><div class="sub">견적 중 수주액 {millions(s['ordered_amount'])} / 견적액 {millions(s['quote_amount'])} 백만원</div><div class="sub">발주 {s['ordered_count']}건 / 견적 {s['quote_count']}건</div></div>
<div class="kpi forecast-kpi"><div class="label">잔여 포캐스트</div><div class="value">{s['forecast_count']}<small>건 · {millions(s['forecast_amount'])} 백만원</small></div><div class="sub">(견적제출 {s['forecast_stages']['submitted']} + 확인필요 {s['forecast_stages']['check']} + 실주대상 {s['forecast_stages']['loss_target']})</div></div>
</div>
<div class="main-grid"><section aria-labelledby="trend-title"><div class="section-head"><h2 id="trend-title">월별 추이</h2><div class="legend"><span>수주</span><span class="sale-key">매출</span></div></div>
<div class="panel"><div class="section-note">공급가액 · 백만원 / 막대를 눌러 건별 내역 보기</div><div class="chart" aria-label="월별 수주와 매출">{''.join(chart_rows) or '<p class="empty">표시할 월이 없습니다.</p>'}</div>
<div class="drill" aria-live="polite"><div class="drill-head"><strong id="month-title">월 막대를 선택해 주세요</strong><span id="month-count">건별 목록</span></div><div id="month-selection" role="status">선택 0건 · 합계 0.0 백만원</div><ul class="detail-list" id="month-list"></ul></div>
<details class="monthly-detail"><summary>월별 금액 상세 · 건수 / 공급가액 / VAT / 총계</summary><div class="table-wrap"><table><thead><tr><th>월</th><th>구분</th><th>건수</th><th>공급가액 (백만원)</th><th>VAT</th><th>총계</th></tr></thead><tbody>{monthly_table}</tbody></table></div></details></div></section>
<section aria-labelledby="customer-title"><div class="section-head"><h2 id="customer-title">고객사별 수주 상위 5곳</h2><span class="section-note">공급가액 · 백만원</span></div><div class="panel"><ol class="customers" id="customer-list">{customers}</ol></div></section></div>
<section aria-labelledby="forecast-title"><div class="section-head"><h2 id="forecast-title">잔여 포캐스트 안건</h2><span class="section-note">진행중 · 경과일 많은 순 / 공급가액 백만원</span></div>
<div class="panel table-wrap"><table><thead><tr><th>견적번호</th><th>고객사</th><th>견적일</th><th>경과일</th><th class="number">견적 금액</th><th>실주대상 기준일</th></tr></thead><tbody>{forecast}</tbody></table></div></section>
<section aria-labelledby="lead-title-section"><div class="section-head"><h2 id="lead-title-section">품목별 실제 납기</h2><span class="section-note">계산서일 − 수주일 / 최근 5품목행</span></div><div class="lead-layout"><div class="lead-list">{lead_buttons}</div>
<div class="panel lead-detail" aria-live="polite"><h3 id="lead-title">품목을 선택해 주세요</h3><div class="statline" id="lead-stats"></div><div class="table-wrap"><table><thead><tr><th>견적번호</th><th>고객사</th><th>수주일</th><th>계산서일</th><th>납기 일수</th></tr></thead><tbody id="lead-body"></tbody></table></div></div></div></section>
<footer>수주·매출·고객·납기 집계: report.py 기준. 포캐스트는 현재 대장 상태의 읽기 전용 화면이며 자동 실주를 적용하지 않습니다.</footer>
</main><script id="dashboard-data" type="application/json">{blob}</script><script>{script}</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', required=True, help='조회 기준일 YYYY-MM-DD')
    parser.add_argument('--ledger', type=Path, default=ROOT / 'data/ledger.csv')
    parser.add_argument('--items', type=Path, default=ROOT / 'data/items.csv')
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    try:
        reference = day(args.as_of, '기준일')
        ledger_rows, item_rows = read_rows(args.ledger), read_rows(args.items)
        report_data = aggregate(ledger_rows, item_rows, reference)
        view = build_view(report_data, ledger_rows, item_rows, reference)
        output = args.out_dir / f'dashboard_{reference:%Y%m%d}.html'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_html(view), encoding='utf-8')
        print(output)
    except (Rejected, ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
