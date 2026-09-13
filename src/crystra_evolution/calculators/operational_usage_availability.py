from crystra_evolution.api.models import MetricResult, MetricSlice
from crystra_evolution.domain.models import OperationalCallUnit, OperationalUsageUnit

from .common import coverage, ratio_value, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("operational-usage-availability@2.0.0", __name__)


def calculate(
    calls: tuple[OperationalCallUnit, ...], usage: tuple[OperationalUsageUnit, ...]
) -> MetricResult:
    by_call = {call.call_identity: call for call in calls}
    if len(by_call) != len(calls):
        raise ValueError("duplicate model call input")
    if any(item.call_identity not in by_call for item in usage):
        raise ValueError("Usage is not bound to an exact model call")
    classifications: dict[str, bool] = {}
    for item in usage:
        prior = classifications.get(item.call_identity)
        if prior is not None and prior != item.source_applicable:
            raise ValueError("conflicting Usage source classification")
        classifications[item.call_identity] = item.source_applicable
    slices = []
    for cohort in sorted({call.cohort for call in calls if call.cohort is not None}):
        assert cohort is not None
        group = tuple(call for call in calls if call.cohort == cohort)
        covered = tuple(call for call in group if call.call_identity in classifications)
        covered_ids = {call.call_identity for call in covered}
        applicable = sum(classifications[call.call_identity] for call in covered)
        provider, model, role, runtime = cohort
        slices.append(
            MetricSlice(
                slice_key={"provider": provider, "model": model, "role": role, "runtime": runtime},
                state="AVAILABLE" if covered else "UNAVAILABLE",
                value=ratio_value(applicable, len(covered)) if covered else None,
                withholding_reason=None if covered else "MISSING_INPUT",
                numerator=applicable,
                denominator=len(covered),
                coverage=coverage(len(covered), len(group)),
                compatibility={
                    "provider": provider,
                    "model": model,
                    "role": role,
                    "runtime": runtime,
                },
                missing_inputs=tuple(
                    sorted(
                        f"usage_source_classification:{call.call_identity}"
                        for call in group
                        if call.call_identity not in classifications
                    )
                ),
                provenance_refs=tuple(
                    sorted(
                        {
                            ref
                            for item in usage
                            for ref in item.provenance_refs
                            if item.call_identity in covered_ids
                        }
                    )
                ),
            )
        )
    if not calls:
        return unavailable(
            "operational-usage-availability", metric_coverage=coverage(0, len(calls))
        )
    return MetricResult(
        metric_id="operational-usage-availability",
        metric_version="2.0.0",
        slices=tuple(slices),
    )
