"""Parquet Storage Engine for normalized financial data models with schema validation."""

import hashlib
import typing
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel


def is_annotation_nullable(annotation: Any) -> bool:
    """Return True iff annotation explicitly permits None / Optional."""
    if annotation is type(None):
        return True
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        return type(None) in typing.get_args(annotation)
    return False


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
    def build_pyarrow_schema(model_cls: type[BaseModel]) -> pa.Schema:
        """Construct PyArrow schema with explicit types and nullability from Pydantic model."""
        fields = []
        for field_name, field_info in model_cls.model_fields.items():
            annotation = field_info.annotation
            is_nullable = is_annotation_nullable(annotation)

            target_type = annotation
            if is_nullable and typing.get_origin(annotation) is typing.Union:
                non_null_args = [a for a in typing.get_args(annotation) if a is not type(None)]
                if non_null_args:
                    target_type = non_null_args[0]

            if target_type is float:
                pa_type = pa.float64()
            elif target_type is int:
                pa_type = pa.int64()
            elif target_type is str:
                pa_type = pa.string()
            elif target_type is bool:
                pa_type = pa.bool_()
            elif target_type is list or typing.get_origin(target_type) is list:
                pa_type = pa.list_(pa.string())
            else:
                pa_type = pa.string()

            fields.append(pa.field(field_name, pa_type, nullable=is_nullable))

        return pa.schema(fields)

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
        pa_schema = ParquetStore.build_pyarrow_schema(type(models[0]))
        table = pa.Table.from_pylist(dicts, schema=pa_schema)

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
    def verify_schema_contract(
        parquet_path: Path,
        model_cls: type[BaseModel],
        partition_cols: Optional[List[str]] = None,
    ) -> None:
        """Verify exact field set, data types, and nullability contracts against Pydantic model."""
        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet path missing at {parquet_path}")

        valid_partition_cols = set(partition_cols) if partition_cols else {"trade_date"}

        files_to_check: List[Path] = []
        if parquet_path.is_dir():
            files_to_check = sorted(p for p in parquet_path.glob("**/*.parquet") if p.is_file())
            if not files_to_check:
                raise ValueError(f"No Parquet files found in directory {parquet_path}")

            dataset_schema = pq.ParquetDataset(parquet_path).schema
            actual_names = set(dataset_schema.names)
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
        else:
            files_to_check = [parquet_path]

        # Verify schema nullability and type contracts for every physical Parquet file
        for p_file in files_to_check:
            schema = pq.read_schema(p_file)
            for field_name, field_info in model_cls.model_fields.items():
                annotation = field_info.annotation
                is_nullable = is_annotation_nullable(annotation)

                if field_name not in schema.names:
                    if field_name in valid_partition_cols:
                        # Hive partition column extracted to directory path
                        continue
                    raise ValueError(
                        f"Field '{field_name}' missing from Parquet file schema in {p_file.name}"
                    )

                pa_field = schema.field(field_name)
                pa_type = pa_field.type

                if pa.types.is_dictionary(pa_type):
                    pa_type = pa_type.value_type

                # Verify PyArrow schema field nullability contract
                if pa_field.nullable != is_nullable:
                    err_null = (
                        f"Field '{field_name}' nullability contract mismatch in {p_file.name}: "
                        f"expected nullable={is_nullable}, got nullable={pa_field.nullable}"
                    )
                    raise ValueError(err_null)

                if pa.types.is_null(pa_type):
                    if not is_nullable:
                        err_null = (
                            f"Field '{field_name}' is non-optional required field, "
                            f"but PyArrow type is null in {p_file.name}"
                        )
                        raise ValueError(err_null)
                    continue

                if _is_type_match(annotation, float):
                    if not (pa.types.is_floating(pa_type) or pa.types.is_decimal(pa_type)):
                        raise ValueError(
                            f"Field '{field_name}' type mismatch in {p_file.name}: "
                            f"expected float/decimal, got {pa_type}"
                        )
                elif _is_type_match(annotation, int):
                    if not pa.types.is_integer(pa_type):
                        raise ValueError(
                            f"Field '{field_name}' type mismatch in {p_file.name}: "
                            f"expected integer, got {pa_type}"
                        )
                elif _is_type_match(annotation, str):
                    if not (pa.types.is_string(pa_type) or pa.types.is_large_string(pa_type)):
                        raise ValueError(
                            f"Field '{field_name}' type mismatch in {p_file.name}: "
                            f"expected string, got {pa_type}"
                        )
                elif _is_type_match(annotation, bool):
                    if not pa.types.is_boolean(pa_type):
                        raise ValueError(
                            f"Field '{field_name}' type mismatch in {p_file.name}: "
                            f"expected boolean, got {pa_type}"
                        )



def _is_type_match(annotation: Any, target_type: type) -> bool:
    """Helper to check if annotation matches target_type directly or inside Optional/Union."""
    if annotation is target_type:
        return True
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        return target_type in typing.get_args(annotation)
    return False

