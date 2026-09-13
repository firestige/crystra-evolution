from crystra_evolution.calculators.operational_attributable_cost import calculate as cost
from crystra_evolution.calculators.operational_usage_availability import (
    calculate as availability,
)
from crystra_evolution.domain.models import OperationalCallUnit, OperationalUsageUnit


def call(index: int) -> OperationalCallUnit:
    return OperationalCallUnit(
        call_identity=f"trace/{index}",
        provider="openai",
        model="gpt-5",
        role="writer",
        runtime="dsh",
        duration_ns=1,
        input_tokens=None,
        output_tokens=None,
        provenance_refs=(f"node:{index}",),
    )


def classified(index: int, applicable: bool, value: int | None = None) -> OperationalUsageUnit:
    return OperationalUsageUnit(
        call_identity=f"trace/{index}",
        source_applicable=applicable,
        kind="money" if applicable else None,
        unit="USD" if applicable else None,
        source="provider" if applicable else None,
        source_id="invoice" if applicable else None,
        value=value if applicable else None,
        provenance_refs=(f"usage:{index}",),
    )


def test_usage_availability_separates_explicit_false_from_missing_classification() -> None:
    calls = (call(1), call(2), call(3))
    metric_slice = availability(calls, (classified(1, True, 25), classified(2, False))).slices[0]

    assert metric_slice.value is not None and metric_slice.value.value == "1/2"
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "2/3"
    assert metric_slice.missing_inputs == ("usage_source_classification:trace/3",)


def test_operational_cost_requires_exact_call_binding_and_usage_coordinate() -> None:
    calls = (call(1), call(2))
    metric_slice = cost(calls, (classified(1, True, 25),)).slices[0]

    assert metric_slice.value is not None and metric_slice.value.value == 25
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "1/2"
    assert metric_slice.compatibility["source_id"] == "invoice"
    assert metric_slice.missing_inputs == ("call_reported_usage:trace/2",)


def test_usage_for_unknown_call_is_rejected_instead_of_delivery_or_time_joined() -> None:
    try:
        cost((call(1),), (classified(2, True, 25),))
    except ValueError as error:
        assert "exact model call" in str(error)
    else:
        raise AssertionError("unbound Usage unexpectedly accepted")


def test_missing_usage_classification_keeps_known_cohort_and_denominator() -> None:
    metric_slice = availability((call(1), call(2)), ()).slices[0]

    assert metric_slice.slice_key["model"] == "gpt-5"
    assert metric_slice.value is None
    assert metric_slice.withholding_reason == "MISSING_INPUT"
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "0"
    assert metric_slice.missing_inputs == (
        "usage_source_classification:trace/1",
        "usage_source_classification:trace/2",
    )
