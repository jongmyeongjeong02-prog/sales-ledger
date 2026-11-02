# 수주·매출대장

견적서를 보낸 뒤 발주 확인을 놓치거나 수주·매출 현황과 실제 납기를 따로 계산해야 하는 문제를 줄이는 영업지원 MVP입니다. 공개 자료는 가상 데이터만 사용합니다.

## 기능 3개
1. 견적서·발주서(도장 회신 견적서 포함)·계산서 발행확인서 PDF에서 항목을 추출하고, 담당자 확인 후 CSV 대장에 기록합니다.
2. 진행중 견적은 30일째부터 확인필요, 60일 초과부터 실주대상으로 표시합니다. 발주가 없으면 30일 초과 알림과 60일 초과 실주 질문을 각 1회 준비하며 자동 실주 처리나 고객사 연락은 하지 않습니다.
3. 월별 수주·매출과 품목별 실제 납기를 오프라인 HTML 대시보드로 보여 줍니다.

## 설치 → 가상 데이터 실행 → 대시보드 확인

저장소 루트에서 Python 3.10 이상으로 실행합니다. 가상환경은 저장소 밖에 만듭니다.

```sh
python3 -m venv "$HOME/.venvs/sales-ledger-demo"
. "$HOME/.venvs/sales-ledger-demo/bin/activate"
python -m pip install -r requirements-demo.txt
python scripts/make_demo.py
python scripts/dashboard.py --as-of 2026-10-31 --ledger demo/expected_ledger.csv --items demo/expected_items.csv
```

마지막 명령이 출력한 `reports/dashboard_20261031.html`을 브라우저에서 열면 월별 수주·매출과 실제 납기를 확인할 수 있습니다. 기본 대시보드 입력은 로컬 `data/`이므로, 공개 시연에는 위처럼 두 가상 CSV를 명시해야 합니다. 생성기는 가상 PDF 102건과 정답표·가상 예상 대장을 다시 만듭니다. 기존 `demo/pdfs/`를 재생성하기 전에는 원본을 별도로 백업하세요.

추출 비교는 `python scripts/compare_extract.py`로 실행합니다(`demo/reports/verify_extract.md`). `python -m unittest discover -s tests`로 테스트할 수 있습니다. `python scripts/alerts.py --as-of 2026-10-31 --ledger demo/expected_ledger.csv`는 발송 없이 알림 대상만 미리 봅니다. `--apply`는 실제로 담당자에게 전달된 뒤에만 사용합니다.

## 평일 08:30 예약 보고

담당자 승인 후 외부 스케줄러에서 평일 08:30(Asia/Seoul)에 `scripts/cron_tick.py`를 호출하도록 설정할 수 있습니다. 월요일은 직전 완료된 월~일 주간 보고와 확인필요·실주대상, 화~금은 일일 현황과 새 알림·실주 질문을 준비합니다. 이 스크립트는 가상 자료 여부를 검사하고 메시지·HTML·발송 대기 기록을 만들지만 Slack으로 직접 보내지는 않습니다. 게이트웨이의 전달 성공 기록을 확인한 다음 실행에서만 대장에 발송 이력을 반영하며, 실패한 전달은 보낸 것으로 처리하지 않습니다. 예약 자체는 이 저장소에 등록되지 않습니다.

Slack 전달은 저장소가 아니라 Hermes 게이트웨이 설정에서 담당하며, 인증 토큰은 Hermes의 `.env`에만 보관합니다. 저장소의 `.env.example`에는 Slack 토큰 항목이나 값이 없습니다. 고객사에 자동 연락하지 않습니다.

## 데이터·라이선스

`demo/`는 공개 가능한 가상 PDF·CSV이고 `inbox/`(원본), `data/`(실제 대장), `reports/`(로컬 보고서), `config/blocklist.local.txt`는 Git에서 제외됩니다. 시연 견적서 수신인은 가상 인물 `신짱 대리`입니다. 실제 데이터나 연락처·비밀값은 공개 저장소에 넣지 않습니다.

프로젝트 코드는 [MIT 라이선스](LICENSE)입니다. `assets/fonts/DemoLedgerKR-Regular.ttf`는 별도 [SIL Open Font License 1.1](assets/fonts/OFL.txt)로 재배포하며 저작권 고지·폰트 라이선스는 그대로 유지합니다. 번들 폰트가 있으므로 `DEMO_KOREAN_FONT`는 별도 글꼴을 지정할 때만 쓰는 선택 환경변수입니다. 자세한 업무 규칙은 `PROJECT.md`를 따릅니다.
