# AI PJT 프런트엔드

HTML·JavaScript·Tailwind CSS와 Node.js/Vite SSR로 구현한 기업 RAG 화면입니다. 실제 GMS 호출은 Python 백엔드에서 수행하며, 프런트엔드는 키를 보유하지 않습니다. 전체 설치·색인 절차는 [루트 README](../README.md)를 따릅니다.

```bash
npm ci
npm run dev
# 배포
npm run build
npm start
```

기본 주소는 `http://localhost:3000`, 백엔드는 `http://127.0.0.1:3001`입니다. 백엔드가 실행되어야 초기 기업 목록을 SSR할 수 있습니다. 서버의 실행·재시작·종료는 사용자가 직접 관리합니다.

- 홈: 기업명 또는 자연어 조건을 입력하면 조건에 맞는 기업 카드가 표시됩니다.
- 기업: 사이드바 또는 결과 카드를 선택하면 `/{종목코드}`로 이동하고 해당 기업의 실제 RAG 답변을 받습니다.
- 요약: 기업 선택 후 입력창의 “사업·위험요인 요약” 버튼을 사용합니다.
- 근거: 답변의 인용 번호와 실제 사용한 문서만 표시하며 원문·출처 유형·발췌를 확인할 수 있습니다.
- 진행: 검색어·수집·선별·색인·검색·생성 상태를 NDJSON 스트림으로 표시합니다.
- 처리 단계는 질문별 번호 목록으로 누적하고 최종 답변 후에도 유지합니다. 오류·중단 상태도 남기며 같은 페이지에서 기업을 전환해도 해당 기업의 진행 내역을 다시 표시합니다. 진행 내역은 다음 질문의 LLM 대화 맥락에 포함하지 않습니다. 새로고침 시에는 다른 대화와 함께 초기화됩니다.
- 저장: 로그인, 대화 저장 API, 세션 쿠키, 대화 localStorage를 사용하지 않습니다. 현재 페이지 메모리의 대화만 있고 새로고침하면 비워집니다.

`src/components`는 렌더링, `src/features`는 동작, `src/services/api.js`는 스트림 요청, `src/entry-server.js`는 초기 HTML 생성입니다. `src/styles`에는 전역 설정만 담은 `globals.css` 하나를 유지합니다. 컴포넌트 스타일은 유틸리티 클래스로 작성합니다.

로컬 Pretendard GOV 가변 동적 서브셋을 사용하고 초기 텍스트에 필요한 파일만 선행 로딩합니다. `font-display: optional`과 고정 로고·아이콘·입력창 공간으로 초기 레이아웃 이동을 줄입니다. 느린 네트워크에서는 첫 방문에 시스템 대체 글꼴이 표시될 수 있습니다. 사이트 로고와 파비콘은 사용자가 지정한 [살래말래 Google Play 앱](https://play.google.com/store/apps/details?id=com.imgobot.stocknote&hl=ko)의 아이콘을 512×512 무손실 WebP로 저장한 `public/logo.webp`를 사용합니다. 폰트 라이선스는 해당 폴더의 `LICENSE.txt`에 있습니다.

```bash
npm test
npm run build
```

테스트는 SSR·초기 상태·기업 URL·로고·근거 없는 입력 이스케이프·폰트 선행 로딩을 검증합니다.
