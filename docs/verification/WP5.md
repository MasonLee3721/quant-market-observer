# WP5 Verification & Audit Evidence Report

**Project**: `quant-market-observer`  
**Package Version**: `0.1.0`  
**Target Work Package**: `WP5` (Data Quality Gate & Atomic Publisher Integrity)  
**Verification Date**: `2026-09-28`  
**Target Git Commit Hash**: `86ad031` (CI workflow alignment & M0 skip update)  
**Author**: 蘇荃 (SuQuan)  
**Reviewer**: 阿珂 (Kiro3)  
**Arbitrator**: MasonLee (老公)  

---

## Executive Summary

This report documents the reproducible verification evidence for Work Package 5 (WP5). All 6 core review requirements, 2 edge-case blockers, and GitHub Actions CI workflow alignment items have been fully resolved and verified.

---

## 1. Environment & Tooling Specifications

| Tool | Version | Verification Command | Result |
| :--- | :--- | :--- | :--- |
| **Python** | `3.12.14` | `python --version` | `Python 3.12.14` (Locked in `.github/workflows/ci.yml`) |
| **uv** | `0.6.14` | `uv --version` | `uv 0.6.14` |
| **pytest** | `9.1.1` | `uv run pytest -v` | **80 / 80 passed** (4.33s) |
| **mypy** | `1.15.0` | `uv run mypy src/qmo` | **Success: no issues found** |
| **ruff** | `0.9.10` | `uv run ruff check src tests` | **All checks passed!** |

---

## 2. GitHub Actions CI Alignment & Fixes

1. **Explicit Python 3.12 Lock**: `.github/workflows/ci.yml` explicitly specifies `python-version: "3.12"` to ensure deterministic execution on GitHub Runners.
2. **Tool Version Logging**: CI workflow logs exact versions of `python`, `pytest`, `mypy`, and `ruff` before running tests.
3. **M0 Large Raw Spike Data Handling**: `test_real_m0_artifact_raw_and_csv_parity` dynamically checks if `data/spike/raw/TaiwanStockPrice` exists. If missing (such as in fresh GitHub Actions CI containers), it calls `pytest.skip(...)`, preventing false negative CI failures while preserving local parity testing when artifacts exist.

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

## 4. Verification Evidence & Log Artifacts

### 4.1 Pytest Execution Summary
```text
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0 -- /home/agent/quant-market-observer/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/agent/quant-market-observer
configfile: pyproject.toml
testpaths: tests
collected 80 items

tests/test_cli.py::test_cli_version PASSED                               [  1%]
tests/test_cli.py::test_cli_status PASSED                                [  2%]
...
tests/test_storage.py::test_orphan_adoption_report_write_failure_leaves_published_dir_unmodified PASSED [ 67%]
tests/test_storage.py::test_corrupted_legacy_report_json_fails_migration_without_backfill PASSED [ 68%]
...
tests/test_validation.py::test_reconciler_fails_closed_on_empty_or_dash_integer_values PASSED [100%]

============================== 80 passed in 4.33s ==============================
```

### 4.2 Mypy Type Check Summary
```text
Success: no issues found in 29 source files
```

### 4.3 Ruff Linter Summary
```text
All checks passed!
```

---

## 5. Sign-off Status

- **Status**: **WP5 VERIFIED & READY FOR THREE-WAY SIGN-OFF**
- **Target Repository Branch**: `origin/main`
