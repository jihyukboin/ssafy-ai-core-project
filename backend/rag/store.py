import hashlib
import json
from pathlib import Path
from threading import RLock

import chromadb
import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import WORK
from .llm import RagError


def diverse_indices(query, embeddings, k, weight):
    vectors = np.asarray(embeddings, dtype=float)
    if not len(vectors):
        return []
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    query = np.asarray(query, dtype=float)
    query /= max(np.linalg.norm(query), 1e-12)
    relevance = vectors @ query
    selected = [int(np.argmax(relevance))]
    while len(selected) < min(k, len(vectors)):
        penalty = (vectors @ vectors[selected].T).max(axis=1)
        scores = weight * relevance - (1 - weight) * penalty
        scores[selected] = -np.inf
        selected.append(int(np.argmax(scores)))
    return selected


class VectorStore:
    def __init__(self, config, embeddings, directory=WORK):
        self.config, self.embeddings = config, embeddings
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.client = chromadb.PersistentClient(path=str(self.directory / "chroma"))
        self.meta = self.client.get_or_create_collection(
            "stock_meta",
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )
        self.docs = self.client.get_or_create_collection(
            "disclosure_docs",
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=["\n\n", "\n", "。", ". ", " ", ""],
        )
        self.signature = hashlib.sha256(
            json.dumps(
                {
                    "embedding": config.embedding_model,
                    "size": config.chunk_size,
                    "overlap": config.chunk_overlap,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:16]
        signature_file = self.directory / "index-settings.json"
        if (
            signature_file.exists()
            and json.loads(signature_file.read_text())["signature"] != self.signature
        ):
            raise RagError(
                "색인 설정이 변경되었습니다. python -m rag.index --rebuild로 색인을 다시 생성하세요."
            )
        signature_file.write_text(
            json.dumps(
                {"signature": self.signature, "config": config.model_dump()},
                ensure_ascii=False,
                indent=2,
            )
        )

    def counts(self):
        return {"stock_meta": self.meta.count(), "disclosure_docs": self.docs.count()}

    def metadata_ready(self, data):
        indexed = self.meta.get(include=["metadatas"])
        expected = {company["stock_code"]: company for company in data.companies}
        return bool(expected) and set(indexed["ids"]) == set(expected) and all(
            metadata.get("price_as_of") == data.price_as_of
            and metadata.get("content_hash")
            == hashlib.sha256(expected[code]["index_text"].encode()).hexdigest()
            for code, metadata in zip(indexed["ids"], indexed["metadatas"])
        )

    def _upsert(self, collection, rows, progress):
        if not rows:
            return 0
        existing = set(
            collection.get(ids=[row["id"] for row in rows], include=[])["ids"]
        )
        pending = [row for row in rows if row["id"] not in existing]
        batch_size = self.config.embedding_batch_size
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            progress(
                f"문서 색인 중 {min(start + batch_size, len(pending))}/{len(pending)} 청크"
            )
            vectors = self.embeddings.embed_documents([row["text"] for row in batch])
            collection.upsert(
                ids=[row["id"] for row in batch],
                documents=[row["text"] for row in batch],
                metadatas=[row["metadata"] for row in batch],
                embeddings=vectors,
            )
        return len(pending)

    def index_metadata(self, data, progress=lambda message: None):
        rows = []
        for company in data.companies:
            # A single item remains a single metadata record, including its basis date.
            url = (
                company["source_urls"][-1]
                if company.get("source_urls")
                else "https://dart.fss.or.kr/"
            )
            if not isinstance(url, str):
                url = "https://dart.fss.or.kr/"
            metadata = {
                "stock_code": company["stock_code"],
                "title": company["name"] + " 기업 메타데이터",
                "source_type": "stock_meta",
                "source_url": url,
                "price_as_of": data.price_as_of,
                "market": company["market"],
                "market_cap_krw": company["market_cap_krw"],
            }
            text = company["index_text"]
            digest = hashlib.sha256(text.encode()).hexdigest()
            metadata["content_hash"] = digest
            metadata["source_urls"] = json.dumps(
                company.get("source_urls", []), ensure_ascii=False
            )
            receipt = company.get("latest_periodic_receipt", "") or ""
            metadata["report_received_on"] = (
                f"{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}"
                if len(receipt) >= 8
                else "미상"
            )
            current = self.meta.get(ids=[company["stock_code"]])
            if current["ids"] and current["metadatas"][0].get("content_hash") == digest:
                self.meta.update(ids=current["ids"], metadatas=[metadata])
                continue
            if current["ids"]:
                self.meta.delete(ids=current["ids"])
            rows.append(
                {"id": company["stock_code"], "text": text, "metadata": metadata}
            )
        with self.lock:
            added = self._upsert(self.meta, rows, progress)
            obsolete = set(self.meta.get(include=[])["ids"]) - {
                company["stock_code"] for company in data.companies
            }
            if obsolete:
                self.meta.delete(ids=list(obsolete))
            return added

    def index_document(self, document, progress):
        text_hash = hashlib.sha256(document["text"].encode()).hexdigest()[:16]
        doc_id = document["id"]
        chunks = self.splitter.split_text(document["text"])
        rows = [
            {
                "id": f"{doc_id}:{self.signature}:{text_hash}:{i}",
                "text": text,
                "metadata": {
                    **document["metadata"],
                    "doc_id": doc_id,
                    "chunk_index": i,
                },
            }
            for i, text in enumerate(chunks)
        ]
        with self.lock:
            added = self._upsert(self.docs, rows, progress)
            # Keep the previous revision until the new one has been fully embedded.
            obsolete = set(self.docs.get(where={"doc_id": doc_id}, include=[])["ids"]) - {
                row["id"] for row in rows
            }
            if obsolete:
                self.docs.delete(ids=list(obsolete))
            return added

    def retrieve(self, code, question, method=None, top_k=None):
        item = self.meta.get(ids=[code])
        if not item["ids"]:
            raise RagError(
                "기업 메타데이터 색인이 없습니다. python -m rag.index를 실행하세요."
            )
        evidence = [
            {"id": item["ids"][0], "text": item["documents"][0], **item["metadatas"][0]}
        ]
        count = len(self.docs.get(where={"stock_code": code}, include=[])["ids"])
        if not count:
            return evidence
        query = self.embeddings.embed_query(question)
        result = self.docs.query(
            query_embeddings=[query],
            where={"stock_code": code},
            n_results=min(count, self.config.fetch_k),
            include=["documents", "metadatas", "embeddings", "distances"],
        )
        k = top_k or self.config.top_k
        method = method or self.config.search_method
        indices = (
            diverse_indices(query, result["embeddings"][0], k, self.config.mmr_lambda)
            if method == "mmr"
            else list(range(min(k, len(result["ids"][0]))))
        )
        seen = {hashlib.sha256(evidence[0]["text"].encode()).hexdigest()}
        for i in indices:
            text = result["documents"][0][i]
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            evidence.append(
                {
                    "id": result["ids"][0][i],
                    "text": text,
                    "distance": result["distances"][0][i],
                    **result["metadatas"][0][i],
                }
            )
        return evidence
