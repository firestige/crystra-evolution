from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crystra_evolution.api.models import EvaluationSelection
from crystra_evolution.application import ResolutionBoundExceeded, UpstreamContractMismatch
from crystra_evolution.domain.ports import (
    DeliveryManifestReading,
    ManifestWorkflow,
    TaskMembershipPage,
    TaskMembershipSummary,
)
from crystra_evolution.resolution.service import ResolutionLimits, SelectionPopulationResolver
from crystra_evolution.workflow_sources.resolution import WorkflowResolution

AS_OF = datetime(2026, 8, 28, 1, tzinfo=UTC)


def membership(delivery_id: str, digest: str) -> TaskMembershipSummary:
    return TaskMembershipSummary(
        task_id="task-a",
        delivery_id=delivery_id,
        manifest_digest=digest,
        accepted_digest="b" * 64,
        profile_version="2.0.0",
        source_identity=f"event:{delivery_id}",
        recorded_at=datetime(2026, 8, 28, 0, 59, tzinfo=UTC),
    )


def manifest(delivery_id: str, digest: str) -> DeliveryManifestReading:
    return DeliveryManifestReading(
        delivery_id=delivery_id,
        task_id="task-a",
        manifest_digest=digest,
        projection_digest="c" * 64,
        workflow=ManifestWorkflow(
            package_name="implementation",
            exact_package_version="2.0.0",
            package_digest=f"sha256:{'d' * 64}",
            workflow_id="workflow.implementation",
            workflow_version="2.0.0",
            snapshot_id="snapshot.implementation.2",
            snapshot_digest=f"sha256:{'e' * 64}",
        ),
        repository_document_state="ABSENT",
        repository_document_digest=None,
        resolved_map_digest=f"sha256:{'f' * 64}",
        roles=(),
        accepted_digest="b" * 64,
        profile_version="2.0.0",
        source_identity=f"event:{delivery_id}",
    )


class EvidenceStub:
    def __init__(self, pages: list[TaskMembershipPage]) -> None:
        self.pages = pages
        self.manifests = {
            item.manifest_digest: manifest(item.delivery_id, item.manifest_digest)
            for page in pages
            for item in page.memberships
        }
        self.membership_calls: list[str | None] = []
        self.manifest_calls: list[str] = []

    async def list_tasks(self, *, limit: int, cursor: str | None) -> object:
        raise AssertionError("selection resolution must not scan the display list")

    async def resolve_membership(
        self,
        *,
        task_id: str,
        as_of: datetime,
        limit: int,
        cursor: str | None,
    ) -> TaskMembershipPage:
        assert task_id == "task-a"
        assert as_of == AS_OF
        assert limit == 200
        self.membership_calls.append(cursor)
        return self.pages.pop(0)

    async def resolve_manifest(self, *, manifest_digest: str) -> DeliveryManifestReading:
        self.manifest_calls.append(manifest_digest)
        return self.manifests[manifest_digest]


class WorkflowResolverStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def resolve(self, reading: DeliveryManifestReading) -> WorkflowResolution:
        self.calls.append(reading.manifest_digest)
        return WorkflowResolution(
            state="NOT_FOUND",
            manifest_digest=reading.manifest_digest,
            attempts=(),
        )


@pytest.mark.asyncio
async def test_selection_resolver_binds_full_membership_and_exact_manifest_readings() -> None:
    first_digest = "1" * 64
    second_digest = "2" * 64
    evidence = EvidenceStub(
        [
            TaskMembershipPage(
                memberships=(membership("delivery-2", second_digest),),
                as_of=AS_OF,
                next_cursor="next",
                route_snapshot="snapshot-a",
            ),
            TaskMembershipPage(
                memberships=(membership("delivery-1", first_digest),),
                as_of=AS_OF,
                next_cursor=None,
                route_snapshot="snapshot-a",
            ),
        ]
    )
    workflows = WorkflowResolverStub()

    resolved = await SelectionPopulationResolver(evidence, workflows).resolve(
        EvaluationSelection(selection_version=1, task_ids=("task-a",)), as_of=AS_OF
    )

    assert evidence.membership_calls == [None, "next"]
    assert evidence.manifest_calls == [first_digest, second_digest]
    assert workflows.calls == [first_digest, second_digest]
    assert [item.delivery_id for item in resolved.task_population[0].memberships] == [
        "delivery-1",
        "delivery-2",
    ]
    assert resolved.evidence_bindings[0].route_snapshot == "snapshot-a"
    assert [item.manifest_digest for item in resolved.workflow_resolutions] == [
        first_digest,
        second_digest,
    ]
    assert [item.identity for item in resolved.input_refs] == [
        "task-a/delivery-1",
        "task-a/delivery-2",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["snapshot", "manifest", "duplicate"])
async def test_selection_resolver_fails_closed_on_cross_read_inconsistency(failure: str) -> None:
    digest = "1" * 64
    first = membership("delivery-1", digest)
    items = (first, first) if failure == "duplicate" else (first,)
    pages = [
        TaskMembershipPage(
            memberships=items,
            as_of=AS_OF,
            next_cursor="next" if failure == "snapshot" else None,
            route_snapshot="snapshot-a",
        )
    ]
    if failure == "snapshot":
        pages.append(
            TaskMembershipPage(
                memberships=(),
                as_of=AS_OF,
                next_cursor=None,
                route_snapshot="snapshot-b",
            )
        )
    evidence = EvidenceStub(pages)
    if failure == "manifest":
        evidence.manifests[digest] = manifest("delivery-other", digest)

    with pytest.raises(UpstreamContractMismatch):
        await SelectionPopulationResolver(evidence, WorkflowResolverStub()).resolve(
            EvaluationSelection(selection_version=1, task_ids=("task-a",)), as_of=AS_OF
        )


@pytest.mark.asyncio
async def test_selection_resolver_enforces_configured_unique_delivery_cap() -> None:
    evidence = EvidenceStub(
        [
            TaskMembershipPage(
                memberships=(
                    membership("delivery-1", "1" * 64),
                    membership("delivery-2", "2" * 64),
                ),
                as_of=AS_OF,
                next_cursor=None,
                route_snapshot="snapshot-a",
            )
        ]
    )

    with pytest.raises(ResolutionBoundExceeded, match="Delivery"):
        await SelectionPopulationResolver(
            evidence,
            WorkflowResolverStub(),
            limits=ResolutionLimits(max_deliveries_per_side=1),
        ).resolve(EvaluationSelection(selection_version=1, task_ids=("task-a",)), as_of=AS_OF)
