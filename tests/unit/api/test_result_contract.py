from datetime import UTC, datetime
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from crystra_evolution.api.models import (
    CatalogBinding,
    CompareResponse,
    Coverage,
    DeltaEntry,
    EvaluationSelection,
    EvidenceBinding,
    ExactValue,
    InputReference,
    MetricResult,
    MetricSlice,
    ResolvedEvaluationContext,
    SideError,
    SideResult,
    SingleResponse,
    TaskMembershipReference,
    TaskPopulationEntry,
    WorkflowResolutionAttempt,
    WorkflowResolutionEntry,
)
from crystra_evolution.catalog import (
    CATALOG_COORDINATES,
    CATALOG_SEMANTIC_DIGEST,
    CATALOG_VERSION,
)


def coverage(
    *,
    numerator: int = 1,
    denominator: int = 1,
    raw_ratio: str | None = "1",
    state: str = "FULL",
    alert: str | None = None,
) -> Coverage:
    return Coverage.model_validate(
        {
            "numerator": numerator,
            "denominator": denominator,
            "raw_ratio": raw_ratio,
            "state": state,
            "alert": alert,
        }
    )


def test_catalog_binding_is_exactly_the_review_candidate() -> None:
    binding = CatalogBinding(
        catalog_id="agentops.evaluation.metric-catalog",
        version=CATALOG_VERSION,
        semantic_digest=CATALOG_SEMANTIC_DIGEST,
        observation_profile="1.0.0",
    )
    assert binding.version == "2.0.0"

    with pytest.raises(ValidationError):
        CatalogBinding.model_validate(
            {
                **binding.model_dump(),
                "semantic_digest": "0" * 64,
            }
        )
    with pytest.raises(ValidationError):
        CatalogBinding.model_validate(
            {
                **binding.model_dump(),
                "version": "1.0.0",
            }
        )


def workflow_resolution(manifest_digest: str) -> WorkflowResolutionEntry:
    return WorkflowResolutionEntry(
        manifest_digest=manifest_digest,
        manifest_projection_digest="4" * 64,
        accepted_digest="5" * 64,
        profile_version="2.0.0",
        source_identity=f"event:manifest-{manifest_digest[:8]}",
        package_name="implementation",
        exact_package_version="2.0.0",
        package_digest=f"sha256:{'6' * 64}",
        workflow_id="workflow.implementation",
        workflow_version="2.0.0",
        snapshot_id="snapshot.implementation.2",
        snapshot_digest=f"sha256:{'7' * 64}",
        state="NOT_FOUND",
        attempts=(
            WorkflowResolutionAttempt(source_id="official", source_index=0, code="NOT_FOUND"),
        ),
    )


def test_receipt_canonicalizes_route_local_read_set_without_global_snapshot() -> None:
    context = ResolvedEvaluationContext(
        context_version=1,
        selection=EvaluationSelection(selection_version=1, task_ids=("task-b", "task-a")),
        as_of=datetime(2026, 8, 28, 1, 0, tzinfo=UTC),
        resolved_at=datetime(2026, 8, 28, 1, 1, tzinfo=UTC),
        task_population=(
            TaskPopulationEntry(
                task_id="task-b",
                memberships=(
                    TaskMembershipReference(
                        delivery_id="delivery-2",
                        manifest_digest="2" * 64,
                        accepted_digest="a" * 64,
                        profile_version="2.0.0",
                        source_identity="event:task-2",
                        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
                    ),
                ),
            ),
            TaskPopulationEntry(
                task_id="task-a",
                display_name="Readable A",
                memberships=(
                    TaskMembershipReference(
                        delivery_id="delivery-3",
                        manifest_digest="3" * 64,
                        accepted_digest="b" * 64,
                        profile_version="2.0.0",
                        source_identity="event:task-3",
                        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
                    ),
                    TaskMembershipReference(
                        delivery_id="delivery-1",
                        manifest_digest="1" * 64,
                        accepted_digest="c" * 64,
                        profile_version="2.0.0",
                        source_identity="event:task-1",
                        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
                    ),
                ),
            ),
        ),
        catalog=CatalogBinding(
            catalog_id="agentops.evaluation.metric-catalog",
            version=CATALOG_VERSION,
            semantic_digest=CATALOG_SEMANTIC_DIGEST,
            observation_profile="1.0.0",
        ),
        evidence_bindings=(
            EvidenceBinding(
                route="/v1/evidence/tasks",
                canonical_filter={
                    "task_id": "task-a",
                    "as_of": "2026-08-28T01:00:00.000000Z",
                },
                contract_revision="1.0.0",
                observation_profile="2.0.0",
                read_model_revision="2.0.0",
                route_snapshot="task-snapshot-a",
                completion_state="COMPLETE",
            ),
            EvidenceBinding(
                route="/v1/evidence/tasks",
                canonical_filter={
                    "task_id": "task-b",
                    "as_of": "2026-08-28T01:00:00.000000Z",
                },
                contract_revision="1.0.0",
                observation_profile="2.0.0",
                read_model_revision="2.0.0",
                route_snapshot="task-snapshot-b",
                completion_state="COMPLETE",
            ),
            EvidenceBinding(
                route="/v1/evidence/traces",
                canonical_filter={"delivery_id": "delivery-2"},
                contract_revision="0.1.0",
                observation_profile="1.0.0",
                read_model_revision="1.0.0",
                route_snapshot="trace-snapshot-1",
                completion_state="COMPLETE",
            ),
            EvidenceBinding(
                route="/v1/evidence/facts",
                canonical_filter={"task_id": "task-a"},
                contract_revision="0.1.0",
                observation_profile="1.0.0",
                read_model_revision="1.0.0",
                route_snapshot="fact-snapshot-1",
                completion_state="PARTIAL",
                error_state="CURSOR_EXPIRED",
            ),
        ),
        input_refs=(
            InputReference(
                kind="TRACE_NODE", identity="trace-z/span-z", provenance_ref="span-source-z"
            ),
            InputReference(kind="FACT", identity="fact-a", provenance_ref="accepted-a"),
        ),
        workflow_resolutions=tuple(
            workflow_resolution(digest) for digest in ("3" * 64, "1" * 64, "2" * 64)
        ),
        population_state="PARTIAL",
    )

    payload = context.model_dump(mode="json", exclude_none=True)

    assert payload["selection"]["task_ids"] == ["task-a", "task-b"]
    assert [entry["task_id"] for entry in payload["task_population"]] == ["task-a", "task-b"]
    assert [item["delivery_id"] for item in payload["task_population"][0]["memberships"]] == [
        "delivery-1",
        "delivery-3",
    ]
    assert [binding["route"] for binding in payload["evidence_bindings"]] == [
        "/v1/evidence/facts",
        "/v1/evidence/tasks",
        "/v1/evidence/tasks",
        "/v1/evidence/traces",
    ]
    assert [reference["identity"] for reference in payload["input_refs"]] == [
        "fact-a",
        "trace-z/span-z",
    ]
    assert [item["manifest_digest"] for item in payload["workflow_resolutions"]] == [
        "1" * 64,
        "2" * 64,
        "3" * 64,
    ]
    assert payload["as_of"] != payload["resolved_at"]
    assert "global_snapshot" not in payload
    assert "snapshot_digest" not in payload
    assert "manifest_digest" not in payload


@pytest.mark.parametrize("unknown", ["global_snapshot", "snapshot_digest", "manifest_digest"])
def test_receipt_rejects_global_snapshot_or_manifest_fields(unknown: str) -> None:
    payload = {
        "context_version": 1,
        "selection": {"selection_version": 1, "task_ids": ["task-a"]},
        "as_of": "2026-08-28T01:00:00Z",
        "resolved_at": "2026-08-28T01:01:00Z",
        "task_population": [
            {
                "task_id": "task-a",
                "memberships": [],
                "exclusions": ["UNDEFINED_TASK_MEMBERSHIP"],
            }
        ],
        "catalog": {
            "catalog_id": "agentops.evaluation.metric-catalog",
            "version": CATALOG_VERSION,
            "semantic_digest": CATALOG_SEMANTIC_DIGEST,
            "observation_profile": "1.0.0",
        },
        "evidence_bindings": [],
        "input_refs": [],
        "population_state": "COMPLETE",
        unknown: "forbidden",
    }

    with pytest.raises(ValidationError):
        ResolvedEvaluationContext.model_validate(payload)


def test_explicit_zero_and_sample_withholding_are_distinct() -> None:
    available = MetricSlice(
        slice_key={},
        state="AVAILABLE",
        value=ExactValue(kind="COUNT", value=0, unit="count"),
        coverage=coverage(),
    )
    insufficient = MetricSlice(
        slice_key={},
        state="UNAVAILABLE",
        withholding_reason="SAMPLE_INSUFFICIENT",
        coverage=coverage(
            numerator=9,
            denominator=20,
            raw_ratio="9/20",
            state="PARTIAL",
        ),
    )

    assert available.model_dump(mode="json", exclude_none=True)["value"]["value"] == "0"
    assert "value" not in insufficient.model_dump(mode="json", exclude_none=True)
    assert insufficient.coverage is not None
    assert insufficient.coverage.numerator == 9


@pytest.mark.parametrize("value", [0.1, "1e3", "01", "-0", "2/4", "1/-3", "NaN", "Infinity"])
def test_authoritative_ratio_rejects_float_or_noncanonical_string(value: object) -> None:
    with pytest.raises(ValidationError):
        ExactValue.model_validate(
            {
                "kind": "RATIO",
                "value": value,
                "unit": "ratio",
            }
        )


def test_authoritative_ratio_uses_exact_reduced_rational_without_display_precision() -> None:
    value = ExactValue(kind="RATIO", value="1/3", unit="ratio")

    assert value.model_dump(mode="json", exclude_none=True) == {
        "kind": "RATIO",
        "value": "1/3",
        "unit": "ratio",
    }

    with pytest.raises(ValidationError):
        ExactValue(
            kind="RATIO",
            value="1/3",
            unit="ratio",
            precision=2,
            rounding="ROUND_HALF_EVEN",
        )

    with pytest.raises(ValidationError):
        ExactValue(
            kind="BOOLEAN",
            value=True,
            unit="boolean",
            precision=0,
            rounding="ROUND_HALF_EVEN",
        )


def test_authoritative_integer_wire_values_are_canonical_decimal_strings() -> None:
    large = 9_007_199_254_740_993
    metric_slice = MetricSlice(
        slice_key={},
        state="AVAILABLE",
        value=ExactValue(kind="COUNT", value=large, unit="count"),
        measures={"observed": large},
        numerator=large,
        denominator=large,
        contributing_count=large,
        coverage=Coverage(
            numerator=large,
            denominator=large,
            raw_ratio="1",
            state="FULL",
            alert=None,
        ),
    )

    payload = metric_slice.model_dump(mode="json", exclude_none=True)

    assert payload["value"]["value"] == str(large)
    assert payload["measures"] == {"observed": str(large)}
    assert payload["numerator"] == str(large)
    assert payload["denominator"] == str(large)
    assert payload["contributing_count"] == str(large)
    assert payload["coverage"] == {
        "numerator": str(large),
        "denominator": str(large),
        "raw_ratio": "1",
        "state": "FULL",
        "alert": None,
    }


def test_no_population_coverage_serializes_explicit_null_fields() -> None:
    payload = Coverage(
        numerator=0,
        denominator=0,
        raw_ratio=None,
        state="NO_POPULATION",
        alert=None,
    ).model_dump(mode="json", exclude_none=True)

    assert payload == {
        "numerator": "0",
        "denominator": "0",
        "raw_ratio": None,
        "state": "NO_POPULATION",
        "alert": None,
    }

    schema = Coverage.model_json_schema(mode="serialization")
    assert schema["required"] == [
        "numerator",
        "denominator",
        "raw_ratio",
        "state",
        "alert",
    ]
    assert schema["properties"]["numerator"]["type"] == "string"
    assert {item["type"] for item in schema["properties"]["raw_ratio"]["anyOf"]} == {
        "string",
        "null",
    }


def test_metric_slice_serializes_unestablished_coverage_as_explicit_null() -> None:
    metric_slice = MetricSlice(
        slice_key={},
        state="UNAVAILABLE",
        withholding_reason="MISSING_INPUT",
        coverage=None,
    )

    payload = metric_slice.model_dump(mode="json")

    assert "coverage" in payload
    assert payload["coverage"] is None
    schema = MetricSlice.model_json_schema(mode="serialization")
    assert "coverage" in schema["required"]


def test_metric_slice_rejects_an_omitted_coverage_field() -> None:
    with pytest.raises(ValidationError):
        MetricSlice.model_validate(
            {
                "slice_key": {},
                "state": "UNAVAILABLE",
                "withholding_reason": "MISSING_INPUT",
            }
        )


@pytest.mark.parametrize(
    ("numerator", "denominator", "raw_ratio", "state", "alert"),
    [
        (0, 0, None, "NO_POPULATION", None),
        (0, 10, "0", "NO_COVERAGE", "LOW_COVERAGE"),
        (1, 20, "1/20", "PARTIAL", "LOW_COVERAGE"),
        (1, 10, "1/10", "PARTIAL", None),
        (1, 3, "1/3", "PARTIAL", None),
        (3, 3, "1", "FULL", None),
    ],
)
def test_coverage_shape_is_exactly_derived_from_integer_counts(
    numerator: int,
    denominator: int,
    raw_ratio: str | None,
    state: str,
    alert: str | None,
) -> None:
    result = Coverage.model_validate(
        {
            "numerator": numerator,
            "denominator": denominator,
            "raw_ratio": raw_ratio,
            "state": state,
            "alert": alert,
        }
    )

    assert result.raw_ratio == raw_ratio


@pytest.mark.parametrize(
    "payload",
    [
        {
            "numerator": 0,
            "denominator": 0,
            "raw_ratio": "0",
            "state": "NO_POPULATION",
            "alert": None,
        },
        {"numerator": 1, "denominator": 3, "raw_ratio": "0.33", "state": "PARTIAL", "alert": None},
        {"numerator": 1, "denominator": 3, "raw_ratio": "1/3", "state": "FULL", "alert": None},
        {"numerator": 1, "denominator": 20, "raw_ratio": "1/20", "state": "PARTIAL", "alert": None},
        {
            "numerator": 1,
            "denominator": 10,
            "raw_ratio": "1/10",
            "state": "PARTIAL",
            "alert": "LOW_COVERAGE",
        },
    ],
)
def test_coverage_rejects_inconsistent_derived_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Coverage.model_validate(payload)


def test_metric_result_rejects_duplicate_or_noncanonical_slice_keys() -> None:
    slice_b = MetricSlice(
        slice_key={"outcome": "B"},
        state="UNAVAILABLE",
        withholding_reason="MISSING_INPUT",
        coverage=coverage(),
    )
    slice_a = MetricSlice(
        slice_key={"outcome": "A"},
        state="UNAVAILABLE",
        withholding_reason="MISSING_INPUT",
        coverage=coverage(),
    )
    result = MetricResult(
        metric_id="delivery-terminal-outcome-rate",
        metric_version=CATALOG_VERSION,
        slices=(slice_b, slice_a),
    )

    assert [item.slice_key["outcome"] for item in result.slices] == ["A", "B"]

    with pytest.raises(ValidationError):
        MetricResult(
            metric_id="delivery-terminal-outcome-rate",
            metric_version=CATALOG_VERSION,
            slices=(slice_a, slice_a),
        )


@pytest.mark.parametrize(
    ("state", "value", "withholding_reason"),
    [
        ("AVAILABLE", None, None),
        ("UNAVAILABLE", {"kind": "COUNT", "value": 0, "unit": "count"}, None),
        ("UNAVAILABLE", None, None),
        ("AVAILABLE", {"kind": "COUNT", "value": 0, "unit": "count"}, "MISSING_INPUT"),
        ("ERROR", None, "MISSING_INPUT"),
    ],
)
def test_metric_slice_truth_and_value_shape_is_closed(
    state: str,
    value: dict[str, object] | None,
    withholding_reason: str | None,
) -> None:
    with pytest.raises(ValidationError):
        MetricSlice.model_validate(
            {
                "slice_key": {},
                "state": state,
                "value": value,
                "withholding_reason": withholding_reason,
                "coverage": coverage().model_dump(mode="json"),
            }
        )


def minimal_context(task_id: str) -> ResolvedEvaluationContext:
    return ResolvedEvaluationContext(
        context_version=1,
        selection=EvaluationSelection(selection_version=1, task_ids=(task_id,)),
        as_of=datetime(2026, 8, 28, 1, 0, tzinfo=UTC),
        resolved_at=datetime(2026, 8, 28, 1, 1, tzinfo=UTC),
        task_population=(
            TaskPopulationEntry(
                task_id=task_id,
                memberships=(),
                exclusions=("UNDEFINED_TASK_MEMBERSHIP",),
            ),
        ),
        catalog=CatalogBinding(
            catalog_id="agentops.evaluation.metric-catalog",
            version=CATALOG_VERSION,
            semantic_digest=CATALOG_SEMANTIC_DIGEST,
            observation_profile="1.0.0",
        ),
        evidence_bindings=(
            EvidenceBinding(
                route="/v1/evidence/tasks",
                canonical_filter={
                    "task_id": task_id,
                    "as_of": "2026-08-28T01:00:00.000000Z",
                },
                contract_revision="1.0.0",
                observation_profile="2.0.0",
                read_model_revision="2.0.0",
                route_snapshot=f"task-snapshot-{task_id}",
                completion_state="COMPLETE",
            ),
        ),
        input_refs=(),
        population_state="OPEN",
    )


def test_task_population_accepts_the_observation_display_name_bound() -> None:
    assert (
        TaskPopulationEntry(
            task_id="task-a",
            display_name="n" * 160,
            memberships=(),
            exclusions=("UNDEFINED_TASK_MEMBERSHIP",),
        ).display_name
        == "n" * 160
    )
    with pytest.raises(ValidationError):
        TaskPopulationEntry(
            task_id="task-a",
            display_name="n" * 161,
            memberships=(),
            exclusions=("UNDEFINED_TASK_MEMBERSHIP",),
        )


def test_workflow_resolution_receipt_is_closed_and_bound_to_membership_manifests() -> None:
    available = workflow_resolution("a" * 64).model_copy(
        update={
            "state": "AVAILABLE",
            "matched_source_id": "official",
            "matched_source_index": 0,
            "matched_repository": "firestige/workflows",
            "validated_archive_digest": f"sha256:{'8' * 64}",
            "validated_package_digest": f"sha256:{'6' * 64}",
            "validated_snapshot_digest": f"sha256:{'7' * 64}",
        }
    )
    assert WorkflowResolutionEntry.model_validate(available.model_dump()).state == "AVAILABLE"

    with pytest.raises(ValidationError):
        WorkflowResolutionEntry.model_validate(
            {**available.model_dump(), "validated_snapshot_digest": f"sha256:{'9' * 64}"}
        )
    with pytest.raises(ValidationError):
        WorkflowResolutionAttempt(code="ATTEMPTS_TRUNCATED", omitted_count=1)

    context = minimal_context("task-a")
    with pytest.raises(ValidationError, match="membership Manifest"):
        ResolvedEvaluationContext(
            **{
                **context.model_dump(),
                "workflow_resolutions": (workflow_resolution("a" * 64),),
            }
        )


def test_receipt_rejects_route_revision_or_selection_population_mismatch() -> None:
    context = minimal_context("task-a")
    with pytest.raises(ValidationError):
        EvidenceBinding(
            route="/v1/evidence/tasks",
            canonical_filter={},
            contract_revision="0.1.0",
            observation_profile="1.0.0",
            read_model_revision="1.0.0",
            route_snapshot="snapshot",
            completion_state="COMPLETE",
        )
    with pytest.raises(ValidationError):
        ResolvedEvaluationContext(
            **{
                **context.model_dump(),
                "task_population": (),
            }
        )


@pytest.mark.parametrize(
    "canonical_filter",
    (
        {"task_id": "task-a"},
        {"task_id": "task-a", "as_of": "2026-08-28T00:59:59.000000Z"},
        {"task_id": "task-a", "as_of": "2026-08-28T01:00:00Z"},
        {
            "task_id": "task-a",
            "as_of": "2026-08-28T01:00:00.000000Z",
            "unexpected": "filter",
        },
    ),
)
def test_receipt_requires_exact_task_membership_filter(
    canonical_filter: dict[str, str],
) -> None:
    context = minimal_context("task-a")
    binding = context.evidence_bindings[0].model_copy(update={"canonical_filter": canonical_filter})

    with pytest.raises(ValidationError):
        ResolvedEvaluationContext(**{**context.model_dump(), "evidence_bindings": (binding,)})


def test_complete_population_requires_complete_task_traversal_and_membership() -> None:
    context = minimal_context("task-a")

    with pytest.raises(ValidationError):
        ResolvedEvaluationContext(**{**context.model_dump(), "population_state": "COMPLETE"})

    partial = context.evidence_bindings[0].model_copy(
        update={"completion_state": "PARTIAL", "error_state": "CURSOR_EXPIRED"}
    )
    with pytest.raises(ValidationError):
        ResolvedEvaluationContext(
            **{
                **context.model_dump(),
                "evidence_bindings": (partial,),
                "population_state": "COMPLETE",
            }
        )


def test_delta_direction_and_withholding_are_closed() -> None:
    with pytest.raises(ValidationError):
        DeltaEntry(metric_coordinate=CATALOG_COORDINATES[0], slice_key={}, state="WITHHELD")
    with pytest.raises(ValidationError):
        DeltaEntry(
            metric_coordinate=CATALOG_COORDINATES[0],
            slice_key={},
            state="AVAILABLE",
            value=ExactValue(kind="COUNT", value=1, unit="count"),
            direction="DECREASE",
        )

    rational_delta = DeltaEntry(
        metric_coordinate=CATALOG_COORDINATES[0],
        slice_key={},
        state="AVAILABLE",
        value=ExactValue(kind="RATIO", value="-1/3", unit="ratio"),
        direction="DECREASE",
    )
    assert rational_delta.direction == "DECREASE"


def test_receipt_rejects_membership_after_as_of_or_without_offset() -> None:
    with pytest.raises(ValidationError):
        TaskMembershipReference(
            delivery_id="delivery-a",
            manifest_digest="a" * 64,
            accepted_digest="b" * 64,
            profile_version="2.0.0",
            source_identity="event:task-a",
            recorded_at=datetime(2026, 8, 28),
        )

    context = minimal_context("task-a")
    late = TaskMembershipReference(
        delivery_id="delivery-a",
        manifest_digest="a" * 64,
        accepted_digest="b" * 64,
        profile_version="2.0.0",
        source_identity="event:task-a",
        recorded_at=datetime(2026, 8, 28, 2, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        ResolvedEvaluationContext(
            **{
                **context.model_dump(),
                "task_population": (TaskPopulationEntry(task_id="task-a", memberships=(late,)),),
            }
        )


def unavailable_result(coordinate: str) -> MetricResult:
    metric_id, metric_version = coordinate.rsplit("@", 1)
    assert metric_version == "2.0.0"
    bound_version = cast(Literal["2.0.0"], metric_version)
    return MetricResult(
        metric_id=metric_id,
        metric_version=bound_version,
        slices=(
            MetricSlice(
                slice_key={},
                state="UNAVAILABLE",
                withholding_reason="MISSING_INPUT",
                coverage=Coverage(
                    numerator=0,
                    denominator=0,
                    raw_ratio=None,
                    state="NO_POPULATION",
                    alert=None,
                ),
            ),
        ),
    )


def side_result(task_id: str) -> SideResult:
    return SideResult(
        tag="SIDE_RESULT",
        receipt=minimal_context(task_id),
        metric_results=tuple(unavailable_result(item) for item in CATALOG_COORDINATES),
    )


def test_successful_side_requires_exact_twelve_candidate_coordinates() -> None:
    response = SingleResponse(api_version=1, mode="SINGLE", result=side_result("task-a"))

    assert len(response.result.metric_results) == 12
    assert (
        tuple(
            f"{result.metric_id}@{result.metric_version}"
            for result in response.result.metric_results
        )
        == CATALOG_COORDINATES
    )

    with pytest.raises(ValidationError):
        SideResult(
            tag="SIDE_RESULT",
            receipt=minimal_context("task-a"),
            metric_results=tuple(unavailable_result(item) for item in CATALOG_COORDINATES[:-1]),
        )


def test_partial_compare_retains_successful_side_and_all_unresolved_deltas() -> None:
    response = CompareResponse(
        api_version=1,
        mode="COMPARE",
        status="PARTIAL_COMPARE",
        left=side_result("task-a"),
        right=SideError(
            tag="SIDE_ERROR",
            code="EVIDENCE_UNAVAILABLE",
            retryable=True,
            detail="Evidence did not answer",
        ),
        deltas=tuple(
            DeltaEntry(metric_coordinate=item, slice_key={}, state="SIDE_UNRESOLVED")
            for item in CATALOG_COORDINATES
        ),
    )

    assert response.left.tag == "SIDE_RESULT"
    assert response.right.tag == "SIDE_ERROR"
    assert len(response.deltas) == 12

    with pytest.raises(ValidationError):
        CompareResponse(
            api_version=1,
            mode="COMPARE",
            status="PARTIAL_COMPARE",
            left=side_result("task-a"),
            right=response.right,
            deltas=(
                DeltaEntry(
                    metric_coordinate=CATALOG_COORDINATES[0],
                    slice_key={},
                    state="AVAILABLE",
                ),
                *response.deltas[1:],
            ),
        )


def test_full_compare_requires_one_delta_per_exact_metric_slice() -> None:
    left = side_result("task-a")
    right = side_result("task-b")
    first = left.metric_results[0]
    sliced = first.model_copy(
        update={
            "slices": (
                first.slices[0].model_copy(update={"slice_key": {"outcome": "FAILED"}}),
                first.slices[0].model_copy(update={"slice_key": {"outcome": "PASSED"}}),
            )
        }
    )
    left = left.model_copy(update={"metric_results": (sliced, *left.metric_results[1:])})
    right = right.model_copy(update={"metric_results": (sliced, *right.metric_results[1:])})
    deltas = [
        DeltaEntry(
            metric_coordinate=coordinate,
            slice_key={},
            state="WITHHELD",
            withholding_reason="MISSING_VALUE",
        )
        for coordinate in CATALOG_COORDINATES[1:]
    ]
    deltas.extend(
        DeltaEntry(
            metric_coordinate=CATALOG_COORDINATES[0],
            slice_key={"outcome": outcome},
            state="WITHHELD",
            withholding_reason="MISSING_VALUE",
        )
        for outcome in ("PASSED", "FAILED")
    )

    response = CompareResponse(
        api_version=1,
        mode="COMPARE",
        status="FULL_COMPARE",
        left=left,
        right=right,
        deltas=tuple(deltas),
    )

    assert len(response.deltas) == 13
    with pytest.raises(ValidationError):
        CompareResponse(
            api_version=1,
            mode="COMPARE",
            status="FULL_COMPARE",
            left=left,
            right=right,
            deltas=response.deltas[:-1],
        )


def test_lower_bound_slices_cannot_publish_an_exact_delta() -> None:
    left = side_result("task-a")
    right = side_result("task-b")
    lower = (
        left.metric_results[0]
        .slices[0]
        .model_copy(
            update={
                "state": "LOWER_BOUND",
                "value": ExactValue(kind="COUNT", value=1, unit="count"),
                "withholding_reason": None,
            }
        )
    )
    left_metric = left.metric_results[0].model_copy(update={"slices": (lower,)})
    right_metric = right.metric_results[0].model_copy(update={"slices": (lower,)})
    left = left.model_copy(update={"metric_results": (left_metric, *left.metric_results[1:])})
    right = right.model_copy(update={"metric_results": (right_metric, *right.metric_results[1:])})
    deltas = [
        DeltaEntry(
            metric_coordinate=CATALOG_COORDINATES[0],
            slice_key={},
            state="AVAILABLE",
            value=ExactValue(kind="COUNT", value=0, unit="count"),
            direction="NO_CHANGE",
        )
    ]
    deltas.extend(
        DeltaEntry(
            metric_coordinate=coordinate,
            slice_key={},
            state="WITHHELD",
            withholding_reason="MISSING_VALUE",
        )
        for coordinate in CATALOG_COORDINATES[1:]
    )

    with pytest.raises(ValidationError):
        CompareResponse(
            api_version=1,
            mode="COMPARE",
            status="FULL_COMPARE",
            left=left,
            right=right,
            deltas=tuple(deltas),
        )


def test_available_delta_must_retain_the_paired_value_kind_and_unit() -> None:
    left = side_result("task-a")
    right = side_result("task-b")
    available = MetricSlice(
        slice_key={},
        state="AVAILABLE",
        value=ExactValue(kind="COUNT", value=1, unit="count"),
        coverage=coverage(),
    )
    left_metric = left.metric_results[0].model_copy(update={"slices": (available,)})
    right_metric = right.metric_results[0].model_copy(update={"slices": (available,)})
    left = left.model_copy(update={"metric_results": (left_metric, *left.metric_results[1:])})
    right = right.model_copy(update={"metric_results": (right_metric, *right.metric_results[1:])})
    deltas = [
        DeltaEntry(
            metric_coordinate=CATALOG_COORDINATES[0],
            slice_key={},
            state="AVAILABLE",
            value=ExactValue(kind="DURATION_MS", value=0, unit="ms"),
            direction="NO_CHANGE",
        )
    ]
    deltas.extend(
        DeltaEntry(
            metric_coordinate=coordinate,
            slice_key={},
            state="WITHHELD",
            withholding_reason="MISSING_VALUE",
        )
        for coordinate in CATALOG_COORDINATES[1:]
    )

    with pytest.raises(ValidationError):
        CompareResponse(
            api_version=1,
            mode="COMPARE",
            status="FULL_COMPARE",
            left=left,
            right=right,
            deltas=tuple(deltas),
        )
