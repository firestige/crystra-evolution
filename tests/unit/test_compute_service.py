import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal, cast

import pytest

from crystra_evolution.api.models import (
    CompareRequest,
    CompareResponse,
    EvaluationSelection,
    EvidenceBinding,
    SideError,
    SingleRequest,
    SingleResponse,
    TaskMembershipReference,
    TaskPopulationEntry,
    WorkflowResolutionAttempt,
    WorkflowResolutionEntry,
)
from crystra_evolution.application import (
    ResolutionBoundExceeded,
    UpstreamContractMismatch,
    UpstreamUnavailable,
)
from crystra_evolution.catalog import CATALOG_COORDINATES, CATALOG_SEMANTIC_DIGEST
from crystra_evolution.compute import EvolutionComputeService
from crystra_evolution.domain.models import ReportedUsageUnit, RoleTemplateDeliveryUnit
from crystra_evolution.domain.ports import (
    FactReading,
    FactRelationship,
    FactRelationshipEndpoint,
    TraceNodeReading,
)
from crystra_evolution.resolution.service import (
    ResolutionLimits,
    ResolvedDeliveryObservation,
    ResolvedSelectionPopulation,
)

NOW = datetime(2026, 8, 28, 1, tzinfo=UTC)


class PopulationStub:
    async def resolve(
        self, selection: EvaluationSelection, *, as_of: datetime
    ) -> ResolvedSelectionPopulation:
        assert as_of == NOW
        return ResolvedSelectionPopulation(
            task_population=(
                TaskPopulationEntry(
                    task_id=selection.task_ids[0],
                    memberships=(
                        TaskMembershipReference(
                            delivery_id="delivery-a",
                            manifest_digest="a" * 64,
                            accepted_digest="b" * 64,
                            profile_version="2.0.0",
                            source_identity="event:membership",
                            recorded_at=NOW,
                        ),
                    ),
                ),
            ),
            evidence_bindings=(
                EvidenceBinding(
                    route="/v1/evidence/tasks",
                    canonical_filter={
                        "task_id": selection.task_ids[0],
                        "as_of": "2026-08-28T01:00:00.000000Z",
                    },
                    contract_revision="1.0.0",
                    observation_profile="2.0.0",
                    read_model_revision="2.0.0",
                    route_snapshot="tasks-a",
                    completion_state="COMPLETE",
                ),
            ),
            input_refs=(),
            workflow_resolutions=(
                WorkflowResolutionEntry(
                    manifest_digest="a" * 64,
                    manifest_projection_digest="f" * 64,
                    accepted_digest="b" * 64,
                    profile_version="2.0.0",
                    source_identity="event:membership",
                    package_name="implementation",
                    exact_package_version="2.0.0",
                    package_digest=f"sha256:{'1' * 64}",
                    workflow_id="workflow.implementation",
                    workflow_version="2.0.0",
                    snapshot_id="snapshot.implementation.2",
                    snapshot_digest=f"sha256:{'2' * 64}",
                    state="NOT_FOUND",
                    attempts=(
                        WorkflowResolutionAttempt(
                            source_id="official", source_index=0, code="NOT_FOUND"
                        ),
                    ),
                ),
            ),
        )


class MixedRetentionPopulationStub(PopulationStub):
    async def resolve(
        self, selection: EvaluationSelection, *, as_of: datetime
    ) -> ResolvedSelectionPopulation:
        resolved = await super().resolve(selection, as_of=as_of)
        second_membership = TaskMembershipReference(
            delivery_id="delivery-b",
            manifest_digest="d" * 64,
            accepted_digest="e" * 64,
            profile_version="2.0.0",
            source_identity="event:membership-b",
            recorded_at=NOW,
        )
        second_workflow = resolved.workflow_resolutions[0].model_copy(
            update={
                "manifest_digest": "d" * 64,
                "manifest_projection_digest": "9" * 64,
                "accepted_digest": "e" * 64,
                "source_identity": "event:membership-b",
            }
        )
        return replace(
            resolved,
            task_population=(
                resolved.task_population[0].model_copy(
                    update={
                        "memberships": (
                            *resolved.task_population[0].memberships,
                            second_membership,
                        )
                    }
                ),
            ),
            workflow_resolutions=(*resolved.workflow_resolutions, second_workflow),
        )


def delivery_summary() -> FactReading:
    return FactReading(
        fact_id="fact-summary",
        kind="EVENT_CONTRIBUTION",
        source_identity="event:summary",
        recorded_at=NOW,
        accepted_digest="c" * 64,
        event_name="delivery.summary",
        completeness="FINAL",
        availability="AVAILABLE",
        expiry="ACTIVE",
        fields=(("C10", "SUCCEEDED"), ("C55", 10), ("C56", "review")),
        compatibility=(),
    )


def model_node() -> TraceNodeReading:
    return TraceNodeReading(
        resource_id="node-a",
        trace_id="d" * 32,
        span_id="e" * 16,
        source_identity=f"span:{'d' * 32}/{'e' * 16}",
        recorded_at=NOW,
        availability="AVAILABLE",
        expiry="ACTIVE",
        start_time_unix_nano=0,
        end_time_unix_nano=2_000_000,
        span_status="OK",
        fields=(
            ("gen_ai.provider.name", "openai"),
            ("C57", "gpt-5"),
            ("C30", "writer"),
            ("C06", "dsh"),
            ("gen_ai.usage.input_tokens", 5),
        ),
    )


class ObservationStub:
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        assert delivery_id == "delivery-a"
        return ResolvedDeliveryObservation(
            delivery_id=delivery_id,
            facts=(delivery_summary(),),
            trace_nodes=(model_node(),),
            trace_state="AVAILABLE",
            evidence_bindings=tuple(
                EvidenceBinding(
                    route=cast(
                        Literal[
                            "/v1/evidence/tasks",
                            "/v1/evidence/facts",
                            "/v1/evidence/traces",
                        ],
                        route,
                    ),
                    canonical_filter={"delivery_id": delivery_id},
                    contract_revision="0.1.0",
                    observation_profile="1.0.0",
                    read_model_revision="1.0.0",
                    route_snapshot=snapshot,
                    completion_state="COMPLETE",
                )
                for route, snapshot in (
                    ("/v1/evidence/facts", "facts-a"),
                    ("/v1/evidence/traces", "traces-a"),
                )
            ),
            input_refs=(),
        )


class AdvancingObservationStub(ObservationStub):
    def __init__(self) -> None:
        self.calls = 0

    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        resolved = await super().resolve(delivery_id=delivery_id)
        self.calls += 1
        node = replace(
            resolved.trace_nodes[0],
            end_time_unix_nano=2_000_000 if self.calls == 1 else 4_000_000,
        )
        return replace(resolved, trace_nodes=(node,))


class ConflictingObservationStub(ObservationStub):
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        resolved = await super().resolve(delivery_id=delivery_id)
        conflicting = replace(
            delivery_summary(),
            fact_id="fact-conflict",
            fields=(("C10", "FAILED"),),
        )
        return replace(resolved, facts=(*resolved.facts, conflicting))


class FutureFactObservationStub(ObservationStub):
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        resolved = await super().resolve(delivery_id=delivery_id)
        future = replace(
            delivery_summary(),
            fact_id="fact-future",
            recorded_at=datetime(2026, 8, 28, 1, 0, 1, tzinfo=UTC),
            fields=(("C10", "FAILED"),),
        )
        return replace(resolved, facts=(*resolved.facts, future))


class PartialTraceObservationStub(ObservationStub):
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        resolved = await super().resolve(delivery_id=delivery_id)
        expired = replace(
            resolved.trace_nodes[0],
            resource_id="node-expired",
            span_id="f" * 16,
            source_identity=f"span:{'d' * 32}/{'f' * 16}",
            availability="UNAVAILABLE",
            expiry="EXPIRED",
            end_time_unix_nano=100_000_000,
            fields=(*resolved.trace_nodes[0].fields[:-1], ("gen_ai.usage.input_tokens", 999)),
        )
        return replace(
            resolved,
            trace_state="PARTIAL",
            trace_nodes=(*resolved.trace_nodes, expired),
            evidence_bindings=tuple(
                binding.model_copy(
                    update={"completion_state": "PARTIAL", "error_state": "TRACE_PARTIAL"}
                )
                if binding.route == "/v1/evidence/traces"
                else binding
                for binding in resolved.evidence_bindings
            ),
        )


class ExpiredTraceObservationStub(ObservationStub):
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        resolved = await super().resolve(delivery_id=delivery_id)
        return replace(
            resolved,
            trace_state="EXPIRED",
            trace_nodes=(),
            evidence_bindings=tuple(
                binding.model_copy(
                    update={"completion_state": "EXPIRED", "error_state": "TRACE_EXPIRED"}
                )
                if binding.route == "/v1/evidence/traces"
                else binding
                for binding in resolved.evidence_bindings
            ),
        )


class ExpiredFactObservationStub(ObservationStub):
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        resolved = await super().resolve(delivery_id=delivery_id)
        expired = replace(
            delivery_summary(),
            fact_id="fact-expired",
            source_identity="event:expired",
            accepted_digest="e" * 64,
            event_name="review.summary",
            availability="UNAVAILABLE",
            expiry="EXPIRED",
            fields=(),
        )
        return replace(resolved, facts=(*resolved.facts, expired))


class MixedRetentionObservationStub(ObservationStub):
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        if delivery_id == "delivery-a":
            return await super().resolve(delivery_id=delivery_id)
        resolved = await super().resolve(delivery_id="delivery-a")
        return replace(
            resolved,
            delivery_id="delivery-b",
            facts=(
                replace(
                    delivery_summary(),
                    fact_id="fact-summary-b",
                    source_identity="event:summary-b",
                    accepted_digest="f" * 64,
                ),
            ),
            trace_nodes=(),
            trace_state="EXPIRED",
            evidence_bindings=tuple(
                binding.model_copy(
                    update={
                        "canonical_filter": {"delivery_id": "delivery-b"},
                        "route_snapshot": f"{binding.route_snapshot}-b",
                        **(
                            {
                                "completion_state": "EXPIRED",
                                "error_state": "TRACE_EXPIRED",
                            }
                            if binding.route == "/v1/evidence/traces"
                            else {}
                        ),
                    }
                )
                for binding in resolved.evidence_bindings
            ),
        )


@pytest.mark.asyncio
async def test_single_compute_orchestrates_resolved_evidence_into_all_twelve_results() -> None:
    response = await EvolutionComputeService(
        PopulationStub(), ObservationStub(), now=lambda: NOW
    ).compute(
        SingleRequest(
            api_version=1,
            mode="SINGLE",
            selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
        )
    )

    assert isinstance(response, SingleResponse)
    assert response.mode == "SINGLE"
    assert response.result.receipt.catalog.version == "2.0.0"
    assert response.result.receipt.catalog.semantic_digest == CATALOG_SEMANTIC_DIGEST
    assert (
        tuple(f"{item.metric_id}@{item.metric_version}" for item in response.result.metric_results)
        == CATALOG_COORDINATES
    )
    by_id = {item.metric_id: item for item in response.result.metric_results}
    terminal = by_id["delivery-terminal-outcome-rate"].slices[0].value
    cycle = by_id["delivery-cycle-time-ms"].slices[0].value
    latency = by_id["operational-latency-ms"].slices[0].value
    assert terminal is not None and terminal.value == "1"
    assert cycle is not None and cycle.value == 10
    assert latency is not None and latency.value == 2
    assert by_id["operational-attributable-cost"].slices[0].value is None
    assert len(response.result.receipt.evidence_bindings) == 3
    task = response.result.receipt.task_population[0]
    assert task.terminal_reading == "SUCCEEDED"
    assert task.exclusions == ()


@pytest.mark.asyncio
async def test_full_compare_aligns_exact_slices_and_computes_exact_deltas() -> None:
    selection = EvaluationSelection(selection_version=1, task_ids=("task-a",))
    response = await EvolutionComputeService(
        PopulationStub(), ObservationStub(), now=lambda: NOW
    ).compute(
        CompareRequest(
            api_version=1,
            mode="COMPARE",
            left=selection,
            right=selection,
        )
    )

    assert isinstance(response, CompareResponse)
    assert response.mode == "COMPARE"
    assert response.status == "FULL_COMPARE"
    assert response.left.tag == "SIDE_RESULT"
    assert response.right.tag == "SIDE_RESULT"
    assert any(entry.state == "AVAILABLE" for entry in response.deltas)
    assert all(
        entry.direction == "NO_CHANGE" for entry in response.deltas if entry.state == "AVAILABLE"
    )


@pytest.mark.asyncio
async def test_full_compare_subtracts_after_minus_before_in_authoritative_unit() -> None:
    selection = EvaluationSelection(selection_version=1, task_ids=("task-a",))
    response = await EvolutionComputeService(
        PopulationStub(), AdvancingObservationStub(), now=lambda: NOW
    ).compute(
        CompareRequest(
            api_version=1,
            mode="COMPARE",
            left=selection,
            right=selection,
        )
    )

    assert isinstance(response, CompareResponse)
    latency = next(
        entry
        for entry in response.deltas
        if entry.metric_coordinate == "operational-latency-ms@2.0.0"
    )
    assert latency.state == "AVAILABLE"
    assert latency.value is not None
    assert latency.value.kind == "DURATION_MS"
    assert latency.value.unit == "milliseconds"
    assert latency.value.value == 2
    assert latency.direction == "INCREASE"


class PartiallyUnavailablePopulation(PopulationStub):
    async def resolve(
        self, selection: EvaluationSelection, *, as_of: datetime
    ) -> ResolvedSelectionPopulation:
        if selection.task_ids == ("task-b",):
            raise UpstreamUnavailable("task-b Evidence unavailable")
        return await super().resolve(selection, as_of=as_of)


class PartiallyBoundedPopulation(PopulationStub):
    async def resolve(
        self, selection: EvaluationSelection, *, as_of: datetime
    ) -> ResolvedSelectionPopulation:
        if selection.task_ids == ("task-b",):
            raise ResolutionBoundExceeded("unique Delivery bound exceeded")
        return await super().resolve(selection, as_of=as_of)


@pytest.mark.asyncio
async def test_partial_compare_preserves_successful_side_and_withholds_all_deltas() -> None:
    response = await EvolutionComputeService(
        PartiallyUnavailablePopulation(), ObservationStub(), now=lambda: NOW
    ).compute(
        CompareRequest(
            api_version=1,
            mode="COMPARE",
            left=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
            right=EvaluationSelection(selection_version=1, task_ids=("task-b",)),
        )
    )

    assert isinstance(response, CompareResponse)
    assert response.status == "PARTIAL_COMPARE"
    assert response.left.tag == "SIDE_RESULT"
    assert isinstance(response.right, SideError)
    assert response.right.retryable is True
    assert all(entry.state == "SIDE_UNRESOLVED" for entry in response.deltas)


@pytest.mark.asyncio
async def test_partial_compare_preserves_successful_side_when_other_side_exceeds_bound() -> None:
    response = await EvolutionComputeService(
        PartiallyBoundedPopulation(), ObservationStub(), now=lambda: NOW
    ).compute(
        CompareRequest(
            api_version=1,
            mode="COMPARE",
            left=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
            right=EvaluationSelection(selection_version=1, task_ids=("task-b",)),
        )
    )

    assert isinstance(response, CompareResponse)
    assert response.status == "PARTIAL_COMPARE"
    assert response.left.tag == "SIDE_RESULT"
    assert isinstance(response.right, SideError)
    assert response.right.code == "RESOLUTION_BOUND_EXCEEDED"
    assert response.right.retryable is False


@pytest.mark.asyncio
async def test_conflicting_evidence_reading_is_a_typed_upstream_mismatch() -> None:
    with pytest.raises(UpstreamContractMismatch, match="normalization"):
        await EvolutionComputeService(
            PopulationStub(), ConflictingObservationStub(), now=lambda: NOW
        ).compute(
            SingleRequest(
                api_version=1,
                mode="SINGLE",
                selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
            )
        )


@pytest.mark.asyncio
async def test_observation_after_side_cutoff_cannot_change_metric_results() -> None:
    response = await EvolutionComputeService(
        PopulationStub(), FutureFactObservationStub(), now=lambda: NOW
    ).compute(
        SingleRequest(
            api_version=1,
            mode="SINGLE",
            selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
        )
    )

    assert isinstance(response, SingleResponse)
    outcome = response.result.metric_results[7].slices[0]
    assert outcome.slice_key == {"outcome": "SUCCEEDED"}
    assert outcome.value is not None and outcome.value.value == "1"
    assert all(item.identity != "fact-future" for item in response.result.receipt.input_refs)


@pytest.mark.asyncio
async def test_retention_partial_trace_excludes_delivery_but_remains_in_receipt() -> None:
    response = await EvolutionComputeService(
        PopulationStub(), PartialTraceObservationStub(), now=lambda: NOW
    ).compute(
        SingleRequest(
            api_version=1,
            mode="SINGLE",
            selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
        )
    )

    assert isinstance(response, SingleResponse)
    by_id = {item.metric_id: item for item in response.result.metric_results}
    empty_coverages = [
        by_id[metric_id].slices[0].coverage
        for metric_id in (
            "operational-latency-ms",
            "operational-token-usage",
            "delivery-terminal-outcome-rate",
        )
    ]
    assert all(item is not None and item.denominator == 0 for item in empty_coverages)
    assert response.result.receipt.population_state == "EXPIRED"
    assert response.result.receipt.task_population[0].exclusions == ("EXPIRED_DELIVERY",)
    trace_binding = next(
        item
        for item in response.result.receipt.evidence_bindings
        if item.route == "/v1/evidence/traces"
    )
    assert (trace_binding.completion_state, trace_binding.error_state) == (
        "PARTIAL",
        "TRACE_PARTIAL",
    )
    assert any(item.identity == "node-expired" for item in response.result.receipt.input_refs)


@pytest.mark.asyncio
async def test_expired_trace_leaves_metric_population_but_remains_in_receipt() -> None:
    response = await EvolutionComputeService(
        PopulationStub(), ExpiredTraceObservationStub(), now=lambda: NOW
    ).compute(
        SingleRequest(
            api_version=1,
            mode="SINGLE",
            selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
        )
    )

    assert isinstance(response, SingleResponse)
    by_id = {item.metric_id: item for item in response.result.metric_results}
    assert by_id["operational-latency-ms"].slices[0].state == "UNAVAILABLE"
    assert (
        by_id["operational-latency-ms"].slices[0].withholding_reason == "NO_APPLICABLE_POPULATION"
    )
    assert response.result.receipt.population_state == "EXPIRED"


@pytest.mark.asyncio
async def test_any_expired_fact_excludes_the_whole_delivery_population() -> None:
    response = await EvolutionComputeService(
        PopulationStub(), ExpiredFactObservationStub(), now=lambda: NOW
    ).compute(
        SingleRequest(
            api_version=1,
            mode="SINGLE",
            selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
        )
    )

    assert isinstance(response, SingleResponse)
    by_id = {item.metric_id: item for item in response.result.metric_results}
    empty_coverages = [
        by_id[metric_id].slices[0].coverage
        for metric_id in (
            "delivery-terminal-outcome-rate",
            "task-cohort-comparison-eligibility",
        )
    ]
    assert all(item is not None and item.denominator == 0 for item in empty_coverages)
    assert response.result.receipt.population_state == "EXPIRED"
    assert response.result.receipt.task_population[0].exclusions == ("EXPIRED_DELIVERY",)
    assert any(item.identity == "fact-expired" for item in response.result.receipt.input_refs)


@pytest.mark.asyncio
async def test_expired_delivery_does_not_remove_active_sibling_from_task_population() -> None:
    response = await EvolutionComputeService(
        MixedRetentionPopulationStub(), MixedRetentionObservationStub(), now=lambda: NOW
    ).compute(
        SingleRequest(
            api_version=1,
            mode="SINGLE",
            selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
        )
    )

    assert isinstance(response, SingleResponse)
    by_id = {item.metric_id: item for item in response.result.metric_results}
    outcome = by_id["delivery-terminal-outcome-rate"].slices[0]
    assert outcome.coverage is not None
    assert (outcome.numerator, outcome.denominator, outcome.coverage.raw_ratio) == (1, 1, "1")
    task = by_id["task-cohort-comparison-eligibility"].slices[0]
    assert task.coverage is not None
    assert (task.denominator, task.coverage.denominator) == (1, 1)
    assert response.result.receipt.task_population[0].exclusions == ("EXPIRED_DELIVERY",)
    assert response.result.receipt.population_state == "EXPIRED"


def test_role_template_usage_is_bound_by_exact_delivery() -> None:
    delivery = RoleTemplateDeliveryUnit(
        delivery_id="delivery-a",
        role_id="writer",
        role_prompt_identity="role.writer",
        role_prompt_digest=f"sha256:{'3' * 64}",
        repair_observed=None,
        provenance_refs=("manifest-a",),
    )
    usage = ReportedUsageUnit(
        usage_identity="usage-a",
        delivery_id="delivery-a",
        kind="money",
        unit="USD-micros",
        source="provider",
        source_id="invoice-a",
        value=25,
        provenance_refs=("fact-a",),
    )

    units = EvolutionComputeService._role_template_usage_units((delivery,), (usage,))

    assert len(units) == 1
    assert units[0].delivery_id == "delivery-a"
    assert units[0].template == delivery.template
    assert units[0].compatibility == usage.compatibility
    assert units[0].value == 25


@pytest.mark.asyncio
async def test_compute_side_enforces_total_fact_and_trace_record_bound() -> None:
    with pytest.raises(ResolutionBoundExceeded, match="input record"):
        await EvolutionComputeService(
            PopulationStub(),
            ObservationStub(),
            now=lambda: NOW,
            limits=ResolutionLimits(max_input_records_per_side=1),
        ).compute(
            SingleRequest(
                api_version=1,
                mode="SINGLE",
                selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
            )
        )


@pytest.mark.asyncio
async def test_compute_side_enforces_configured_deadline() -> None:
    class SlowPopulation(PopulationStub):
        async def resolve(
            self, selection: EvaluationSelection, *, as_of: datetime
        ) -> ResolvedSelectionPopulation:
            await asyncio.sleep(0.02)
            return await super().resolve(selection, as_of=as_of)

    with pytest.raises(ResolutionBoundExceeded, match="deadline"):
        await EvolutionComputeService(
            SlowPopulation(),
            ObservationStub(),
            now=lambda: NOW,
            limits=ResolutionLimits(side_deadline_seconds=0.001),
        ).compute(
            SingleRequest(
                api_version=1,
                mode="SINGLE",
                selection=EvaluationSelection(selection_version=1, task_ids=("task-a",)),
            )
        )


def test_repair_reading_uses_recorded_finding_fix_relationship_without_counting_repeats() -> None:
    relationship = FactRelationship(
        kind="FINDING_FIX",
        source=FactRelationshipEndpoint(kind="FIX", key=("fix-a",)),
        target=FactRelationshipEndpoint(kind="FINDING_TARGET", key=("finding-a",)),
    )
    first = replace(
        delivery_summary(),
        fact_id="fix-a",
        kind="FINDING_FIX",
        relationships=(relationship,),
    )
    second = replace(first, fact_id="fix-b")
    expired = replace(
        first,
        fact_id="fix-expired",
        availability="UNAVAILABLE",
        expiry="EXPIRED",
        relationships=(),
    )
    unavailable = replace(
        first,
        fact_id="fix-unavailable",
        availability="UNAVAILABLE",
        relationships=(),
    )

    assert EvolutionComputeService._repair_observed((first, second)) is True
    assert EvolutionComputeService._repair_observed((delivery_summary(),)) is False
    assert EvolutionComputeService._repair_reading((first, expired)) == (True, False)
    assert EvolutionComputeService._repair_reading((unavailable, expired)) == (None, False)
    assert EvolutionComputeService._repair_reading((expired,)) == (None, True)
