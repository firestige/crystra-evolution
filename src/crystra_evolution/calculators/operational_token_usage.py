from crystra_evolution.api.models import ExactValue, MetricResult, MetricSlice
from crystra_evolution.domain.models import OperationalCallUnit

from .common import coverage, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("operational-token-usage@2.0.0", __name__)


def calculate(units: tuple[OperationalCallUnit, ...]) -> MetricResult:
    cohorts = sorted({unit.cohort for unit in units if unit.cohort is not None})
    slices = []
    for cohort in cohorts:
        assert cohort is not None
        group = tuple(unit for unit in units if unit.cohort == cohort)
        provider, model, role, runtime = cohort
        for direction, attribute in (("input", "input_tokens"), ("output", "output_tokens")):
            covered = tuple(unit for unit in group if getattr(unit, attribute) is not None)
            total = sum(int(getattr(unit, attribute)) for unit in covered)
            slices.append(
                MetricSlice(
                    slice_key={
                        "provider": provider,
                        "model": model,
                        "role": role,
                        "runtime": runtime,
                        "direction": direction,
                    },
                    state="AVAILABLE" if covered else "UNAVAILABLE",
                    value=(
                        ExactValue(kind="QUANTITY", value=total, unit="tokens") if covered else None
                    ),
                    withholding_reason=None if covered else "MISSING_INPUT",
                    contributing_count=len(covered),
                    coverage=coverage(len(covered), len(group)),
                    compatibility={
                        "provider": provider,
                        "model": model,
                        "role": role,
                        "runtime": runtime,
                        "direction": direction,
                    },
                    missing_inputs=tuple(
                        sorted(
                            f"model_call.{attribute}:{unit.call_identity}"
                            for unit in group
                            if getattr(unit, attribute) is None
                        )
                    ),
                    provenance_refs=tuple(
                        sorted({ref for unit in covered for ref in unit.provenance_refs})
                    ),
                )
            )
    if not cohorts:
        return unavailable("operational-token-usage", metric_coverage=coverage(0, len(units)))
    return MetricResult(
        metric_id="operational-token-usage", metric_version="2.0.0", slices=tuple(slices)
    )
