import json
from pathlib import Path

from .config import DATA


class CompanyData:
    def __init__(self, root=DATA):
        self.root = Path(root)
        latest = json.loads((self.root / "latest.json").read_text(encoding="utf-8"))
        self.snapshot = self.root / latest["snapshot"]
        self.price_as_of = latest["price_as_of"]
        self.companies = sorted(
            json.loads((self.snapshot / "companies.json").read_text(encoding="utf-8")),
            key=lambda row: row["rank"],
        )
        self.by_code = {company["stock_code"]: company for company in self.companies}
        self.disclosures = json.loads(
            (self.snapshot / "disclosures.json").read_text(encoding="utf-8")
        )

    def candidates(self, code):
        return [
            row
            for row in self.disclosures
            if row["stock_code"] == code and row["body_status"] == "downloaded"
        ]

    def baseline(self, code):
        return next(
            (row for row in self.candidates(code) if row["is_baseline_periodic"]), None
        )

    def document(self, row):
        return {
            "id": f"{row['stock_code']}:{row['receipt_no']}",
            "text": (self.root / row["text_path"]).read_text(encoding="utf-8"),
            "metadata": {
                "stock_code": row["stock_code"],
                "title": row["title"],
                "source_url": row["source_url"],
                "source_type": "dart_disclosure",
                "received_on": row["received_on"],
            },
        }

    def summary(self, company):
        return {
            key: company[key]
            for key in ("rank", "stock_code", "name", "market", "market_cap_krw")
        } | {
            "logo_url": f"/api/companies/{company['stock_code']}/logo"
            if company.get("logo")
            else None
        }
