import json
import os

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import SystemMessage, HumanMessage

from .config import GMS_URL


class RagError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def require_key():
    key = os.environ.get("GMS_KEY")
    if not key:
        raise RagError(
            "GMS_KEY가 없습니다. backend/.env에 키를 설정한 후 서버를 다시 실행하세요."
        )
    return key


def make_model(config):
    return ChatOpenAI(
        model=config.chat_model,
        api_key=require_key(),
        base_url=GMS_URL,
        max_completion_tokens=2500,
        timeout=90,
        max_retries=2,
    )


def make_embeddings(config):
    return OpenAIEmbeddings(
        model=config.embedding_model,
        api_key=require_key(),
        base_url=GMS_URL,
        check_embedding_ctx_length=False,
        chunk_size=config.embedding_batch_size,
        request_timeout=90,
        max_retries=3,
    )


def ask_json(model, schema, instruction, payload):
    # JSON schema validation keeps model output out of executable code and filters.
    prompt = (
        instruction
        + "\nJSON 객체만 출력하세요. 스키마: "
        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )
    messages = [
        SystemMessage(prompt),
        HumanMessage(json.dumps(payload, ensure_ascii=False)),
    ]
    for attempt in range(2):
        try:
            result = model.bind(response_format={"type": "json_object"}).invoke(
                messages
            )
            return schema.model_validate_json(result.content)
        except (ValueError, TypeError):
            messages.append(
                HumanMessage(
                    "응답이 스키마를 만족하지 않았습니다. 숫자는 원 단위 숫자, 목록은 JSON 배열로 출력하세요. 배열 항목이 없으면 []를 사용하고 모든 필드 형식을 스키마와 맞추세요."
                )
            )
            if attempt:
                raise RagError(
                    "모델의 응답 형식을 확인하지 못했습니다. 다시 질문해 주세요."
                ) from None
    raise RagError("모델 응답을 처리하지 못했습니다.")
