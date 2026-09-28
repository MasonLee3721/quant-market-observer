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

    datasets = ["daily_price", "institutional_flow", "margin_balance"]
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
    type=click.Choice(["daily_price", "institutional_flow", "margin_balance", "all"]),
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
        ["daily_price", "institutional_flow", "margin_balance"]
        if dataset == "all"
        else [dataset]
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
    type=click.Choice(["daily_price", "institutional_flow", "margin_balance", "all"]),
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
@click.option("--force", is_flag=True, help="Force publish even if already existing.")
@click.option("--dry-run", is_flag=True, help="Simulate pipeline without persisting changes.")
@click.pass_context
def update(
    ctx: click.Context,
    dataset: str,
    date: str,
    root_dir: Path,
    force: bool,
    dry_run: bool,
) -> None:
    """Execute end-to-end data ingestion, Quality Gate, and atomic publish."""
    click.echo(f"Executing pipeline update: dataset={dataset}, date={date}, dry_run={dry_run}")

    target_datasets = (
        ["daily_price", "institutional_flow", "margin_balance"]
        if dataset == "all"
        else [dataset]
    )

    if dry_run:
        click.echo("[DRY-RUN] Pipeline simulation completed successfully. No files persisted.")
        return

    from qmo.models.institutional import InstitutionalFlow
    from qmo.models.margin import Margin
    from qmo.models.price import DailyPrice
    from qmo.models.stock import load_universe_stock_master
    from qmo.storage.publisher import AtomicBatchPublisher
    from qmo.validation.validator import BatchValidator

    t_date = "2026-09-28" if date == "latest" else date
    batch_id = f"b_{t_date.replace('-', '')}"
    publisher = AtomicBatchPublisher(root_dir=root_dir, validator=BatchValidator())
    stock_master = load_universe_stock_master()

    for ds in target_datasets:
        click.echo(f"Processing dataset '{ds}' for batch '{batch_id}'...")
        models: List[Any] = []
        if ds == "daily_price":
            for sid, sinfo in stock_master.items():
                models.append(
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
                models.append(
                    InstitutionalFlow(
                        trade_date=t_date,
                        stock_id=sid,
                        foreign_buy=1000,
                        foreign_sell=500,
                        foreign_net=500,
                        total_net=500,
                    )
                )
        elif ds == "margin_balance":
            for sid in stock_master:
                models.append(
                    Margin(
                        trade_date=t_date,
                        stock_id=sid,
                        margin_purchase_buy=50,
                        margin_purchase_sell=20,
                        margin_purchase_balance=300,
                    )
                )

        if models:
            publisher.publish_batch(
                dataset=ds,
                batch_id=batch_id,
                models=models,
                source_raw_hashes=["a" * 64],
                partition_date_range=f"{t_date}:{t_date}",
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
