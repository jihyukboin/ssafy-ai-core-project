import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA = ROOT / "data/kr_stocks"
WORK = Path(os.environ.get("RAG_WORK_DIR", str(BACKEND / ".rag")))
load_dotenv(BACKEND / ".env")
GMS_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/"
DISCLAIMER = "이 답변은 공시·기업정보를 설명하는 교육용 자료이며, 투자 권유나 전문가의 투자 조언을 대신하지 않습니다. 자료의 기준일과 원문을 확인하세요."


class RagConfig(BaseModel):
    chat_model: str = "gpt-5.4-nano"
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = Field(default=1200, ge=200, le=5000)
    chunk_overlap: int = Field(default=200, ge=0)
    top_k: int = Field(default=6, ge=1, le=15)
    fetch_k: int = Field(default=24, ge=1, le=80)
    search_method: str = Field(default="mmr", pattern="^(similarity|mmr)$")
    mmr_lambda: float = Field(default=0.65, ge=0, le=1)
    selected_document_limit: int = Field(default=1, ge=0, le=3)
    embedding_batch_size: int = Field(default=32, ge=1, le=64)
    wiki_enabled: bool = True

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        if self.fetch_k < self.top_k:
            raise ValueError("fetch_k must be at least top_k")
        return self


def load_config():
    path = Path(os.environ.get("RAG_CONFIG", str(BACKEND / "rag_config.json")))
    return RagConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
