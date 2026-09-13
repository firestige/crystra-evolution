from crystra_evolution.calculators.role_model_task_outcome_rate import calculate
from crystra_evolution.domain.models import RoleModelTaskUnit


def task(index: int, outcome: str, *, model: str = "gpt-5") -> RoleModelTaskUnit:
    return RoleModelTaskUnit(
        task_id=f"task-{index:02d}",
        provider="openai",
        model=model,
        role="writer",
        runtime="dsh",
        terminal_outcome=outcome,
        provenance_refs=(f"task-{index:02d}",),
    )


def test_role_model_outcome_is_task_rate_per_exact_cohort() -> None:
    units = tuple(task(index, "SUCCEEDED" if index < 15 else "FAILED") for index in range(20))
    result = calculate(units)

    assert len(result.slices) == 2
    failed, succeeded = result.slices
    assert failed.slice_key["outcome"] == "FAILED"
    assert failed.value is not None and failed.value.value == "1/4"
    assert succeeded.slice_key["outcome"] == "SUCCEEDED"
    assert succeeded.value is not None and succeeded.value.value == "3/4"
    assert all(item.denominator == 20 for item in result.slices)
    assert all(
        item.coverage is not None and item.coverage.raw_ratio == "1" for item in result.slices
    )


def test_duplicate_task_in_same_cohort_fails_closed() -> None:
    duplicate = task(0, "SUCCEEDED")
    try:
        calculate((duplicate, duplicate))
    except ValueError as error:
        assert "duplicate Task/cohort" in str(error)
    else:
        raise AssertionError("duplicate Task/cohort unexpectedly accepted")


def test_role_model_outcome_keeps_exact_slices_below_minimum_sample() -> None:
    result = calculate(tuple(task(index, "SUCCEEDED") for index in range(19)))

    assert len(result.slices) == 1
    metric_slice = result.slices[0]
    assert metric_slice.slice_key["outcome"] == "SUCCEEDED"
    assert metric_slice.state == "UNAVAILABLE"
    assert metric_slice.withholding_reason == "SAMPLE_INSUFFICIENT"
    assert metric_slice.value is None
    assert metric_slice.numerator == 19
    assert metric_slice.denominator == 19
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "1"
