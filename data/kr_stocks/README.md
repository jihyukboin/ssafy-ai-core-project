# 국내 시가총액 상위 100개 기업 데이터셋

`backend/.env`의 `OPENDART_API_KEY`, `DATA_GO_KR_API_KEY`를 사용한다. 인증키는 결과 파일과 로그에 저장하지 않는다. GMS/LLM 호출은 사용하지 않는다.

최초 구축(2026-10-21): 시세 기준일 **2026-10-20**, 기업 **100개**(KOSPI 91, KOSDAQ 9), 사업 원문 발췌 **100건**, WebP 로고 **100개**, 공시 목록 **988건**, 공시 본문 **360건**. 공시 조회 기간은 **2026-09-21~2026-10-20**이다. 본문 대상 중 첨부정정 공시 2건은 원본 API가 `014: 파일이 존재하지 않습니다`를 반환하여 목록·링크와 실패 사유만 남겼다. 나머지 본문 미선정 공시는 수집 상한에 따른 것이다. 최신 실행 결과는 `manifest.json`, `validation.json`, `errors.json`을 확인한다.

## 실행

프로젝트 루트에서 실행한다.

```bash
backend/.venv/bin/python -m pip install -r scripts/requirements-dataset.txt
backend/.venv/bin/python scripts/build_stock_dataset.py
# 특정 시세 기준일로 재현
backend/.venv/bin/python scripts/build_stock_dataset.py --as-of 2026-10-20
backend/.venv/bin/python scripts/validate_stock_dataset.py
```

`--days 30`은 최근 공시 목록 조회 기간, `--recent-bodies 3`은 기업별 최근 공시 본문 수집 상한이다. 최신 정기보고서 1건은 별도로 수집하며, 같은 접수번호는 중복 저장하지 않는다. 최신 기준일은 실행 시 주식시세 API에서 탐색한다. 휴장·갱신 지연 때문에 실행일과 기준일이 다를 수 있다.

## 선정 기준

- 코스피와 코스닥을 통합한다. 코넥스는 제외한다.
- 같은 기준일의 전체 주식시세 페이지를 수집한 뒤 시가총액을 **정수(원)**로 정렬한다.
- OpenDART 고유번호 파일의 대표 종목코드와 연결되는 기업만 포함한다. 우선주 등 같은 기업의 별도 종목으로 기업이 중복되지 않게 한다.
- 기업별 대표 종목의 시가총액 내림차순 상위 100개다. **종류주식 시가총액을 합산한 기업 가치 순위가 아니다.** 동률은 종목코드 오름차순이다.
- 시세 기준일과 기업개황 수집일은 구분한다. 기업개황은 수집 시점 값이며 과거 기준일의 기업개황을 재현하는 자료가 아니다.

## 파일

`latest.json`에 현재 스냅샷 경로와 시세 기준일이 있다.

| 경로 | 내용 |
|---|---|
| `snapshots/YYYYMMDD/companies.json` | 기업 100건, 정규화 속성, 사업 원문 발췌, 로고 경로·출처, 검색 텍스트 |
| `snapshots/YYYYMMDD/companies.csv` | 동일 기업정보의 UTF-8 BOM CSV |
| `snapshots/YYYYMMDD/ranking.json` | 선정된 100개 대표 종목의 원천 시세 행 |
| `snapshots/YYYYMMDD/disclosures.json` | 최근 기간 공시 목록 및 최신 정기보고서, 본문 수집 상태 |
| `snapshots/YYYYMMDD/documents/{접수번호}.txt` | ZIP 내부 XML/HTML에서 추출한 공시 본문 |
| `snapshots/YYYYMMDD/rag_documents.jsonl` | `stock_meta`, `disclosure_docs`로 분리 가능한 검색용 문서 |
| `snapshots/YYYYMMDD/manifest.json` | 선정 기준, 기준일, 기간, 건수, 제한 사항, 산출물 SHA-256 |
| `snapshots/YYYYMMDD/errors.json` | 로고·문서 수집 실패 식별자. 키·인증 URL·추적 정보 없음 |
| `snapshots/YYYYMMDD/validation.json` | 실제 데이터 검증 결과 |
| `logos/{종목코드}.webp` | 무손실 WebP 로고. 래스터 원본 크기 유지, SVG는 256×256으로 변환 |
| `logos/{종목코드}.json` | 로고 원본 URL, 제공자, 크기, SHA-256, 권리 안내 |
| `raw/` | 재실행용 공식 API 응답·공시 ZIP 캐시. 인증키 미포함 |

기업·종목코드와 접수번호는 문자열이다. 금액·주식수·거래량은 정수, 등락률은 퍼센트 숫자, 날짜는 `YYYY-MM-DD`, 빈 값은 `null`로 통일한다. 홈페이지에 스킴이 없으면 `https://`를 붙인다. 사업 설명은 최신 정기보고서의 「사업의 개요」 등을 최대 6,000자 원문 발췌한 것이며 생성형 요약이 아니다. 발췌에 실패하면 `null`로 남긴다. 원문 파일·접수번호·문자 위치를 함께 저장한다. 업종코드는 명칭·테마로 임의 변환하지 않는다.

공시 본문은 표 셀 구분과 문단·행 경계를 남겨 텍스트로 변환한다. 원본 ZIP도 보관하므로 수치와 단위는 원문에서 재확인할 수 있다. 공시 목록은 최종보고서 검색 옵션을 사용한다. 모든 정정 이력이나 DART에서 제공하지 않는 거래소 공시까지 포괄하는 자료는 아니다. `in_recent_window`와 `is_baseline_periodic`으로 최근 공시와 기본 기업 설명 문서를 구분한다. `body_status=not_selected`는 실패가 아니라 본문 수집 상한에 따른 미선정이다.

동일 기준일·기간의 성공한 응답과 본문을 재사용한다. 공시 정정 등으로 동일 기준일 자료를 새로 조회해야 하면 해당 `raw/lists/` 캐시를 제거하고 재실행한다. 동일 기준일의 결과물은 다시 작성하므로 이전 버전을 보관하려면 스냅샷을 별도 복사한다. 네트워크·서버 오류는 제한적으로 재시도하며 호출 사이에 간격을 둔다.

## 출처와 이용 조건

- [금융위원회 주식시세정보](https://www.data.go.kr/data/15094808/openapi.do): `getStockPriceInfo`. 상세 안내상 일 1회, 기준일 다음 영업일 오후 1시 이후 갱신. 공공누리 4유형, 상업적 이용·변경 제한 및 제3자 무단 제공·재배포 제한이 명시되어 있다. 비상업적 교육 목적이라도 자유로운 재배포가 허용된다고 간주하지 않는다.
- [OpenDART 고유번호](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018): 종목코드와 기업 고유번호 연결.
- [OpenDART 기업개황](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002): 기업 기본 속성.
- [OpenDART 공시검색](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001), [공시 원본](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003): 기업 제출 공시. API 공개를 원문 전체의 무제한 재배포 허가로 해석하지 않는다. 이용 시 [OpenDART 이용약관](https://opendart.fss.or.kr/intro/terms.do)과 원문 권리를 확인한다.
- 로고는 Toss 증권 정적 CDN에서 받고 실패하면 Alphasquare, 네이버 금융 정적 CDN을 차례로 사용한다. SVG는 CairoSVG로 래스터화한다. 각 이미지의 정확한 URL·제공자를 저장한다. 기업·권리자의 상표 및 이미지이며 공개 라이선스·재배포 허가는 확인되지 않았다. 출처를 명시했다고 권리가 부여되는 것은 아니다.

생성 데이터·원본·로고는 로컬에 저장하며 `.gitignore`에 포함한다. 공개 저장소 업로드나 외부 서비스 재배포 전에는 해당 제공자의 조건을 확인해야 한다. 수집 스크립트와 이 설명 문서는 형상관리할 수 있다.

이 데이터는 기업정보·공시 확인을 위한 교육용 자료이며 전문가의 투자 조언을 대신하지 않는다. 청킹·임베딩·Vector DB 구축 및 챗봇 구현은 이 데이터셋 구축 작업에 포함하지 않는다.

## 질문 시 추가 수집하는 설명 문서

RAG 서비스는 한국어 위키백과 API에서 후보를 검색하고 선별한 문서 본문을 로컬 `backend/.rag/cache/`에 저장한다. 문서 제목·원문 URL·문서 ID·수집일·출처 유형을 함께 보관하고, 실제 답변에서 인용된 문서의 원문 링크를 표시한다. 공시와 위키백과는 서로 다른 출처 유형으로 구분한다. 위키백과 원문 캐시는 Git에 포함하지 않는다.

이용 조건은 [Wikimedia 이용약관의 콘텐츠 라이선스 안내](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content)와 해당 원문 페이지의 라이선스 안내를 따른다. API 요청에는 [User-Agent 정책](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)에 맞춰 애플리케이션 이름과 연락처를 포함한다. `WIKI_CONTACT`는 이메일 또는 프로젝트 연락 URL로 설정한다. 재사용 시 원문 링크와 저작자 표시 등 해당 라이선스 조건을 확인한다.
