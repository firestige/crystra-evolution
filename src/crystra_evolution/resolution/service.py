from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from crystra_evolution.api.models import (
    EvaluationSelection,
    EvidenceBinding,
    InputReference,
    TaskMembershipReference,
    TaskPopulationEntry,
    WorkflowResolutionAttempt,
    WorkflowResolutionEntry,
)
from crystra_evolution.application import ResolutionBoundExceeded, UpstreamContractMismatch
from crystra_evolution.domain.ports import (
    DeliveryManifestReading,
    FactPage,
    FactReading,
    TaskMembershipPage,
    TraceNodeReading,
    TracePage,
)
from crystra_evolution.workflow_sources.resolution import WorkflowResolution


class SelectionEvidenceReader(Protocol):
    async def resolve_membership(
        self,
        *,
        task_id: str,
        as_of: datetime,
        limit: int,
        cursor: str | None,
    ) -> TaskMembershipPage: ...

    async def resolve_manifest(self, *, manifest_digest: str) -> DeliveryManifestReading: ...


class ManifestWorkflowResolver(Protocol):
    async def resolve(self, reading: DeliveryManifestReading) -> WorkflowResolution: ...


class ObservationEvidenceReader(Protocol):
    async def resolve_facts(
        self, *, delivery_id: str, limit: int, cursor: str | None
    ) -> FactPage: ...

    async def resolve_traces(
        self, *, delivery_id: str, limit: int, cursor: str | None
    ) -> TracePage: ...


@dataclass(frozen=True, slots=True)
class ResolvedSelectionPopulation:
    task_population: tuple[TaskPopulationEntry, ...]
    evidence_bindings: tuple[EvidenceBinding, ...]
    input_refs: tuple[InputReference, ...]
    workflow_resolutions: tuple[WorkflowResolutionEntry, ...]
    manifest_readings: tuple[DeliveryManifestReading, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedDeliveryObservation:
    delivery_id: str
    facts: tuple[FactReading, ...]
    trace_nodes: tuple[TraceNodeReading, ...]
    trace_state: str
    evidence_bindings: tuple[EvidenceBinding, ...]
    input_refs: tuple[InputReference, ...]


@dataclass(frozen=True, slots=True)
class ResolutionLimits:
    max_deliveries_per_side: int = 500
    max_pages_per_traversal: int = 20
    max_input_records_per_side: int = 100_000
    side_deadline_seconds: float = 120.0

    def __post_init__(self) -> None:
        if (
            min(
                self.max_deliveries_per_side,
                self.max_pages_per_traversal,
                self.max_input_records_per_side,
            )
            <= 0
            or self.side_deadline_seconds <= 0
        ):
            raise ValueError("resolution limits must be positive")


class DeliveryObservationResolver:
    def __init__(
        self, evidence: ObservationEvidenceReader, *, limits: ResolutionLimits | None = None
    ) -> None:
        self._evidence = evidence
        self._limits = limits or ResolutionLimits()

    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation:
        facts: list[FactReading] = []
        fact_cursor: str | None = None
        fact_snapshot: str | None = None
        fact_pages = 0
        seen_fact_cursors: set[str] = set()
        while True:
            if fact_pages >= self._limits.max_pages_per_traversal:
                raise ResolutionBoundExceeded("Facts page bound exceeded")
            fact_page = await self._evidence.resolve_facts(
                delivery_id=delivery_id, limit=200, cursor=fact_cursor
            )
            if fact_snapshot is not None and fact_page.route_snapshot != fact_snapshot:
                raise UpstreamContractMismatch("Evidence Facts route snapshot drift")
            fact_snapshot = fact_page.route_snapshot
            facts.extend(fact_page.facts)
            fact_pages += 1
            fact_cursor = fact_page.next_cursor
            if fact_cursor is None:
                break
            if fact_cursor in seen_fact_cursors:
                raise ResolutionBoundExceeded("Facts cursor repeated")
            seen_fact_cursors.add(fact_cursor)

        nodes: list[TraceNodeReading] = []
        trace_cursor: str | None = None
        trace_snapshot: str | None = None
        trace_state: str | None = None
        trace_pages = 0
        seen_trace_cursors: set[str] = set()
        while True:
            if trace_pages >= self._limits.max_pages_per_traversal:
                raise ResolutionBoundExceeded("Traces page bound exceeded")
            trace_page = await self._evidence.resolve_traces(
                delivery_id=delivery_id, limit=200, cursor=trace_cursor
            )
            if trace_snapshot is not None and trace_page.route_snapshot != trace_snapshot:
                raise UpstreamContractMismatch("Evidence Traces route snapshot drift")
            if trace_state is not None and trace_page.trace_state != trace_state:
                raise UpstreamContractMismatch("Evidence Trace state drift")
            trace_snapshot = trace_page.route_snapshot
            trace_state = trace_page.trace_state
            nodes.extend(trace_page.nodes)
            trace_pages += 1
            trace_cursor = trace_page.next_cursor
            if trace_cursor is None:
                break
            if trace_cursor in seen_trace_cursors:
                raise ResolutionBoundExceeded("Traces cursor repeated")
            seen_trace_cursors.add(trace_cursor)

        if fact_snapshot is None or trace_snapshot is None or trace_state is None:
            raise UpstreamContractMismatch("Evidence observation traversal has no coordinate")
        by_fact = {item.fact_id: item for item in facts}
        by_node = {item.resource_id: item for item in nodes}
        if len(by_fact) != len(facts) or len(by_node) != len(nodes):
            raise UpstreamContractMismatch("Evidence observation identity is duplicated")
        ordered_facts = tuple(by_fact[key] for key in sorted(by_fact, key=str.encode))
        ordered_nodes = tuple(by_node[key] for key in sorted(by_node, key=str.encode))
        bindings = (
            EvidenceBinding(
                route="/v1/evidence/facts",
                canonical_filter={"delivery_id": delivery_id},
                contract_revision="0.1.0",
                observation_profile="1.0.0",
                read_model_revision="1.0.0",
                route_snapshot=fact_snapshot,
                completion_state="COMPLETE",
            ),
            EvidenceBinding(
                route="/v1/evidence/traces",
                canonical_filter={"delivery_id": delivery_id},
                contract_revision="0.1.0",
                observation_profile="1.0.0",
                read_model_revision="1.0.0",
                route_snapshot=trace_snapshot,
                completion_state=(
                    "EXPIRED"
                    if trace_state == "EXPIRED"
                    else "PARTIAL"
                    if trace_state == "PARTIAL"
                    else "COMPLETE"
                ),
                error_state=(
                    "TRACE_EXPIRED"
                    if trace_state == "EXPIRED"
                    else "TRACE_PARTIAL"
                    if trace_state == "PARTIAL"
                    else None
                ),
            ),
        )
        references = tuple(
            sorted(
                (
                    *(
                        InputReference(
                            kind="FACT",
                            identity=item.fact_id,
                            provenance_ref=item.accepted_digest,
                        )
                        for item in ordered_facts
                    ),
                    *(
                        InputReference(
                            kind="TRACE_NODE",
                            identity=item.resource_id,
                            provenance_ref=item.source_identity,
                        )
                        for item in ordered_nodes
                    ),
                ),
                key=lambda item: item.identity.encode(),
            )
        )
        return ResolvedDeliveryObservation(
            delivery_id=delivery_id,
            facts=ordered_facts,
            trace_nodes=ordered_nodes,
            trace_state=trace_state,
            evidence_bindings=bindings,
            input_refs=references,
        )


def _normalized_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("selection cutoff must include an offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _workflow_entry(
    reading: DeliveryManifestReading, resolution: WorkflowResolution
) -> WorkflowResolutionEntry:
    candidate = resolution.candidate
    attempts = tuple(
        WorkflowResolutionAttempt(
            source_id=attempt.source_id,
            source_index=attempt.source_index,
            code=attempt.code,
            omitted_count=attempt.omitted_count,
        )
        for attempt in resolution.attempts
    )
    return WorkflowResolutionEntry(
        manifest_digest=reading.manifest_digest,
        manifest_projection_digest=reading.projection_digest,
        accepted_digest=reading.accepted_digest,
        profile_version="2.0.0",
        source_identity=reading.source_identity,
        package_name=reading.workflow.package_name,
        exact_package_version=reading.workflow.exact_package_version,
        package_digest=reading.workflow.package_digest,
        workflow_id=reading.workflow.workflow_id,
        workflow_version=reading.workflow.workflow_version,
        snapshot_id=reading.workflow.snapshot_id,
        snapshot_digest=reading.workflow.snapshot_digest,
        state=resolution.state,
        matched_source_id=resolution.matched_source_id,
        matched_source_index=resolution.matched_source_index,
        matched_repository=resolution.matched_repository,
        validated_archive_digest=None if candidate is None else candidate.archive_digest,
        validated_package_digest=None if candidate is None else candidate.package_digest,
        validated_snapshot_digest=None if candidate is None else candidate.snapshot_digest,
        attempts=attempts,
    )


class SelectionPopulationResolver:
    def __init__(
        self,
        evidence: SelectionEvidenceReader,
        workflows: ManifestWorkflowResolver,
        *,
        limits: ResolutionLimits | None = None,
    ) -> None:
        self._evidence = evidence
        self._workflows = workflows
        self._limits = limits or ResolutionLimits()

    async def resolve(
        self, selection: EvaluationSelection, *, as_of: datetime
    ) -> ResolvedSelectionPopulation:
        cutoff = _normalized_utc(as_of)
        populations: list[TaskPopulationEntry] = []
        bindings: list[EvidenceBinding] = []
        references: list[InputReference] = []
        all_memberships: list[tuple[str, TaskMembershipReference]] = []
        unique_delivery_ids: set[str] = set()
        for task_id in selection.task_ids:
            cursor: str | None = None
            route_snapshot: str | None = None
            memberships: list[TaskMembershipReference] = []
            page_count = 0
            seen_cursors: set[str] = set()
            while True:
                if page_count >= self._limits.max_pages_per_traversal:
                    raise ResolutionBoundExceeded("Task membership page bound exceeded")
                page = await self._evidence.resolve_membership(
                    task_id=task_id,
                    as_of=as_of,
                    limit=200,
                    cursor=cursor,
                )
                if page.as_of != as_of or (
                    route_snapshot is not None and page.route_snapshot != route_snapshot
                ):
                    raise UpstreamContractMismatch("Evidence Task traversal coordinate drift")
                route_snapshot = page.route_snapshot
                for item in page.memberships:
                    if item.task_id != task_id or item.recorded_at > as_of:
                        raise UpstreamContractMismatch("Evidence Task membership mismatch")
                    reference = TaskMembershipReference(
                        delivery_id=item.delivery_id,
                        manifest_digest=item.manifest_digest,
                        accepted_digest=item.accepted_digest,
                        profile_version="2.0.0",
                        source_identity=item.source_identity,
                        recorded_at=item.recorded_at,
                    )
                    memberships.append(reference)
                    unique_delivery_ids.add(item.delivery_id)
                    if len(unique_delivery_ids) > self._limits.max_deliveries_per_side:
                        raise ResolutionBoundExceeded("unique Delivery bound exceeded")
                    references.append(
                        InputReference(
                            kind="TASK_MEMBERSHIP",
                            identity=f"{task_id}/{item.delivery_id}",
                            provenance_ref=item.source_identity,
                        )
                    )
                page_count += 1
                cursor = page.next_cursor
                if cursor is None:
                    break
                if cursor in seen_cursors:
                    raise ResolutionBoundExceeded("Task membership cursor repeated")
                seen_cursors.add(cursor)
            delivery_ids = [item.delivery_id for item in memberships]
            if len(set(delivery_ids)) != len(delivery_ids) or route_snapshot is None:
                raise UpstreamContractMismatch("Evidence Task traversal is inconsistent")
            ordered = tuple(sorted(memberships, key=lambda item: item.delivery_id.encode()))
            populations.append(
                TaskPopulationEntry(
                    task_id=task_id,
                    memberships=ordered,
                    exclusions=() if ordered else ("UNDEFINED_TASK_MEMBERSHIP",),
                )
            )
            all_memberships.extend((task_id, item) for item in ordered)
            bindings.append(
                EvidenceBinding(
                    route="/v1/evidence/tasks",
                    canonical_filter={"task_id": task_id, "as_of": cutoff},
                    contract_revision="1.0.0",
                    observation_profile="2.0.0",
                    read_model_revision="2.0.0",
                    route_snapshot=route_snapshot,
                    completion_state="COMPLETE",
                )
            )

        readings: dict[str, DeliveryManifestReading] = {}
        membership_by_digest = sorted(
            all_memberships, key=lambda item: item[1].manifest_digest.encode()
        )
        for task_id, membership in membership_by_digest:
            reading = readings.get(membership.manifest_digest)
            if reading is None:
                reading = await self._evidence.resolve_manifest(
                    manifest_digest=membership.manifest_digest
                )
                readings[membership.manifest_digest] = reading
            if (
                reading.task_id != task_id
                or reading.delivery_id != membership.delivery_id
                or reading.manifest_digest != membership.manifest_digest
                or reading.accepted_digest != membership.accepted_digest
                or reading.profile_version != membership.profile_version
                or reading.source_identity != membership.source_identity
            ):
                raise UpstreamContractMismatch(
                    "Evidence Manifest projection conflicts with Task membership"
                )
        workflow_entries = []
        for digest, reading in sorted(readings.items()):
            resolution = await self._workflows.resolve(reading)
            if resolution.manifest_digest != digest:
                raise UpstreamContractMismatch("Workflow resolution selected another Manifest")
            workflow_entries.append(_workflow_entry(reading, resolution))
        return ResolvedSelectionPopulation(
            task_population=tuple(populations),
            evidence_bindings=tuple(bindings),
            input_refs=tuple(sorted(references, key=lambda item: item.identity.encode())),
            workflow_resolutions=tuple(workflow_entries),
            manifest_readings=tuple(reading for _, reading in sorted(readings.items())),
        )
