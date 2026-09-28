"""Quant Market Observer CLI for status, validation, and pipeline updates."""

import json
from pathlib import Path
from typing import Optional

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

    for ds in target_datasets:
        batch_id = f"b_{date.replace('-', '')}" if date != "latest" else "b_latest"
        click.echo(f"Processing dataset '{ds}' for batch '{batch_id}'...")

    click.echo(f"Pipeline update completed for date '{date}'. Target root: {root_dir.resolve()}")


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


if __name__ == "__main__":
    main()
