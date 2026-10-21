import json
import os
import tempfile
import unittest
import requests
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
import app as api
from rag.collector import Collector, QueryPlan, DocumentChoice, JsonCache, WikiClient
from rag.config import RagConfig
from rag.llm import RagError, require_key
from rag.pipeline import (
    cited_numbers, source_views, RagService, ExplorePlan, CompanyMatch, CompanyMatches,
)
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

    def test_metadata_readiness_checks_content_date_and_identity(self):
        self.assertFalse(self.store.metadata_ready(self.data))
        self.store.index_metadata(self.data)
        self.assertTrue(self.store.metadata_ready(self.data))
        self.data.price_as_of = "2026-10-21"
        self.assertFalse(self.store.metadata_ready(self.data))
        self.store.index_metadata(self.data)
        self.assertTrue(self.store.metadata_ready(self.data))
        self.data.companies[0]["index_text"] = "갱신된 반도체 사업"
        self.assertFalse(self.store.metadata_ready(self.data))
        self.store.index_metadata(self.data)
        self.assertTrue(self.store.metadata_ready(self.data))
        self.data.companies[1] = company("000003", "새 기업")
        self.assertFalse(self.store.metadata_ready(self.data))
        self.store.index_metadata(self.data)
        self.assertEqual(set(self.store.meta.get()["ids"]), {"000001", "000003"})
        self.assertTrue(self.store.metadata_ready(self.data))

    def test_document_revision_replaces_old_chunks_after_success(self):
        doc = {
            "id": "000001:report",
            "text": "이전 사업 " * 100,
            "metadata": {
                "stock_code": "000001", "title": "보고서",
                "source_url": "https://example.com/", "source_type": "dart_disclosure",
            },
        }
        self.store.index_document(doc, lambda _: None)
        old_ids = set(self.store.docs.get()["ids"])
        doc["text"] = "갱신된 사업 " * 100
        with patch.object(self.embeddings, "embed_documents", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.store.index_document(doc, lambda _: None)
        self.assertEqual(set(self.store.docs.get()["ids"]), old_ids)
        self.store.index_document(doc, lambda _: None)
        current = self.store.docs.get()
        self.assertFalse(old_ids.intersection(current["ids"]))
        self.assertTrue(all("갱신된" in text for text in current["documents"]))

    def test_shared_document_does_not_overwrite_other_company(self):
        for code in ("000001", "000002"):
            self.store.index_document({
                "id": f"{code}:wiki:123", "text": "같은 설명 문서",
                "metadata": {"stock_code": code, "title": "공통 문서"},
            }, lambda _: None)
        for code in ("000001", "000002"):
            self.assertEqual(len(self.store.docs.get(where={"stock_code": code})["ids"]), 1)

    def test_duplicate_metadata_and_external_text_is_merged(self):
        self.store.index_metadata(self.data)
        self.store.index_document({
            "id": "000001:report", "text": "반도체 사업",
            "metadata": {"stock_code": "000001", "title": "보고서"},
        }, lambda _: None)
        self.assertEqual(len(self.store.retrieve("000001", "반도체")), 1)

    def test_top_k_changes_external_evidence_and_keeps_metadata(self):
        self.store.index_metadata(self.data)
        for i in range(4):
            self.store.index_document({
                "id": f"000001:report:{i}", "text": f"반도체 제품 {i} 설명",
                "metadata": {"stock_code": "000001", "title": f"공시 {i}"},
            }, lambda _: None)
        for k in (1, 3):
            with self.subTest(k=k):
                result = self.store.retrieve("000001", "반도체", method="similarity", top_k=k)
                self.assertEqual(len(result), 1 + k)
                self.assertEqual(result[0]["source_type"], "stock_meta")

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
    def test_graph_runs_retrieve_then_generate_and_returns_cited_sources(self):
        steps = []
        evidence = [{
            "id": "000001", "title": "기업 메타데이터", "source_type": "stock_meta",
            "source_url": "https://example.com/", "text": "반도체 사업",
        }, {
            "id": "000001:report:0", "title": "공시", "source_type": "dart_disclosure",
            "source_url": "https://example.com/report", "text": "확인된 제품 설명",
        }]

        def retrieve(*args):
            steps.append("retrieve")
            return evidence

        def generate(messages):
            steps.append("generate")
            return SimpleNamespace(content="반도체 제품 사업입니다. [근거 2]")

        store = SimpleNamespace(
            metadata_ready=lambda _: True, retrieve=retrieve,
            counts=lambda: {"stock_meta": 1, "disclosure_docs": 1},
        )
        data = SimpleNamespace(by_code={"000001": company("000001", "반도체 사업")})
        with (
            patch("rag.pipeline.VectorStore", return_value=store),
            patch.dict(os.environ, {"GMS_KEY": "unit-test-key"}),
        ):
            service = RagService(data)
            service.model = SimpleNamespace(invoke=generate)
            service.collector = SimpleNamespace(prepare=Mock(return_value=("사업은?", [], {})))
            result = service.answer("000001", "사업은?", [], lambda *a, **kw: None)
        self.assertEqual(steps, ["retrieve", "generate"])
        self.assertEqual(result["retrieved_ids"], [row["id"] for row in evidence])
        self.assertEqual([source["number"] for source in result["sources"]], [2])
        self.assertEqual(result["sources"][0]["type"], "dart_disclosure")
        self.assertIn("전문가", result["disclaimer"])
        self.assertFalse(result["no_citations"])

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


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.indexed = []
        self.row = {
            "receipt_no": "123", "title": "정기보고서", "received_on": "2026-06-01",
            "is_baseline_periodic": True,
        }
        self.data = SimpleNamespace(
            by_code={"000001": {"name": "테스트", "business_description": "반도체 사업"}},
            price_as_of="2026-10-20", baseline=lambda _: self.row,
            candidates=lambda _: [self.row],
            document=lambda _: self.document("000001:123", "dart_disclosure"),
        )
        store = SimpleNamespace(
            directory=Path(self.temp.name),
            index_document=lambda doc, _: self.indexed.append(doc),
        )
        self.collector = Collector(self.data, object(), store, RagConfig())

    def document(self, identity, kind):
        return {
            "id": identity, "text": "실제 사업 설명",
            "metadata": {"title": identity, "source_type": kind},
        }

    def prepare(self):
        return self.collector.prepare("000001", "사업은?", [], lambda *a, **kw: None)

    def test_every_extracted_query_is_searched_and_cached(self):
        with (
            patch("rag.collector.ask_json", side_effect=[
                QueryPlan(standalone_question="사업은?", queries=["반도체", "물류", "제품"]),
                DocumentChoice(),
            ]) as ask,
            patch.object(self.collector.wiki, "request", return_value={"query": {"search": []}}) as request,
        ):
            self.prepare()
            self.prepare()
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(
            [call.args[0]["srsearch"] for call in request.call_args_list],
            ["테스트", "반도체", "물류", "제품"],
        )

    def test_own_article_is_indexed_without_a_baseline_or_llm_selection(self):
        self.data.baseline = lambda _: None
        self.data.candidates = lambda _: []
        own = {"id": "000001:wiki:1", "kind": "wikipedia", "title": "테스트", "pageid": 1}
        with (
            patch("rag.collector.ask_json", side_effect=[
                QueryPlan(standalone_question="사업은?", queries=["테스트"]),
                DocumentChoice(selected_ids=["unknown"]),
            ]),
            patch.object(self.collector.wiki, "search", return_value=[own]),
            patch.object(self.collector.wiki, "document", return_value=self.document(own["id"], "wikipedia")),
        ):
            result = self.prepare()
        self.assertEqual([doc["id"] for doc in self.indexed], [own["id"]])
        self.assertEqual(result[2]["selected"][0]["type"], "wikipedia")

    def test_wiki_outage_preserves_the_mandatory_report(self):
        with (
            patch("rag.collector.ask_json", side_effect=[
                QueryPlan(standalone_question="사업은?", queries=["테스트"]),
                DocumentChoice(),
            ]),
            patch.object(self.collector.wiki, "search", side_effect=requests.ConnectionError),
        ):
            result = self.prepare()
        self.assertEqual([doc["id"] for doc in self.indexed], ["000001:123"])
        self.assertEqual(result[2]["selected"][0]["type"], "dart_disclosure")

    def test_two_external_source_types_are_indexed_together(self):
        own = {"id": "000001:wiki:1", "kind": "wikipedia", "title": "테스트", "pageid": 1}
        with (
            patch("rag.collector.ask_json", side_effect=[
                QueryPlan(standalone_question="사업은?", queries=["테스트"]), DocumentChoice(),
            ]),
            patch.object(self.collector.wiki, "search", return_value=[own]),
            patch.object(self.collector.wiki, "document", return_value=self.document(own["id"], "wikipedia")),
        ):
            self.prepare()
        self.assertEqual(
            {doc["metadata"]["source_type"] for doc in self.indexed},
            {"wikipedia", "dart_disclosure"},
        )

    def test_wiki_retries_transient_network_and_http_failures(self):
        wiki = WikiClient(JsonCache(Path(self.temp.name) / "wiki"))
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: {"query": {}})
        limited = SimpleNamespace(status_code=429)
        with (
            patch("rag.collector.requests.get", side_effect=[requests.Timeout, limited, response]) as get,
            patch("rag.collector.time.sleep"),
        ):
            self.assertEqual(wiki.request({"list": "search"}), {"query": {}})
        self.assertEqual(get.call_count, 3)
        self.assertIn("User-Agent", get.call_args.kwargs["headers"])
        with (
            patch("rag.collector.requests.get", side_effect=requests.ConnectionError) as get,
            patch("rag.collector.time.sleep"),
            self.assertRaises(requests.ConnectionError),
        ):
            wiki.request({"list": "search"})
        self.assertEqual(get.call_count, 3)


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
            metadata_ready=lambda _: True,
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

    def test_semantic_selection_rejects_unseen_and_duplicate_companies(self):
        companies = [company(f"{i:06}", "반도체 사업") for i in range(1, 31)]
        data = SimpleNamespace(
            companies=companies, price_as_of="2026-10-20", summary=lambda row: row,
        )
        store = SimpleNamespace(
            metadata_ready=lambda _: True, embeddings=FakeEmbeddings(),
            meta=SimpleNamespace(query=lambda **_: {"ids": [["000011"]]}),
        )
        with (
            patch("rag.pipeline.VectorStore", return_value=store),
            patch("rag.pipeline.ask_json", side_effect=[
                ExplorePlan(search_query="반도체", keywords=["반도체"]),
                CompanyMatches(matches=[
                    CompanyMatch(stock_code=code, reason="사업 설명")
                    for code in ("000011", "000011", "000030", "999999")
                ]),
            ]),
            patch.dict(os.environ, {"GMS_KEY": "unit-test-key"}),
        ):
            service = RagService(data)
            service.model = object()
            result = service.explore("반도체 기업", lambda *args, **kwargs: None)
        self.assertEqual([item["stock_code"] for item in result["items"]], ["000011"])

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

    def test_unready_service_returns_actionable_503_before_streaming(self):
        data, service = self.fixtures()
        for message in ("GMS_KEY가 없습니다.", "기업 메타데이터 색인이 없습니다."):
            with self.subTest(message=message):
                service.ready = lambda: (_ for _ in ()).throw(RagError(message))
                with (
                    patch.object(api, "CompanyData", return_value=data),
                    patch.object(api, "RagService", return_value=service),
                    TestClient(api.app) as client,
                ):
                    response = client.post("/api/chat", json={"question": "사업은?"})
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json(), {"detail": message})


if __name__ == "__main__":
    unittest.main()
