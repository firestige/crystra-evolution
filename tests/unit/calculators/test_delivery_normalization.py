from datetime import UTC, datetime

import pytest

from crystra_evolution.domain.ports import FactReading
from crystra_evolution.normalization.delivery import normalize_delivery


def summary(
    fact_id: str,
    fields: tuple[tuple[str, str | int | None], ...],
    *,
    availability: str = "AVAILABLE",
    expiry: str = "ACTIVE",
) -> FactReading:
    return FactReading(
        fact_id=fact_id,
        kind="EVENT_CONTRIBUTION",
        source_identity=f"event:{fact_id}",
        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
        accepted_digest=fact_id[0] * 64,
        event_name="delivery.summary",
        completeness="FINAL",
        availability=availability,
        expiry=expiry,
        fields=fields,
        compatibility=(),
    )


def test_normalizes_only_active_available_delivery_summary_direct_fields() -> None:
    normalized = normalize_delivery(
        "delivery-a",
        (
            summary("a-summary", (("C10", "SUCCEEDED"), ("C55", 31), ("C56", "review"))),
            summary("b-expired", (("C55", 999),), expiry="EXPIRED"),
        ),
    )

    assert normalized.terminal_outcome == "SUCCEEDED"
    assert normalized.elapsed_time_ms == 31
    assert normalized.reached_stages == ("review",)
    assert normalized.provenance_refs == ("a" * 64,)


def test_conflicting_direct_delivery_facts_fail_closed_without_time_winner() -> None:
    with pytest.raises(ValueError, match="conflicting terminal outcome"):
        normalize_delivery(
            "delivery-a",
            (
                summary("a-summary", (("C10", "SUCCEEDED"),)),
                summary("b-summary", (("C10", "FAILED"),)),
            ),
        )
