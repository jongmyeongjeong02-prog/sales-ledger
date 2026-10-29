# 검증·알림·집계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 공개 가능한 가상 PDF 전수 추출 검증, 읽기 전용 알림 미리보기와 명시적 적용, CSV 기반 JSON 실적 집계.

**Architecture:** 추출 하위 에이전트는 정답표를 보지 않고 `demo/pdfs/`만 읽어 `demo/extracted/`에 저장한다. 비교기는 정답표와 추출물을 합쳐 정확도 리포트를 만든다. 알림은 `ledger.py`의 상태 계산을 재사용하고, 리포트는 CSV만 읽는다.

**Tech Stack:** Python 3 표준 라이브러리 (CSV·JSON·날짜), PDF 텍스트 추출은 별도 하위 에이전트.

**Spec:** 담당자님의 이번 요청 및 `PROJECT.md` 3·6·7·9·12장.

## Global Constraints
- `data/`에 어떤 문서도 기록하지 않는다. 테스트는 임시 디렉터리에서만 한다.
- 코드·가상 결과는 로컬 커밋하되 push/cron 등록은 하지 않는다.
- PDF의 추출 단계에서 정답표·생성기·예상 대장은 보지 않는다. 비교 단계에서만 정답표를 읽는다.
- 30일·60일 경계 당일은 제외하고, 자동 실주가 알림보다 우선이다.
- 오류를 꾸며내지 않고 미판독·불일치 내용을 리포트에 남긴다.

## Review Focus
- 누락 PDF/중복 JSON: 파일명 집합을 대조해 보고서에 남긴다.
- 비어 있는 대장: 미리보기는 빈 목록, 적용해도 파일 생성 안 함.
- `+30`, `+60` 경계일과 이미 알림/수주/실주 처리된 행: 다시 대상에 올리지 않는다.
- 기준일 이후 이벤트는 리포트에 포함하지 않는다.
- 품목별 납기에서 미출고 행은 제외하고 평균 계산은 실제 날짜 차이로 한다.

### Task 1: Blind extraction and comparison
**Files:** `demo/extracted/*.json` (하위 에이전트), `scripts/compare_extract.py`, `tests/test_compare_extract.py`, `demo/reports/verify_extract.md`.
**Interfaces:** `compare(answer_key_path, extracted_dir, pdf_dir) -> result` with per-doc-type/per-field counts and mismatch records.
- [ ] 하위 에이전트가 정답표 접근 없이 102개 PDF를 읽어 102 JSON 생성; 파일명 집합 검증.
- [ ] 비교 실패 테스트: 틀린 항목, null, 누락·초과 파일, 품목 라인 차이를 검출한다.
- [ ] 실패 확인 후 구현·테스트 통과.
- [ ] 실데이터 미포함 검사·전수 실행·리포트 생성 후 커밋.

### Task 2: Read-only alerts and explicit apply
**Files:** `scripts/ledger.py`, `scripts/alerts.py`, `tests/test_alerts.py`.
**Interfaces:** `ledger.advance_rows(rows, as_of) -> actions`; `alerts.py --as-of YYYY-MM-DD [--ledger PATH] [--apply]` JSON output.
- [ ] 예상 대장을 바탕으로 처리 직전 상태를 임시 CSV에 재구성하여 4건 자동 실주·2건 알림, 경계·중복·미리보기 무변경·적용 검증 테스트 작성.
- [ ] 실패 확인 후 계산을 `ledger.py`에서 공유하고 CLI 구현.
- [ ] 전체 테스트 통과, `data/` 비어 있음 확인 후 커밋.

### Task 3: JSON aggregation
**Files:** `scripts/report.py`, `tests/test_report.py`.
**Interfaces:** `report.py --as-of YYYY-MM-DD [--ledger PATH] [--items PATH]` JSON `{orders_by_month, sales_by_month, lead_by_model, customers}`.
- [ ] 임시 items.csv + 예상 대장에서 독립 계산한 월별 건수·공급가액·VAT·총계, 고객사 합계, 품목별 납기 차이 0원·0일 테스트 작성.
- [ ] 실패 확인 후 읽기 전용 집계 구현; `as-of` 이후 날짜 제외.
- [ ] 전체 테스트·CLI 실행·보안·Git 검증 후 로컬 커밋, push 없음.
