from collections import defaultdict

from crystra_evolution.api.models import ExactValue, MetricResult, MetricSlice
from crystra_evolution.domain.models import OperationalCallUnit, OperationalUsageUnit

from .common import coverage, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("operational-attributable-cost@2.0.0", __name__)


def calculate(
    calls: tuple[OperationalCallUnit, ...], usage: tuple[OperationalUsageUnit, ...]
) -> MetricResult:
    by_call = {call.call_identity: call for call in calls}
    if len(by_call) != len(calls):
        raise ValueError("duplicate model call input")
    if any(item.call_identity not in by_call for item in usage):
        raise ValueError("Usage is not bound to an exact model call")
    groups: dict[
        tuple[tuple[str, str, str, str], tuple[str, str, str, str]],
        list[OperationalUsageUnit],
    ] = defaultdict(list)
    for item in usage:
        call = by_call[item.call_identity]
        if call.cohort is None or item.compatibility is None:
            continue
        if item.kind == "money" and item.value is not None:
            groups[(call.cohort, item.compatibility)].append(item)
    if not groups:
        return unavailable("operational-attributable-cost", metric_coverage=coverage(0, len(calls)))
    slices = []
    for (cohort, usage_coordinate), values in sorted(groups.items()):
        candidate_calls = tuple(call for call in calls if call.cohort == cohort)
        covered_ids = {item.call_identity for item in values}
        provider, model, role, runtime = cohort
        kind, unit_name, source, source_id = usage_coordinate
        slices.append(
            MetricSlice(
                slice_key={
                    "provider": provider,
                    "model": model,
                    "role": role,
                    "runtime": runtime,
                    "kind": kind,
                    "unit": unit_name,
                    "source": source,
                    "source_id": source_id,
                },
                state="AVAILABLE",
                value=ExactValue(
                    kind="MONEY",
                    value=sum(item.value for item in values if item.value is not None),
                    unit=unit_name,
                ),
                contributing_count=len(covered_ids),
                coverage=coverage(len(covered_ids), len(candidate_calls)),
                compatibility={
                    "provider": provider,
                    "model": model,
                    "role": role,
                    "runtime": runtime,
                    "kind": kind,
                    "unit": unit_name,
                    "source": source,
                    "source_id": source_id,
                },
                missing_inputs=tuple(
                    sorted(
                        f"call_reported_usage:{call.call_identity}"
                        for call in candidate_calls
                        if call.call_identity not in covered_ids
                    )
                ),
                provenance_refs=tuple(
                    sorted({ref for item in values for ref in item.provenance_refs})
                ),
                reading="partial recorded Usage; not total cost",
            )
        )
    return MetricResult(
        metric_id="operational-attributable-cost",
        metric_version="2.0.0",
        slices=tuple(slices),
    )
