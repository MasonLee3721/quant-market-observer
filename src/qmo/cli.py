"""Quant Market Observer CLI for status, validation, and pipeline updates."""

import json
from pathlib import Path
from typing import Any, List, Optional

import click

from qmo import __version__
from qmo.storage.catalog import DuckDBCatalog
from qmo.storage.raw_store import RawSnapshotStore


@click.group(invoke_without_command=True)
@click.option("--version", "-v", is_flag=True, help="Show the version and exit.")
@click.pass_context
def main(ctx: click.Context, version: bool) -> None:
    """Quant Market Observer (QMO) CLI."""
    if version:
        click.echo(f"qmo version {__version__}")
        ctx.exit()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option(
    "--root-dir",
    type=click.Path(path_type=Path),
    default=Path("data"),
    help="Root storage directory path.",
)
def status(root_dir: Path) -> None:
    """Show current pipeline, catalog, and data storage status."""
    click.echo("=== Quant Market Observer Status ===")
    click.echo(f"CLI Version: {__version__}")
    click.echo("Current Phase: M1 — Data Pipeline MVP")
    click.echo(f"Storage Root: {root_dir.resolve()}")

    cat_path = root_dir / "catalog" / "qmo_catalog.duckdb"
    if not cat_path.exists() and (root_dir / "catalog.duckdb").exists():
        cat_path = root_dir / "catalog.duckdb"
    catalog = DuckDBCatalog(cat_path if cat_path.exists() else None)
    raw_store = RawSnapshotStore(root_dir / "raw")

    click.echo(f"Raw Snapshots Directory: {raw_store.base_dir}")
    click.echo(f"Catalog DB: {cat_path} (Exists: {cat_path.exists()})")

    datasets = ["daily_price", "institutional_flow", "margin"]
    click.echo("\n--- Published Datasets Summary ---")
    for ds in datasets:
        batches = catalog.list_published_batches(ds)
        if not batches:
            click.echo(f"  [{ds}]: No published batches")
            continue

        total_records = sum(b.get("record_count", 0) for b in batches)
        latest_batch = batches[0]
        date_range = latest_batch.get("partition_date_range") or "N/A"
        click.echo(
            f"  [{ds}]: {len(batches)} batch(es), "
            f"{total_records} total rows, "
            f"latest batch='{latest_batch.get('batch_id')}' ({date_range})"
        )


@main.command()
@click.option(
    "--dataset",
    type=click.Choice(["daily_price", "institutional_flow", "margin", "all"]),
    default="all",
    help="Target dataset to validate.",
)
@click.option("--batch", "batch_id", help="Specific batch ID to validate.")
@click.option(
    "--root-dir",
    type=click.Path(path_type=Path),
    default=Path("data"),
    help="Root storage directory path.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "markdown"]),
    default="text",
    help="Output report format.",
)
@click.pass_context
def validate(
    ctx: click.Context,
    dataset: str,
    batch_id: Optional[str],
    root_dir: Path,
    output_format: str,
) -> None:
    """Run data quality gate and catalog spot-check validator."""
    cat_path = root_dir / "catalog" / "qmo_catalog.duckdb"
    if not cat_path.exists() and (root_dir / "catalog.duckdb").exists():
        cat_path = root_dir / "catalog.duckdb"
    catalog = DuckDBCatalog(cat_path if cat_path.exists() else None)

    target_datasets = (
        ["daily_price", "institutional_flow", "margin"] if dataset == "all" else [dataset]
    )

    validated_reports = []
    has_failure = False

    for ds in target_datasets:
        batches = catalog.list_published_batches(ds)
        if batch_id:
            batches = [b for b in batches if b.get("batch_id") == batch_id]

        for b in batches:
            b_id = b.get("batch_id", "")
            qr_dict = catalog.get_quality_report(ds, b_id)
            if qr_dict is not None:
                from qmo.validation.models import QualityReport

                qr = QualityReport.model_validate(qr_dict)
                validated_reports.append(qr)
                if not qr.overall_passed:
                    has_failure = True

    if not validated_reports:
        click.echo(f"No registered quality reports found for selection (dataset={dataset}).")
        return

    if output_format == "json":
        reports_json = [r.model_dump() for r in validated_reports]
        click.echo(json.dumps(reports_json, indent=2))
    elif output_format == "markdown":
        for r in validated_reports:
            click.echo(r.to_markdown())
            click.echo("\n---")
    else:
        click.echo(f"Validated {len(validated_reports)} quality report(s):")
        for r in validated_reports:
            status_str = "PASSED" if r.overall_passed else "FAILED"
            click.echo(
                f"  [{r.dataset}] batch='{r.batch_id}' status={status_str} "
                f"checks={r.summary.get('passed_checks', 0)}/{r.summary.get('total_checks', 0)} "
                f"hash={r.report_hash[:12]}..."
            )

    if has_failure:
        click.echo("\n[WARNING] One or more quality reports failed validation gate checks.")
        ctx.exit(1)


@main.command()
@click.option(
    "--dataset",
    type=click.Choice(["daily_price", "institutional_flow", "margin", "all"]),
    default="all",
    help="Target dataset to update.",
)
@click.option(
    "--date",
    default="latest",
    help="Target date to update (YYYY-MM-DD or 'latest').",
)
@click.option(
    "--root-dir",
    type=click.Path(path_type=Path),
    default=Path("data"),
    help="Root storage directory path.",
)
@click.option(
    "--api-token",
    default="",
    envvar="FINMIND_API_TOKEN",
    help="FinMind API token; defaults to FINMIND_API_TOKEN.",
)
@click.option(
    "--real-api/--synthetic",
    default=True,
    help="Use real providers (default); --synthetic is for explicit development only.",
)
@click.option(
    "--holiday-calendar",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Optional CSV containing Taiwan market closure dates.",
)
@click.option("--limit", type=click.IntRange(min=1), help="Limit universe size for smoke runs.")
@click.option(
    "--request-interval",
    type=click.FloatRange(min=0.0),
    default=0.25,
    show_default=True,
    help="Minimum seconds between provider requests.",
)
@click.option(
    "--max-retries",
    type=click.IntRange(min=0, max=10),
    default=3,
    show_default=True,
    help="Retries for network, HTTP 429, and HTTP 5xx errors.",
)
@click.option(
    "--resume/--no-resume",
    default=True,
    help="Reuse hash-verified raw snapshots for matching requests.",
)
@click.option("--force", is_flag=True, help="Force publish even if already existing.")
@click.option("--dry-run", is_flag=True, help="Simulate pipeline without persisting changes.")
@click.pass_context
def update(
    ctx: click.Context,
    dataset: str,
    date: str,
    root_dir: Path,
    api_token: str,
    real_api: bool,
    holiday_calendar: Optional[Path],
    limit: Optional[int],
    request_interval: float,
    max_retries: int,
    resume: bool,
    force: bool,
    dry_run: bool,
) -> None:
    """Execute end-to-end data ingestion, Quality Gate, and atomic publish."""
    click.echo(f"Executing pipeline update: dataset={dataset}, date={date}, dry_run={dry_run}")

    target_datasets = (
        ["daily_price", "institutional_flow", "margin"] if dataset == "all" else [dataset]
    )

    if dry_run:
        click.echo("[DRY-RUN] Pipeline simulation completed successfully. No files persisted.")
        return

    from datetime import datetime, timezone

    from qmo.models.stock import load_universe_stock_master, parse_stock_info_payload
    from qmo.normalizers.institutional import InstitutionalNormalizer
    from qmo.normalizers.margin import MarginNormalizer
    from qmo.normalizers.price import PriceNormalizer
    from qmo.providers.finmind import FinMindProvider
    from qmo.providers.transport import HttpTransport
    from qmo.storage.execution_report import (
        ExecutionFailureRecord,
        ExecutionSummaryReport,
        save_execution_summary,
    )
    from qmo.storage.publisher import AtomicBatchPublisher
    from qmo.storage.raw_store import RawSnapshotStore
    from qmo.trading_calendar import load_market_holidays, resolve_latest_trading_date
    from qmo.validation.validator import BatchValidator

    holidays = load_market_holidays(holiday_calendar) if holiday_calendar else set()
    t_date = (
        resolve_latest_trading_date(holidays=holidays).isoformat() if date == "latest" else date
    )
    batch_id = f"b_{t_date.replace('-', '')}"
    publisher = AtomicBatchPublisher(root_dir=root_dir, validator=BatchValidator())
    raw_store = RawSnapshotStore(base_dir=root_dir / "raw")
    transport = HttpTransport(max_retries=max_retries, min_request_interval=request_interval)
    provider = FinMindProvider(transport=transport, api_token=api_token)

    if real_api:
        click.echo("Fetching full Taiwan listed and OTC stock master universe from FinMind API...")
        try:
            info_envelope = (
                raw_store.load_matching("stock_info", {"dataset": "TaiwanStockInfo"})
                if resume
                else None
            )
            if info_envelope is None:
                info_envelope = provider.fetch_stock_info()
            if info_envelope.status_code != 200:
                raise ValueError(f"TaiwanStockInfo returned HTTP {info_envelope.status_code}")
            raw_store.save(info_envelope, "stock_info")
            stock_master = parse_stock_info_payload(info_envelope.raw_body_str)
        except Exception as e:
            click.echo(f"[FAIL-CLOSED] Failed to fetch dynamic stock master info: {e}", err=True)
            ctx.exit(1)
    else:
        stock_master = load_universe_stock_master()

    if limit is not None:
        stock_master = dict(list(stock_master.items())[:limit])
        click.echo(f"Smoke-run universe limited to {len(stock_master)} ticker(s).")

    for ds in target_datasets:
        click.echo(f"Processing dataset '{ds}' for batch '{batch_id}'...")
        started_at = datetime.now(timezone.utc).isoformat()
        models: List[Any] = []
        raw_hashes: List[str] = []
        cache_hits = 0
        api_requests = 0
        success_count = 0
        empty_data_count = 0
        failure_records: List[ExecutionFailureRecord] = []

        if real_api:
            if ds == "daily_price":
                normalizer = PriceNormalizer(stock_master=stock_master)
                for sid in stock_master:
                    try:
                        required_params = {
                            "data_id": sid,
                            "start_date": t_date,
                            "end_date": t_date,
                        }
                        env = raw_store.load_matching(ds, required_params) if resume else None
                        if env is None:
                            api_requests += 1
                            env = provider.fetch_daily_price(sid, t_date, t_date)
                            h_val, _ = raw_store.save(env, ds)
                        else:
                            cache_hits += 1
                            h_val = env.content_hash
                        raw_hashes.append(h_val)
                        norm_models: List[Any] = normalizer.normalize(env)
                        if norm_models:
                            success_count += 1
                            models.extend(norm_models)
                        else:
                            empty_data_count += 1
                    except Exception as exc:
                        failure_records.append(
                            ExecutionFailureRecord(
                                stock_id=sid,
                                error_type=type(exc).__name__,
                                error_message=str(exc),
                            )
                        )
            elif ds == "institutional_flow":
                inst_normalizer = InstitutionalNormalizer(stock_master=stock_master)
                for sid in stock_master:
                    try:
                        required_params = {
                            "data_id": sid,
                            "start_date": t_date,
                            "end_date": t_date,
                        }
                        env = raw_store.load_matching(ds, required_params) if resume else None
                        if env is None:
                            api_requests += 1
                            env = provider.fetch_institutional_flow(sid, t_date, t_date)
                            h_val, _ = raw_store.save(env, ds)
                        else:
                            cache_hits += 1
                            h_val = env.content_hash
                        raw_hashes.append(h_val)
                        inst_models: List[Any] = inst_normalizer.normalize(env)
                        if inst_models:
                            success_count += 1
                            models.extend(inst_models)
                        else:
                            empty_data_count += 1
                    except Exception as exc:
                        failure_records.append(
                            ExecutionFailureRecord(
                                stock_id=sid,
                                error_type=type(exc).__name__,
                                error_message=str(exc),
                            )
                        )
            elif ds == "margin":
                margin_normalizer = MarginNormalizer(stock_master=stock_master)
                for sid in stock_master:
                    try:
                        required_params = {
                            "data_id": sid,
                            "start_date": t_date,
                            "end_date": t_date,
                        }
                        env = raw_store.load_matching(ds, required_params) if resume else None
                        if env is None:
                            api_requests += 1
                            env = provider.fetch_margin(sid, t_date, t_date)
                            h_val, _ = raw_store.save(env, ds)
                        else:
                            cache_hits += 1
                            h_val = env.content_hash
                        raw_hashes.append(h_val)
                        mrg_models: List[Any] = margin_normalizer.normalize(env)
                        if mrg_models:
                            success_count += 1
                            models.extend(mrg_models)
                        else:
                            empty_data_count += 1
                    except Exception as exc:
                        failure_records.append(
                            ExecutionFailureRecord(
                                stock_id=sid,
                                error_type=type(exc).__name__,
                                error_message=str(exc),
                            )
                        )
        else:
            from qmo.models.institutional import InstitutionalFlow
            from qmo.models.margin import Margin
            from qmo.models.price import DailyPrice

            synth_models: List[Any] = []
            if ds == "daily_price":
                for sid, sinfo in stock_master.items():
                    synth_models.append(
                        DailyPrice(
                            trade_date=t_date,
                            stock_id=sid,
                            market=sinfo.market,
                            open_price=100.0,
                            high_price=105.0,
                            low_price=98.0,
                            close_price=102.5,
                            trading_volume=50000,
                            trading_value=5125000,
                            source="TWSE:STOCK_DAY",
                        )
                    )
            elif ds == "institutional_flow":
                for sid in stock_master:
                    synth_models.append(
                        InstitutionalFlow(
                            trade_date=t_date,
                            stock_id=sid,
                            foreign_buy=1000,
                            foreign_sell=500,
                            foreign_net=500,
                            total_net=500,
                        )
                    )
            elif ds == "margin":
                for sid in stock_master:
                    synth_models.append(
                        Margin(
                            trade_date=t_date,
                            stock_id=sid,
                            margin_purchase_buy=50,
                            margin_purchase_sell=20,
                            margin_purchase_balance=300,
                        )
                    )
            models = synth_models
            success_count = len(models)

        ended_at = datetime.now(timezone.utc).isoformat()
        summary_report = ExecutionSummaryReport(
            started_at=started_at,
            ended_at=ended_at,
            dataset=ds,
            target_date=t_date,
            universe_count=len(stock_master),
            success_count=success_count,
            empty_data_count=empty_data_count,
            failure_count=len(failure_records),
            failures=failure_records,
            cache_hits=cache_hits,
            api_requests=api_requests,
        )
        report_file = save_execution_summary(root_dir=root_dir, report=summary_report)
        click.echo(f"  [{ds}] Execution summary report persisted to '{report_file}'.")

        if failure_records:
            preview = "; ".join(f"{f.stock_id}:{f.error_type}" for f in failure_records[:5])
            raise click.ClickException(
                f"[FAIL-CLOSED] {ds} failed for {len(failure_records)} ticker(s): {preview}"
            )

        if not models:
            raise click.ClickException(
                f"[FAIL-CLOSED] Provider returned zero normalized rows for {ds}"
            )
        publisher.publish_batch(
            dataset=ds,
            batch_id=batch_id,
            models=models,
            source_raw_hashes=raw_hashes if raw_hashes else ["a" * 64],
            partition_date_range=f"{t_date}:{t_date}",
            target_tickers=list(stock_master),
        )
        click.echo(f"  [{ds}] Published {len(models)} record(s) to dataset '{ds}'.")

    click.echo(
        f"Pipeline update completed for date '{t_date}'. "
        f"Catalog DB updated at: {root_dir.resolve()}"
    )


@main.command()
@click.option(
    "--date",
    default="latest",
    help="Target date to compute indicators (YYYY-MM-DD or 'latest').",
)
@click.option(
    "--root-dir",
    type=click.Path(path_type=Path),
    default=Path("data"),
    help="Root storage directory path.",
)
def calculate(date: str, root_dir: Path) -> None:
    """Execute end-to-end factor computation, market breadth, and stock ranking."""
    click.echo(f"Executing indicator calculation pipeline for date: {date}")

    from qmo.indicators.pipeline import IndicatorPipelineRunner

    runner = IndicatorPipelineRunner(root_dir=root_dir)
    res = runner.run_pipeline(prices_data=[], inst_data=[], margin_data=[], date_str=date)

    click.echo("=== Indicator Calculation Summary ===")
    click.echo(f"Batch ID: {res.get('batch_id')}")
    click.echo(f"Market Breadth (20D): {res.get('market_breadth_20')}")
    click.echo(f"Market Composite Score: {res.get('market_score')}")
    click.echo(f"Processed Tickers: {res.get('processed_stocks')}")


@main.command()
@click.option(
    "--date",
    default="latest",
    help="Target date to generate signals (YYYY-MM-DD or 'latest').",
)
@click.option(
    "--root-dir",
    type=click.Path(path_type=Path),
    default=Path("data"),
    help="Root storage directory path.",
)
def signal(date: str, root_dir: Path) -> None:
    """Generate strategy selection signals and portfolio weights."""
    click.echo(f"Generating strategy signals for date: {date}")

    from qmo.indicators.pipeline import IndicatorPipelineRunner
    from qmo.signals.engine import generate_leader_breakout_signals
    from qmo.signals.portfolio import allocate_portfolio

    runner = IndicatorPipelineRunner(root_dir=root_dir)
    summary = runner.run_pipeline(prices_data=[], inst_data=[], margin_data=[], date_str=date)

    sample_stocks = summary.get("stocks", [])
    signals = generate_leader_breakout_signals(sample_stocks)
    portfolio = allocate_portfolio(signals)

    click.echo("=== Strategy Signal Summary ===")
    click.echo(f"Active Signals Count: {len(signals)}")
    click.echo(f"Allocated Portfolio Positions: {len(portfolio)}")


@main.command()
@click.option(
    "--date",
    default="latest",
    help="Target date for report generation (YYYY-MM-DD or 'latest').",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "html"]),
    default="markdown",
    help="Output report format.",
)
@click.option(
    "--root-dir",
    type=click.Path(path_type=Path),
    default=Path("data"),
    help="Root storage directory path.",
)
def report(date: str, output_format: str, root_dir: Path) -> None:
    """Generate daily Markdown market report or HTML visual dashboard."""
    click.echo(f"Generating {output_format} market report for date: {date}", err=True)

    from qmo.indicators.pipeline import IndicatorPipelineRunner
    from qmo.reports.generator import generate_html_report, generate_markdown_report
    from qmo.signals.engine import generate_leader_breakout_signals
    from qmo.signals.portfolio import allocate_portfolio

    runner = IndicatorPipelineRunner(root_dir=root_dir)
    summary = runner.run_pipeline(prices_data=[], inst_data=[], margin_data=[], date_str=date)
    stocks = summary.get("stocks", [])
    signals = generate_leader_breakout_signals(stocks)
    portfolio = allocate_portfolio(signals)

    if output_format == "html":
        content = generate_html_report(summary, signals, portfolio)
    else:
        content = generate_markdown_report(summary, signals, portfolio)

    click.echo(content)


if __name__ == "__main__":
    main()
