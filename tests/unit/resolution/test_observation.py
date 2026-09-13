from datetime import UTC, datetime

import pytest

from crystra_evolution.application import ResolutionBoundExceeded, UpstreamContractMismatch
from crystra_evolution.domain.ports import (
    FactPage,
    FactReading,
    TraceNodeReading,
    TracePage,
)
from crystra_evolution.resolution.service import DeliveryObservationResolver, ResolutionLimits


def fact(fact_id: str) -> FactReading:
    return FactReading(
        fact_id=fact_id,
        kind="EVENT_CONTRIBUTION",
        source_identity=f"event:{fact_id}",
        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
        accepted_digest="a" * 64,
        event_name="usage",
        completeness="FINAL",
        availability="AVAILABLE",
        expiry="ACTIVE",
        fields=(("C46", 25),),
        compatibility=(("C42", "money"),),
    )


def node(resource_id: str) -> TraceNodeReading:
    return TraceNodeReading(
        resource_id=resource_id,
        trace_id="a" * 32,
        span_id="b" * 16,
        source_identity=f"span:{'a' * 32}/{'b' * 16}",
        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
        availability="AVAILABLE",
        expiry="ACTIVE",
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        span_status="OK",
        fields=(),
    )


class ReaderStub:
    def __init__(self, *, drift: bool = False, trace_state: str = "AVAILABLE") -> None:
        self.drift = drift
        self.trace_state = trace_state
        self.fact_calls: list[str | None] = []
        self.trace_calls: list[str | None] = []

    async def resolve_facts(self, *, delivery_id: str, limit: int, cursor: str | None) -> FactPage:
        assert delivery_id == "delivery-a"
        assert limit == 200
        self.fact_calls.append(cursor)
        if cursor is None:
            return FactPage((fact("fact-b"),), "next-fact", "facts-a")
        return FactPage((fact("fact-a"),), None, "facts-b" if self.drift else "facts-a")

    async def resolve_traces(
        self, *, delivery_id: str, limit: int, cursor: str | None
    ) -> TracePage:
        assert delivery_id == "delivery-a"
        assert limit == 200
        self.trace_calls.append(cursor)
        return TracePage((node("node-a"),), None, "traces-a", self.trace_state)


@pytest.mark.asyncio
async def test_observation_resolver_fully_traverses_and_binds_route_local_snapshots() -> None:
    reader = ReaderStub()
    result = await DeliveryObservationResolver(reader).resolve(delivery_id="delivery-a")

    assert reader.fact_calls == [None, "next-fact"]
    assert reader.trace_calls == [None]
    assert [item.fact_id for item in result.facts] == ["fact-a", "fact-b"]
    assert [item.resource_id for item in result.trace_nodes] == ["node-a"]
    assert [(item.route, item.route_snapshot) for item in result.evidence_bindings] == [
        ("/v1/evidence/facts", "facts-a"),
        ("/v1/evidence/traces", "traces-a"),
    ]
    assert [item.identity for item in result.input_refs] == ["fact-a", "fact-b", "node-a"]


@pytest.mark.asyncio
async def test_observation_resolver_rejects_route_snapshot_drift() -> None:
    with pytest.raises(UpstreamContractMismatch, match="snapshot"):
        await DeliveryObservationResolver(ReaderStub(drift=True)).resolve(delivery_id="delivery-a")


@pytest.mark.asyncio
async def test_partial_trace_read_set_is_never_claimed_complete() -> None:
    result = await DeliveryObservationResolver(ReaderStub(trace_state="PARTIAL")).resolve(
        delivery_id="delivery-a"
    )

    trace_binding = next(
        item for item in result.evidence_bindings if item.route == "/v1/evidence/traces"
    )
    assert trace_binding.completion_state == "PARTIAL"
    assert trace_binding.error_state == "TRACE_PARTIAL"


@pytest.mark.asyncio
async def test_observation_resolver_rejects_repeated_cursor() -> None:
    class RepeatingReader(ReaderStub):
        async def resolve_facts(
            self, *, delivery_id: str, limit: int, cursor: str | None
        ) -> FactPage:
            return FactPage((fact("fact-a"),), "same", "facts-a")

    with pytest.raises(ResolutionBoundExceeded, match="cursor"):
        await DeliveryObservationResolver(RepeatingReader()).resolve(delivery_id="delivery-a")


@pytest.mark.asyncio
async def test_observation_resolver_enforces_configured_page_cap() -> None:
    with pytest.raises(ResolutionBoundExceeded, match="page"):
        await DeliveryObservationResolver(
            ReaderStub(), limits=ResolutionLimits(max_pages_per_traversal=1)
        ).resolve(delivery_id="delivery-a")
