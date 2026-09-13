from __future__ import annotations

import json
from hashlib import sha256

import httpx
import pytest

from crystra_evolution.workflow_sources.github import GitHubWorkflowSource
from crystra_evolution.workflow_sources.resolution import (
    SourceFailure,
    WorkflowCandidate,
    WorkflowSourceConfig,
)


def candidate(archive_digest: str) -> WorkflowCandidate:
    return WorkflowCandidate(
        package_name="implementation",
        exact_package_version="2.0.0",
        package_digest=f"sha256:{'a' * 64}",
        workflow_id="workflow.implementation",
        workflow_version="2.0.0",
        snapshot_id="snapshot.implementation.2",
        snapshot_digest=f"sha256:{'b' * 64}",
        archive_digest=archive_digest,
        roles=(),
    )


class ValidatorStub:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, str, str]] = []

    async def validate(
        self,
        *,
        archive: bytes,
        archive_digest: str,
        package_name: str,
        exact_version: str,
    ) -> WorkflowCandidate:
        self.calls.append((archive, archive_digest, package_name, exact_version))
        return candidate(archive_digest)


@pytest.mark.asyncio
async def test_github_source_fetches_exact_scoped_release_and_checks_bytes() -> None:
    archive = b"bounded workflow archive"
    archive_digest = "sha256:" + sha256(archive).hexdigest()
    archive_name = "workflow-package-implementation-2.0.0.tar.gz"
    descriptor_name = "workflow-package-implementation-2.0.0.json"
    archive_url = "https://github.test/assets/archive"
    descriptor_url = "https://github.test/assets/descriptor"
    checksum_url = "https://github.test/assets/checksum"
    provenance_url = "https://github.test/assets/provenance"
    provenance_name = "workflow-package-implementation-2.0.0.provenance.json"
    provenance = {
        "schemaVersion": "workflow-package.provenance@1.0.0",
        "subject": {"name": archive_name, "sha256": archive_digest},
        "source": {"repository": "firestige/crystra-workflow-package", "revision": "c" * 40},
        "contract": {"repository": "firestige/crystra-contracts", "revision": "d" * 40},
        "builder": {"workflow": ".github/workflows/release-candidate.yml"},
    }
    provenance_bytes = (json.dumps(provenance, separators=(",", ":")) + "\n").encode()
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "workflow-package/implementation/v2.0.0",
                        "draft": False,
                        "prerelease": False,
                        "assets": [
                            {"name": archive_name, "browser_download_url": archive_url},
                            {"name": descriptor_name, "browser_download_url": descriptor_url},
                            {
                                "name": f"{archive_name}.sha256",
                                "browser_download_url": checksum_url,
                            },
                            {
                                "name": provenance_name,
                                "browser_download_url": provenance_url,
                            },
                        ],
                    }
                ],
            )
        if str(request.url) == descriptor_url:
            return httpx.Response(
                200,
                json={
                    "schemaVersion": "workflow-package.package-release@2.0.0",
                    "tag": "workflow-package/implementation/v2.0.0",
                    "package": {
                        "name": "implementation",
                        "version": "2.0.0",
                        "digest": f"sha256:{'a' * 64}",
                    },
                    "archive": {
                        "name": archive_name,
                        "sha256": archive_digest,
                        "bytes": len(archive),
                    },
                    "checksum": {"name": f"{archive_name}.sha256"},
                    "provenance": {
                        "name": provenance_name,
                        "sha256": "sha256:" + sha256(provenance_bytes).hexdigest(),
                    },
                    "contract": {
                        "repository": "firestige/crystra-contracts",
                        "revision": "d" * 40,
                        "minVersion": "1.1.0",
                        "maxVersion": "1.1.0",
                    },
                },
            )
        if str(request.url) == checksum_url:
            return httpx.Response(200, content=f"{archive_digest[7:]}  {archive_name}\n")
        if str(request.url) == provenance_url:
            return httpx.Response(200, content=provenance_bytes)
        if str(request.url) == archive_url:
            return httpx.Response(200, content=archive)
        raise AssertionError(f"unexpected request {request.url}")

    validator = ValidatorStub()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        source = GitHubWorkflowSource(
            WorkflowSourceConfig("official", "firestige/crystra-workflow-package"),
            transport,
            validator,
        )
        result = await source.fetch_exact(
            package_name="implementation", exact_version="2.0.0", timeout_seconds=3.0
        )

    assert result.archive_digest == archive_digest
    assert validator.calls == [(archive, archive_digest, "implementation", "2.0.0")]
    assert calls[0] == (
        "https://api.github.com/repos/firestige/crystra-workflow-package/releases?per_page=100&page=1"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["descriptor", "checksum", "archive"])
async def test_github_source_maps_integrity_failures_without_leaking_response(
    corruption: str,
) -> None:
    archive = b"archive"
    digest = "sha256:" + sha256(archive).hexdigest()
    archive_name = "workflow-package-implementation-2.0.0.tar.gz"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "workflow-package/implementation/v2.0.0",
                        "draft": False,
                        "prerelease": False,
                        "assets": [
                            {
                                "name": archive_name,
                                "browser_download_url": "https://github.test/archive",
                            },
                            {
                                "name": "workflow-package-implementation-2.0.0.json",
                                "browser_download_url": "https://github.test/descriptor",
                            },
                            {
                                "name": f"{archive_name}.sha256",
                                "browser_download_url": "https://github.test/checksum",
                            },
                        ],
                    }
                ],
            )
        if request.url.path == "/descriptor":
            if corruption == "descriptor":
                return httpx.Response(200, json={"unexpected": True})
            return httpx.Response(
                200,
                json={
                    "schemaVersion": "workflow-package.package-release@1.0.0",
                    "revision": "c" * 40,
                    "tag": "workflow-package/implementation/v2.0.0",
                    "package": {
                        "name": "implementation",
                        "version": "2.0.0",
                        "digest": f"sha256:{'a' * 64}",
                    },
                    "archive": {
                        "name": archive_name,
                        "sha256": digest,
                        "bytes": len(archive),
                    },
                    "checksum": {"name": f"{archive_name}.sha256"},
                },
            )
        if request.url.path == "/checksum":
            value = "0" * 64 if corruption == "checksum" else digest[7:]
            return httpx.Response(200, content=f"{value}  {archive_name}\n")
        return httpx.Response(200, content=b"wrong" if corruption == "archive" else archive)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        source = GitHubWorkflowSource(
            WorkflowSourceConfig("official", "firestige/workflows"),
            transport,
            ValidatorStub(),
        )
        with pytest.raises(SourceFailure) as caught:
            await source.fetch_exact(
                package_name="implementation", exact_version="2.0.0", timeout_seconds=3.0
            )

    assert (
        caught.value.code
        == {
            "descriptor": "INVALID_DESCRIPTOR",
            "checksum": "CHECKSUM_MISMATCH",
            "archive": "INVALID_ARCHIVE",
        }[corruption]
    )


@pytest.mark.asyncio
async def test_github_source_resolves_exact_historical_aggregate_release() -> None:
    archive = b"historical archive"
    archive_digest = "sha256:" + sha256(archive).hexdigest()
    archive_name = "workflow-package-implementation-0.3.0.tar.gz"
    descriptor_name = "workflow-package-release-0.3.0.json"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "0.3.0",
                        "draft": False,
                        "prerelease": False,
                        "assets": [
                            {
                                "name": descriptor_name,
                                "browser_download_url": "https://github.test/historical-descriptor",
                            },
                            {
                                "name": archive_name,
                                "browser_download_url": "https://github.test/historical-archive",
                            },
                        ],
                    }
                ],
            )
        if request.url.path == "/historical-descriptor":
            return httpx.Response(
                200,
                json={
                    "schemaVersion": "workflow-package.release@1.0.0",
                    "revision": "e" * 40,
                    "tag": "0.3.0",
                    "assets": [
                        {
                            "name": archive_name,
                            "sha256": archive_digest,
                            "bytes": len(archive),
                            "package": "implementation",
                            "version": "0.3.0",
                            "packageDigest": f"sha256:{'a' * 64}",
                        }
                    ],
                },
            )
        if request.url.path == "/historical-archive":
            return httpx.Response(200, content=archive)
        raise AssertionError(str(request.url))

    validator = ValidatorStub()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        source = GitHubWorkflowSource(
            WorkflowSourceConfig("official", "firestige/crystra-workflow-package"),
            transport,
            validator,
        )
        resolved = await source.fetch_exact(
            package_name="implementation", exact_version="0.3.0", timeout_seconds=3
        )

    assert resolved.archive_digest == archive_digest
    assert validator.calls == [(archive, archive_digest, "implementation", "0.3.0")]


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "code"), [(404, "NOT_FOUND"), (503, "SOURCE_UNAVAILABLE")])
async def test_github_source_distinguishes_missing_repository_from_outage(
    status: int, code: str
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"failure")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        source = GitHubWorkflowSource(
            WorkflowSourceConfig("official", "firestige/crystra-workflow-package"),
            transport,
            ValidatorStub(),
        )
        with pytest.raises(SourceFailure) as caught:
            await source.fetch_exact(
                package_name="implementation", exact_version="2.0.0", timeout_seconds=3
            )

    assert caught.value.code == code
