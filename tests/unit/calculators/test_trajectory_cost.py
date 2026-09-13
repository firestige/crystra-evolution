from crystra_evolution.calculators.trajectory_partial_cost import calculate
from crystra_evolution.domain.models import ReportedUsageUnit


def usage(
    delivery: str, value: int, *, unit: str = "USD", lower_bound: bool = False
) -> ReportedUsageUnit:
    return ReportedUsageUnit(
        usage_identity=f"usage:{delivery}",
        delivery_id=delivery,
        kind="money",
        unit=unit,
        source="provider",
        source_id="invoice",
        value=value,
        provenance_refs=(f"fact:{delivery}",),
        lower_bound=lower_bound,
    )


def test_trajectory_cost_sums_only_exact_usage_group_and_exposes_holes() -> None:
    deliveries = tuple(f"d-{index:02d}" for index in range(21))
    units = tuple(usage(delivery, index + 1) for index, delivery in enumerate(deliveries[:20]))
    result = calculate(deliveries, units)
    metric_slice = result.slices[0]

    assert metric_slice.value is not None
    assert metric_slice.value.kind == "MONEY"
    assert metric_slice.value.value == 210
    assert metric_slice.value.unit == "USD"
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "20/21"
    assert metric_slice.missing_inputs == ("reported_usage:d-20",)
    assert "cost_basis" not in metric_slice.compatibility


def test_money_and_tokens_or_different_units_never_combine() -> None:
    deliveries = tuple(f"d-{index:02d}" for index in range(40))
    usd = tuple(usage(delivery, 1, unit="USD") for delivery in deliveries[:20])
    eur = tuple(usage(delivery, 2, unit="EUR") for delivery in deliveries[20:])
    token = ReportedUsageUnit(
        "usage:tokens", "d-00", "tokens", "tokens", "provider", "meter", 999, ()
    )
    result = calculate(deliveries, (*usd, *eur, token))

    assert [
        (item.slice_key["unit"], item.value.value if item.value else None) for item in result.slices
    ] == [
        ("EUR", 40),
        ("USD", 20),
    ]


def test_lower_bound_usage_sum_remains_a_lower_bound_metric_result() -> None:
    deliveries = tuple(f"d-{index:02d}" for index in range(20))
    units = tuple(
        usage(delivery, 1, lower_bound=index == 0) for index, delivery in enumerate(deliveries)
    )

    metric_slice = calculate(deliveries, units).slices[0]

    assert metric_slice.state == "LOWER_BOUND"
    assert metric_slice.value is not None and metric_slice.value.value == 20
