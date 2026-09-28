# WP5 Verification & Audit Evidence Report

**Project**: `quant-market-observer`  
**Package Version**: `0.1.0`  
**Target Work Package**: `WP5` (Data Quality Gate & Atomic Publisher Integrity)  
**Verification Date**: `2026-09-28`  
**Target Git Commit Hash**: `ff42236` (Final audit evidence documentation alignment)  
**GitHub Actions Run**: [`36370440844`](https://github.com/MasonLee3721/quant-market-observer/actions/runs/36370440844) (SUCCESS / GREEN LIGHT)  
**Author**: 蘇荃 (SuQuan)  
**Reviewer**: 阿珂 (Kiro3)  
**Arbitrator**: MasonLee (老公)  

---

## Executive Summary

This report documents the verified audit evidence for Work Package 5 (WP5). All 6 core review requirements, 2 edge-case blockers, and GitHub Actions CI workflow alignment items have been fully resolved, verified via unit tests, type-checked, formatted, and validated across both local environments and GitHub Actions CI cloud runners.

---

## 1. Environment & Tooling Specifications

| Tool | Version | Verification Command | Execution Scope & Result |
| :--- | :--- | :--- | :--- |
| **Python** | `3.12.14` | `python --version` | `Python 3.12.14` (Explicitly locked in `.github/workflows/ci.yml`) |
| **uv** | `0.6.14` / `0.12.19` | `uv --version` | Executable package manager |
| **pytest** | `9.1.1` | `uv run pytest -v` | **Local (with raw M0 artifacts)**: `80 / 80 passed`<br>**GitHub CI Runner**: `79 passed, 1 skipped` |
| **mypy** | `2.3.1` | `uv run mypy src/qmo` | **Success: no issues found in 29 source files** |
| **ruff** | `0.16.9` | `uv run ruff check src tests` | **All checks passed!** |

---

## 2. Execution Scope & Data Parity Specification

1. **Local Full Artifact Execution**:
   - Includes uncommitted M0 raw spike payload directory (`data/spike/raw/TaiwanStockPrice`).
   - Executes `test_real_m0_artifact_raw_and_csv_parity` to verify full field-by-field raw-to-CSV normalization parity.
   - Result: **80 passed** (0 skipped, 0 failed).

2. **GitHub Actions CI Cloud Runner Execution**:
   - Clean ephemeral runner container without uncommitted large raw data dumps.
   - Dynamically evaluates `test_real_m0_artifact_raw_and_csv_parity`: when `data/spike/raw/TaiwanStockPrice` is absent, it calls `pytest.skip(...)`.
   - Result: **79 passed, 1 skipped** (Run [`36370440844`](https://github.com/MasonLee3721/quant-market-observer/actions/runs/36370440844), Status: `success`).

---

## 3. Requirements & Verification Traceability Matrix

| Requirement / Review Issue | Source File(s) | Key Implementation Detail | Test Case Name | Status |
| :--- | :--- | :--- | :--- | :--- |
| **1. Fail-Closed Numerical Parsing** | `src/qmo/validation/reconciler.py` | `_strict_int()` raises `ValueError` on `None`, `""`, and `"--"` instead of returning `0`. | `test_reconciler_fails_closed_on_empty_or_dash_integer_values` | **PASS** |
| **2. DuckDB Schema Migration & Backfill** | `src/qmo/storage/catalog.py` | `_init_and_migrate_schema()` adds `report_hash` column if missing and backfills canonical SHA-256 for legacy rows. | `test_duckdb_catalog_migrates_legacy_quality_reports_table_missing_report_hash_column` | **PASS** |
| **3. Immutable QualityReport & SHA-256 Validation** | `src/qmo/storage/catalog.py`, `src/qmo/validation/models.py` | Enforces SHA-256 canonical calculation; raises `BatchConflictError` on hash conflict without `INSERT OR REPLACE`. | `test_catalog_quality_report_immutable_conflict_detection` | **PASS** |
| **4. Dataset & Batch ID Cross Binding** | `src/qmo/storage/catalog.py` | `register_published_batch()` verifies `quality_report.dataset` and `quality_report.batch_id` match `manifest`. | `test_catalog_rejects_cross_batch_report_and_forged_hash` | **PASS** |
| **5. Atomic Report Backfill in Orphan Adoption** | `src/qmo/storage/publisher.py` | Stages report files in isolated temp dir, replaces via `.tmp`, and rolls back unlinked files on any failure. | `test_orphan_adoption_report_write_failure_leaves_published_dir_unmodified` | **PASS** |
| **6. Corrupt Legacy Report Migration Protection** | `src/qmo/storage/catalog.py` | Legacy `quality_reports` rows with invalid JSON fail closed via `StorageValidationError` without backfilling hash. | `test_corrupted_legacy_report_json_fails_migration_without_backfill` | **PASS** |
| **7. Tampered Published Artifact Protection** | `src/qmo/storage/publisher.py` | `_verify_existing_published_provenance()` validates physical existence and SHA-256 digests of all registered files. | `test_publisher_fails_closed_on_deleted_or_tampered_published_report_files` | **PASS** |
| **8. Removal of Silent Exception Swallowing** | `src/qmo/storage/publisher.py` | All `except Exception: pass` removed; report I/O and deserialization errors raise `StorageValidationError`. | `test_publisher_quality_report_write_failure_causes_rollback` | **PASS** |

---

## 4. Sign-off Status

- **Functionality**: **PASSED & SEALED**
- **GitHub Actions CI Pipeline**: **PASSED & VERIFIED (Run `36370440844`)**
- **Audit Documentation**: **FULLY ALIGNED & SEALED**
