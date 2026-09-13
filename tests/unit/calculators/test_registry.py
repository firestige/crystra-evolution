import importlib

from crystra_evolution.calculators.registry import CALCULATOR_SLOTS
from crystra_evolution.catalog import CATALOG_COORDINATES

EXPECTED_COORDINATES = (
    "role-template-rework-rate@2.0.0",
    "role-template-trajectory-partial-cost@2.0.0",
    "role-model-task-outcome-rate@2.0.0",
    "operational-latency-ms@2.0.0",
    "trajectory-partial-cost@2.0.0",
    "task-cohort-comparison-eligibility@2.0.0",
    "delivery-stage-reach@2.0.0",
    "delivery-terminal-outcome-rate@2.0.0",
    "delivery-cycle-time-ms@2.0.0",
    "operational-token-usage@2.0.0",
    "operational-attributable-cost@2.0.0",
    "operational-usage-availability@2.0.0",
)


def test_registry_has_exact_owner_approved_candidate_coordinates() -> None:
    assert CATALOG_COORDINATES == EXPECTED_COORDINATES
    assert tuple(CALCULATOR_SLOTS) == EXPECTED_COORDINATES
    assert len(set(CALCULATOR_SLOTS)) == 12
    assert "packet-rework-rate@1.0.0" not in CALCULATOR_SLOTS
    assert "direct-evidence-basis-rate@1.0.0" not in CALCULATOR_SLOTS


def test_every_coordinate_has_one_importable_module_slot() -> None:
    modules = []
    for coordinate, slot in CALCULATOR_SLOTS.items():
        module = importlib.import_module(slot.module)
        modules.append(slot.module)
        assert slot == module.SLOT
        assert slot.coordinate == coordinate
        assert callable(module.calculate)

    assert len(set(modules)) == 12


def test_slots_expose_no_runtime_engine_or_fallback() -> None:
    for slot in CALCULATOR_SLOTS.values():
        assert not hasattr(slot, "engine")
        assert not hasattr(slot, "fallback")
        assert not hasattr(slot, "selector")
