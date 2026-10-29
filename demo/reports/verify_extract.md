# 가상 PDF 추출 정확도 검증

정답표는 추출 단계에서 사용하지 않았으며, 비교 시에만 읽었습니다.

- PDF: 102개 / 정답 행: 102개 / 추출 JSON: 102개
- 전체 필드 일치율: **100.00%** (2490/2490)
- 완전일치 문서: **102/102**
- 견적서는 VAT·총계 미표시, 도장 회신 견적서는 VAT·총계 미표시: 문서에 없는 계산값을 정확도 분모에서 제외합니다.

## 검증 한계 (불일치가 아닌 문서상 미기재)

- 견적번호 파일명 연결: 11건 — PDF 본문 번호 검증이 아니라 담당자 전달 정보 역할의 파일명으로 연결했습니다.
- 발주서 별도 수신일 미표시: 29건 — 문서의 작성/발주일을 비교했으며 실제 수신일 증명은 아닙니다.
- 계산서 품목별 수량 미표시: 28건 — 품목 수량 일치는 평가하지 않았습니다.

## 문서 종류·항목별 일치율

| 종류 | 항목 | 일치/대상 | 일치율 |
|---|---|---:|---:|
| quote | customer | 40/40 | 100.00% |
| quote | document_date | 40/40 | 100.00% |
| quote | document_type | 40/40 | 100.00% |
| quote | items.amount | 160/160 | 100.00% |
| quote | items.count | 40/40 | 100.00% |
| quote | items.model | 160/160 | 100.00% |
| quote | items.part_no | 160/160 | 100.00% |
| quote | items.product_code | 160/160 | 100.00% |
| quote | items.qty | 160/160 | 100.00% |
| quote | items.unit_price | 160/160 | 100.00% |
| quote | quote_no | 40/40 | 100.00% |
| quote | supply_amount | 40/40 | 100.00% |
| quote | **문서 완전일치** | 40/40 | 100.00% |
| order | customer | 34/34 | 100.00% |
| order | document_date | 34/34 | 100.00% |
| order | document_type | 34/34 | 100.00% |
| order | items.amount | 133/133 | 100.00% |
| order | items.count | 34/34 | 100.00% |
| order | items.customer_item_code | 113/113 | 100.00% |
| order | items.model | 133/133 | 100.00% |
| order | items.part_no | 133/133 | 100.00% |
| order | items.product_code | 20/20 | 100.00% |
| order | items.qty | 133/133 | 100.00% |
| order | items.unit_price | 133/133 | 100.00% |
| order | po_no | 34/34 | 100.00% |
| order | quote_no | 34/34 | 100.00% |
| order | supply_amount | 34/34 | 100.00% |
| order | total | 29/29 | 100.00% |
| order | vat | 29/29 | 100.00% |
| order | **문서 완전일치** | 34/34 | 100.00% |
| invoice | customer | 28/28 | 100.00% |
| invoice | document_date | 28/28 | 100.00% |
| invoice | document_type | 28/28 | 100.00% |
| invoice | quote_no | 28/28 | 100.00% |
| invoice | supply_amount | 28/28 | 100.00% |
| invoice | total | 28/28 | 100.00% |
| invoice | vat | 28/28 | 100.00% |
| invoice | **문서 완전일치** | 28/28 | 100.00% |

## 파일 범위

- 미추출 PDF: 0
- 초과 JSON: 0
- 정답표에만 있는 파일: 0
- 정답표에 없는 PDF: 0

## 틀린 항목 목록

| 파일 | 항목 | 정답 | 추출 |
|---|---|---|---|
| — | 없음 | — | — |
