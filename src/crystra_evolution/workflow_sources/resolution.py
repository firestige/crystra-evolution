from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from crystra_evolution.domain.ports import DeliveryManifestReading

SourceDiagnosticCode = Literal[
    "NOT_FOUND",
    "SOURCE_UNAVAILABLE",
    "INVALID_DESCRIPTOR",
    "CHECKSUM_MISMATCH",
    "INVALID_ARCHIVE",
    "INVALID_WORKFLOW",
    "PACKAGE_DIGEST_MISMATCH",
    "SNAPSHOT_DIGEST_MISMATCH",
    "ROLE_BINDING_MISMATCH",
    "DEADLINE_EXCEEDED",
    "ATTEMPTS_TRUNCATED",
]
SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
PREFIXED_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class WorkflowSourceConfig:
    source_id: str
    repository: str

    def __post_init__(self) -> None:
        if (
            SOURCE_ID.fullmatch(self.source_id) is None
            or REPOSITORY.fullmatch(self.repository) is None
        ):
            raise ValueError("invalid public Workflow source coordinate")


@dataclass(frozen=True, slots=True)
class WorkflowResolutionConfig:
    sources: tuple[WorkflowSourceConfig, ...]
    request_timeout_seconds: float = 10.0
    total_deadline_seconds: float = 30.0

    def __post_init__(self) -> None:
        identities = tuple(source.source_id for source in self.sources)
        if not 1 <= len(self.sources) <= 8 or len(set(identities)) != len(identities):
            raise ValueError("Workflow sources must contain 1-8 unique identities")
        if not 0 < self.request_timeout_seconds <= 10:
            raise ValueError("Workflow request timeout must be in (0,10]")
        if not 0 < self.total_deadline_seconds <= 30:
            raise ValueError("Workflow resolution deadline must be in (0,30]")


@dataclass(frozen=True, slots=True)
class WorkflowCandidateRole:
    role_id: str
    role_prompt_identity: str
    role_prompt_digest: str


@dataclass(frozen=True, slots=True)
class WorkflowCandidate:
    package_name: str
    exact_package_version: str
    package_digest: str
    workflow_id: str
    workflow_version: str
    snapshot_id: str
    snapshot_digest: str
    archive_digest: str
    roles: tuple[WorkflowCandidateRole, ...]

    def __post_init__(self) -> None:
        digests = (self.package_digest, self.snapshot_digest, self.archive_digest)
        role_ids = tuple(role.role_id for role in self.roles)
        if not all(PREFIXED_DIGEST.fullmatch(item) is not None for item in digests):
            raise ValueError("Workflow candidate digest is invalid")
        if role_ids != tuple(sorted(set(role_ids), key=lambda value: value.encode())):
            raise ValueError("Workflow candidate Roles must be unique and sorted")


class SourceFailure(RuntimeError):
    def __init__(self, code: SourceDiagnosticCode) -> None:
        super().__init__(code)
        self.code = code


class WorkflowSource(Protocol):
    async def fetch_exact(
        self, *, package_name: str, exact_version: str, timeout_seconds: float
    ) -> WorkflowCandidate: ...


@dataclass(frozen=True, slots=True)
class ResolutionAttempt:
    source_id: str | None
    source_index: int | None
    code: SourceDiagnosticCode
    omitted_count: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowResolution:
    state: Literal["AVAILABLE", "NOT_FOUND", "UNAVAILABLE"]
    manifest_digest: str
    attempts: tuple[ResolutionAttempt, ...]
    matched_source_id: str | None = None
    matched_source_index: int | None = None
    matched_repository: str | None = None
    candidate: WorkflowCandidate | None = None


_INDETERMINATE = {
    "SOURCE_UNAVAILABLE",
    "INVALID_DESCRIPTOR",
    "CHECKSUM_MISMATCH",
    "INVALID_ARCHIVE",
    "INVALID_WORKFLOW",
    "DEADLINE_EXCEEDED",
}


def _candidate_mismatch(
    manifest: DeliveryManifestReading, candidate: WorkflowCandidate
) -> SourceDiagnosticCode | None:
    expected = manifest.workflow
    if (
        candidate.package_name != expected.package_name
        or candidate.exact_package_version != expected.exact_package_version
    ):
        return "INVALID_DESCRIPTOR"
    if candidate.package_digest != expected.package_digest:
        return "PACKAGE_DIGEST_MISMATCH"
    if (
        candidate.workflow_id != expected.workflow_id
        or candidate.workflow_version != expected.workflow_version
    ):
        return "INVALID_WORKFLOW"
    if (
        candidate.snapshot_id != expected.snapshot_id
        or candidate.snapshot_digest != expected.snapshot_digest
    ):
        return "SNAPSHOT_DIGEST_MISMATCH"
    expected_roles = tuple(
        (role.role_id, role.role_prompt_identity, role.role_prompt_digest)
        for role in manifest.roles
    )
    candidate_roles = tuple(
        (role.role_id, role.role_prompt_identity, role.role_prompt_digest)
        for role in candidate.roles
    )
    return "ROLE_BINDING_MISMATCH" if candidate_roles != expected_roles else None


class WorkflowSourceResolver:
    def __init__(
        self,
        configuration: WorkflowResolutionConfig,
        sources: Mapping[str, WorkflowSource],
    ) -> None:
        expected = {source.source_id for source in configuration.sources}
        if set(sources) != expected:
            raise ValueError("Workflow source implementations must exactly match configuration")
        self._configuration = configuration
        self._sources = dict(sources)
        self._validated_cache: dict[
            tuple[object, ...], tuple[str, int, str, WorkflowCandidate]
        ] = {}

    async def resolve(self, manifest: DeliveryManifestReading) -> WorkflowResolution:
        cache_key = _exact_content_coordinate(manifest)
        cached = self._validated_cache.get(cache_key)
        if cached is not None:
            source_id, source_index, repository, candidate = cached
            return WorkflowResolution(
                state="AVAILABLE",
                manifest_digest=manifest.manifest_digest,
                attempts=(),
                matched_source_id=source_id,
                matched_source_index=source_index,
                matched_repository=repository,
                candidate=candidate,
            )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._configuration.total_deadline_seconds
        attempts: list[ResolutionAttempt] = []
        for index, configured in enumerate(self._configuration.sources):
            remaining = deadline - loop.time()
            if remaining <= 0:
                attempts.append(ResolutionAttempt(None, None, "DEADLINE_EXCEEDED"))
                break
            timeout = min(self._configuration.request_timeout_seconds, remaining)
            try:
                candidate = await asyncio.wait_for(
                    self._sources[configured.source_id].fetch_exact(
                        package_name=manifest.workflow.package_name,
                        exact_version=manifest.workflow.exact_package_version,
                        timeout_seconds=timeout,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                code: SourceDiagnosticCode = (
                    "DEADLINE_EXCEEDED" if loop.time() >= deadline else "SOURCE_UNAVAILABLE"
                )
                attempts.append(
                    ResolutionAttempt(
                        None if code == "DEADLINE_EXCEEDED" else configured.source_id,
                        None if code == "DEADLINE_EXCEEDED" else index,
                        code,
                    )
                )
                if code == "DEADLINE_EXCEEDED":
                    break
                continue
            except SourceFailure as failure:
                attempts.append(ResolutionAttempt(configured.source_id, index, failure.code))
                continue
            mismatch = _candidate_mismatch(manifest, candidate)
            if mismatch is not None:
                attempts.append(ResolutionAttempt(configured.source_id, index, mismatch))
                continue
            self._validated_cache[cache_key] = (
                configured.source_id,
                index,
                configured.repository,
                candidate,
            )
            return WorkflowResolution(
                state="AVAILABLE",
                manifest_digest=manifest.manifest_digest,
                attempts=_bounded_attempts(attempts),
                matched_source_id=configured.source_id,
                matched_source_index=index,
                matched_repository=configured.repository,
                candidate=candidate,
            )
        bounded = _bounded_attempts(attempts)
        state: Literal["NOT_FOUND", "UNAVAILABLE"] = (
            "UNAVAILABLE" if any(item.code in _INDETERMINATE for item in attempts) else "NOT_FOUND"
        )
        return WorkflowResolution(
            state=state,
            manifest_digest=manifest.manifest_digest,
            attempts=bounded,
        )


def _exact_content_coordinate(manifest: DeliveryManifestReading) -> tuple[object, ...]:
    workflow = manifest.workflow
    return (
        workflow.package_name,
        workflow.exact_package_version,
        workflow.package_digest,
        workflow.workflow_id,
        workflow.workflow_version,
        workflow.snapshot_id,
        workflow.snapshot_digest,
        tuple(
            (role.role_id, role.role_prompt_identity, role.role_prompt_digest)
            for role in manifest.roles
        ),
    )


def _bounded_attempts(attempts: list[ResolutionAttempt]) -> tuple[ResolutionAttempt, ...]:
    if len(attempts) <= 8:
        return tuple(attempts)
    return (
        *attempts[:7],
        ResolutionAttempt(None, None, "ATTEMPTS_TRUNCATED", len(attempts) - 7),
    )
