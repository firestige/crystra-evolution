from dataclasses import dataclass
from typing import Protocol

from crystra_evolution.api.models import MetricResult
from crystra_evolution.domain.models import NormalizedMetricInput


class Calculator(Protocol):
    coordinate: str

    def calculate(self, normalized: NormalizedMetricInput) -> MetricResult: ...


@dataclass(frozen=True, slots=True)
class CalculatorSlot:
    coordinate: str
    module: str
