"""Tests for QMO CLI commands and option workflows."""

from pathlib import Path

from click.testing import CliRunner

from qmo import __version__
from qmo.cli import main
from qmo.models.price import DailyPrice
from qmo.storage.publisher import AtomicBatchPublisher


def test_cli_version() -> None:
    """Verify --version flag outputs CLI version."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_status_with_root_dir(tmp_path: Path) -> None:
    """Verify qmo status displays storage summary."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]
    publisher.publish_batch(
        batch_id="b_status_test",
        dataset="daily_price",
        models=models,
        source_raw_hashes=["a" * 64],
    )

    runner = CliRunner()
    result = runner.invoke(main, ["status", "--root-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Quant Market Observer Status" in result.output
    assert "b_status_test" in result.output


def test_cli_update_dry_run(tmp_path: Path) -> None:
    """Verify qmo update with --dry-run option."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["update", "--date", "2026-09-27", "--dry-run", "--root-dir", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "[DRY-RUN]" in result.output


def test_cli_validate_formats(tmp_path: Path) -> None:
    """Verify qmo validate with text, json, and markdown formats."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]
    publisher.publish_batch(
        batch_id="b_val_test",
        dataset="daily_price",
        models=models,
        source_raw_hashes=["a" * 64],
    )

    runner = CliRunner()

    # Text format
    res_text = runner.invoke(main, ["validate", "--root-dir", str(tmp_path), "--format", "text"])
    assert res_text.exit_code == 0
    assert "Validated 1 quality report(s)" in res_text.output

    # JSON format
    res_json = runner.invoke(main, ["validate", "--root-dir", str(tmp_path), "--format", "json"])
    assert res_json.exit_code == 0
    assert '"batch_id": "b_val_test"' in res_json.output

    # Markdown format
    res_md = runner.invoke(main, ["validate", "--root-dir", str(tmp_path), "--format", "markdown"])
    assert res_md.exit_code == 0
    assert "# Quality Validation Report" in res_md.output


def test_cli_help() -> None:
    """Verify help message when invoking main without subcommand."""
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "Quant Market Observer (QMO) CLI." in result.output


def test_cli_validate_no_reports(tmp_path: Path) -> None:
    """Verify validate command handling when no reports exist."""
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--root-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No registered quality reports found" in result.output


def test_cli_update_datasets(tmp_path: Path) -> None:
    """Verify update command with dataset parameter."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "update",
            "--dataset",
            "daily_price",
            "--date",
            "2026-09-25",
            "--synthetic",
            "--root-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "Executing pipeline update" in result.output
    assert "Processing dataset 'daily_price'" in result.output


def test_cli_calculate(tmp_path: Path) -> None:
    """Verify qmo calculate command execution."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["calculate", "--date", "2026-09-28", "--root-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Executing indicator calculation pipeline" in result.output
    assert "Indicator Calculation Summary" in result.output


def test_cli_signal(tmp_path: Path) -> None:
    """Verify qmo signal command execution."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["signal", "--date", "2026-09-28", "--root-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Generating strategy signals" in result.output
    assert "Active Signals Count" in result.output


def test_cli_report(tmp_path: Path) -> None:
    """Verify qmo report command execution."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["report", "--date", "2026-09-28", "--format", "markdown", "--root-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Quant Market Observer 每日量化市場觀測報告" in result.output


def test_cli_update_official_bulk_e2e(tmp_path: Path) -> None:
    """Verify qmo update official-bulk mode E2E workflow."""
    from unittest.mock import MagicMock, patch

    from qmo.providers.transport import HttpResponse
    from qmo.storage.catalog import DuckDBCatalog

    fx_dir = Path("tests/fixtures/official")
    fixtures_map = {
        "MI_INDEX": (fx_dir / "twse_price_mi_index_20260924.json").read_bytes(),
        "afterTrading/dailyQuotes": (fx_dir / "tpex_price_stk_quote_20260924.json").read_bytes(),
        "fund/T86": (fx_dir / "twse_inst_t86_20260924.json").read_bytes(),
        "insti/dailyTrade": (fx_dir / "tpex_inst_dailyTrade_20260924.json").read_bytes(),
        "MI_MARGN": (fx_dir / "twse_margin_mimargn_20260924.json").read_bytes(),
        "margin/balance": (fx_dir / "tpex_margin_balance_20260924.json").read_bytes(),
    }

    mock_execute = MagicMock()

    def side_effect(url: str, params: dict | None = None) -> HttpResponse:
        for key, body in fixtures_map.items():
            if key in url:
                return HttpResponse(
                    status_code=200,
                    headers={"content-type": "application/json"},
                    raw_bytes=body,
                )
        raise ValueError(f"Unexpected URL: {url}")

    mock_execute.side_effect = side_effect

    runner = CliRunner()

    with patch("qmo.providers.transport.HttpTransport.execute", mock_execute):
        # 1. First run: cold execution
        res1 = runner.invoke(
            main,
            [
                "update",
                "--provider-mode",
                "official-bulk",
                "--date",
                "2026-09-24",
                "--root-dir",
                str(tmp_path),
            ],
        )
        assert res1.exit_code == 0, f"CLI update failed: {res1.output}"
        assert mock_execute.call_count == 6  # Exactly 6 requests (3 TWSE + 3 TPEx)

        # Verify DuckDB Catalog registered batches and Parquet content
        import pyarrow.parquet as pq

        catalog = DuckDBCatalog(tmp_path / "catalog" / "qmo_catalog.duckdb")
        for ds in ["daily_price", "institutional_flow", "margin"]:
            batches = catalog.list_published_batches(ds)
            assert len(batches) == 1
            assert batches[0]["record_count"] > 0

            # Assert Universe count & dual-market ticker coverage (TWSE 2330, TPEx 8069)
            pq_file = tmp_path / "normalized" / ds / "b_20260924" / "data.parquet"
            assert pq_file.exists()
            tbl = pq.read_table(pq_file)
            sids = set(tbl.column("stock_id").to_pylist())
            markets = set(tbl.column("market").to_pylist())
            assert "2330" in sids, f"TWSE stock 2330 missing from {ds}"
            assert "8069" in sids, f"TPEx stock 8069 missing from {ds}"
            assert "TWSE" in markets and "TPEx" in markets, (
                f"Dual market coverage missing from {ds}"
            )

        # Verify Raw Snapshots exist
        raw_files = list((tmp_path / "raw").rglob("*.json"))
        assert len(raw_files) == 6

        # 2. Second run with --resume: should hit cache with 0 new HTTP requests
        mock_execute.reset_mock()
        res2 = runner.invoke(
            main,
            [
                "update",
                "--provider-mode",
                "official-bulk",
                "--date",
                "2026-09-24",
                "--resume",
                "--root-dir",
                str(tmp_path),
            ],
        )
        assert res2.exit_code == 0
        assert mock_execute.call_count == 0  # 100% cache hits from RawSnapshotStore!


def test_cli_update_official_bulk_limit_10_balanced(tmp_path: Path) -> None:
    """Verify official-bulk CLI --limit 10 yields 10 records per dataset (5 TWSE + 5 TPEx)."""
    import json
    from unittest.mock import patch

    import pyarrow.parquet as pq
    from click.testing import CliRunner

    from qmo.cli import main
    from qmo.providers.transport import HttpResponse

    twse_sids = ["1101", "1102", "2303", "2317", "2330", "2454"]
    tpex_sids = ["3105", "3293", "5347", "6274", "8069", "8299"]

    twse_price_payload = {
        "stat": "OK",
        "date": "20260924",
        "tables": [
            {
                "title": "每日收盤行情",
                "fields": [
                    "證券代號",
                    "證券名稱",
                    "成交股數",
                    "成交筆數",
                    "成交金額",
                    "開盤價",
                    "最高價",
                    "最低價",
                    "收盤價",
                    "漲跌(+/-)",
                    "漲跌價差",
                ],
                "data": [
                    [
                        sid,
                        f"TW_{sid}",
                        "1000",
                        "10",
                        "100000",
                        "100.0",
                        "102.0",
                        "99.0",
                        "100.0",
                        "+",
                        "1.0",
                    ]
                    for sid in twse_sids
                ],
            }
        ],
    }
    tpex_price_payload = {
        "stat": "OK",
        "date": "115/09/24",
        "tables": [
            {
                "title": "上櫃股票行情",
                "fields": [
                    "代號",
                    "名稱",
                    "收盤",
                    "漲跌",
                    "開盤",
                    "最高",
                    "最低",
                    "均價",
                    "成交股數",
                    "成交金額(元)",
                    "成交筆數",
                ],
                "data": [
                    [
                        sid,
                        f"TP_{sid}",
                        "50.0",
                        "1.0",
                        "50.0",
                        "51.0",
                        "49.0",
                        "50.0",
                        "500",
                        "25000",
                        "5",
                    ]
                    for sid in tpex_sids
                ],
            }
        ],
    }
    twse_inst_payload = {
        "stat": "OK",
        "date": "20260924",
        "fields": [
            "證券代號",
            "外陸資買進股數(不含外資自營商)",
            "外陸資賣出股數(不含外資自營商)",
            "外資自營商買進股數",
            "外資自營商賣出股數",
            "投信買進股數",
            "投信賣出股數",
            "自營商買進股數(自行買賣)",
            "自營商賣出股數(自行買賣)",
            "自營商買進股數(避險)",
            "自營商賣出股數(避險)",
            "三大法人買賣超股數",
        ],
        "data": [
            [sid, "100", "50", "0", "0", "50", "20", "30", "10", "0", "0", "100"]
            for sid in twse_sids
        ],
    }
    tpex_inst_payload = {
        "stat": "OK",
        "date": "115/09/24",
        "tables": [
            {
                "title": "三大法人買賣明細資訊",
                "fields": [
                    "代號",
                    "名稱",
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "外資買進",
                    "外資賣出",
                    "10",
                    "投信買進",
                    "投信賣出",
                    "13",
                    "14",
                    "15",
                    "16",
                    "17",
                    "18",
                    "19",
                    "自營買進",
                    "自營賣出",
                    "22",
                    "總買賣超",
                ],
                "data": [
                    [
                        sid,
                        f"TP_{sid}",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "100",
                        "50",
                        "50",
                        "50",
                        "20",
                        "30",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "30",
                        "10",
                        "20",
                        "100",
                    ]
                    for sid in tpex_sids
                ],
            }
        ],
    }
    twse_margin_payload = {
        "stat": "OK",
        "date": "20260924",
        "fields": [
            "代號",
            "名稱",
            "買進",
            "賣出",
            "現金償還",
            "前日餘額",
            "今日餘額",
            "限額",
            "買進",
            "賣出",
            "現券償還",
            "前日餘額",
            "今日餘額",
            "限額",
            "資券互抵",
            "註記",
        ],
        "data": [
            [
                sid,
                f"TW_{sid}",
                "10",
                "5",
                "0",
                "100",
                "105",
                "1000",
                "2",
                "1",
                "0",
                "20",
                "19",
                "500",
                "0",
                "",
            ]
            for sid in twse_sids
        ],
    }
    tpex_margin_payload = {
        "stat": "OK",
        "date": "115/09/24",
        "tables": [
            {
                "title": "上櫃股票融資融券餘額",
                "fields": [
                    "代號",
                    "名稱",
                    "前資餘額",
                    "資買",
                    "資賣",
                    "資現償",
                    "資餘額",
                    "資專戶",
                    "資償還",
                    "資限額",
                    "前券餘額",
                    "券賣",
                    "券買",
                    "券現償",
                    "券餘額",
                    "券專戶",
                    "券償還",
                    "券限額",
                    "資券相抵",
                    "備註",
                ],
                "data": [
                    [
                        sid,
                        f"TP_{sid}",
                        "100",
                        "10",
                        "5",
                        "0",
                        "105",
                        "0",
                        "0",
                        "1000",
                        "20",
                        "2",
                        "1",
                        "0",
                        "21",
                        "0",
                        "0",
                        "500",
                        "0",
                        "",
                    ]
                    for sid in tpex_sids
                ],
            }
        ],
    }

    def mock_execute(url: str, params: dict | None = None) -> HttpResponse:
        if "MI_INDEX" in url:
            body = json.dumps(twse_price_payload).encode("utf-8")
        elif "afterTrading/dailyQuotes" in url or "stk_quote" in url:
            body = json.dumps(tpex_price_payload).encode("utf-8")
        elif "fund/T86" in url:
            body = json.dumps(twse_inst_payload).encode("utf-8")
        elif "insti/dailyTrade" in url:
            body = json.dumps(tpex_inst_payload).encode("utf-8")
        elif "MI_MARGN" in url:
            body = json.dumps(twse_margin_payload).encode("utf-8")
        elif "margin/balance" in url:
            body = json.dumps(tpex_margin_payload).encode("utf-8")
        else:
            raise ValueError(f"Unexpected URL: {url}")
        return HttpResponse(
            status_code=200, headers={"content-type": "application/json"}, raw_bytes=body
        )

    runner = CliRunner()
    with patch("qmo.providers.transport.HttpTransport.execute", side_effect=mock_execute):
        res = runner.invoke(
            main,
            [
                "update",
                "--provider-mode",
                "official-bulk",
                "--limit",
                "10",
                "--date",
                "2026-09-24",
                "--root-dir",
                str(tmp_path),
            ],
        )
        assert res.exit_code == 0, f"CLI output: {res.output}"

        for ds in ["daily_price", "institutional_flow", "margin"]:
            pq_file = tmp_path / "normalized" / ds / "b_20260924" / "data.parquet"
            assert pq_file.exists()
            tbl = pq.read_table(pq_file)
            assert len(tbl) == 10, f"Dataset {ds} record count is {len(tbl)}, expected 10"
            markets = tbl.column("market").to_pylist()
            twse_count = sum(1 for m in markets if m == "TWSE")
            tpex_count = sum(1 for m in markets if m == "TPEx")
            assert twse_count == 5, f"Dataset {ds} TWSE count is {twse_count}, expected 5"
            assert tpex_count == 5, f"Dataset {ds} TPEx count is {tpex_count}, expected 5"


def test_cli_cross_dataset_universe_does_not_expand(tmp_path: Path) -> None:
    """Verify that margin dataset does not expand stock_master beyond daily_price universe."""
    import json
    from unittest.mock import patch

    import pyarrow.parquet as pq
    from click.testing import CliRunner

    from qmo.cli import main
    from qmo.providers.transport import HttpResponse

    twse_margin_sids = ["2330", "1441"]
    tpex_margin_sids = ["8069"]

    twse_price_payload = {
        "stat": "OK",
        "date": "20260924",
        "tables": [
            {
                "title": "每日收盤行情",
                "fields": [
                    "證券代號",
                    "證券名稱",
                    "成交股數",
                    "成交筆數",
                    "成交金額",
                    "開盤價",
                    "最高價",
                    "最低價",
                    "收盤價",
                    "漲跌(+/-)",
                    "漲跌價差",
                ],
                "data": [
                    [
                        "2330",
                        "台積電",
                        "1000",
                        "10",
                        "100000",
                        "100.0",
                        "102.0",
                        "99.0",
                        "100.0",
                        "+",
                        "1.0",
                    ]
                ],
            }
        ],
    }
    tpex_price_payload = {
        "stat": "OK",
        "date": "115/09/24",
        "tables": [
            {
                "title": "上櫃股票行情",
                "fields": [
                    "代號",
                    "名稱",
                    "收盤",
                    "漲跌",
                    "開盤",
                    "最高",
                    "最低",
                    "均價",
                    "成交股數",
                    "成交金額(元)",
                    "成交筆數",
                ],
                "data": [
                    [
                        "8069",
                        "元太",
                        "50.0",
                        "1.0",
                        "50.0",
                        "51.0",
                        "49.0",
                        "50.0",
                        "500",
                        "25000",
                        "5",
                    ]
                ],
            }
        ],
    }
    twse_margin_payload = {
        "stat": "OK",
        "date": "20260924",
        "fields": [
            "代號",
            "名稱",
            "買進",
            "賣出",
            "現金償還",
            "前日餘額",
            "今日餘額",
            "限額",
            "買進",
            "賣出",
            "現券償還",
            "前日餘額",
            "今日餘額",
            "限額",
            "資券互抵",
            "註記",
        ],
        "data": [
            [
                sid,
                f"TW_{sid}",
                "10",
                "5",
                "0",
                "100",
                "105",
                "1000",
                "2",
                "1",
                "0",
                "20",
                "19",
                "500",
                "0",
                "",
            ]
            for sid in twse_margin_sids
        ],
    }
    tpex_margin_payload = {
        "stat": "OK",
        "date": "115/09/24",
        "tables": [
            {
                "title": "上櫃股票融資融券餘額",
                "fields": [
                    "代號",
                    "名稱",
                    "前資餘額",
                    "資買",
                    "資賣",
                    "資現償",
                    "資餘額",
                    "資專戶",
                    "資償還",
                    "資限額",
                    "前券餘額",
                    "券賣",
                    "券買",
                    "券現償",
                    "券餘額",
                    "券專戶",
                    "券償還",
                    "券限額",
                    "資券相抵",
                    "備註",
                ],
                "data": [
                    [
                        sid,
                        f"TP_{sid}",
                        "100",
                        "10",
                        "5",
                        "0",
                        "105",
                        "0",
                        "0",
                        "1000",
                        "20",
                        "2",
                        "1",
                        "0",
                        "21",
                        "0",
                        "0",
                        "500",
                        "0",
                        "",
                    ]
                    for sid in tpex_margin_sids
                ],
            }
        ],
    }

    twse_inst_payload = {
        "stat": "OK",
        "date": "20260924",
        "fields": [
            "證券代號",
            "外陸資買進股數(不含外資自營商)",
            "外陸資賣出股數(不含外資自營商)",
            "外資自營商買進股數",
            "外資自營商賣出股數",
            "投信買進股數",
            "投信賣出股數",
            "自營商買進股數(自行買賣)",
            "自營商賣出股數(自行買賣)",
            "自營商買進股數(避險)",
            "自營商賣出股數(避險)",
            "三大法人買賣超股數",
        ],
        "data": [["2330", "100", "50", "0", "0", "50", "20", "30", "10", "0", "0", "100"]],
    }
    tpex_inst_payload = {
        "stat": "OK",
        "date": "115/09/24",
        "tables": [
            {
                "title": "三大法人買賣明細資訊",
                "fields": [
                    "代號",
                    "名稱",
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "外資買進",
                    "外資賣出",
                    "10",
                    "投信買進",
                    "投信賣出",
                    "13",
                    "14",
                    "15",
                    "16",
                    "17",
                    "18",
                    "19",
                    "自營買進",
                    "自營賣出",
                    "22",
                    "總買賣超",
                ],
                "data": [
                    [
                        "8069",
                        "元太",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "100",
                        "50",
                        "50",
                        "50",
                        "20",
                        "30",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "30",
                        "10",
                        "20",
                        "100",
                    ]
                ],
            }
        ],
    }

    def mock_execute(url: str, params: dict | None = None) -> HttpResponse:
        if "MI_INDEX" in url:
            body = json.dumps(twse_price_payload).encode("utf-8")
        elif "afterTrading/dailyQuotes" in url or "stk_quote" in url:
            body = json.dumps(tpex_price_payload).encode("utf-8")
        elif "fund/T86" in url:
            body = json.dumps(twse_inst_payload).encode("utf-8")
        elif "insti/dailyTrade" in url:
            body = json.dumps(tpex_inst_payload).encode("utf-8")
        elif "MI_MARGN" in url:
            body = json.dumps(twse_margin_payload).encode("utf-8")
        elif "margin/balance" in url:
            body = json.dumps(tpex_margin_payload).encode("utf-8")
        else:
            raise ValueError(f"Unexpected URL: {url}")
        return HttpResponse(
            status_code=200, headers={"content-type": "application/json"}, raw_bytes=body
        )

    runner = CliRunner()
    with patch("qmo.providers.transport.HttpTransport.execute", side_effect=mock_execute):
        res = runner.invoke(
            main,
            [
                "update",
                "--provider-mode",
                "official-bulk",
                "--dataset",
                "all",
                "--date",
                "2026-09-24",
                "--root-dir",
                str(tmp_path),
            ],
        )
        assert res.exit_code == 0, res.output

        pq_file = tmp_path / "normalized" / "margin" / "b_20260924" / "data.parquet"
        assert pq_file.exists()
        tbl = pq.read_table(pq_file)
        sids = set(tbl.column("stock_id").to_pylist())
        assert "1441" not in sids, "Extra stock 1441 in margin table should not expand universe"
        assert sids == {"2330", "8069"}
