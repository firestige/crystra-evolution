from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

type Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class FactRelationshipEndpoint:
    kind: str
    key: tuple[Scalar, ...]


@dataclass(frozen=True, slots=True)
class FactRelationship:
    kind: str
    source: FactRelationshipEndpoint
    target: FactRelationshipEndpoint


@dataclass(frozen=True, slots=True)
class FactReading:
    fact_id: str
    kind: str
    source_identity: str
    recorded_at: datetime
    accepted_digest: str
    event_name: str | None
    completeness: str | None
    availability: str
    expiry: str
    fields: tuple[tuple[str, Scalar], ...]
    compatibility: tuple[tuple[str, Scalar], ...]
    relationships: tuple[FactRelationship, ...] = ()

    @property
    def field_map(self) -> dict[str, Scalar]:
        return dict(self.fields)

    @property
    def compatibility_map(self) -> dict[str, Scalar]:
        return dict(self.compatibility)


@dataclass(frozen=True, slots=True)
class FactPage:
    facts: tuple[FactReading, ...]
    next_cursor: str | None
    route_snapshot: str


@dataclass(frozen=True, slots=True)
class TraceNodeReading:
    resource_id: str
    trace_id: str
    span_id: str
    source_identity: str
    recorded_at: datetime
    availability: str
    expiry: str
    start_time_unix_nano: int
    end_time_unix_nano: int
    span_status: str
    fields: tuple[tuple[str, Scalar], ...]

    @property
    def field_map(self) -> dict[str, Scalar]:
        return dict(self.fields)


@dataclass(frozen=True, slots=True)
class TracePage:
    nodes: tuple[TraceNodeReading, ...]
    next_cursor: str | None
    route_snapshot: str
    trace_state: str


@dataclass(frozen=True, slots=True)
class TaskSummary:
    task_id: str
    display_name: str | None


@dataclass(frozen=True, slots=True)
class TaskPage:
    tasks: tuple[TaskSummary, ...]
    next_cursor: str | None
    route_snapshot: str


@dataclass(frozen=True, slots=True)
class TaskMembershipSummary:
    task_id: str
    delivery_id: str
    manifest_digest: str
    accepted_digest: str
    profile_version: str
    source_identity: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class TaskMembershipPage:
    memberships: tuple[TaskMembershipSummary, ...]
    as_of: datetime
    next_cursor: str | None
    route_snapshot: str


@dataclass(frozen=True, slots=True)
class ManifestWorkflow:
    package_name: str
    exact_package_version: str
    package_digest: str
    workflow_id: str
    workflow_version: str
    snapshot_id: str
    snapshot_digest: str


@dataclass(frozen=True, slots=True)
class ManifestRoleBinding:
    role_id: str
    role_prompt_identity: str
    role_prompt_digest: str
    agent_provider_id: str
    model_provider_id: str
    model_id: str
    resolution_source: str


@dataclass(frozen=True, slots=True)
class DeliveryManifestReading:
    delivery_id: str
    task_id: str
    manifest_digest: str
    projection_digest: str
    workflow: ManifestWorkflow
    repository_document_state: str
    repository_document_digest: str | None
    resolved_map_digest: str
    roles: tuple[ManifestRoleBinding, ...]
    accepted_digest: str
    profile_version: str
    source_identity: str


class EvidenceTaskReader(Protocol):
    async def list_tasks(self, *, limit: int, cursor: str | None) -> TaskPage: ...

    async def resolve_membership(
        self,
        *,
        task_id: str,
        as_of: datetime,
        limit: int,
        cursor: str | None,
    ) -> TaskMembershipPage: ...

    async def resolve_manifest(self, *, manifest_digest: str) -> DeliveryManifestReading: ...
