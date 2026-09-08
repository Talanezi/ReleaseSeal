import pytest
from pydantic import ValidationError

from releaseseal.models import Finding, FindingSeverity, FindingStatus


def test_finding_schema_accepts_valid_timestamp_range() -> None:
    finding = Finding(
        code="example.code",
        severity=FindingSeverity.WARNING,
        status=FindingStatus.NEEDS_REVIEW,
        message="Example finding",
        source="example",
        timestamp_start_seconds=1.25,
        timestamp_end_seconds=2.5,
        details={"measured": 3},
        suggestion="Review this interval.",
    )

    assert finding.model_dump(mode="json")["status"] == "NEEDS_REVIEW"


def test_finding_schema_rejects_invalid_timestamp_range() -> None:
    with pytest.raises(ValidationError):
        Finding(
            code="example.code",
            severity=FindingSeverity.ERROR,
            status=FindingStatus.BLOCKED,
            message="Example finding",
            source="example",
            timestamp_start_seconds=2,
            timestamp_end_seconds=1,
        )
