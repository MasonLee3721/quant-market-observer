"""Execution Summary and Failure Persistence with Security Masking."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from qmo.storage.validation import validate_safe_identifier


def sanitize_sensitive_text(text: str) -> str:
    """Mask sensitive tokens, API keys, and credentials in text strings."""
    if not text:
        return ""
    # Mask key=val or token=val patterns in text
    pattern = re.compile(
        r"(token|api_token|api_key|key|secret|password)=([^\s&'\"]+)",
        flags=re.IGNORECASE,
    )
    return pattern.sub(r"\1=***MASKED***", text)


class ExecutionFailureRecord(BaseModel):
    """Failure record for a specific stock ticker."""

    stock_id: str
    error_type: str
    error_message: str

    def model_post_init(self, __context: Any) -> None:
        """Sanitize error message to prevent token leakage."""
        object.__setattr__(self, "error_message", sanitize_sensitive_text(self.error_message))


class ExecutionSummaryReport(BaseModel):
    """Execution summary and failure report model."""

    started_at: str
    ended_at: str
    dataset: str
    target_date: str
    universe_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    empty_data_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    failures: List[ExecutionFailureRecord] = Field(default_factory=list)
    cache_hits: int = Field(ge=0)
    api_requests: int = Field(ge=0)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with sanitized fields."""
        data = self.model_dump(mode="json")
        for failure in data.get("failures", []):
            if "error_message" in failure:
                failure["error_message"] = sanitize_sensitive_text(failure["error_message"])
        return data


def save_execution_summary(root_dir: Path, report: ExecutionSummaryReport) -> Path:
    """Persist execution summary and failure list as JSON to storage root.

    Stored under <root_dir>/reports/execution_summary_<dataset>_<target_date>.json
    Ensures safe dataset identifier validation and strict token masking.
    """
    validate_safe_identifier(report.dataset, "dataset")
    reports_dir = Path(root_dir) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    date_str = report.target_date.replace("-", "")
    report_path = reports_dir / f"execution_summary_{report.dataset}_{date_str}.json"

    data = report.to_dict()
    report_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return report_path


def load_execution_summary(report_path: Path) -> ExecutionSummaryReport:
    """Load and validate an execution summary report from JSON file."""
    text = Path(report_path).read_text(encoding="utf-8")
    data = json.loads(text)
    return ExecutionSummaryReport.model_validate(data)
