"""Tests for strict full-market stock-master parsing."""

import json

import pytest

from qmo.models.stock import parse_stock_info_payload


def test_parse_stock_info_payload_maps_listed_and_otc() -> None:
    payload = json.dumps(
        {
            "data": [
                {"stock_id": "2330", "stock_name": "台積電", "type": "上市"},
                {"stock_id": "8069", "stock_name": "元太", "type": "上櫃"},
                {"stock_id": "X", "stock_name": "Other", "type": "興櫃"},
            ]
        },
        ensure_ascii=False,
    )
    result = parse_stock_info_payload(payload)
    assert set(result) == {"2330", "8069"}
    assert result["2330"].market == "TWSE"
    assert result["8069"].market == "TPEx"


@pytest.mark.parametrize("payload", ["not-json", "{}", '{"data": []}'])
def test_parse_stock_info_payload_fails_closed(payload: str) -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_stock_info_payload(payload)
