---
name: sales-ledger-intake
description: Use when receiving sales quote, order, or invoice PDFs in Slack.
version: 0.1.0
---

# PDF → 수주·매출대장

프로젝트 `PROJECT.md`가 업무 규칙의 기준입니다. 이 스킬은 PDF 수신·추출·확인 절차이고, CSV 읽기·쓰기와 상태·날짜 계산은 `scripts/ledger.py`만 담당합니다.

## When to Use
- 담당자님이 Slack으로 견적서·발주서·계산서 발행확인서 PDF를 보냈을 때.
- PDF만 처리합니다. 실제 데이터는 담당자님의 명시적 허락이 있는 로컬 연결 테스트에만 사용하고, 공개 저장소·시연·제출·공유 보고서에는 가상 데이터만 사용합니다.

## Procedure
1. `read_file`로 `PROJECT.md`를 읽습니다. 수신 PDF의 확장자와 실제 데이터 사용 허락 여부를 확인합니다. 허락 없는 실제 정보는 대장에 넣지 않고 가상 PDF를 요청합니다. 허락이 있으면 실제 원본·추출 JSON·CSV를 Git 제외된 `inbox/`·`data/`에만 둡니다.
2. 수신 원본을 수정·삭제하지 않고 프로젝트 `inbox/`에 보관합니다. 같은 이름의 파일이 있어도 덮어쓰지 않습니다(내용이 동일한지 확인하거나 새 이름으로 저장). `inbox/`는 Git 제외입니다.
3. `read_file`의 PDF 추출 또는 `pdf` 스킬의 텍스트 추출을 이용합니다. 스캔/판독 불가 부분은 임의로 채우지 않고 질문합니다. `PROJECT.md` 3장의 위치·의미 규칙대로 JSON을 정리합니다.
4. 견적: `quote_no`, `quote_date`, `customer`, `customer_contact`, `contact_title`, `sales_rep`, `quote_amount`, `items`를 추출합니다. 품명 구분 행의 `예비품 견적서`는 `remark=예비품`, 그 밖 문구는 사양번호로 `remark`에 넣습니다. 연락처는 JSON·CSV에 넣지 않습니다. 품목은 `line_no,model,part_no,product_code,remark,qty,unit_price,amount` 형식입니다.
5. 발주: 문구의 의미로 `po_no`, `received_date`, `order_amount`, `order_vat`, `order_total`, `items`를 정리합니다. 고객이 도장·서명해 회신한 견적서는 해당 견적번호별로 발주서로 봅니다. 이때 `stamped_quote=true`, `po_no=""`로 입력하고, 팩스·스캔 수신일을 `received_date`로 쓰며, `order_vat`·`order_total`은 `ledger.py`가 10%(원 미만 버림)와 공급가액 합으로 계산하게 생략합니다. 손글씨 요청은 요약에 표시하고 `memo_append`로 건 단위에 더합니다. 품목은 `model,qty,unit_price,customer_item_code` 형식이며, 고객 코드는 우리 코드로 취급하지 않습니다. 계산서: `invoice_date`, `invoice_amount`, `invoice_vat`, `invoice_total`; 품목별 수량이 명시된 경우에만 선택적으로 `items`를 넣습니다. 발주·계산서의 견적번호가 없거나 미등록이면 `미연결`을 보고하고 중지합니다.
6. 파일명이나 문맥에서 값을 추측하지 않습니다. 추출값(번호·날짜·고객·금액·품목 수량)과 견적과의 차이를 담당자님께 요약해 먼저 보여 줍니다. 금액·수량 차이 또는 누락/불명확한 값이 있으면 그 값을 질문하고 중지합니다. **담당자님의 명시적인 “확인” 전에는 `ledger.py`를 실행하여 기록하지 않습니다.** 확인은 제시한 바로 그 JSON에만 적용됩니다.
7. 확인된 JSON 파일은 `data/`에 저장합니다(Git 제외). `terminal`에서 `python scripts/ledger.py add-quote|add-order|add-invoice <JSON 경로>`로 기록합니다. 실주·재진행도 확인된 JSON으로 `lost|reopen`을 사용합니다. 스크립트가 `미연결`, `중복`, `차이 확인 필요`를 반환하면 수정하거나 우회하지 않고 담당자님께 보고합니다.
8. 기록 성공 후 `python scripts/ledger.py show <JSON 경로>`로 대상 건 상태를 읽고, 담당자님께 결과를 한 줄로 보고합니다. 고객사에 직접 연락하지 않습니다.

## Pitfalls
- PDF 문서 날짜가 없다고 수주일을 지어내지 않습니다. 팩스·스캔 수신일을 우선 확인하고, 없으면 담당자님께 확인받습니다.
- 계산서에 품목 수량이 없으면 수량 일치를 증명했다고 말하지 않습니다. 제공된 금액과 품목 수량만 대조합니다.
- 동일 견적번호 재전송은 중복으로 막습니다. 다른 견적번호로 자동 변경하지 않습니다.
- 1견적=1발주=1계산서입니다. 분할 발주는 견적번호 `-A`, `-B`를 담당자님과 먼저 확인합니다.

## Verification
- PDF 원본이 `inbox/`에 그대로 있고, CSV는 `data/`에만 있는지 확인합니다.
- CSV 기록은 `ledger.py` 성공 및 `show`의 상태 확인 후에만 성공으로 보고합니다.
