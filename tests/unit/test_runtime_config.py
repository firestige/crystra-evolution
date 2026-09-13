import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from crystra_evolution.runtime import RuntimeConfiguration, load_configuration


def valid_configuration() -> dict[str, object]:
    return {
        "schema_version": "evolution.runtime@1.0.0",
        "evidence_base_url": "http://evidence:4318",
        "workflow_sources": [
            {"source_id": "official", "repository": "firestige/crystra-workflow-package"}
        ],
        "limits": {
            "max_deliveries_per_side": 500,
            "max_pages_per_traversal": 20,
            "max_input_records_per_side": 100_000,
            "side_deadline_seconds": 120,
            "workflow_request_timeout_seconds": 10,
            "workflow_total_deadline_seconds": 30,
        },
    }


def test_runtime_configuration_is_closed_and_has_no_database_or_credentials() -> None:
    parsed = RuntimeConfiguration.model_validate(valid_configuration())

    assert parsed.evidence_base_url == "http://evidence:4318"
    assert parsed.workflow_sources[0].source_id == "official"
    for forbidden in ("database_url", "credential_ref", "github_token"):
        value = valid_configuration()
        value[forbidden] = "secret"
        with pytest.raises(ValidationError):
            RuntimeConfiguration.model_validate(value)


@pytest.mark.parametrize(
    "url",
    (
        "evidence:4318",
        "ftp://evidence/query",
        "http://user:secret@evidence:4318",
        "http://evidence:4318/path",
        "http://evidence:4318?query=1",
        "http://evidence:4318#fragment",
    ),
)
def test_evidence_base_url_is_an_exact_origin(url: str) -> None:
    value = valid_configuration()
    value["evidence_base_url"] = url

    with pytest.raises(ValidationError):
        RuntimeConfiguration.model_validate(value)


def test_safety_limit_overrides_may_not_raise_published_maxima() -> None:
    for field, value in (
        ("max_deliveries_per_side", 501),
        ("max_pages_per_traversal", 21),
        ("max_input_records_per_side", 100_001),
        ("side_deadline_seconds", 121),
        ("workflow_request_timeout_seconds", 11),
        ("workflow_total_deadline_seconds", 31),
    ):
        candidate = valid_configuration()
        configured_limits = candidate["limits"]
        assert isinstance(configured_limits, dict)
        limits = dict(configured_limits)
        limits[field] = value
        candidate["limits"] = limits
        with pytest.raises(ValidationError):
            RuntimeConfiguration.model_validate(candidate)


def test_load_configuration_requires_an_explicit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CRYSTRA_EVOLUTION_CONFIG", raising=False)
    with pytest.raises(RuntimeError, match="CRYSTRA_EVOLUTION_CONFIG"):
        load_configuration()

    path = tmp_path / "evolution.json"
    path.write_text(json.dumps(valid_configuration()))
    monkeypatch.setenv("CRYSTRA_EVOLUTION_CONFIG", str(path))
    assert load_configuration().schema_version == "evolution.runtime@1.0.0"


def test_crystra_runtime_environment_loads_explicit_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "evolution.json"
    file.write_text(json.dumps(valid_configuration()))
    monkeypatch.delenv("CRYSTRA_EVOLUTION_CONFIG", raising=False)
    monkeypatch.setenv("CRYSTRA_EVOLUTION_CONFIG", str(file))
    assert load_configuration().evidence_base_url == "http://evidence:4318"
