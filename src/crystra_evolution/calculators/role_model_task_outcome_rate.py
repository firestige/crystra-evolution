from crystra_evolution.api.models import MetricResult, MetricSlice
from crystra_evolution.domain.models import RoleModelTaskUnit

from .common import coverage, ratio_value, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("role-model-task-outcome-rate@2.0.0", __name__)


def calculate(units: tuple[RoleModelTaskUnit, ...]) -> MetricResult:
    identities = {(unit.task_id, unit.cohort) for unit in units}
    if len(identities) != len(units):
        raise ValueError("duplicate Task/cohort input")
    cohorts = sorted({unit.cohort for unit in units})
    slices = []
    for cohort in cohorts:
        group = tuple(unit for unit in units if unit.cohort == cohort)
        sufficient = len(group) >= 20
        provider, model, role, runtime = cohort
        for outcome in sorted({unit.terminal_outcome for unit in group}):
            numerator = sum(unit.terminal_outcome == outcome for unit in group)
            slices.append(
                MetricSlice(
                    slice_key={
                        "provider": provider,
                        "model": model,
                        "role": role,
                        "runtime": runtime,
                        "outcome": outcome,
                    },
                    state="AVAILABLE" if sufficient else "UNAVAILABLE",
                    value=ratio_value(numerator, len(group)) if sufficient else None,
                    withholding_reason=None if sufficient else "SAMPLE_INSUFFICIENT",
                    numerator=numerator,
                    denominator=len(group),
                    coverage=coverage(len(group), len(group)),
                    compatibility={
                        "provider": provider,
                        "model": model,
                        "role": role,
                        "runtime": runtime,
                    },
                    provenance_refs=tuple(
                        sorted({ref for unit in group for ref in unit.provenance_refs})
                    ),
                    reading="descriptive association; no model causality",
                )
            )
    if not slices:
        return unavailable(
            "role-model-task-outcome-rate", metric_coverage=coverage(len(units), len(units))
        )
    return MetricResult(
        metric_id="role-model-task-outcome-rate",
        metric_version="2.0.0",
        slices=tuple(slices),
    )
