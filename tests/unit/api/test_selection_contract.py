import pytest
from pydantic import ValidationError

from crystra_evolution.api.models import CompareRequest, SingleRequest


def test_single_selection_is_canonical_task_population() -> None:
    request = SingleRequest.model_validate(
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {
                "selection_version": 1,
                "task_ids": ["task-z", "task-a"],
            },
        }
    )

    assert request.selection.task_ids == ("task-a", "task-z")


def test_compare_has_exact_independent_sides() -> None:
    request = CompareRequest.model_validate(
        {
            "api_version": 1,
            "mode": "COMPARE",
            "left": {"selection_version": 1, "task_ids": ["task-left"]},
            "right": {"selection_version": 1, "task_ids": ["task-right"]},
        }
    )

    assert request.left.task_ids == ("task-left",)
    assert request.right.task_ids == ("task-right",)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "api_version": 2,
            "mode": "SINGLE",
            "selection": {"selection_version": 1, "task_ids": ["task-a"]},
        },
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {"selection_version": 2, "task_ids": ["task-a"]},
        },
        {"api_version": 1, "mode": "SINGLE", "selection": {"selection_version": 1, "task_ids": []}},
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {"selection_version": 1, "task_ids": ["task-a", "task-a"]},
        },
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {
                "selection_version": 1,
                "task_ids": [f"task-{index}" for index in range(25)],
            },
        },
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {"selection_version": 1, "task_ids": [" task-a"]},
        },
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {"selection_version": 1, "task_ids": ["a" * 129]},
        },
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {"selection_version": 1, "task_ids": ["task-a"], "display_name": "A"},
        },
        {
            "api_version": 1,
            "mode": "SINGLE",
            "selection": {"selection_version": 1, "task_ids": ["task-a"]},
            "left": {"selection_version": 1, "task_ids": ["task-left"]},
        },
        {
            "api_version": 1,
            "mode": "COMPARE",
            "left": {"selection_version": 1, "task_ids": ["task-left"]},
            "right": {"selection_version": 1, "task_ids": ["task-right"]},
            "selection": {"selection_version": 1, "task_ids": ["task-a"]},
        },
    ],
)
def test_selection_rejects_unknown_version_shape_or_identity(payload: dict[str, object]) -> None:
    model = CompareRequest if payload.get("mode") == "COMPARE" else SingleRequest

    with pytest.raises(ValidationError):
        model.model_validate(payload)
