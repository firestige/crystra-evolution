from fractions import Fraction
from math import isfinite

from crystra_evolution.domain.models import DeliveryMetricUnit
from crystra_evolution.domain.ports import FactReading


def normalize_delivery(delivery_id: str, facts: tuple[FactReading, ...]) -> DeliveryMetricUnit:
    summaries = tuple(
        fact
        for fact in facts
        if fact.kind == "EVENT_CONTRIBUTION"
        and fact.event_name == "delivery.summary"
        and fact.completeness == "FINAL"
        and fact.availability == "AVAILABLE"
        and fact.expiry == "ACTIVE"
    )
    outcomes = {
        value
        for fact in summaries
        if isinstance((value := fact.field_map.get("C10")), str) and value
    }
    if len(outcomes) > 1:
        raise ValueError("conflicting terminal outcome facts")
    elapsed_values = {
        Fraction(str(value))
        for fact in summaries
        if isinstance((value := fact.field_map.get("C55")), (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or isfinite(value))
        and value >= 0
    }
    if len(elapsed_values) > 1:
        raise ValueError("conflicting Delivery elapsed-time facts")
    stages = {
        value
        for fact in summaries
        if isinstance((value := fact.field_map.get("C56")), str) and value
    }
    elapsed = next(iter(elapsed_values), None)
    return DeliveryMetricUnit(
        delivery_id=delivery_id,
        terminal_outcome=next(iter(outcomes), None),
        elapsed_time_ms=(
            None if elapsed is None else elapsed.numerator if elapsed.denominator == 1 else elapsed
        ),
        reached_stages=tuple(sorted(stages, key=str.encode)),
        provenance_refs=tuple(sorted({fact.accepted_digest for fact in summaries}, key=str.encode)),
    )
