"""Stock Master Metadata Model and Universe Registry Loader."""

import csv
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from pydantic import BaseModel


class StockMaster(BaseModel):
    """Stock Metadata Master Record."""

    symbol: str
    name: str
    market: str  # TWSE / TPEx
    industry: Optional[str] = None
    is_active: bool = True


def parse_stock_info_payload(payload_json: str) -> Dict[str, StockMaster]:
    """Parse the latest active TWSE/TPEx common-stock universe.

    FinMind TaiwanStockInfo contains historical snapshots and non-equity
    instruments. Production ingestion deliberately excludes ETFs, ETNs,
    indices, depositary receipts, warrants, and non-four-digit symbols.
    """
    import json
    import re

    data_obj = json.loads(payload_json)
    if not isinstance(data_obj, dict) or not isinstance(data_obj.get("data"), list):
        raise ValueError("TaiwanStockInfo payload must contain a data list")
    rows = data_obj["data"]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("TaiwanStockInfo data rows must be objects")

    iso_date = re.compile(r"\d{4}-\d{2}-\d{2}")
    market_types = {"twse", "tpex", "上市", "上櫃"}
    valid_dates = [
        str(row.get("date"))
        for row in rows
        if str(row.get("type", "")).strip().casefold() in market_types
        and iso_date.fullmatch(str(row.get("date")))
    ]
    if not valid_dates:
        raise ValueError("TaiwanStockInfo contained no valid snapshot dates")
    latest_date = max(valid_dates)
    excluded_categories = (
        "etf",
        "etn",
        "index",
        "指數",
        "存託憑證",
        "受益證券",
        "所有證券",
        "大盤",
    )

    registry: Dict[str, StockMaster] = {}
    for row in rows:
        if str(row.get("date")) != latest_date:
            continue
        sid = str(row.get("stock_id", "")).strip()
        stock_type = str(row.get("type", "")).strip().casefold()
        industry = str(row.get("industry_category", "")).strip()
        if not re.fullmatch(r"\d{4}", sid) or sid.startswith("00"):
            continue
        if any(token in industry.casefold() for token in excluded_categories):
            continue
        if stock_type in {"tpex", "上櫃"}:
            market = "TPEx"
        elif stock_type in {"twse", "上市"}:
            market = "TWSE"
        else:
            continue
        registry[sid] = StockMaster(
            symbol=sid,
            name=str(row.get("stock_name", sid)),
            market=market,
            industry=industry or None,
            is_active=True,
        )
    if not registry:
        raise ValueError("TaiwanStockInfo contained no active listed or OTC common stocks")
    return registry


def load_universe_stock_master(csv_path: Optional[Path] = None) -> Dict[str, StockMaster]:
    """Load stock master universe mapping from CSV file."""
    if csv_path is None:
        csv_path = Path(__file__).parents[3] / "config" / "universe_spike.csv"

    registry: Dict[str, StockMaster] = {}
    if not csv_path.exists():
        return registry

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row["stock_id"]
            registry[sid] = StockMaster(
                symbol=sid,
                name=row.get("name", ""),
                market=row.get("market", "TWSE"),
                industry=row.get("subtheme"),
            )
    return registry


def extract_official_stock_master(envelopes: Sequence[Any]) -> Dict[str, StockMaster]:
    """Extract active TWSE/TPEx stock master directly from official market payloads."""
    import json
    import re

    registry: Dict[str, StockMaster] = {}
    for env in envelopes:
        if getattr(env, "status_code", None) != 200 or not getattr(env, "raw_body_bytes", None):
            continue
        provider = getattr(env, "provider_name", "")
        market = "TWSE" if provider == "twse" else "TPEx" if provider == "tpex" else None
        if not market:
            continue
        try:
            payload = json.loads(env.raw_body_str)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        tables = payload.get("tables")
        if not isinstance(tables, list):
            tables = [payload]

        for table in tables:
            if not isinstance(table, dict):
                continue
            fields = table.get("fields")
            data = table.get("data")
            if not isinstance(fields, list) or not isinstance(data, list):
                continue

            sid_col = next((c for c in ("證券代號", "股票代號", "代號") if c in fields), None)
            name_col = next((c for c in ("證券名稱", "股票名稱", "名稱") if c in fields), None)
            if sid_col is None:
                continue

            idx_sid = fields.index(sid_col)
            idx_name = fields.index(name_col) if name_col is not None else None

            for row in data:
                if not isinstance(row, list) or len(row) <= idx_sid:
                    continue
                sid = str(row[idx_sid]).strip()
                if not re.fullmatch(r"\d{4}", sid) or sid.startswith(("00", "91")):
                    continue
                name = (
                    str(row[idx_name]).strip()
                    if idx_name is not None and len(row) > idx_name
                    else sid
                )
                name = re.sub(r"<[^>]+>", "", name).strip()
                if name.endswith("-DR") or "存託憑證" in name:
                    continue
                if sid not in registry:
                    registry[sid] = StockMaster(
                        symbol=sid,
                        name=name or sid,
                        market=market,
                        is_active=True,
                    )
    return registry


def apply_balanced_universe_limit(
    stock_master: Dict[str, StockMaster], limit: int
) -> Dict[str, StockMaster]:
    """Slice stock master limit while guaranteeing balanced TWSE and TPEx market representation."""
    if limit <= 0 or len(stock_master) <= limit:
        return stock_master

    twse_stocks = [s for s in stock_master.values() if s.market == "TWSE"]
    tpex_stocks = [s for s in stock_master.values() if s.market == "TPEx"]

    if not twse_stocks:
        return {s.symbol: s for s in tpex_stocks[:limit]}
    if not tpex_stocks:
        return {s.symbol: s for s in twse_stocks[:limit]}

    n_twse = max(1, limit // 2)
    n_tpex = limit - n_twse

    selected = twse_stocks[:n_twse] + tpex_stocks[:n_tpex]
    return {s.symbol: s for s in selected}


