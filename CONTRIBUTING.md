# 기여하기

살래말래(Sell or Not)의 버그 수정, 문서 개선, 기능 제안을 환영합니다.

## 개발 시작

설치·데이터 준비·실행 방법은 [README](README.md#시작하기)를 확인하세요. 서버 실행은 직접 관리하며, 테스트를 위해 별도 서버를 실행할 필요는 없습니다.

1. 저장소를 Fork하고 작업 브랜치를 만듭니다.
2. 해결하려는 문제에 필요한 변경만 작성합니다.
3. 관련 테스트와 빌드를 확인합니다.
4. `main`을 대상으로 Pull Request를 열고 변경 이유와 검증 결과를 적습니다.

큰 기능이나 동작 변경은 먼저 [기능 제안](https://github.com/jihyukboin/ssafy-ai-core-project/issues/new?template=feature_request.yml)으로 논의해 주세요. 과도한 추상화와 불필요한 의존성은 피하고, deprecated API를 사용하지 않습니다.

## 검증

프로젝트 루트에서 실행합니다.

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend
npm test
npm run build
```

단위 테스트는 실제 모델 호출 없이 실행합니다. 실제 GMS 응답 비교는 API 키와 호출 비용이 필요하므로 [README의 응답 비교 안내](README.md#테스트와-응답-비교)를 확인하세요.

## 이슈와 Pull Request

- 버그 제보에는 재현 순서, 기대 동작, 실제 동작과 실행 환경을 적어 주세요.
- 답변 오류에는 질문, 기업 종목코드, 자료 기준일과 원문 근거를 함께 적어 주세요.
- PR에는 해결한 문제, 변경 후 동작, 실행한 검증을 적어 주세요.
- API 키, `.env`, `secret/`, 수집 원문·기업 로고·색인·대화 내역은 첨부하지 마세요. 로그와 화면에 민감한 정보가 있으면 제거해 주세요.

코드와 문서 기여에는 저장소의 [MIT 라이선스](LICENSE)가 적용됩니다. 외부 이미지·폰트·데이터는 원래 권리와 이용 조건을 확인하고 출처를 함께 밝혀 주세요.
