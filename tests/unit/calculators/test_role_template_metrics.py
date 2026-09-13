from crystra_evolution.calculators.role_template_rework_rate import calculate as rework
from crystra_evolution.calculators.role_template_trajectory_partial_cost import (
    calculate as template_cost,
)
from crystra_evolution.domain.models import RoleTemplateDeliveryUnit, RoleTemplateUsageUnit


def delivery(index: int, repaired: bool | None = False) -> RoleTemplateDeliveryUnit:
    return RoleTemplateDeliveryUnit(
        delivery_id=f"delivery-{index:02d}",
        role_id="writer",
        role_prompt_identity="prompt.writer",
        role_prompt_digest=f"sha256:{'a' * 64}",
        repair_observed=repaired,
        provenance_refs=(f"task:{index:02d}",),
    )


def test_role_template_rework_uses_only_covered_deliveries() -> None:
    units = tuple(delivery(index, repaired=index < 4) for index in range(20)) + (
        delivery(20, None),
    )
    metric_slice = rework(units).slices[0]
    assert metric_slice.value is not None and metric_slice.value.value == "1/5"
    assert metric_slice.numerator == 4
    assert metric_slice.denominator == 20
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "20/21"
    assert metric_slice.missing_inputs == ("repair_relationship:delivery-20",)


def test_role_template_cost_keeps_template_and_usage_coordinates_exact() -> None:
    deliveries = tuple(delivery(index) for index in range(21))
    usage = tuple(
        RoleTemplateUsageUnit(
            delivery_id=item.delivery_id,
            role_id=item.role_id,
            role_prompt_identity=item.role_prompt_identity,
            role_prompt_digest=item.role_prompt_digest,
            kind="money",
            unit="USD",
            source="provider",
            source_id="invoice",
            value=2,
            provenance_refs=(f"usage:{item.delivery_id}",),
        )
        for item in deliveries[:20]
    )
    metric_slice = template_cost(deliveries, usage).slices[0]
    assert metric_slice.value is not None and metric_slice.value.value == 40
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "20/21"
    assert metric_slice.compatibility["role_prompt_digest"] == f"sha256:{'a' * 64}"
    assert "cost_basis" not in metric_slice.compatibility


def test_role_template_rework_keeps_template_slice_below_minimum_sample() -> None:
    metric_slice = rework(tuple(delivery(index) for index in range(19))).slices[0]

    assert metric_slice.slice_key["role"] == "writer"
    assert metric_slice.state == "UNAVAILABLE"
    assert metric_slice.withholding_reason == "SAMPLE_INSUFFICIENT"
    assert metric_slice.value is None
    assert metric_slice.numerator == 0
    assert metric_slice.denominator == 19
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "1"


def test_two_deliveries_in_one_task_remain_two_rework_units() -> None:
    units = tuple(delivery(index, repaired=index in {0, 1}) for index in range(20))
    metric_slice = rework(units).slices[0]

    assert metric_slice.numerator == 2
    assert metric_slice.denominator == 20
    assert metric_slice.value is not None and metric_slice.value.value == "1/10"


def test_expired_repair_input_leaves_rework_candidate_population() -> None:
    active = tuple(delivery(index) for index in range(20))
    expired = RoleTemplateDeliveryUnit(
        delivery_id="delivery-expired",
        role_id="writer",
        role_prompt_identity="prompt.writer",
        role_prompt_digest=f"sha256:{'a' * 64}",
        repair_observed=None,
        repair_expired=True,
        provenance_refs=("expired",),
    )

    metric_slice = rework((*active, expired)).slices[0]

    assert metric_slice.denominator == 20
    assert metric_slice.coverage is not None
    assert metric_slice.coverage.raw_ratio == "1"
    assert metric_slice.missing_inputs == ()
