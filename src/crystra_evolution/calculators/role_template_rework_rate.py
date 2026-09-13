from crystra_evolution.api.models import MetricResult, MetricSlice
from crystra_evolution.domain.models import RoleTemplateDeliveryUnit

from .common import coverage, ratio_value, unavailable
from .protocol import CalculatorSlot

SLOT = CalculatorSlot("role-template-rework-rate@2.0.0", __name__)


def calculate(units: tuple[RoleTemplateDeliveryUnit, ...]) -> MetricResult:
    identities = {(unit.delivery_id, unit.template) for unit in units}
    if len(identities) != len(units):
        raise ValueError("duplicate Delivery/template input")
    slices = []
    for template in sorted({unit.template for unit in units}):
        candidates = tuple(
            unit for unit in units if unit.template == template and not unit.repair_expired
        )
        covered = tuple(unit for unit in candidates if unit.repair_observed is not None)
        sufficient = len(covered) >= 20
        repaired = sum(unit.repair_observed is True for unit in covered)
        role_id, identity, digest = template
        slices.append(
            MetricSlice(
                slice_key={
                    "role": role_id,
                    "role_prompt_identity": identity,
                    "role_prompt_digest": digest,
                },
                state="AVAILABLE" if sufficient else "UNAVAILABLE",
                value=ratio_value(repaired, len(covered)) if sufficient else None,
                withholding_reason=None if sufficient else "SAMPLE_INSUFFICIENT",
                numerator=repaired,
                denominator=len(covered),
                coverage=coverage(len(covered), len(candidates)),
                compatibility={
                    "role": role_id,
                    "role_prompt_identity": identity,
                    "role_prompt_digest": digest,
                },
                missing_inputs=tuple(
                    sorted(
                        f"repair_relationship:{unit.delivery_id}"
                        for unit in candidates
                        if unit.repair_observed is None
                    )
                ),
                provenance_refs=tuple(
                    sorted({ref for unit in covered for ref in unit.provenance_refs})
                ),
                reading="descriptive association; no template causality",
            )
        )
    if not slices:
        return unavailable("role-template-rework-rate", metric_coverage=coverage(0, len(units)))
    return MetricResult(
        metric_id="role-template-rework-rate",
        metric_version="2.0.0",
        slices=tuple(slices),
    )
