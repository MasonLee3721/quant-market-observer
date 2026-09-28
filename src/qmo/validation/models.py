"""Data models for quality validation results, checks, and quality reports."""

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class CheckSeverity(str, Enum):
    """Severity level of a validation check failure."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ValidationCheckResult(BaseModel):
    """Result of an individual validation check."""

    check_name: str
    severity: CheckSeverity
    passed: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    """Comprehensive quality validation report for a batch of models."""

    batch_id: str
    dataset: str
    created_at: str
    overall_passed: bool
    check_results: List[ValidationCheckResult] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    report_hash: str = ""

    def compute_report_hash(self) -> str:
        """Compute deterministic SHA-256 digest of QualityReport content."""
        import hashlib
        import json

        data_dict = {
            "batch_id": self.batch_id,
            "dataset": self.dataset,
            "created_at": self.created_at,
            "overall_passed": self.overall_passed,
            "summary": self.summary,
            "check_results": [c.model_dump() for c in self.check_results],
        }
        serialized = json.dumps(data_dict, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        computed = self.compute_report_hash()
        if not self.report_hash:
            self.report_hash = computed
        elif self.report_hash != computed:
            err_msg = (
                f"Invalid or forged report_hash: declared '{self.report_hash}', "
                f"expected '{computed}'"
            )
            raise ValueError(err_msg)

    def to_json(self, indent: int = 2) -> str:
        """Serialize QualityReport to JSON format."""
        return self.model_dump_json(indent=indent)

    def to_markdown(self) -> str:
        """Format QualityReport as a Markdown document."""
        status_icon = "✅ PASSED" if self.overall_passed else "❌ FAILED"
        lines = [
            f"# Quality Validation Report: {self.dataset} / {self.batch_id}",
            "",
            f"- **Status**: {status_icon}",
            f"- **Batch ID**: `{self.batch_id}`",
            f"- **Dataset**: `{self.dataset}`",
            f"- **Timestamp**: `{self.created_at}`",
            "",
            "## Summary Metrics",
            "",
            f"- Total Models / Rows: {self.summary.get('total_records', 0)}",
            f"- Unique Stocks: {self.summary.get('unique_stocks', 0)}",
            f"- Date Range: {self.summary.get('date_range', 'N/A')}",
            (
                f"- Checks Passed: {self.summary.get('passed_checks', 0)} / "
                f"{self.summary.get('total_checks', 0)}"
            ),
            "",
            "## Check Details",
            "",
            "| Check Name | Severity | Result | Message |",
            "|---|---|---|---|",
        ]

        for check in self.check_results:
            icon = "✅ PASS" if check.passed else f"❌ FAIL ({check.severity.value})"
            msg = check.message.replace("\n", " ")
            lines.append(f"| `{check.check_name}` | {check.severity.value} | {icon} | {msg} |")

        lines.append("")
        return "\n".join(lines)


class QualityGateError(Exception):
    """Raised when quality validation fails due to CRITICAL check failures."""

    def __init__(self, report: QualityReport) -> None:
        self.report = report
        critical_fails = [
            c for c in report.check_results if not c.passed and c.severity == CheckSeverity.CRITICAL
        ]
        fail_msgs_list: List[str] = []
        for c in critical_fails:
            detail_items: List[str] = []
            for key in ("violations", "invalid_dates", "freshness_issues", "mismatches"):
                if c.details and key in c.details and c.details[key]:
                    detail_items.append(", ".join(str(x) for x in c.details[key]))
            if detail_items:
                fail_msgs_list.append(f"{c.message} [{' | '.join(detail_items)}]")
            else:
                fail_msgs_list.append(c.message)
        fail_msgs = "; ".join(fail_msgs_list)
        super().__init__(
            f"Quality Gate failed for batch '{report.batch_id}' ({report.dataset}): {fail_msgs}"
        )
