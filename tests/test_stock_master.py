"""Tests for strict full-market stock-master parsing."""

import json

import pytest

from qmo.models.stock import parse_stock_info_payload


def test_parse_stock_info_payload_maps_listed_and_otc() -> None:
    payload = json.dumps(
        {
            "data": [
                {
                    "stock_id": "2330",
                    "stock_name": "舊台積電",
                    "type": "上市",
                    "date": "2026-09-26",
                },
                {"stock_id": "2330", "stock_name": "台積電", "type": "twse", "date": "2026-09-27"},
                {"stock_id": "8069", "stock_name": "元太", "type": "tpex", "date": "2026-09-27"},
                {
                    "stock_id": "0050",
                    "stock_name": "元大台灣50",
                    "type": "twse",
                    "industry_category": "ETF",
                    "date": "2026-09-27",
                },
                {
                    "stock_id": "711133",
                    "stock_name": "權證",
                    "type": "tpex",
                    "industry_category": "所有證券",
                    "date": "2026-09-27",
                },
                {"stock_id": "X", "stock_name": "Other", "type": "興櫃", "date": "2026-09-27"},
            ]
        },
        ensure_ascii=False,
    )
    result = parse_stock_info_payload(payload)
    assert set(result) == {"2330", "8069"}
    assert result["2330"].market == "TWSE"
    assert result["8069"].market == "TPEx"


@pytest.mark.parametrize(
    "payload",
    ["not-json", "{}", '{"data": []}', '{"data": [{"stock_id": "2330", "type": "twse"}]}'],
)
def test_parse_stock_info_payload_fails_closed(payload: str) -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_stock_info_payload(payload)
