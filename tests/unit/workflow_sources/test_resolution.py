from __future__ import annotations

from dataclasses import replace

import pytest

from crystra_evolution.domain.ports import (
    DeliveryManifestReading,
    ManifestRoleBinding,
    ManifestWorkflow,
)
from crystra_evolution.workflow_sources.resolution import (
    SourceFailure,
    WorkflowCandidate,
    WorkflowCandidateRole,
    WorkflowResolutionConfig,
    WorkflowSource,
    WorkflowSourceConfig,
    WorkflowSourceResolver,
)


def manifest() -> DeliveryManifestReading:
    return DeliveryManifestReading(
        delivery_id="delivery-a",
        task_id="task-a",
        manifest_digest="a" * 64,
        projection_digest="b" * 64,
        workflow=ManifestWorkflow(
            package_name="implementation",
            exact_package_version="2.0.0",
            package_digest=f"sha256:{'c' * 64}",
            workflow_id="workflow.implementation",
            workflow_version="2.0.0",
            snapshot_id="snapshot.implementation.2",
            snapshot_digest=f"sha256:{'d' * 64}",
        ),
        repository_document_state="ABSENT",
        repository_document_digest=None,
        resolved_map_digest=f"sha256:{'e' * 64}",
        roles=(
            ManifestRoleBinding(
                role_id="role.writer",
                role_prompt_identity="prompt.role.writer",
                role_prompt_digest=f"sha256:{'f' * 64}",
                agent_provider_id="provider.dsh",
                model_provider_id="deepseek-official",
                model_id="deepseek-reasoner",
                resolution_source="EXECUTION_DEFAULT",
            ),
        ),
        accepted_digest="1" * 64,
        profile_version="2.0.0",
        source_identity="event:task-event-a",
    )


def candidate() -> WorkflowCandidate:
    reading = manifest()
    return WorkflowCandidate(
        package_name=reading.workflow.package_name,
        exact_package_version=reading.workflow.exact_package_version,
        package_digest=reading.workflow.package_digest,
        workflow_id=reading.workflow.workflow_id,
        workflow_version=reading.workflow.workflow_version,
        snapshot_id=reading.workflow.snapshot_id,
        snapshot_digest=reading.workflow.snapshot_digest,
        archive_digest=f"sha256:{'2' * 64}",
        roles=(
            WorkflowCandidateRole(
                role_id="role.writer",
                role_prompt_identity="prompt.role.writer",
                role_prompt_digest=f"sha256:{'f' * 64}",
            ),
        ),
    )


class StubSource(WorkflowSource):
    def __init__(self, outcomes: list[WorkflowCandidate | SourceFailure]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str, float]] = []

    async def fetch_exact(
        self, *, package_name: str, exact_version: str, timeout_seconds: float
    ) -> WorkflowCandidate:
        self.calls.append((package_name, exact_version, timeout_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, SourceFailure):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_resolver_uses_declared_order_until_every_digest_and_role_matches() -> None:
    mismatch = replace(candidate(), package_digest=f"sha256:{'9' * 64}")
    first = StubSource([mismatch])
    second = StubSource([SourceFailure("SOURCE_UNAVAILABLE")])
    third = StubSource([candidate()])
    resolver = WorkflowSourceResolver(
        WorkflowResolutionConfig(
            sources=(
                WorkflowSourceConfig("official", "firestige/workflows"),
                WorkflowSourceConfig("team", "example/workflows"),
                WorkflowSourceConfig("fork", "other/workflows"),
            )
        ),
        {"official": first, "team": second, "fork": third},
    )

    result = await resolver.resolve(manifest())

    assert result.state == "AVAILABLE"
    assert result.matched_source_id == "fork"
    assert result.matched_source_index == 2
    assert [item.code for item in result.attempts] == [
        "PACKAGE_DIGEST_MISMATCH",
        "SOURCE_UNAVAILABLE",
    ]
    assert first.calls == [("implementation", "2.0.0", 10.0)]
    assert len(second.calls) == len(third.calls) == 1


@pytest.mark.asyncio
async def test_resolver_distinguishes_proven_absence_from_indeterminate_failure() -> None:
    role_mismatch = replace(
        candidate(),
        roles=(
            WorkflowCandidateRole(
                role_id="role.other",
                role_prompt_identity="prompt.role.other",
                role_prompt_digest=f"sha256:{'8' * 64}",
            ),
        ),
    )
    configuration = WorkflowResolutionConfig(
        sources=(
            WorkflowSourceConfig("one", "example/one"),
            WorkflowSourceConfig("two", "example/two"),
        )
    )
    absent = WorkflowSourceResolver(
        configuration,
        {
            "one": StubSource([SourceFailure("NOT_FOUND")]),
            "two": StubSource([role_mismatch]),
        },
    )
    unavailable = WorkflowSourceResolver(
        configuration,
        {
            "one": StubSource([SourceFailure("NOT_FOUND")]),
            "two": StubSource([SourceFailure("INVALID_ARCHIVE")]),
        },
    )

    assert (await absent.resolve(manifest())).state == "NOT_FOUND"
    assert (await unavailable.resolve(manifest())).state == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_validated_cache_is_keyed_by_exact_content_and_never_substitutes() -> None:
    exact = candidate()
    source = StubSource([exact, exact, exact])
    resolver = WorkflowSourceResolver(
        WorkflowResolutionConfig(
            sources=(WorkflowSourceConfig("official", "firestige/crystra-workflow-package"),)
        ),
        {"official": source},
    )

    first = await resolver.resolve(manifest())
    second = await resolver.resolve(manifest())
    changed = replace(
        manifest(),
        manifest_digest="9" * 64,
        workflow=replace(manifest().workflow, package_digest=f"sha256:{'8' * 64}"),
    )
    third = await resolver.resolve(changed)

    assert first.state == second.state == "AVAILABLE"
    assert second.manifest_digest == manifest().manifest_digest
    assert third.state == "NOT_FOUND"
    assert [item.code for item in third.attempts] == ["PACKAGE_DIGEST_MISMATCH"]
    assert len(source.calls) == 2


@pytest.mark.parametrize(
    "sources",
    [
        (),
        tuple(WorkflowSourceConfig(f"source-{index}", f"owner/repo-{index}") for index in range(9)),
        (
            WorkflowSourceConfig("same", "owner/one"),
            WorkflowSourceConfig("same", "owner/two"),
        ),
    ],
)
def test_source_configuration_is_nonempty_bounded_and_identity_unique(
    sources: tuple[WorkflowSourceConfig, ...],
) -> None:
    with pytest.raises(ValueError):
        WorkflowResolutionConfig(sources=sources)


@pytest.mark.parametrize(
    "repository",
    ["https://github.com/owner/repo", "owner", "owner/repo/extra", "user:token@owner/repo"],
)
def test_source_configuration_accepts_only_public_repository_coordinates(
    repository: str,
) -> None:
    with pytest.raises(ValueError):
        WorkflowSourceConfig("source", repository)
