from crystra_evolution.api.models import MetricResult, MetricSlice
from crystra_evolution.domain.models import DeliveryMetricUnit

from .common import coverage, ratio_value, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("delivery-stage-reach@2.0.0", __name__)


def calculate(units: tuple[DeliveryMetricUnit, ...]) -> MetricResult:
    terminal = tuple(unit for unit in units if unit.terminal_outcome is not None)
    covered = tuple(unit for unit in terminal if unit.reached_stages)
    metric_coverage = coverage(len(covered), len(terminal))
    if not covered:
        return unavailable("delivery-stage-reach", metric_coverage=metric_coverage)
    missing = tuple(
        sorted(
            f"delivery.stage.reached:{unit.delivery_id}"
            for unit in terminal
            if not unit.reached_stages
        )
    )
    stages = sorted({stage for unit in covered for stage in unit.reached_stages})
    return MetricResult(
        metric_id="delivery-stage-reach",
        metric_version="2.0.0",
        slices=tuple(
            MetricSlice(
                slice_key={"stage": stage},
                state="AVAILABLE",
                value=ratio_value(
                    sum(stage in unit.reached_stages for unit in covered), len(covered)
                ),
                numerator=sum(stage in unit.reached_stages for unit in covered),
                denominator=len(covered),
                coverage=metric_coverage,
                missing_inputs=missing,
                provenance_refs=tuple(
                    sorted({ref for unit in covered for ref in unit.provenance_refs})
                ),
            )
            for stage in stages
        ),
    )
