from datetime import UTC, datetime

from crystra_evolution.domain.ports import TraceNodeReading
from crystra_evolution.normalization.operational import normalize_model_calls


def node(
    identity: str,
    fields: tuple[tuple[str, str | int], ...],
    *,
    start: int = 1_000_000,
    end: int = 3_000_000,
) -> TraceNodeReading:
    return TraceNodeReading(
        resource_id=f"node:{identity}",
        trace_id=identity.split("/")[0],
        span_id=identity.split("/")[1],
        source_identity=f"span:{identity}",
        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
        availability="AVAILABLE",
        expiry="ACTIVE",
        start_time_unix_nano=start,
        end_time_unix_nano=end,
        span_status="OK",
        fields=fields,
    )


def test_normalizes_exact_otel_model_tuple_duration_and_token_fields() -> None:
    calls = normalize_model_calls(
        (
            node(
                f"{'a' * 32}/{'b' * 16}",
                (
                    ("gen_ai.provider.name", "openai"),
                    ("C57", "gpt-5"),
                    ("C30", "writer"),
                    ("C06", "dsh"),
                    ("gen_ai.usage.input_tokens", 11),
                    ("gen_ai.usage.output_tokens", 7),
                ),
            ),
        )
    )

    assert len(calls) == 1
    assert calls[0].cohort == ("openai", "gpt-5", "writer", "dsh")
    assert calls[0].duration_ns == 2_000_000
    assert calls[0].input_tokens == 11
    assert calls[0].output_tokens == 7


def test_invalid_or_expired_measurements_remain_missing_not_zero() -> None:
    trace = node(
        f"{'a' * 32}/{'b' * 16}",
        (("gen_ai.provider.name", "openai"), ("C57", "gpt-5"), ("C30", "writer"), ("C06", "dsh")),
        start=3,
        end=2,
    )
    calls = normalize_model_calls((trace,))
    assert calls[0].duration_ns is None
    assert calls[0].input_tokens is None
    assert calls[0].output_tokens is None


def test_expired_trace_node_cannot_leak_token_measurements() -> None:
    trace = node(
        f"{'a' * 32}/{'b' * 16}",
        (
            ("gen_ai.provider.name", "openai"),
            ("C57", "gpt-5"),
            ("C30", "writer"),
            ("C06", "dsh"),
            ("gen_ai.usage.input_tokens", 11),
            ("gen_ai.usage.output_tokens", 7),
        ),
    )
    object.__setattr__(trace, "expiry", "EXPIRED")

    call = normalize_model_calls((trace,))[0]

    assert call.duration_ns is None
    assert call.input_tokens is None
    assert call.output_tokens is None
