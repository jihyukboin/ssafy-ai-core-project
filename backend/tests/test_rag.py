import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as api
from rag.collector import Collector, QueryPlan, DocumentChoice
from rag.config import RagConfig
from rag.llm import RagError, require_key
from rag.pipeline import cited_numbers, source_views, RagService, ExplorePlan
from rag.store import VectorStore, diverse_indices


class FakeEmbeddings:
    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += len(texts)
        return [[1.0, float("반도체" in text), float("물류" in text)] for text in texts]

    def embed_query(self, text):
        return [1.0, float("반도체" in text), float("물류" in text)]


def company(code, text):
    return {
        "stock_code": code,
        "name": code,
        "source_urls": ["https://example.com/report"],
        "market": "KOSPI",
        "market_cap_krw": 100,
        "index_text": text,
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.embeddings = FakeEmbeddings()
        self.config = RagConfig(chunk_size=200, chunk_overlap=20, top_k=2, fetch_k=4)
        self.store = VectorStore(self.config, self.embeddings, self.temp.name)
        self.data = SimpleNamespace(
            companies=[
                company("000001", "반도체 사업"),
                company("000002", "물류 사업"),
            ],
            price_as_of="2026-10-20",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_reindex_is_idempotent_and_company_filter_is_mandatory(self):
        self.store.index_metadata(self.data)
        self.store.index_metadata(self.data)
        self.assertEqual(self.store.meta.count(), 2)
        self.assertEqual(self.embeddings.calls, 2)
        for code, text in [
            ("000001", "반도체 연구 " * 100),
            ("000002", "물류 계획 " * 100),
        ]:
            doc = {
                "id": f"{code}:report",
                "text": text,
                "metadata": {
                    "stock_code": code,
                    "title": "보고서",
                    "source_url": "https://example.com/",
                    "source_type": "dart_disclosure",
                },
            }
            self.store.index_document(doc, lambda _: None)
            count, calls = self.store.docs.count(), self.embeddings.calls
            self.store.index_document(doc, lambda _: None)
            self.assertEqual(self.store.docs.count(), count)
            self.assertEqual(self.embeddings.calls, calls)
        evidence = self.store.retrieve("000001", "반도체", top_k=2)
        self.assertEqual(evidence[0]["source_type"], "stock_meta")
        self.assertTrue(all(row["stock_code"] == "000001" for row in evidence))
        self.assertEqual(len({row["text"] for row in evidence}), len(evidence))

    def test_configuration_change_is_detected(self):
        with self.assertRaises(RagError):
            VectorStore(
                self.config.model_copy(update={"chunk_size": 300}),
                self.embeddings,
                self.temp.name,
            )

    def test_no_index_is_an_actionable_error(self):
        with self.assertRaisesRegex(RagError, "색인"):
            self.store.retrieve("000099", "unknown")

    def test_chunk_settings_change_the_chunk_count(self):
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        text = "사업과 위험에 대한 설명입니다. " * 200
        self.assertGreater(
            len(self.store.splitter.split_text(text)),
            len(
                RecursiveCharacterTextSplitter(
                    chunk_size=400, chunk_overlap=20
                ).split_text(text)
            ),
        )


class GroundingTests(unittest.TestCase):
    def test_only_real_citations_are_displayed(self):
        evidence = [
            {
                "id": str(i),
                "title": "문서",
                "source_url": "https://example.com",
                "source_type": "dart_disclosure",
                "text": "원문",
            }
            for i in range(3)
        ]
        self.assertEqual(
            cited_numbers("설명 [근거 1, 3] [근거 90] [근거 1]", 3), [1, 3]
        )
        self.assertEqual(
            [row["number"] for row in source_views("설명 [근거 3]", evidence)], [3]
        )
        self.assertEqual(source_views("확인되지 않습니다.", evidence), [])

    def test_mmr_selects_diverse_evidence_without_duplicates(self):
        self.assertEqual(
            diverse_indices([1, 0], [[1, 0], [0.99, 0.01], [0, 1]], 2, 0.2), [0, 2]
        )

    def test_missing_key_is_reported_without_secrets(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(RagError, "GMS_KEY"),
        ):
            require_key()

    def test_collector_always_indexes_own_report_and_reuses_llm_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            row = {
                "stock_code": "000001",
                "receipt_no": "123",
                "title": "정기보고서",
                "received_on": "2026-06-01",
                "is_baseline_periodic": True,
            }
            indexed = []
            data = SimpleNamespace(
                by_code={
                    "000001": {"name": "테스트", "business_description": "반도체 사업"}
                },
                price_as_of="2026-10-20",
                baseline=lambda _: row,
                candidates=lambda _: [row],
                document=lambda _: {
                    "id": "000001:123",
                    "text": "반도체 사업 원문",
                    "metadata": {
                        "title": "정기보고서",
                        "source_type": "dart_disclosure",
                    },
                },
            )
            store = SimpleNamespace(
                directory=Path(directory),
                index_document=lambda doc, cb: indexed.append(doc["id"]),
            )
            collector = Collector(data, object(), store, RagConfig(wiki_enabled=False))
            with patch(
                "rag.collector.ask_json",
                side_effect=[
                    QueryPlan(standalone_question="질문", queries=["테스트"]),
                    DocumentChoice(selected_ids=["invented"]),
                ],
            ) as ask:
                first = collector.prepare(
                    "000001", "사업은?", [], lambda *args, **kwargs: None
                )
                second = collector.prepare(
                    "000001", "사업은?", [], lambda *args, **kwargs: None
                )
                self.assertEqual(ask.call_count, 2)
            self.assertIn("000001:123", indexed)
            self.assertFalse(first[2]["cache_hit"])
            self.assertTrue(second[2]["cache_hit"])
            self.assertEqual(first[0], "사업은?")


class ExploreTests(unittest.TestCase):
    def test_null_semantic_conditions_and_numeric_market_filters(self):
        small = company("000001", "사업 설명")
        large = company("000002", "사업 설명")
        small["market_cap_krw"], large["market_cap_krw"] = 100, 20000000000000
        data = SimpleNamespace(
            companies=[small, large],
            price_as_of="2026-10-20",
            summary=lambda row: {
                "name": row["name"],
                "stock_code": row["stock_code"],
                "market": row["market"],
                "market_cap_krw": row["market_cap_krw"],
            },
        )
        store = SimpleNamespace(
            meta=SimpleNamespace(
                count=lambda: 2, query=lambda **kwargs: {"ids": [["000002"]]}
            ),
            embeddings=FakeEmbeddings(),
        )
        plan = ExplorePlan.model_validate(
            {
                "search_query": "10조 이상 코스피",
                "market": "KOSPI",
                "min_market_cap_krw": 10000000000000,
                "keywords": None,
                "company_names": None,
            }
        )
        with (
            patch("rag.pipeline.VectorStore", return_value=store),
            patch("rag.pipeline.ask_json", return_value=plan),
            patch.dict(os.environ, {"GMS_KEY": "unit-test-key"}),
        ):
            service = RagService(data)
            service.model = object()
            result = service.explore("10조 이상 코스피", lambda *args, **kwargs: None)
        self.assertEqual([row["stock_code"] for row in result["items"]], ["000002"])
        self.assertGreaterEqual(result["items"][0]["market_cap_krw"], 10000000000000)

    def test_business_excerpt_skips_table_of_contents(self):
        from scripts.build_stock_dataset import business_excerpt

        toc = "1. 사업의 개요 |\n------- |\n2. 주요 제품 |\n"
        body = (
            "1. 사업의 개요\n"
            + "실제 반도체 제품과 사업 활동을 설명합니다. " * 30
            + "\n2. 주요 제품\n다음 절"
        )
        text = toc + "\n보고서 본문\n" + body
        excerpt = business_excerpt(text)
        self.assertGreater(excerpt["start_offset"], len(toc))
        self.assertIn("실제 반도체", excerpt["text"])
        self.assertEqual(
            text[excerpt["start_offset"] : excerpt["end_offset"]].strip(),
            excerpt["text"],
        )


class ApiTests(unittest.TestCase):
    def fixtures(self):
        data = SimpleNamespace(
            companies=[company("000001", "반도체 사업")],
            by_code={"000001": company("000001", "반도체 사업")},
            price_as_of="2026-10-20",
        )
        service = SimpleNamespace(
            ready=lambda: None,
            answer=lambda *args: {
                "kind": "answer",
                "answer": "반도체 [근거 1]",
                "sources": [],
            },
            explore=lambda *args: {"kind": "companies", "items": []},
            status=lambda: {"ready": True},
        )
        return data, service

    def test_chat_stream_and_validation(self):
        data, service = self.fixtures()
        with (
            patch.object(api, "CompanyData", return_value=data),
            patch.object(api, "RagService", return_value=service),
            TestClient(api.app) as client,
        ):
            response = client.post(
                "/api/chat", json={"stock_code": "000001", "question": "사업은?"}
            )
            self.assertEqual(
                [json.loads(line) for line in response.text.splitlines()][-1]["type"],
                "result",
            )
            self.assertEqual(
                client.post("/api/chat", json={"question": "  "}).status_code, 422
            )
            self.assertEqual(
                client.post(
                    "/api/chat", json={"question": "test", "stock_code": "bad"}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/api/chat", json={"question": "test", "stock_code": "000099"}
                ).status_code,
                404,
            )
            self.assertEqual(
                client.post(
                    "/api/chat", json={"question": "test", "mode": "summary"}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/api/explore", json={"question": "반도체 기업"}
                ).status_code,
                200,
            )
            self.assertNotIn("set-cookie", response.headers)

    def test_stream_failure_is_sanitized(self):
        data, service = self.fixtures()

        def failure(*args):
            raise RuntimeError("secret trace hidden")

        service.answer = failure
        with (
            patch.object(api, "CompanyData", return_value=data),
            patch.object(api, "RagService", return_value=service),
            TestClient(api.app) as client,
        ):
            response = client.post(
                "/api/chat", json={"stock_code": "000001", "question": "사업은?"}
            )
            self.assertIn('"type": "error"', response.text)
            self.assertNotIn("secret trace hidden", response.text)


if __name__ == "__main__":
    unittest.main()
