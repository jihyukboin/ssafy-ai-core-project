"""Run from backend: .venv/bin/python -m rag.index [--rebuild] [--company 402340]."""

import argparse
import shutil
from .config import WORK, load_config
from .data import CompanyData
from .llm import make_embeddings
from .store import VectorStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--company", help="Also index the company's full baseline report"
    )
    args = parser.parse_args()
    if args.rebuild and WORK.exists():
        shutil.rmtree(WORK)
    data = CompanyData()
    store = VectorStore(load_config(), make_embeddings(load_config()))
    store.index_metadata(data, lambda message: print(message, flush=True))
    if args.company:
        baseline = data.baseline(args.company)
        if not baseline:
            parser.error("No company baseline report")
        store.index_document(
            data.document(baseline), lambda message: print(message, flush=True)
        )
    print(store.counts())


if __name__ == "__main__":
    main()
