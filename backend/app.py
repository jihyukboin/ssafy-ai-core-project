"""Company data and stateless evidence-based RAG API."""

from contextlib import asynccontextmanager
import json
import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from rag.data import CompanyData
from rag.pipeline import RagService
from rag.llm import RagError

DATA = Path(__file__).resolve().parents[1] / "data/kr_stocks"


@asynccontextmanager
async def lifespan(app: FastAPI):
    data = CompanyData()
    app.state.data = data
    app.state.companies = data.companies
    app.state.by_code = data.by_code
    app.state.price_as_of = data.price_as_of
    try:
        app.state.rag = RagService(data)
        app.state.rag_error = None
    except RagError as error:
        app.state.rag = None
        app.state.rag_error = str(error)
    yield


app = FastAPI(title="국내 주식 기업정보 API", version="1.0.0", lifespan=lifespan)


class CompanySummary(BaseModel):
    rank: int
    stock_code: str
    name: str
    market: str
    market_cap_krw: int
    logo_url: str | None


class CompanyList(BaseModel):
    price_as_of: str
    total: int
    items: list[CompanySummary]


def get_company(stock_code: str):
    company = app.state.by_code.get(stock_code)
    if company is None:
        raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다.")
    return company


@app.get("/health")
def health():
    return {
        "status": "ok",
        "companies": len(app.state.companies),
        "price_as_of": app.state.price_as_of,
    }


@app.get("/api/companies", response_model=CompanyList)
def list_companies(
    q: str = Query(default="", max_length=100),
    market: Literal["KOSPI", "KOSDAQ"] | None = None,
):
    query = q.strip().casefold()
    companies = [
        company
        for company in app.state.companies
        if (market is None or company["market"] == market)
        and (
            not query
            or query in company["name"].casefold()
            or query in company["stock_code"]
        )
    ]
    return {
        "price_as_of": app.state.price_as_of,
        "total": len(companies),
        "items": [
            {
                **{
                    key: company[key]
                    for key in (
                        "rank",
                        "stock_code",
                        "name",
                        "market",
                        "market_cap_krw",
                    )
                },
                "logo_url": f"/api/companies/{company['stock_code']}/logo"
                if company["logo"]
                else None,
            }
            for company in companies
        ],
    }


@app.get("/api/companies/{stock_code}")
def company_detail(stock_code: str):
    company = get_company(stock_code)
    return {
        **company,
        "logo_url": f"/api/companies/{stock_code}/logo" if company["logo"] else None,
    }


@app.get("/api/companies/{stock_code}/logo", response_class=FileResponse)
def company_logo(stock_code: str):
    company = get_company(stock_code)
    if not company["logo"]:
        raise HTTPException(status_code=404, detail="로고가 없습니다.")
    path = DATA / company["logo"]["path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="로고 파일이 없습니다.")
    return FileResponse(
        path, media_type="image/webp", headers={"Cache-Control": "public, max-age=3600"}
    )


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    stock_code: str | None = Field(default=None, pattern=r"^[0-9A-Z]{6}$")
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["chat", "summary"] = "chat"
    history: list[HistoryMessage] = Field(default_factory=list, max_length=8)
    search_method: Literal["similarity", "mmr"] | None = None
    top_k: int | None = Field(default=None, ge=1, le=15)

    @field_validator("question")
    @classmethod
    def non_empty(cls, value):
        if not value.strip():
            raise ValueError("질문을 입력하세요.")
        return value.strip()


def service():
    if app.state.rag is None:
        raise RagError(app.state.rag_error or "색인을 초기화하지 못했습니다.")
    return app.state.rag


@app.exception_handler(RagError)
async def rag_error(request: Request, error: RagError):
    return JSONResponse(status_code=error.status, content={"detail": str(error)})


@app.get("/api/rag/status")
def rag_status():
    try:
        return service().status()
    except RagError as error:
        return {
            "ready": False,
            "companies": len(app.state.companies),
            "counts": {"stock_meta": 0, "disclosure_docs": 0},
            "message": str(error),
            "price_as_of": app.state.price_as_of,
        }


def safe_error(error):
    if isinstance(error, RagError):
        return str(error)
    code = getattr(error, "status_code", None)
    if code in (401, 403):
        return "GMS 인증에 실패했습니다. 서버의 GMS_KEY 설정을 확인하세요."
    if code == 429:
        return "모델 호출 한도에 도달했습니다. 잠시 후 다시 시도하세요."
    logging.getLogger("aipjt").warning("RAG request failed (%s)", type(error).__name__)
    return "문서 검색 또는 답변 생성에 실패했습니다. 네트워크와 색인 상태를 확인한 뒤 다시 시도하세요."


@app.post("/api/chat")
@app.post("/api/explore")
async def chat(body: ChatRequest, request: Request):
    rag = service()
    rag.ready()
    if body.stock_code and body.stock_code not in app.state.by_code:
        raise HTTPException(404, "기업을 찾을 수 없습니다.")
    if body.mode == "summary" and not body.stock_code:
        raise HTTPException(422, "먼저 기업을 선택하세요.")
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(stage, message, **details):
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "status", "stage": stage, "message": message, **details},
        )

    def run():
        try:
            if request.url.path.endswith("/explore") or not body.stock_code:
                result = rag.explore(body.question, emit)
            else:
                result = rag.answer(
                    body.stock_code,
                    body.question,
                    [message.model_dump() for message in body.history],
                    emit,
                    body.mode,
                    body.search_method,
                    body.top_k,
                )
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "result", **result})
        except Exception as error:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "message": safe_error(error)}
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def events():
        task = asyncio.create_task(asyncio.to_thread(run))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield json.dumps({"type": "heartbeat"}) + "\n"
                    continue
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False) + "\n"
            await task
        finally:
            # No request messages or answers are persisted, even when a client disconnects.
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=3001)
