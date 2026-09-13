from crystra_evolution.domain.models import ReportedUsageUnit
from crystra_evolution.domain.ports import FactReading, Scalar


def _text(fields: dict[str, Scalar], name: str) -> str | None:
    value = fields.get(name)
    return value if isinstance(value, str) and value else None


def _integer(value: Scalar) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def normalize_reported_usage(
    delivery_id: str, facts: tuple[FactReading, ...]
) -> tuple[ReportedUsageUnit, ...]:
    units = []
    for fact in facts:
        if (
            fact.kind != "EVENT_CONTRIBUTION"
            or fact.event_name != "usage"
            or fact.availability != "AVAILABLE"
            or fact.expiry != "ACTIVE"
            or fact.completeness not in {"FINAL", "LOWER_BOUND"}
        ):
            continue
        fields = fact.field_map
        kind = _text(fields, "C42")
        unit = _text(fields, "C43")
        source = _text(fields, "C44")
        source_id = _text(fields, "C45")
        value = _integer(fields.get("C46"))
        if None in (kind, unit, source, source_id, value):
            continue
        assert kind is not None and unit is not None
        assert source is not None and source_id is not None and value is not None
        units.append(
            ReportedUsageUnit(
                usage_identity=fact.fact_id,
                delivery_id=delivery_id,
                kind=kind,
                unit=unit,
                source=source,
                source_id=source_id,
                value=value,
                provenance_refs=(fact.accepted_digest,),
                lower_bound=fact.completeness == "LOWER_BOUND",
            )
        )
    return tuple(sorted(units, key=lambda item: item.usage_identity.encode()))
