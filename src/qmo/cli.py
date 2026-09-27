"""QMO Command Line Interface."""

from typing import Optional

import click

from qmo import __version__


@click.group(invoke_without_command=True)
@click.option("--version", "-v", is_flag=True, help="Show the version and exit.")
@click.pass_context
def main(ctx: click.Context, version: bool) -> None:
    """Quant Market Observer CLI."""
    if version:
        click.echo(f"qmo version {__version__}")
        ctx.exit()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
def status() -> None:
    """Show current pipeline and data storage status."""
    click.echo("=== Quant Market Observer Status ===")
    click.echo(f"CLI Version: {__version__}")
    click.echo("Current Phase: M1 — Data Pipeline MVP")
    click.echo("Status: Initialized")


@main.command()
@click.option("--date", default="latest", help="Target date to update (YYYY-MM-DD or 'latest').")
def update(date: str) -> None:
    """Fetch raw data and run normalization pipeline."""
    click.echo(f"Updating market data for date: {date}")
    click.echo("Provider execution shell — ready for WP2/WP3 integration.")


@main.command()
@click.option("--batch", "batch_id", help="Specific batch ID to validate.")
def validate(batch_id: Optional[str]) -> None:
    """Run data quality and spot-check validator."""
    target = batch_id or "latest"
    click.echo(f"Validating batch: {target}")
    click.echo("Validator execution shell — ready for WP5 integration.")


if __name__ == "__main__":
    main()
