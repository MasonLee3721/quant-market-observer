"""Parquet Storage Engine for normalized financial data models."""

import hashlib
from pathlib import Path
from typing import List, Sequence

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel


class ParquetStore:
    """Serializes normalized Pydantic models to Parquet tables with SHA-256 integrity."""

    @staticmethod
    def write_models(models: Sequence[BaseModel], output_path: Path) -> str:
        """Write list of Pydantic models to a Parquet file.

        Returns SHA-256 hash of the generated Parquet file.
        """
        if not models:
            raise ValueError("Cannot write empty model list to Parquet")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        dicts = [m.model_dump() for m in models]
        table = pa.Table.from_pylist(dicts)

        # Write Parquet with snappy compression
        pq.write_table(table, output_path, compression="snappy")

        file_bytes = output_path.read_bytes()
        return hashlib.sha256(file_bytes).hexdigest()

    @staticmethod
    def read_record_count(parquet_path: Path) -> int:
        """Read exact row count from Parquet metadata without loading entire dataset."""
        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file missing at {parquet_path}")
        meta = pq.read_metadata(parquet_path)
        return int(meta.num_rows)

    @staticmethod
    def inspect_schema_names(parquet_path: Path) -> List[str]:
        """Inspect schema field names from Parquet file."""
        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file missing at {parquet_path}")
        schema = pq.read_schema(parquet_path)
        return list(schema.names)
