"""Parquet Storage Engine for normalized financial data models with schema validation."""

import hashlib
import typing
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel


class ParquetStore:
    """Serializes Pydantic models to Parquet tables with SHA-256 integrity and schema validation."""

    @staticmethod
    def validate_model_schema(models: Sequence[BaseModel]) -> Dict[str, Any]:
        """Inspect Pydantic models and return field schema type mapping."""
        if not models:
            raise ValueError("Cannot inspect empty model sequence")
        sample = models[0]
        schema_types = {}
        for f_name, f_info in sample.model_fields.items():
            schema_types[f_name] = f_info.annotation
        return schema_types

    @staticmethod
    def write_models(
        models: Sequence[BaseModel],
        output_path: Path,
        partition_cols: Optional[List[str]] = None,
    ) -> str:
        """Write list of Pydantic models to a Parquet file or partitioned dataset directory.

        Returns SHA-256 hash of the generated Parquet file (or composite hash if dataset).
        """
        if not models:
            raise ValueError("Cannot write empty model list to Parquet")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        dicts = [m.model_dump() for m in models]
        table = pa.Table.from_pylist(dicts)

        if partition_cols:
            output_path.mkdir(parents=True, exist_ok=True)
            pq.write_to_dataset(
                table,
                root_path=output_path,
                partition_cols=partition_cols,
                compression="snappy",
            )
            # Compute composite SHA-256 hash across partitioned files
            part_files = sorted(output_path.glob("**/*.parquet"))
            combined_hashes = "".join(
                hashlib.sha256(pf.read_bytes()).hexdigest() for pf in part_files
            )
            return hashlib.sha256(combined_hashes.encode("utf-8")).hexdigest()
        else:
            # Write single Parquet file with snappy compression
            pq.write_table(table, output_path, compression="snappy")
            file_bytes = output_path.read_bytes()
            return hashlib.sha256(file_bytes).hexdigest()

    @staticmethod
    def read_record_count(parquet_path: Path) -> int:
        """Read row count from Parquet metadata or dataset without full table load."""
        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet path missing at {parquet_path}")

        if parquet_path.is_dir():
            dataset = pq.ParquetDataset(parquet_path)
            return sum(fragment.metadata.num_rows for fragment in dataset.fragments)
        else:
            meta = pq.read_metadata(parquet_path)
            return int(meta.num_rows)

    @staticmethod
    def inspect_schema(parquet_path: Path) -> pa.Schema:
        """Inspect PyArrow schema from Parquet file or partitioned dataset."""
        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet path missing at {parquet_path}")

        if parquet_path.is_dir():
            dataset = pq.ParquetDataset(parquet_path)
            return dataset.schema
        else:
            return pq.read_schema(parquet_path)

    @staticmethod
    def inspect_schema_names(parquet_path: Path) -> List[str]:
        """Inspect schema field names from Parquet file or partitioned dataset."""
        schema = ParquetStore.inspect_schema(parquet_path)
        return list(schema.names)

    @staticmethod
    def verify_schema_contract(parquet_path: Path, model_cls: type[BaseModel]) -> None:
        """Verify exact field set, data types, and nullability contracts against Pydantic model."""
        schema = ParquetStore.inspect_schema(parquet_path)
        actual_names = set(schema.names)
        expected_names = set(model_cls.model_fields.keys())

        if actual_names != expected_names:
            missing = expected_names - actual_names
            extra = actual_names - expected_names
            msg = []
            if missing:
                msg.append(f"missing fields {sorted(missing)}")
            if extra:
                msg.append(f"extra fields {sorted(extra)}")
            raise ValueError(f"Schema field set mismatch for {parquet_path}: {', '.join(msg)}")

        # Verify data types and nullability for each field
        for field_name, field_info in model_cls.model_fields.items():
            pa_field = schema.field(field_name)
            annotation = field_info.annotation
            pa_type = pa_field.type

            if pa.types.is_dictionary(pa_type):
                pa_type = pa_type.value_type

            is_optional = False
            if annotation is not None:
                origin = typing.get_origin(annotation)
                if origin is typing.Union:
                    args = typing.get_args(annotation)
                    if type(None) in args:
                        is_optional = True
                elif annotation is type(None):
                    is_optional = True

            if field_info.default is None or not field_info.is_required():
                is_optional = True

            if pa.types.is_null(pa_type):
                if not is_optional:
                    err_null = (
                        f"Field '{field_name}' is non-optional required field, "
                        "but PyArrow type is null"
                    )
                    raise ValueError(err_null)
                continue

            if _is_type_match(annotation, float):
                if not (pa.types.is_floating(pa_type) or pa.types.is_decimal(pa_type)):
                    raise ValueError(
                        f"Field '{field_name}' type mismatch: expected float/decimal, got {pa_type}"
                    )
            elif _is_type_match(annotation, int):
                if not pa.types.is_integer(pa_type):
                    raise ValueError(
                        f"Field '{field_name}' type mismatch: expected integer, got {pa_type}"
                    )
            elif _is_type_match(annotation, str):
                if not (pa.types.is_string(pa_type) or pa.types.is_large_string(pa_type)):
                    raise ValueError(
                        f"Field '{field_name}' type mismatch: expected string, got {pa_type}"
                    )
            elif _is_type_match(annotation, bool):
                if not pa.types.is_boolean(pa_type):
                    raise ValueError(
                        f"Field '{field_name}' type mismatch: expected boolean, got {pa_type}"
                    )


def _is_type_match(annotation: Any, target_type: type) -> bool:
    """Helper to check if annotation matches target_type directly or inside Optional/Union."""
    if annotation is target_type:
        return True
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        return target_type in typing.get_args(annotation)
    return False

