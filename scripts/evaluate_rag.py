"""Compare live GMS answers with/without RAG and compare similarity/MMR retrieval.
Run from project root: PYTHONPATH=backend backend/.venv/bin/python scripts/evaluate_rag.py --url http://127.0.0.1:3001
"""

import argparse
import json
import time
from pathlib import Path

import httpx
from langchain_core.messages import SystemMessage, HumanMessage
from rag.config import load_config
from rag.llm import make_model

QUESTIONS = [
    (
        "SK스퀘어의 주요 사업 부문 네 가지는 무엇인가요?",
        "투자사업·모빌리티사업·플랫폼사업·커머스사업(2026년 반기보고서 사업 개요)",
    ),
    (
        "기업 메타데이터에 등록된 SK스퀘어의 설립일과 시장은 무엇인가요?",
        "설립일 2021-11-02, 시장 KOSPI(기업 메타데이터)",
    ),
    (
        "제공된 2026년 반기보고서 사업 개요 요약에서 11번가의 상반기 영업이익은 얼마인가요?",
        "(182)억원, 즉 영업손실 182억원. SK스퀘어 연결 전체 손익과 구분",
    ),
    (
        "2026년 10월 20일 시세 기준 SK스퀘어의 시가총액을 원 단위로 알려주세요.",
        "97,755,682,518,000원(2026-10-20 주식시세 스냅샷)",
    ),
    (
        "자료에 없는 SK스퀘어의 2030년 확정 영업이익은 얼마인가요?",
        "문서에서 확인되지 않는다고 답해야 함. 예측·확정 수치 생성 금지",
    ),
]


def request(client, base, question, method="mmr"):
    stages, result = [], None
    with client.stream(
        "POST",
        base + "/api/chat",
        json={"stock_code": "402340", "question": question, "search_method": method},
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event["type"] == "status":
                stages.append(event["stage"])
            if event["type"] == "error":
                raise RuntimeError(event["message"])
            if event["type"] == "result":
                result = event
    if result is None:
        raise RuntimeError("No result")
    return result, stages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3001")
    parser.add_argument("--output", default="docs/검증/RAG_품질비교.md")
    args = parser.parse_args()
    model = make_model(load_config())
    lines = [
        "# RAG 사용 전후 실제 응답 비교",
        "",
        f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')} / GMS `{load_config().chat_model}`",
        "",
        "동일한 대표 질문 5개를 GMS 일반 답변과 RAG 답변으로 비교했다. 아래 기대 사실은 로컬 메타데이터·공시 원문에서 확인할 기준이며, 실제 응답은 실행 결과 그대로 기록했다. 이 비교는 투자 판단을 위한 자료가 아니다.",
    ]
    results = []
    with httpx.Client(timeout=300) as client:
        for number, (question, expected) in enumerate(QUESTIONS, 1):
            baseline = model.invoke(
                [
                    SystemMessage(
                        "한국 기업 질문에 알고 있는 범위에서 간결하게 답하세요. 불확실한 사실과 미래 수치는 확인할 수 없다고 말하고, 확인하지 않은 출처나 근거 번호를 만들지 마세요."
                    ),
                    HumanMessage(question),
                ]
            ).content
            result, stages = request(client, args.url, question)
            results.append(result)
            print(
                f"{number}/5: {result['metrics']['elapsed_seconds']}s, {len(result['sources'])} cited sources",
                flush=True,
            )
            lines += [
                "",
                f"## {number}. {question}",
                "",
                f"확인 기준: {expected}",
                "",
                "### RAG 미사용",
                "",
                baseline,
                "",
                "### RAG 사용",
                "",
                result["answer"],
                "",
                f"처리 {result['metrics']['elapsed_seconds']}초 / 인용 근거 {len(result['sources'])}건 / 단계: {' → '.join(dict.fromkeys(stages))}",
                "",
                "사용한 출처:",
            ]
            lines += [
                f"- [근거 {source['number']}] {source['type']} · [{source['title']}]({source['url']})"
                for source in result["sources"]
            ] or ["- 인용 없음"]
        similarity, _ = request(client, args.url, QUESTIONS[0][0], "similarity")
        mmr = results[0]
        lines += [
            "",
            "## 검색 방식 비교",
            "",
            "동일 질문·Top-k에서 실제 선택된 청크 ID를 비교했다. 다양성은 문서 의미의 중복 여부를 원문과 함께 판단해야 한다.",
            "",
            "### 유사도 검색",
            "",
            *[f"- `{value}`" for value in similarity["retrieved_ids"]],
            "",
            "### MMR 검색",
            "",
            *[f"- `{value}`" for value in mmr["retrieved_ids"]],
            "",
            f"검색 목록 차이: {similarity['retrieved_ids'] != mmr['retrieved_ids']}",
            "",
            "## 검토 기준",
            "",
            "- 사실 정확성: 날짜·원 단위·사업 부문을 위 확인 기준과 대조한다.",
            "- 근거 제시: RAG 답변의 번호와 실제 표시된 문서만 일치하는지 확인한다.",
            "- 불확실성: 2030년 확정 수치를 만들어내지 않는지 확인한다.",
            "- 단순 단어 포함 여부로 정확도 점수를 만들지 않았으며, 응답 전문과 원문을 함께 검토한다.",
            "",
            "기업 메타데이터의 복합 원천: 금융위원회 주식시세정보(https://www.data.go.kr/data/15094808/openapi.do), OpenDART 기업개황(https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002), 각 기업 정기보고서 원문. 시가총액은 주식시세 스냅샷에서, 사업 설명은 정기보고서에서 가져온다.",
        ]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
