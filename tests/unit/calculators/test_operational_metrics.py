from crystra_evolution.calculators.operational_latency_ms import calculate as latency
from crystra_evolution.calculators.operational_token_usage import calculate as tokens
from crystra_evolution.domain.models import OperationalCallUnit


def call(
    identity: str,
    *,
    duration_ns: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    model: str = "gpt-5",
) -> OperationalCallUnit:
    return OperationalCallUnit(
        call_identity=identity,
        provider="openai",
        model=model,
        role="writer",
        runtime="dsh",
        duration_ns=duration_ns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provenance_refs=(identity,),
    )


def test_latency_groups_exact_model_role_cohorts_and_excludes_missing_duration() -> None:
    result = latency(
        (
            call("a/1", duration_ns=1_000_000, input_tokens=1, output_tokens=2),
            call("a/2", duration_ns=2_000_000, input_tokens=3, output_tokens=4),
            call("a/3", duration_ns=None, input_tokens=5, output_tokens=6),
            call(
                "a/4",
                duration_ns=4_000_000,
                input_tokens=7,
                output_tokens=8,
                model="gpt-5-mini",
            ),
        )
    )

    assert len(result.slices) == 2
    gpt5 = next(item for item in result.slices if item.slice_key["model"] == "gpt-5")
    assert gpt5.value is not None
    assert gpt5.value.value == "3/2"
    assert gpt5.coverage is not None
    assert gpt5.coverage.raw_ratio == "2/3"
    assert gpt5.contributing_count == 2
    assert gpt5.missing_inputs == ("model_call.duration:a/3",)


def test_token_directions_are_independent_and_missing_never_contributes_zero() -> None:
    result = tokens(
        (
            call("a/1", duration_ns=1, input_tokens=10, output_tokens=4),
            call("a/2", duration_ns=1, input_tokens=20, output_tokens=None),
        )
    )

    assert [item.slice_key["direction"] for item in result.slices] == ["input", "output"]
    input_slice, output_slice = result.slices
    assert input_slice.value is not None and input_slice.value.value == 30
    assert input_slice.value.kind == "QUANTITY"
    assert input_slice.coverage is not None
    assert input_slice.coverage.raw_ratio == "1"
    assert output_slice.value is not None and output_slice.value.value == 4
    assert output_slice.coverage is not None
    assert output_slice.coverage.raw_ratio == "1/2"
    assert output_slice.missing_inputs == ("model_call.output_tokens:a/2",)


def test_known_operational_slices_remain_visible_when_measurements_are_missing() -> None:
    missing = call("a/1", duration_ns=None, input_tokens=None, output_tokens=None)

    latency_slice = latency((missing,)).slices[0]
    assert latency_slice.slice_key["model"] == "gpt-5"
    assert latency_slice.value is None
    assert latency_slice.withholding_reason == "MISSING_INPUT"
    assert latency_slice.coverage is not None
    assert latency_slice.coverage.raw_ratio == "0"

    token_slices = tokens((missing,)).slices
    assert [item.slice_key["direction"] for item in token_slices] == ["input", "output"]
    assert all(item.value is None for item in token_slices)
    assert all(
        item.coverage is not None and item.coverage.raw_ratio == "0" for item in token_slices
    )
