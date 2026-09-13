from crystra_evolution.api.models import MetricResult, MetricSlice
from crystra_evolution.domain.models import DeliveryMetricUnit

from .common import coverage, ratio_value, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("delivery-terminal-outcome-rate@2.0.0", __name__)


def calculate(units: tuple[DeliveryMetricUnit, ...]) -> MetricResult:
    terminal = tuple(unit for unit in units if unit.terminal_outcome is not None)
    metric_coverage = coverage(len(terminal), len(units))
    if not terminal:
        return unavailable("delivery-terminal-outcome-rate", metric_coverage=metric_coverage)
    outcomes = sorted({unit.terminal_outcome for unit in terminal if unit.terminal_outcome})
    missing = tuple(
        sorted(
            f"delivery.terminal_outcome:{unit.delivery_id}"
            for unit in units
            if unit.terminal_outcome is None
        )
    )
    return MetricResult(
        metric_id="delivery-terminal-outcome-rate",
        metric_version="2.0.0",
        slices=tuple(
            MetricSlice(
                slice_key={"outcome": outcome},
                state="AVAILABLE",
                value=ratio_value(
                    sum(unit.terminal_outcome == outcome for unit in terminal), len(terminal)
                ),
                numerator=sum(unit.terminal_outcome == outcome for unit in terminal),
                denominator=len(terminal),
                coverage=metric_coverage,
                missing_inputs=missing,
                provenance_refs=tuple(
                    sorted({ref for unit in terminal for ref in unit.provenance_refs})
                ),
            )
            for outcome in outcomes
        ),
    )
