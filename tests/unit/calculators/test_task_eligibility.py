from crystra_evolution.calculators.task_cohort_comparison_eligibility import calculate
from crystra_evolution.domain.models import TaskMetricUnit


def task(index: int, *, state: str, covered: bool = True) -> TaskMetricUnit:
    return TaskMetricUnit(
        task_id=f"task-{index:02d}",
        terminal_outcome="SUCCEEDED" if state == "ELIGIBLE" else None,
        classification=state,
        covered=covered,
        provenance_refs=(f"task-ref-{index:02d}",),
    )


def test_eligibility_uses_covered_population_and_publishes_exclusion_counts() -> None:
    units = tuple(task(index, state="ELIGIBLE") for index in range(16)) + (
        task(16, state="OPEN_DELIVERY"),
        task(17, state="MIXED_DELIVERY_OUTCOMES"),
        task(18, state="UNDEFINED_TASK_MEMBERSHIP", covered=False),
        task(19, state="MISSING_DELIVERY_READING", covered=False),
    )

    result = calculate(units)
    metric_slice = result.slices[0]
    assert metric_slice.value is not None and metric_slice.value.value == "4/5"
    assert metric_slice.withholding_reason is None
    assert metric_slice.numerator == 16
    assert metric_slice.denominator == 20
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "9/10"
    assert metric_slice.measures == {
        "excluded_MISSING_DELIVERY_READING": 1,
        "excluded_MIXED_DELIVERY_OUTCOMES": 1,
        "excluded_OPEN_DELIVERY": 1,
        "excluded_UNDEFINED_TASK_MEMBERSHIP": 1,
    }


def test_eligibility_publishes_exact_ratio_at_minimum_sample() -> None:
    units = tuple(task(index, state="ELIGIBLE") for index in range(19)) + (
        task(19, state="OPEN_DELIVERY"),
    )
    metric_slice = calculate(units).slices[0]
    assert metric_slice.value is not None
    assert metric_slice.value.value == "19/20"
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "1"
