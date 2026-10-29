# Offline Sales Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the existing read-only `report.py` aggregates as an offline, responsive, interactive HTML dashboard and send the 2026-10-31 screenshot/file.

**Architecture:** `scripts/dashboard.py` imports `report.aggregate()` without changing calculation logic, reads the same ledger/items, builds only presentation/drilldown data, then writes a single HTML file with embedded CSS/JS/data. Profile skill/project guidance connects future Korean Slack report requests to today's dashboard artifact.

**Tech Stack:** Python standard library, HTML/CSS/vanilla JavaScript; no external runtime assets.

**Spec:** User's dashboard request in the 2026-10-27 Slack conversation; PROJECT.md controls date/status/security rules.

## Global Constraints

- Read-only ledger/items; never `alerts --apply`, never push.
- Amounts shown in 백만원 with one decimal; chart spans 2026-04 through the as-of month.
- Quotes, orders, sales and leads use their dated evidence; customer/rate/forecast presentation uses the same ledger source and is labeled clearly.
- No real names, company information or credentials in tracked artifacts. HTML output under ignored `reports/`.
- Dashboard is primarily a **Monitor** surface: dense, scannable, no marketing hero.

## Review Focus

1. Zero/missing months still appear and empty drilldowns say so; test in Task 1.
2. The +30-day strict boundary is not an alert on day 30; test in Task 1.
3. No divide-by-zero for quote-free periods or empty CSV; test in Task 1.
4. Embedded customer names cannot execute HTML/JS; test in Task 2.
5. Existing test suites must tolerate already-populated ignored `data/` without changing it; test in Task 3.

### Task 1: Read-only view model and numeric parity

**Files:** Create `scripts/dashboard.py`; create `tests/test_dashboard.py`.

**Interfaces:** `build_view(aggregate_result, ledger_rows, item_rows, reference) -> dict` returns `summary`, `months`, `top_customers`, `forecast`, `leads`, `month_details`.

- [x] Write failing tests against independent `report.aggregate()` output: current month orders/sales, all visible months, quote-based conversion, top-five customers, forecast sort/threshold, model lead stats/detail dates, empty period/CSV.
- [x] Run `python -m unittest discover -s tests -p test_dashboard.py -v` and see failures for missing implementation.
- [x] Implement view-model assembly, reusing aggregate sums/statistics verbatim and making ledger detail lists only for drilldown.
- [x] Re-run targeted tests to green.

### Task 2: Offline responsive HTML and interactions

**Files:** Modify `scripts/dashboard.py`; extend `tests/test_dashboard.py`.

**Interfaces:** `render_html(view) -> str`; CLI `--as-of YYYY-MM-DD [--ledger PATH] [--items PATH] [--out-dir PATH]` writes `dashboard_YYYYMMDD.html`.

- [x] Add failing tests for self-contained asset-free HTML, safely escaped embedded JSON, mobile viewport/style, accessible month/model controls, CLI read-only output and exact parity of embedded report JSON with `report.aggregate()`.
- [x] Run target tests red; implement semantic HTML, responsive CSS, two drilldown panels and vanilla JS delegated click handlers.
- [x] Run target tests green; open generated 2026-10-31 file in a real browser at desktop and mobile sizes and inspect clicks/screenshots.

### Task 3: Integration, regression and delivery

**Files:** Modify `PROJECT.md`, `README.md`, stale test assertions in `tests/test_alerts.py`, `tests/test_demo.py` and `tests/test_report.py`.

- [x] Make existing tests assert no mutation of ignored `data/` rather than requiring an empty directory; run full suite.
- [x] Document commands, offline/read-only behavior, forecast caveat when automatic loss is preview-only, and future Korean Slack trigger procedure in PROJECT.md. A profile skill is unnecessary for this project-specific rule.
- [x] Verify generated HTML contains fictional data only; check source/CSV hashes, `git diff --check`, full test suite and browser screenshot.
- [ ] Commit code/docs/tests locally; do not push. Attach screenshot and HTML file in Slack.

## Review disposition

- Added expandable monthly count/supply/VAT/total table under the paired bars, preserving the existing report requirement.
- Ruling: rate uses orders from the same in-period quote cohort as its denominator. This prevents a prior-period quote's new order from falsely inflating conversion; the rate numerator can differ from the monthly bar total when older quotes are ordered.
- Filtered lead-time drilldown rows by quote date as well as event dates to match `report.py`.
