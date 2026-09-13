from collections import defaultdict

from crystra_evolution.api.models import ExactValue, MetricResult, MetricSlice
from crystra_evolution.domain.models import RoleTemplateDeliveryUnit, RoleTemplateUsageUnit

from .common import coverage, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("role-template-trajectory-partial-cost@2.0.0", __name__)


def calculate(
    deliveries: tuple[RoleTemplateDeliveryUnit, ...], usage: tuple[RoleTemplateUsageUnit, ...]
) -> MetricResult:
    delivery_index = {(item.delivery_id, item.template): item for item in deliveries}
    if len(delivery_index) != len(deliveries):
        raise ValueError("duplicate Delivery/template input")
    groups: dict[
        tuple[tuple[str, str, str], tuple[str, str, str, str]],
        list[RoleTemplateUsageUnit],
    ] = defaultdict(list)
    for item in usage:
        if (item.delivery_id, item.template) not in delivery_index:
            raise ValueError("Usage has no exact Delivery/template candidate")
        if item.kind == "money":
            groups[(item.template, item.compatibility)].append(item)
    if not groups:
        return unavailable(
            "role-template-trajectory-partial-cost",
            metric_coverage=coverage(0, len(deliveries)),
        )
    slices = []
    for (template, usage_coordinate), values in sorted(groups.items()):
        candidates = tuple(item for item in deliveries if item.template == template)
        lower_bound = any(item.lower_bound for item in values)
        covered_ids = {item.delivery_id for item in values}
        role_id, identity, digest = template
        kind, unit_name, source, source_id = usage_coordinate
        sufficient = len(covered_ids) >= 20
        slices.append(
            MetricSlice(
                slice_key={
                    "role": role_id,
                    "role_prompt_identity": identity,
                    "role_prompt_digest": digest,
                    "kind": kind,
                    "unit": unit_name,
                    "source": source,
                    "source_id": source_id,
                },
                state=(
                    "LOWER_BOUND"
                    if sufficient and lower_bound
                    else "AVAILABLE"
                    if sufficient
                    else "UNAVAILABLE"
                ),
                value=(
                    ExactValue(
                        kind="MONEY",
                        value=sum(item.value for item in values),
                        unit=unit_name,
                    )
                    if sufficient
                    else None
                ),
                withholding_reason=None if sufficient else "SAMPLE_INSUFFICIENT",
                contributing_count=len(covered_ids),
                coverage=coverage(len(covered_ids), len(candidates)),
                compatibility={
                    "role": role_id,
                    "role_prompt_identity": identity,
                    "role_prompt_digest": digest,
                    "kind": kind,
                    "unit": unit_name,
                    "source": source,
                    "source_id": source_id,
                },
                missing_inputs=tuple(
                    sorted(
                        f"reported_usage:{item.delivery_id}"
                        for item in candidates
                        if item.delivery_id not in covered_ids
                    )
                ),
                provenance_refs=tuple(
                    sorted({ref for item in values for ref in item.provenance_refs})
                ),
                reading="partial recorded Usage; not total cost or template causality",
            )
        )
    return MetricResult(
        metric_id="role-template-trajectory-partial-cost",
        metric_version="2.0.0",
        slices=tuple(slices),
    )
