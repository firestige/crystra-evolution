from typing import Any

import httpx
import pytest

from crystra_evolution.application import UpstreamContractMismatch
from crystra_evolution.evidence.client import EvidenceHttpClient


def fact_envelope() -> dict[str, Any]:
    return {
        "contract": {"name": "evidence.query", "revision": "0.1.0"},
        "observation_profile": "1.0.0",
        "read_model_revision": "1.0.0",
        "snapshot": "facts-snapshot-a",
        "items": [
            {
                "id": "fact-usage-a",
                "kind": "EVENT_CONTRIBUTION",
                "source": {"kind": "EVENT", "event_id": "usage-a"},
                "recorded_at": "2026-08-28T01:00:00.000000Z",
                "provenance": {
                    "accepted_digest": "a" * 64,
                    "profile_version": "1.0.0",
                    "family_schema": "implementation@1",
                    "owner_key": ["usage", "usage-a"],
                },
                "compatibility": {
                    "family_schema": "implementation@1",
                    "event_name": "usage",
                    "completeness": "FINAL",
                    "dimensions": [
                        {"field": "C42", "value": "money"},
                        {"field": "C43", "value": "USD"},
                        {"field": "C44", "value": "provider"},
                        {"field": "C45", "value": "invoice-a"},
                    ],
                },
                "truth": {
                    "completeness": "FINAL",
                    "availability": "AVAILABLE",
                    "expiry": "ACTIVE",
                    "expires_at": "2027-08-28T01:00:00.000000Z",
                },
                "fields": [
                    {"field": "C42", "value": "money"},
                    {"field": "C43", "value": "USD"},
                    {"field": "C44", "value": "provider"},
                    {"field": "C45", "value": "invoice-a"},
                    {"field": "C46", "value": 25},
                ],
                "relationships": [],
            }
        ],
        "next_cursor": "next-facts",
    }


def finding_fix_envelope() -> dict[str, Any]:
    payload = fact_envelope()
    item = payload["items"][0]
    item["id"] = "fact-fix-a"
    item["kind"] = "FINDING_FIX"
    item["relationships"] = [
        {
            "kind": "FINDING_FIX",
            "from": {"kind": "FIX", "key": ["fix-a"]},
            "to": {
                "kind": "FINDING_TARGET",
                "key": ["finding-a", "scope-a", "SECTION", "section-a", None],
            },
        }
    ]
    return payload


def trace_envelope() -> dict[str, Any]:
    return {
        "contract": {"name": "evidence.query", "revision": "0.1.0"},
        "observation_profile": "1.0.0",
        "read_model_revision": "1.0.0",
        "snapshot": "traces-snapshot-a",
        "items": [
            {
                "id": "node-a",
                "trace_id": "a" * 32,
                "kind": "NODE",
                "source": {"kind": "SPAN", "trace_id": "a" * 32, "span_id": "b" * 16},
                "recorded_at": "2026-08-28T01:00:00.000000Z",
                "truth": {
                    "completeness": None,
                    "availability": "AVAILABLE",
                    "expiry": "ACTIVE",
                    "expires_at": "2026-09-28T01:00:00.000000Z",
                },
                "node": {
                    "span_id": "b" * 16,
                    "span_name": "chat",
                    "span_kind": "CLIENT",
                    "start_time_unix_nano": "1000000000",
                    "end_time_unix_nano": "2500000000",
                    "span_status": "OK",
                    "span_flags": 1,
                    "trace_state": None,
                    "fields": [
                        {"field": "C30", "value": "writer"},
                        {"field": "C57", "value": "gpt-5"},
                        {"field": "gen_ai.usage.input_tokens", "value": 10},
                    ],
                },
                "edge": None,
            }
        ],
        "next_cursor": None,
        "trace_state": "AVAILABLE",
        "trace_summaries": [{"trace_id": "a" * 32, "state": "AVAILABLE"}],
    }


@pytest.mark.asyncio
async def test_reads_exact_delivery_scoped_fact_and_trace_pages() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["delivery_id"] == "delivery-a"
        assert request.url.params["limit"] == "200"
        if request.url.path.endswith("/facts"):
            assert request.url.params["cursor"] == "facts-cursor"
            return httpx.Response(200, json=fact_envelope())
        assert "cursor" not in request.url.params
        return httpx.Response(200, json=trace_envelope())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        client = EvidenceHttpClient(transport)
        facts = await client.resolve_facts(
            delivery_id="delivery-a", limit=200, cursor="facts-cursor"
        )
        traces = await client.resolve_traces(delivery_id="delivery-a", limit=200, cursor=None)

    assert facts.route_snapshot == "facts-snapshot-a"
    assert facts.next_cursor == "next-facts"
    assert facts.facts[0].field_map["C46"] == 25
    assert facts.facts[0].event_name == "usage"
    assert facts.facts[0].compatibility_map == {
        "C42": "money",
        "C43": "USD",
        "C44": "provider",
        "C45": "invoice-a",
    }
    assert facts.facts[0].source_identity == "event:usage-a"
    assert traces.route_snapshot == "traces-snapshot-a"
    assert traces.trace_state == "AVAILABLE"
    assert traces.nodes[0].start_time_unix_nano == 1_000_000_000
    assert traces.nodes[0].end_time_unix_nano == 2_500_000_000
    assert traces.nodes[0].field_map["gen_ai.usage.input_tokens"] == 10


@pytest.mark.asyncio
async def test_rejects_contract_drift_instead_of_coercing_observation_data() -> None:
    payload = fact_envelope()
    payload["contract"]["revision"] = "9.9.9"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        with pytest.raises(UpstreamContractMismatch):
            await EvidenceHttpClient(transport).resolve_facts(
                delivery_id="delivery-a", limit=200, cursor=None
            )


@pytest.mark.asyncio
async def test_preserves_typed_finding_fix_relationship() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=finding_fix_envelope())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://evidence.test"
    ) as transport:
        page = await EvidenceHttpClient(transport).resolve_facts(
            delivery_id="delivery-a", limit=200, cursor=None
        )

    relationship = page.facts[0].relationships[0]
    assert relationship.kind == "FINDING_FIX"
    assert relationship.source.kind == "FIX"
    assert relationship.source.key == ("fix-a",)
    assert relationship.target.kind == "FINDING_TARGET"
    assert relationship.target.key[-1] is None
