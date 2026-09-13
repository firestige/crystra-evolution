from fractions import Fraction

from crystra_evolution.calculators.delivery_cycle_time_ms import calculate as cycle_time
from crystra_evolution.calculators.delivery_stage_reach import calculate as stage_reach
from crystra_evolution.calculators.delivery_terminal_outcome_rate import calculate as outcome_rate
from crystra_evolution.domain.models import DeliveryMetricUnit


def unit(
    delivery_id: str,
    *,
    outcome: str | None,
    elapsed_ms: int | float | None,
    stages: tuple[str, ...] = (),
) -> DeliveryMetricUnit:
    return DeliveryMetricUnit(
        delivery_id=delivery_id,
        terminal_outcome=outcome,
        elapsed_time_ms=(
            Fraction(str(elapsed_ms)) if isinstance(elapsed_ms, float) else elapsed_ms
        ),
        reached_stages=stages,
        provenance_refs=(f"fact:{delivery_id}",),
    )


def test_terminal_outcome_publishes_one_exact_rate_per_recorded_category() -> None:
    result = outcome_rate(
        (
            unit("d-1", outcome="SUCCEEDED", elapsed_ms=10),
            unit("d-2", outcome="FAILED", elapsed_ms=21),
            unit("d-3", outcome="SUCCEEDED", elapsed_ms=None),
            unit("d-open", outcome=None, elapsed_ms=None),
        )
    )

    assert result.metric_version == "2.0.0"
    assert [item.slice_key for item in result.slices] == [
        {"outcome": "FAILED"},
        {"outcome": "SUCCEEDED"},
    ]
    assert [item.value.value for item in result.slices if item.value] == ["1/3", "2/3"]
    assert all(item.denominator == 3 for item in result.slices)
    assert all(
        item.coverage is not None and item.coverage.raw_ratio == "3/4" for item in result.slices
    )
    assert all(
        item.missing_inputs == ("delivery.terminal_outcome:d-open",) for item in result.slices
    )


def test_cycle_time_uses_only_covered_terminal_deliveries_without_zero_fill() -> None:
    result = cycle_time(
        (
            unit("d-1", outcome="SUCCEEDED", elapsed_ms=10),
            unit("d-2", outcome="FAILED", elapsed_ms=21),
            unit("d-3", outcome="SUCCEEDED", elapsed_ms=None),
            unit("d-open", outcome=None, elapsed_ms=1_000),
        )
    )

    metric_slice = result.slices[0]
    assert metric_slice.value is not None
    assert metric_slice.value.value == "31/2"
    assert metric_slice.contributing_count == 2
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "2/3"
    assert metric_slice.coverage.state == "PARTIAL"
    assert metric_slice.missing_inputs == ("delivery.elapsed_time_ms:d-3",)


def test_stage_reach_tolerates_per_delivery_holes_and_keeps_exact_stage_identity() -> None:
    result = stage_reach(
        (
            unit("d-1", outcome="SUCCEEDED", elapsed_ms=10, stages=("review", "write")),
            unit("d-2", outcome="FAILED", elapsed_ms=20, stages=("write",)),
            unit("d-3", outcome="SUCCEEDED", elapsed_ms=30),
        )
    )

    assert [item.slice_key for item in result.slices] == [
        {"stage": "review"},
        {"stage": "write"},
    ]
    assert [item.value.value for item in result.slices if item.value] == ["1/2", "1"]
    assert all(item.denominator == 2 for item in result.slices)
    assert all(
        item.coverage is not None and item.coverage.raw_ratio == "2/3" for item in result.slices
    )
    assert all(item.missing_inputs == ("delivery.stage.reached:d-3",) for item in result.slices)


def test_cycle_time_preserves_a_legal_fractional_c55_without_float_authority() -> None:
    metric_slice = cycle_time((unit("d-1", outcome="SUCCEEDED", elapsed_ms=812.5),)).slices[0]

    assert metric_slice.value is not None
    assert metric_slice.value.value == "1625/2"
    assert metric_slice.measures == {"sum_ms": "812.5"}
