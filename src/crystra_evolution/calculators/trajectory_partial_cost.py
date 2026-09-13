from collections import defaultdict

from crystra_evolution.api.models import ExactValue, MetricResult, MetricSlice
from crystra_evolution.domain.models import ReportedUsageUnit

from .common import coverage, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("trajectory-partial-cost@2.0.0", __name__)


def calculate(delivery_ids: tuple[str, ...], units: tuple[ReportedUsageUnit, ...]) -> MetricResult:
    if len(set(delivery_ids)) != len(delivery_ids):
        raise ValueError("Delivery population must be unique")
    population = set(delivery_ids)
    groups: dict[tuple[str, str, str, str], list[ReportedUsageUnit]] = defaultdict(list)
    for unit in units:
        if unit.delivery_id not in population:
            raise ValueError("Usage belongs outside the selected Delivery population")
        if unit.kind == "money":
            groups[unit.compatibility].append(unit)
    if not groups:
        return unavailable(
            "trajectory-partial-cost", metric_coverage=coverage(0, len(delivery_ids))
        )
    slices = []
    for compatibility in sorted(groups):
        group = tuple(groups[compatibility])
        lower_bound = any(item.lower_bound for item in group)
        covered_ids = {unit.delivery_id for unit in group}
        kind, unit_name, source, source_id = compatibility
        sample_sufficient = len(covered_ids) >= 20
        slices.append(
            MetricSlice(
                slice_key={
                    "kind": kind,
                    "unit": unit_name,
                    "source": source,
                    "source_id": source_id,
                },
                state=(
                    "LOWER_BOUND"
                    if sample_sufficient and lower_bound
                    else "AVAILABLE"
                    if sample_sufficient
                    else "UNAVAILABLE"
                ),
                value=(
                    ExactValue(
                        kind="MONEY",
                        value=sum(item.value for item in group),
                        unit=unit_name,
                    )
                    if sample_sufficient
                    else None
                ),
                withholding_reason=None if sample_sufficient else "SAMPLE_INSUFFICIENT",
                contributing_count=len(covered_ids),
                coverage=coverage(len(covered_ids), len(delivery_ids)),
                compatibility={
                    "kind": kind,
                    "unit": unit_name,
                    "source": source,
                    "source_id": source_id,
                },
                missing_inputs=tuple(
                    f"reported_usage:{identity}"
                    for identity in delivery_ids
                    if identity not in covered_ids
                ),
                provenance_refs=tuple(
                    sorted({ref for item in group for ref in item.provenance_refs})
                ),
                reading="partial recorded Usage; not total cost",
            )
        )
    return MetricResult(
        metric_id="trajectory-partial-cost",
        metric_version="2.0.0",
        slices=tuple(slices),
    )
