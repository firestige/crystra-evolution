import json
from datetime import UTC, datetime
from hashlib import sha256

import httpx
import pytest

from crystra_evolution.application import UpstreamContractMismatch, UpstreamUnavailable
from crystra_evolution.evidence.client import EvidenceHttpClient


def task_response(*, revision: str = "1.0.0") -> dict[str, object]:
    return {
        "contract": {"name": "evidence.query", "revision": revision},
        "observation_profile": "2.0.0",
        "read_model_revision": "2.0.0",
        "snapshot": "task-snapshot-a",
        "items": [
            {
                "task_id": "task-a",
                "delivery_id": "delivery-a",
                "manifest_digest": "a" * 64,
                "recorded_at": "2026-08-28T00:59:00.000000Z",
                "provenance": {
                    "accepted_digest": "b" * 64,
                    "profile_version": "2.0.0",
                    "source": {"kind": "EVENT", "event_id": "task-event-a"},
                },
            }
        ],
        "next_cursor": "cursor-next",
    }


def manifest_response(*, projection_digest: str | None = None) -> dict[str, object]:
    roles = [
        {
            "role_id": "role.writer",
            "role_prompt_identity": "prompt.role.writer",
            "role_prompt_digest": f"sha256:{'c' * 64}",
            "agent_provider_id": "provider.dsh",
            "agent_provider_version": "1.2.3",
            "agent_provider_adapter_key": "dsh-sdk",
            "agent_provider_descriptor_digest": f"sha256:{'1' * 64}",
            "required_capabilities": ["structured-completion"],
            "model_provider_id": "deepseek-official",
            "model_id": "deepseek-reasoner",
            "resolution_source": "REPOSITORY",
        }
    ]
    resolved_roles = [
        {
            "roleId": "role.writer",
            "rolePromptIdentity": "prompt.role.writer",
            "rolePromptDigest": f"sha256:{'c' * 64}",
            "agentProviderId": "provider.dsh",
            "agentProviderVersion": "1.2.3",
            "agentProviderAdapterKey": "dsh-sdk",
            "agentProviderDescriptorDigest": f"sha256:{'1' * 64}",
            "requiredCapabilities": ["structured-completion"],
            "modelProviderId": "deepseek-official",
            "modelId": "deepseek-reasoner",
            "resolutionSource": "REPOSITORY",
        }
    ]
    projection = {
        "schema_version": "execution.delivery-manifest-projection@1.0.0",
        "delivery_id": "delivery-a",
        "task_id": "task-a",
        "manifest_digest": "a" * 64,
        "workflow": {
            "package_name": "implementation",
            "exact_package_version": "2.0.0",
            "package_digest": f"sha256:{'d' * 64}",
            "workflow_id": "workflow.implementation",
            "workflow_version": "2.0.0",
            "snapshot_id": "snapshot.implementation.2",
            "snapshot_digest": f"sha256:{'e' * 64}",
        },
        "repository_model_bindings": {
            "document_state": "PRESENT",
            "document_digest": f"sha256:{'f' * 64}",
            "resolved_map_digest": "sha256:"
            + sha256(
                json.dumps(
                    resolved_roles,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        },
        "roles": roles,
    }
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "contract": {"name": "evidence.query", "revision": "1.0.0"},
        "observation_profile": "2.0.0",
        "read_model_revision": "2.0.0",
        "manifest": projection,
        "manifest_projection_digest": projection_digest or sha256(canonical.encode()).hexdigest(),
        "provenance": {
            "accepted_digest": "b" * 64,
            "profile_version": "2.0.0",
            "source": {"kind": "EVENT", "event_id": "task-event-a"},
        },
    }


@pytest.mark.asyncio
async def test_task_client_sends_normalized_cutoff_and_decodes_exact_provenance() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/evidence/tasks"
        assert dict(request.url.params) == {
            "task_id": "task-a",
            "as_of": "2026-08-28T01:00:00.000000Z",
            "limit": "200",
            "cursor": "cursor-current",
        }
        return httpx.Response(200, json=task_response())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        page = await EvidenceHttpClient(transport).resolve_membership(
            task_id="task-a",
            as_of=datetime(2026, 8, 28, 1, tzinfo=UTC),
            limit=200,
            cursor="cursor-current",
        )

    assert page.route_snapshot == "task-snapshot-a"
    assert page.next_cursor == "cursor-next"
    assert page.memberships[0].source_identity == "event:task-event-a"
    assert page.memberships[0].accepted_digest == "b" * 64


@pytest.mark.asyncio
async def test_task_client_rejects_unknown_evidence_coordinates() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=task_response(revision="1.1.0"))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        with pytest.raises(UpstreamContractMismatch):
            await EvidenceHttpClient(transport).resolve_membership(
                task_id="task-a",
                as_of=datetime(2026, 8, 28, 1, tzinfo=UTC),
                limit=200,
                cursor=None,
            )


@pytest.mark.asyncio
async def test_task_client_maps_retryable_query_failure_without_fabricating_a_page() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"code": "QUERY_UNAVAILABLE", "message": "try later"}},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        with pytest.raises(UpstreamUnavailable):
            await EvidenceHttpClient(transport).resolve_membership(
                task_id="task-a",
                as_of=datetime(2026, 8, 28, 1, tzinfo=UTC),
                limit=200,
                cursor=None,
            )


@pytest.mark.asyncio
async def test_manifest_client_queries_exact_digest_and_validates_role_map() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/evidence/manifests"
        assert dict(request.url.params) == {"manifest_digest": "a" * 64}
        return httpx.Response(200, json=manifest_response())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        reading = await EvidenceHttpClient(transport).resolve_manifest(manifest_digest="a" * 64)

    assert reading.delivery_id == "delivery-a"
    assert reading.workflow.package_name == "implementation"
    assert reading.roles[0].role_id == "role.writer"
    assert reading.roles[0].model_id == "deepseek-reasoner"
    assert reading.source_identity == "event:task-event-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["projection", "role-map", "identity"])
async def test_manifest_client_rejects_internal_projection_incompatibility(mutation: str) -> None:
    response = manifest_response()
    manifest = response["manifest"]
    assert isinstance(manifest, dict)
    if mutation == "projection":
        response["manifest_projection_digest"] = "0" * 64
    elif mutation == "role-map":
        bindings = manifest["repository_model_bindings"]
        assert isinstance(bindings, dict)
        bindings["resolved_map_digest"] = f"sha256:{'0' * 64}"
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        response["manifest_projection_digest"] = sha256(canonical.encode()).hexdigest()
    else:
        manifest["manifest_digest"] = "9" * 64
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        response["manifest_projection_digest"] = sha256(canonical.encode()).hexdigest()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        with pytest.raises(UpstreamContractMismatch):
            await EvidenceHttpClient(transport).resolve_manifest(manifest_digest="a" * 64)
