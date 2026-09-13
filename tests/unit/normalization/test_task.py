from crystra_evolution.domain.models import DeliveryMetricUnit
from crystra_evolution.normalization.task import normalize_task


def delivery(identity: str, outcome: str | None) -> DeliveryMetricUnit:
    return DeliveryMetricUnit(identity, outcome, None, (), (f"fact:{identity}",))


def test_task_reading_is_exactly_terminal_open_or_mixed() -> None:
    eligible = normalize_task(
        "task-a", ("d-1", "d-2"), (delivery("d-1", "OK"), delivery("d-2", "OK"))
    )
    opened = normalize_task(
        "task-b", ("d-1", "d-2"), (delivery("d-1", "OK"), delivery("d-2", None))
    )
    mixed = normalize_task(
        "task-c", ("d-1", "d-2"), (delivery("d-1", "OK"), delivery("d-2", "FAILED"))
    )

    assert (eligible.classification, eligible.terminal_outcome, eligible.covered) == (
        "ELIGIBLE",
        "OK",
        True,
    )
    assert (opened.classification, opened.terminal_outcome, opened.covered) == (
        "OPEN_DELIVERY",
        None,
        True,
    )
    assert (mixed.classification, mixed.terminal_outcome, mixed.covered) == (
        "MIXED_DELIVERY_OUTCOMES",
        None,
        True,
    )


def test_missing_membership_or_delivery_reading_is_a_coverage_hole() -> None:
    undefined = normalize_task("task-a", (), ())
    missing = normalize_task("task-b", ("d-1", "d-2"), (delivery("d-1", "OK"),))
    assert (undefined.classification, undefined.covered) == ("UNDEFINED_TASK_MEMBERSHIP", False)
    assert (missing.classification, missing.covered) == ("MISSING_DELIVERY_READING", False)
