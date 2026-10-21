# 기업 RAG API

현재 실제 서비스는 `app.py`와 `rag/`입니다. 설치·데이터 준비·색인·실행은 [루트 README](../README.md), 요청·응답 형식은 [기능명세](../docs/기능명세서/1.md)를 따릅니다.

`GMS_KEY`는 `backend/.env`에서 읽습니다. 기업 메타데이터 100건을 먼저 색인하고 질문에 따라 원문을 선별·청킹·색인한 뒤 LangGraph `retrieve`/`generate`로 답변합니다. `GET /api/rag/status`에서 준비 상태와 색인 건수를 확인합니다. `POST /api/chat`과 `/api/explore`는 실제 진행 이벤트와 최종 결과를 NDJSON으로 반환합니다. 로그인과 대화 영구 저장은 없습니다.

```bash
# backend 디렉토리에서
.venv/bin/python -m rag.index
.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 3001
PYTHONPATH=.. .venv/bin/python -m unittest discover -s tests -v
```
