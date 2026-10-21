"""Validate the generated top-100 dataset and write an evidence report."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from dotenv import dotenv_values
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/kr_stocks"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate():
    snapshot = OUT / read_json(OUT / "latest.json")["snapshot"]
    manifest = read_json(snapshot / "manifest.json")
    companies = read_json(snapshot / "companies.json")
    ranking = read_json(snapshot / "ranking.json")
    disclosures = read_json(snapshot / "disclosures.json")
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)

    check("100_unique_companies", len(companies) == len({c["corp_code"] for c in companies}) == 100)
    check("100_unique_stocks", len(companies) == len({c["stock_code"] for c in companies}) == 100)
    check("contiguous_ranks", [c["rank"] for c in companies] == list(range(1, 101)))
    check("descending_market_cap", companies == sorted(companies, key=lambda c: (-c["market_cap_krw"], c["stock_code"])))
    check("consistent_price_date", all(c["price_as_of"] == manifest["price_as_of"] for c in companies))
    check("supported_markets", all(c["market"] in {"KOSPI", "KOSDAQ"} for c in companies))
    check("identifiers_are_strings", all(re.fullmatch(r"[0-9A-Z]{6}", c["stock_code"]) and
          re.fullmatch(r"\d{8}", c["corp_code"]) for c in companies))
    check("integer_amounts_and_counts", all(type(c[k]) is int for c in companies for k in
          ["market_cap_krw", "close_price_krw", "listed_shares", "volume", "trading_value_krw"]))
    check("market_cap_equals_close_times_shares", all(c["market_cap_krw"] == c["close_price_krw"] * c["listed_shares"] for c in companies))
    check("ranking_matches_normalized_companies", [(r["srtnCd"], int(r["mrktTotAmt"])) for r in ranking] ==
          [(c["stock_code"], c["market_cap_krw"]) for c in companies])
    codes = {c["stock_code"] for c in companies}
    check("disclosure_foreign_keys", all(d["stock_code"] in codes and
          next(c["corp_code"] for c in companies if c["stock_code"] == d["stock_code"]) == d["corp_code"] for d in disclosures))
    check("disclosures_unique", len(disclosures) == len({(d["stock_code"], d["receipt_no"]) for d in disclosures}))
    begin, end = manifest["recent_window"]["begin"], manifest["recent_window"]["end"]
    check("recent_disclosures_in_window", all(begin <= d["received_on"] <= end for d in disclosures if d["in_recent_window"]))
    downloaded = [d for d in disclosures if d["body_status"] == "downloaded"]
    check("downloaded_document_integrity", all((OUT / d["text_path"]).exists() and
          hashlib.sha256((OUT / d["text_path"]).read_bytes()).hexdigest() == d["text_sha256"] and
          len((OUT / d["text_path"]).read_text(encoding="utf-8")) == d["text_length"] > 0 for d in downloaded))
    check("100_baseline_reports", len([d for d in downloaded if d["is_baseline_periodic"]]) == 100)
    excerpts = [c for c in companies if c["business_description"]]
    check("100_business_descriptions", len(excerpts) == 100)
    check("substantive_business_descriptions", all(len(re.findall(r"[가-힣]", c["business_description"])) >= 100 for c in excerpts))
    check("business_excerpts_are_verbatim", all((OUT / c["business_description_source"]["text_path"]).read_text(encoding="utf-8")[
          c["business_description_source"]["start_offset"]:c["business_description_source"]["end_offset"]].strip() ==
          c["business_description"] for c in excerpts))
    logo_errors = []
    for c in companies:
        try:
            logo = c["logo"]
            assert logo and logo["source_url"].startswith("https://")
            path = OUT / logo["path"]
            with Image.open(path) as image:
                image.load()
                assert image.format == "WEBP" and list(image.size) == [logo["width"], logo["height"]]
                assert min(image.size) >= 16
            assert hashlib.sha256(path.read_bytes()).hexdigest() == logo["sha256"]
        except (AssertionError, OSError, TypeError, KeyError):
            logo_errors.append(c["stock_code"])
    check("100_valid_webp_logos", not logo_errors)
    with (snapshot / "companies.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    check("csv_roundtrip", len(rows) == 100 and [r["stock_code"] for r in rows] == [c["stock_code"] for c in companies])
    rag_counts = {"stock_meta": 0, "disclosure_docs": 0}
    rag_ids = set()
    with (snapshot / "rag_documents.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            assert row["text"].strip()
            identity = (row["collection"], row["id"])
            assert identity not in rag_ids
            rag_ids.add(identity)
            rag_counts[row["collection"]] += 1
    check("rag_export_counts", rag_counts == {"stock_meta": 100, "disclosure_docs": len(downloaded)})
    check("manifest_checksums", all(hashlib.sha256((snapshot / f).read_bytes()).hexdigest() == digest
          for f, digest in manifest["artifacts"].items()))
    secrets = [v.encode() for v in dotenv_values(ROOT / "backend" / ".env").values() if v and len(v) >= 16]
    # Include raw responses as well as exports; skip binary logo/archive payloads.
    leaked_files = []
    for path in OUT.rglob("*"):
        if path.suffix not in {".json", ".jsonl", ".csv", ".txt"}:
            continue
        content = path.read_bytes()
        if any(secret in content for secret in secrets):
            leaked_files.append(str(path.relative_to(OUT)))
    check("no_credentials_in_dataset", not leaked_files)
    report = {"validated_on": date.today().isoformat(), "price_as_of": manifest["price_as_of"],
              "passed": all(checks.values()), "checks": checks,
              "counts": {"companies": len(companies), "disclosures": len(disclosures),
                         "full_texts": len(downloaded), "business_excerpts": len(excerpts),
                         "unavailable_full_texts": sum(d["body_status"] == "unavailable" for d in disclosures),
                         "not_selected_full_texts": sum(d["body_status"] == "not_selected" for d in disclosures), **rag_counts},
              "invalid_logo_stocks": logo_errors, "credential_leak_files": leaked_files}
    (snapshot / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    validate()
