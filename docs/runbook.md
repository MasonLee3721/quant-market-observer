# Quant Market Observer (QMO) — Operational Runbook & User Guide

**Document Version**: `v1.0`  
**Target Milestone**: `M1 — Data Pipeline MVP`  
**CLI Tooling**: `qmo` (Python Click CLI)  

---

## Executive Overview

This Runbook specifies standard operational procedures for running, validating, and troubleshooting the `quant-market-observer` data pipeline. The system processes market data across three primary datasets:
1. `daily_price` (OHLCV price and volume data)
2. `institutional_flow` (Foreign, Investment Trust, and Dealer institutional buy/sell flows)
3. `margin_balance` (Margin purchase and short sale balances)

---

## 1. Quick Start & Basic Commands

### 1.1 CLI Version & Help
To verify QMO installation and CLI version:
```bash
qmo --version
qmo --help
```

### 1.2 View Storage & Pipeline Status
To inspect current storage root, DuckDB catalog status, and published batch counts:
```bash
qmo status --root-dir data/
```

### 1.3 Run Data Quality Validation
To run validation gate spot-checks across published catalog batches:
```bash
# Text summary report across all datasets
qmo validate --root-dir data/ --format text

# Output JSON report format for automation
qmo validate --root-dir data/ --format json

# Output Markdown report format
qmo validate --root-dir data/ --format markdown

# Validate specific dataset or batch
qmo validate --dataset daily_price --batch b_20260925 --root-dir data/
```

### 1.4 Execute Pipeline Update
To execute end-to-end data ingestion, Quality Gate check, and atomic publish:
```bash
# Dry-run simulation (no disk changes)
qmo update --date 2026-09-25 --dry-run --root-dir data/

# Real pipeline update across all datasets
qmo update --date 2026-09-25 --root-dir data/

# Force update for specific dataset
qmo update --dataset daily_price --date 2026-09-25 --force --root-dir data/
```

---

## 2. Standard Operating Procedures (SOP)

### 2.1 Daily Automated Update (Post-Market 15:30 CST)
1. Run pipeline update for the current trade date:
   ```bash
   qmo update --date today --root-dir /var/lib/qmo/data/
   ```
2. Verify catalog status and quality report gate:
   ```bash
   qmo validate --root-dir /var/lib/qmo/data/ --format text
   ```
3. Confirm return status code `0`. If return code is `1`, refer to Section 3 Troubleshooting.

### 2.2 Historical Data Backfill Procedure
When backfilling historical date ranges:
```bash
for d in $(seq -w 01 30); do
  qmo update --date 2026-09-$d --root-dir data/
done
```

---

## 3. Error Handling & Troubleshooting

| Symptom / Error | Cause | Resolution Procedure |
| :--- | :--- | :--- |
| `BatchConflictError` | Batch already published with conflicting SHA-256 hash or provenance. | Verify raw data source integrity. Use `--force` flag only if re-publishing intentional data correction. |
| `StorageValidationError` | Staging schema mismatch or Quality Gate rule failure (e.g. stale date / duplicate PKs). | Inspect output log. Run `qmo validate --dataset <ds> --format json` to inspect specific failing check rules. |
| `DuckDBCatalog schema migration failed` | Uncommitted primary key or schema structure conflict. | Catalog automatically executes safe DuckDB table migration on startup. Ensure write lock is not held by another process. |

---

## 4. Maintenance & Audit Verification

All pipeline execution artifacts, raw byte snapshots, Parquet files, and DuckDB catalog records enforce SHA-256 byte-for-byte immutability.

To run the full test and verification suite locally:
```bash
uv run pytest -v
uv run mypy src/qmo
uv run ruff check src tests
```
