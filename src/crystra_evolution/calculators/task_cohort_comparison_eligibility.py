from collections import Counter

from crystra_evolution.api.models import MetricResult, MetricSlice
from crystra_evolution.domain.models import TaskMetricUnit

from .common import coverage, ratio_value
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("task-cohort-comparison-eligibility@2.0.0", __name__)


def calculate(units: tuple[TaskMetricUnit, ...]) -> MetricResult:
    covered = tuple(unit for unit in units if unit.covered)
    eligible = tuple(unit for unit in covered if unit.classification == "ELIGIBLE")
    metric_coverage = coverage(len(covered), len(units))
    exclusions = Counter(unit.classification for unit in units if unit.classification != "ELIGIBLE")
    available = len(units) >= 20
    return MetricResult(
        metric_id="task-cohort-comparison-eligibility",
        metric_version="2.0.0",
        slices=(
            MetricSlice(
                slice_key={},
                state="AVAILABLE" if available else "UNAVAILABLE",
                value=(ratio_value(len(eligible), len(units)) if available else None),
                withholding_reason=None if available else "SAMPLE_INSUFFICIENT",
                numerator=len(eligible),
                denominator=len(units),
                measures={f"excluded_{key}": value for key, value in sorted(exclusions.items())},
                coverage=metric_coverage,
                missing_inputs=tuple(
                    sorted(f"task.reading:{unit.task_id}" for unit in units if not unit.covered)
                ),
                provenance_refs=tuple(
                    sorted({ref for unit in covered for ref in unit.provenance_refs})
                ),
            ),
        ),
    )
