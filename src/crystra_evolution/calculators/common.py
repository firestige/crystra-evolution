from fractions import Fraction
from typing import Literal

from crystra_evolution.api.models import Coverage, ExactValue, MetricResult, MetricSlice


def rational(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def coverage(numerator: int, denominator: int) -> Coverage:
    if denominator == 0:
        return Coverage(
            numerator=0,
            denominator=0,
            raw_ratio=None,
            state="NO_POPULATION",
            alert=None,
        )
    ratio = rational(Fraction(numerator, denominator))
    state: Literal["NO_COVERAGE", "PARTIAL", "FULL"] = (
        "NO_COVERAGE" if numerator == 0 else "FULL" if numerator == denominator else "PARTIAL"
    )
    alert: Literal["LOW_COVERAGE"] | None = (
        "LOW_COVERAGE" if 100 * numerator < 10 * denominator else None
    )
    return Coverage(
        numerator=numerator,
        denominator=denominator,
        raw_ratio=ratio,
        state=state,
        alert=alert,
    )


def unavailable(metric_id: str, *, metric_coverage: Coverage) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        metric_version="2.0.0",
        slices=(
            MetricSlice(
                slice_key={},
                state="UNAVAILABLE",
                withholding_reason=(
                    "NO_APPLICABLE_POPULATION"
                    if metric_coverage.denominator == 0
                    else "MISSING_INPUT"
                ),
                coverage=metric_coverage,
            ),
        ),
    )


def ratio_value(numerator: int, denominator: int) -> ExactValue:
    return ExactValue(
        kind="RATIO",
        value=rational(Fraction(numerator, denominator)),
        unit="ratio",
    )
