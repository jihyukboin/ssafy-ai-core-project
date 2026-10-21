"""Build a dated Korean top-100 company dataset from authenticated official APIs.

Run with: backend/.venv/bin/python scripts/build_stock_dataset.py
Credentials are read from backend/.env and never written to outputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
import xml.etree.ElementTree as ET

import requests
import cairosvg
from dotenv import dotenv_values
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/kr_stocks"
PRICE_URL = "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo"
DART = "https://opendart.fss.or.kr/api/"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "CoreProjectStockDataset/1.0"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def request(url, params=None):
    # Do not log exception messages: requests exceptions may contain keyed URLs.
    for attempt in range(4):
        time.sleep(0.15)
        try:
            response = SESSION.get(url, params=params, timeout=(10, 60))
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {url.split('?')[0]}")
            return response
        except (requests.Timeout, requests.ConnectionError):
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"Request failed after retries: {url.split('?')[0]}")


def dart_json(endpoint, params, cache):
    if cache.exists():
        return read_json(cache)
    result = request(DART + endpoint + ".json", {"crtfc_key": KEYS["OPENDART_API_KEY"], **params}).json()
    if result.get("status") not in ("000", "013"):
        raise RuntimeError(f"DART {endpoint}: status {result.get('status')}")
    write_json(cache, result)
    return result


def price_page(params):
    result = request(PRICE_URL, {"serviceKey": unquote(KEYS["DATA_GO_KR_API_KEY"]),
                                "resultType": "json", **params}).json()
    response = result["response"]
    if response["header"]["resultCode"] != "00":
        raise RuntimeError("Public-data API returned an error status")
    return response["body"]


def items(body):
    value = body.get("items") or {}
    value = value.get("item", []) if isinstance(value, dict) else []
    return value if isinstance(value, list) else [value]


def corporation_master():
    path = OUT / "raw" / f"corp_codes_{date.today():%Y%m%d}.zip"
    if not path.exists():
        content = request(DART + "corpCode.xml", {"crtfc_key": KEYS["OPENDART_API_KEY"]}).content
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise RuntimeError("DART company-code download was not a ZIP file")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read(archive.namelist()[0]))
    result = {}
    for element in root.findall("list"):
        row = {child.tag: (child.text or "").strip() for child in element}
        if row.get("stock_code"):
            code = row["stock_code"]
            if code in result:
                raise RuntimeError(f"Ambiguous DART primary stock code: {code}")
            result[code] = row
    return result


def iso_date(value):
    value = (value or "").strip()
    if not value or value == "00000000":
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def optional(value):
    value = re.sub(r"\s+", " ", value or "").strip()
    return value or None


class DocumentText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"p", "title", "tr", "section-1", "section-2", "table", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"p", "title", "tr", "section-1", "section-2", "table"}:
            self.parts.append("\n")
        elif tag.lower() in {"td", "th", "tu", "te"}:
            self.parts.append(" | ")

    def handle_data(self, value):
        self.parts.append(value)

    def text(self):
        lines = [re.sub(r"[\t \xa0]+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


def download_document(row, snapshot):
    receipt = row["rcept_no"]
    target = snapshot / "documents" / f"{receipt}.txt"
    if not target.exists():
        raw = OUT / "raw/documents" / f"{receipt}.zip"
        if not raw.exists():
            content = request(DART + "document.xml", {"crtfc_key": KEYS["OPENDART_API_KEY"], "rcept_no": receipt}).content
            if not zipfile.is_zipfile(io.BytesIO(content)):
                try:
                    root = ET.fromstring(content)
                    write_json(OUT / "raw/document_status" / f"{receipt}.json",
                               {"status": root.findtext("status"), "message": root.findtext("message")})
                except ET.ParseError:
                    pass
                raise RuntimeError("DART document unavailable or error response")
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(content)
        texts = []
        with zipfile.ZipFile(raw) as archive:
            for name in archive.namelist():
                if not name.lower().endswith((".xml", ".html", ".htm")):
                    continue
                content = archive.read(name)
                encoding_match = re.search(br'encoding=[\"\x27]([^\"\x27]+)', content[:200])
                encoding = encoding_match.group(1).decode("ascii") if encoding_match else "utf-8"
                parser = DocumentText()
                parser.feed(content.decode(encoding, errors="replace"))
                if parser.text():
                    texts.append(f"[원본 파일: {name}]\n{parser.text()}")
        text = "\n\n".join(texts)
        if not text.strip():
            raise RuntimeError("No extractable text in document")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return {"text_path": str(target.relative_to(OUT)), "text_length": len(target.read_text(encoding="utf-8")),
            "text_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def logo_for(code):
    target = OUT / "logos" / f"{code}.webp"
    sidecar = target.with_suffix(".json")
    sources = [(f"https://static.toss.im/png-icons/securities/icn-sec-{code}.png", "Toss securities static image CDN"),
               (f"https://file.alphasquare.co.kr/media/images/stock_logo/kr/{code}.png", "Alphasquare stock logo CDN"),
               (f"https://ssl.pstatic.net/imgstock/fn/real/logo/stock/Stock{code}.svg", "Naver Finance stock logo CDN")]
    url, provider = sources[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        for url, provider in sources:
            try:
                response = request(url)
                content = response.content
                if url.endswith(".svg"):
                    content = cairosvg.svg2png(bytestring=content, output_width=256, output_height=256)
                with Image.open(io.BytesIO(content)) as image:
                    image.load()
                    image.convert("RGBA").save(target, "WEBP", lossless=True)
                break
            except (RuntimeError, OSError):
                continue
        else:
            raise RuntimeError("No downloadable company logo from configured sources")
    elif sidecar.exists():
        saved = read_json(sidecar)
        url, provider = saved["source_url"], saved["source_provider"]
    with Image.open(target) as image:
        assert image.format == "WEBP" and image.width > 0 and image.height > 0
        size = list(image.size)
    result = {"path": str(target.relative_to(OUT)), "source_url": url,
            "source_provider": provider, "width": size[0], "height": size[1],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "rights": "기업/권리자 상표·이미지. 공개 라이선스 확인 안 됨. 재배포 권한을 의미하지 않음."}
    write_json(sidecar, result)
    return result


def business_excerpt(text):
    """Skip table-of-contents matches and retain a substantive verbatim section."""
    matches = list(re.finditer(r"(?m)^\s*1\.\s*사업의\s*개요", text))
    matches += list(re.finditer(r"주요\s*사업의\s*내용", text))
    for match in matches:
        start = match.start()
        next_section = re.search(r"(?m)^\s*2\.\s*[^\n]+", text[match.end():])
        end = match.end() + next_section.start() if next_section else len(text)
        end = min(end, start + 6000)
        excerpt = text[start:end].strip()
        if len(re.findall(r"[가-힣]", excerpt)) < 100:
            continue
        return {"text": excerpt, "start_offset": start, "end_offset": end,
                "method": "substantive verbatim section excerpt, max 6000 characters"}
    return None


def build(args):
    OUT.mkdir(parents=True, exist_ok=True)
    master = corporation_master()
    if args.as_of:
        basis = args.as_of.replace("-", "")
        datetime.strptime(basis, "%Y%m%d")
    else:
        # API defaults to descending dates; explicitly constrain and sort dates locally.
        recent = items(price_page({"numOfRows": 100, "pageNo": 1,
                                   "beginBasDt": (date.today() - timedelta(days=14)).strftime("%Y%m%d"),
                                   "endBasDt": date.today().strftime("%Y%m%d")}))
        if not recent:
            raise RuntimeError("No stock prices in the last 14 days")
        basis = max(row["basDt"] for row in recent)
    snapshot = OUT / "snapshots" / basis
    raw_daily = OUT / "raw" / f"prices_{basis}.json"
    if raw_daily.exists():
        prices = read_json(raw_daily)
    else:
        first = price_page({"numOfRows": 1000, "pageNo": 1, "basDt": basis})
        prices = items(first)
        for page in range(2, (int(first["totalCount"]) + 999) // 1000 + 1):
            prices.extend(items(price_page({"numOfRows": 1000, "pageNo": page, "basDt": basis})))
        assert len(prices) == int(first["totalCount"])
        write_json(raw_daily, prices)
    assert prices and all(row["basDt"] == basis for row in prices)
    assert len({row["srtnCd"] for row in prices}) == len(prices)
    eligible = [row for row in prices if row["mrktCtg"] in {"KOSPI", "KOSDAQ"}
                and row["srtnCd"] in master and int(row["mrktTotAmt"]) > 0]
    eligible.sort(key=lambda row: (-int(row["mrktTotAmt"]), row["srtnCd"]))
    selected, seen = [], set()
    for row in eligible:
        corporate_id = master[row["srtnCd"]]["corp_code"]
        if corporate_id not in seen:
            selected.append(row)
            seen.add(corporate_id)
        if len(selected) == 100:
            break
    assert len(selected) == 100
    write_json(snapshot / "ranking.json", selected)
    print(f"Snapshot {basis}: {len(prices)} market rows, {len(eligible)} eligible, top 100 selected", flush=True)
    companies, disclosures, errors = [], [], []
    basis_date = datetime.strptime(basis, "%Y%m%d").date()
    begin = (basis_date - timedelta(days=args.days - 1)).strftime("%Y%m%d")
    for rank, price in enumerate(selected, 1):
        code = price["srtnCd"]
        corporate_id = master[code]["corp_code"]
        profile = dart_json("company", {"corp_code": corporate_id}, OUT / "raw/profiles" / f"{basis}_{corporate_id}.json")
        if profile.get("status") != "000" or profile.get("stock_code") != code:
            raise RuntimeError(f"Company mapping mismatch: {code}")
        company = {
            "rank": rank, "stock_code": code, "corp_code": corporate_id, "isin": price["isinCd"],
            "name": price["itmsNm"], "legal_name": optional(profile.get("corp_name")),
            "english_name": optional(profile.get("corp_name_eng")), "market": price["mrktCtg"],
            "market_cap_krw": int(price["mrktTotAmt"]), "price_as_of": iso_date(basis),
            "close_price_krw": int(price["clpr"]), "change_krw": int(price["vs"]),
            "change_rate_pct": float(Decimal(price["fltRt"])),
            "listed_shares": int(price["lstgStCnt"]), "volume": int(price["trqu"]),
            "trading_value_krw": int(price["trPrc"]), "industry_code": optional(profile.get("induty_code")),
            "ceo": optional(profile.get("ceo_nm")), "address": optional(profile.get("adres")),
            "established_on": iso_date(profile.get("est_dt")),
            "fiscal_year_end_month": int(profile["acc_mt"]) if profile.get("acc_mt", "").isdigit() else None,
            "homepage_url": optional(profile.get("hm_url")), "ir_url": optional(profile.get("ir_url")),
            "corporate_registration_number": optional(profile.get("jurir_no")),
            "business_registration_number": optional(profile.get("bizr_no")),
            "source_urls": ["https://www.data.go.kr/data/15094808/openapi.do",
                            "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002"],
            "profile_collected_on": date.today().isoformat(),
        }
        for field in ("homepage_url", "ir_url"):
            if company[field] and not re.match(r"^https?://", company[field], re.I):
                company[field] = "https://" + company[field]
        try:
            company["logo"] = logo_for(code)
        except Exception as exc:
            company["logo"] = None
            errors.append({"stock_code": code, "stage": "logo", "error_type": type(exc).__name__})
        # Fetch every page; retain all titles in the date window, latest/final reports only.
        recent_rows = []
        page = 1
        while True:
            result = dart_json("list", {"corp_code": corporate_id, "bgn_de": begin, "end_de": basis,
                              "last_reprt_at": "Y", "sort": "date", "sort_mth": "desc",
                              "page_count": 100, "page_no": page},
                              OUT / "raw/lists" / f"{corporate_id}_{begin}_{basis}_{page}.json")
            recent_rows.extend(result.get("list", []))
            if page >= int(result.get("total_page", 0)):
                break
            page += 1
        periodic = dart_json("list", {"corp_code": corporate_id, "bgn_de": f"{basis_date.year-1}0101",
                             "end_de": basis, "pblntf_ty": "A", "last_reprt_at": "Y",
                             "sort": "date", "sort_mth": "desc", "page_count": 1},
                             OUT / "raw/lists" / f"{corporate_id}_periodic_{basis}.json").get("list", [])
        # Bounded corpus: newest periodic report + newest N recent disclosures per company.
        body_ids = {r["rcept_no"] for r in recent_rows[:args.recent_bodies] + periodic[:1]}
        by_id = {row["rcept_no"]: row for row in recent_rows + periodic[:1]}
        company["recent_disclosure_count"] = len(recent_rows)
        company["latest_periodic_receipt"] = periodic[0]["rcept_no"] if periodic else None
        for receipt, row in by_id.items():
            record = {"stock_code": code, "corp_code": corporate_id, "receipt_no": receipt,
                      "title": optional(row["report_nm"]), "received_on": iso_date(row["rcept_dt"]),
                      "filer": optional(row.get("flr_nm")), "remarks": optional(row.get("rm")),
                      "in_recent_window": row in recent_rows, "is_baseline_periodic": bool(periodic and receipt == periodic[0]["rcept_no"]),
                      "source_type": "dart_disclosure", "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
                      "body_status": "not_selected", "text_path": None}
            if receipt in body_ids:
                try:
                    record.update(download_document(row, snapshot))
                    record["body_status"] = "downloaded"
                except Exception as exc:
                    record["body_status"] = "unavailable"
                    status_path = OUT / "raw/document_status" / f"{receipt}.json"
                    source_error = read_json(status_path) if status_path.exists() else None
                    record["body_source_error"] = source_error
                    errors.append({"stock_code": code, "receipt_no": receipt, "stage": "document",
                                   "error_type": type(exc).__name__, "source_error": source_error})
            disclosures.append(record)
        company["business_description"] = None
        company["business_description_source"] = None
        if periodic:
            baseline_path = snapshot / "documents" / f"{periodic[0]['rcept_no']}.txt"
            if baseline_path.exists():
                excerpt = business_excerpt(baseline_path.read_text(encoding="utf-8"))
                if excerpt:
                    company["business_description"] = excerpt.pop("text")
                    company["business_description_source"] = {**excerpt, "receipt_no": periodic[0]["rcept_no"],
                        "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={periodic[0]['rcept_no']}",
                        "text_path": str(baseline_path.relative_to(OUT))}
                    company["source_urls"].append(company["business_description_source"]["source_url"])
        company["index_text"] = "\n".join(f"{label}: {company[field]}" for label, field in [
            ("종목명", "name"), ("정식명칭", "legal_name"), ("영문명", "english_name"),
            ("종목코드", "stock_code"), ("시장", "market"), ("업종코드", "industry_code"),
            ("대표자", "ceo"), ("주소", "address"), ("설립일", "established_on"),
            ("시가총액(원)", "market_cap_krw"), ("시세기준일", "price_as_of")]
            if company[field] is not None)
        if company["business_description"]:
            company["index_text"] += "\n사업 설명(정기보고서 원문 발췌):\n" + company["business_description"]
        companies.append(company)
        write_json(snapshot / "companies.json", companies)
        write_json(snapshot / "disclosures.json", disclosures)
        write_json(snapshot / "errors.json", errors)
        print(f"{rank:03}/100 {code} {company['name']}: {len(recent_rows)} disclosures; logo={'ok' if company['logo'] else 'missing'}", flush=True)
    fields = [key for key in companies[0] if key not in {"logo", "source_urls", "index_text", "business_description_source"}]
    with (snapshot / "companies.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(companies)
    with (snapshot / "rag_documents.jsonl").open("w", encoding="utf-8") as stream:
        for company in companies:
            stream.write(json.dumps({"id": company["stock_code"], "collection": "stock_meta", "text": company["index_text"],
                         "metadata": {key: company[key] for key in ["stock_code", "corp_code", "name", "market", "price_as_of"]}}, ensure_ascii=False) + "\n")
        for record in disclosures:
            if record["body_status"] == "downloaded":
                stream.write(json.dumps({"id": f"{record['stock_code']}:{record['receipt_no']}", "collection": "disclosure_docs",
                             "text": (OUT / record["text_path"]).read_text(encoding="utf-8"),
                             "metadata": {key: record[key] for key in ["stock_code", "corp_code", "receipt_no", "title", "received_on", "source_url", "source_type"]}}, ensure_ascii=False) + "\n")
    manifest = {"schema_version": 1, "built_at": datetime.now().astimezone().isoformat(), "price_as_of": iso_date(basis),
                "recent_window": {"begin": iso_date(begin), "end": iso_date(basis)},
                "ranking_definition": "KOSPI+KOSDAQ; DART primary stock code only; unique corporations; descending primary-stock market cap (not sum of share classes); ties by stock code",
                "ranking_rows": len(prices), "eligible_rows": len(eligible), "companies": len(companies),
                "logos": sum(bool(c["logo"]) for c in companies), "disclosures": len(disclosures),
                "downloaded_documents": sum(d["body_status"] == "downloaded" for d in disclosures),
                "recent_bodies_per_company": args.recent_bodies, "errors": len(errors),
                "profile_temporality": "Current company profiles collected on build date, not historical profiles at price date",
                "disclosure_coverage": "Only DART-accessible reports; every list page in recent window, latest periodic + bounded recent full texts; not all exchange disclosures",
                "source_terms": "See README.md. Data-go-kr price redistribution restricted; logos rights not granted.",
                "artifacts": {}}
    for filename in ["companies.json", "companies.csv", "disclosures.json", "rag_documents.jsonl", "ranking.json", "errors.json"]:
        manifest["artifacts"][filename] = hashlib.sha256((snapshot / filename).read_bytes()).hexdigest()
    write_json(snapshot / "manifest.json", manifest)
    write_json(OUT / "latest.json", {"snapshot": str(snapshot.relative_to(OUT)), "price_as_of": iso_date(basis)})
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="Exact price date YYYY-MM-DD; default latest available API date")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--recent-bodies", type=int, default=3)
    args = parser.parse_args()
    if args.days < 1 or args.recent_bodies < 0:
        parser.error("days must be positive; recent-bodies must be nonnegative")
    KEYS = dotenv_values(ROOT / "backend" / ".env")
    for name in ("OPENDART_API_KEY", "DATA_GO_KR_API_KEY"):
        if not KEYS.get(name):
            raise SystemExit(f"Missing environment setting: {name}")
    try:
        build(args)
    except Exception as exc:
        # Avoid traceback frames exposing request parameters or credentialed URLs.
        raise SystemExit(f"Dataset build failed ({type(exc).__name__}). Cached successful requests retained.") from None
