from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

ROOT = Path(__file__).parents[2]
VALIDATOR = ROOT / "release" / "validate_image_qualification.py"
PROVENANCE = ROOT / "tests" / "fixtures" / "release" / "platform-provenance.json"
IMAGE_CONFIG = ROOT / "tests" / "fixtures" / "release" / "platform-image.json"
COMMIT = "a" * 40
AUTHORITY = COMMIT
PUBLISHER = "c" * 40
DIGEST = "sha256:" + "d" * 64


def qualification() -> dict[str, object]:
    return {
        "schemaVersion": "crystra.evolution-image-qualification@1.0.0",
        "candidateTag": "crystra-evolution-v0.1.0-rc.1",
        "version": "0.1.0",
        "commit": COMMIT,
        "authority": {
            "repository": "firestige/crystra-evolution",
            "revision": AUTHORITY,
        },
        "publisherRevision": PUBLISHER,
        "image": f"ghcr.io/firestige/crystra-evolution:crystra-evolution-v0.1.0-rc.1@{DIGEST}",
        "ociDigest": DIGEST,
        "source": "https://github.com/firestige/crystra-evolution",
        "platforms": ["linux/amd64", "linux/arm64"],
        "provenance": {"mode": "max", "status": "PASS"},
        "sbom": {"requested": True},
    }


def invoke(
    tmp_path: Path,
    value: dict[str, object],
    provenance: dict[str, object] | None = None,
    image_config: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "release-qualification.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    arguments = [
        sys.executable,
        str(VALIDATOR),
        str(source),
        "--candidate-tag",
        "crystra-evolution-v0.1.0-rc.1",
        "--final-tag",
        "crystra-evolution-v0.1.0",
        "--commit",
        COMMIT,
    ]
    if provenance is not None:
        provenance_path = tmp_path / "provenance.json"
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        arguments.extend(["--provenance", str(provenance_path)])
    if image_config is not None:
        image_path = tmp_path / "image.json"
        image_path.write_text(json.dumps(image_config), encoding="utf-8")
        arguments.extend(["--image-config", str(image_path)])
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
    )


def test_exact_candidate_qualification_is_accepted(tmp_path: Path) -> None:
    completed = invoke(tmp_path, qualification())

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "authorityRevision": AUTHORITY,
        "ociDigest": DIGEST,
        "status": "PASS",
    }


def test_candidate_qualification_rejects_any_open_or_mutable_input(tmp_path: Path) -> None:
    mutations: dict[str, Callable[[dict[str, object]], None]] = {
        "unknown-key": lambda value: value.update({"extra": True}),
        "mutable-image": lambda value: value.update(
            {"image": "ghcr.io/firestige/crystra-evolution:latest"}
        ),
        "wrong-platforms": lambda value: value.update({"platforms": ["linux/amd64"]}),
        "unqualified-provenance": lambda value: value.update(
            {"provenance": {"mode": "min", "status": "PASS"}}
        ),
        "wrong-product": lambda value: value.update({"commit": "e" * 40}),
    }
    for name, mutate in mutations.items():
        value = qualification()
        mutate(value)
        completed = invoke(tmp_path, value)
        assert completed.returncode != 0, name


def platform_provenance() -> dict[str, object]:
    value = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def platform_image() -> dict[str, object]:
    value = json.loads(IMAGE_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def provenance_arguments(value: dict[str, object], platform: str) -> dict[str, str]:
    current: object = value[platform]
    for key in (
        "SLSA",
        "buildDefinition",
        "externalParameters",
        "request",
        "root",
        "request",
        "args",
    ):
        assert isinstance(current, dict)
        current = current[key]
    assert isinstance(current, dict)
    return cast(dict[str, str], current)


def test_platform_keyed_provenance_accepts_both_required_platforms(tmp_path: Path) -> None:
    completed = invoke(tmp_path, qualification(), platform_provenance(), platform_image())

    assert completed.returncode == 0


def test_platform_keyed_provenance_rejects_missing_or_mismatched_attestation(
    tmp_path: Path,
) -> None:
    def remove_arm64(value: dict[str, object]) -> None:
        value.pop("linux/arm64")

    def mismatch_revision(value: dict[str, object]) -> None:
        provenance_arguments(value, "linux/arm64")["vcs:revision"] = "e" * 40

    def mismatch_source(value: dict[str, object]) -> None:
        provenance_arguments(value, "linux/amd64")["vcs:source"] = (
            "https://example.invalid/untrusted"
        )

    def mismatch_product(value: dict[str, object]) -> None:
        provenance_arguments(value, "linux/amd64")["build-arg:CRYSTRA_RELEASE_REVISION"] = "e" * 40

    mutations: dict[str, Callable[[dict[str, object]], None]] = {
        "missing-arm64": remove_arm64,
        "mismatched-revision": mismatch_revision,
        "mismatched-source": mismatch_source,
        "mismatched-product": mismatch_product,
    }
    for name, mutate in mutations.items():
        value = platform_provenance()
        mutate(value)
        completed = invoke(tmp_path, qualification(), value, platform_image())
        assert completed.returncode != 0, name


def test_platform_keyed_image_accepts_both_required_platform_labels(tmp_path: Path) -> None:
    completed = invoke(tmp_path, qualification(), platform_provenance(), platform_image())

    assert completed.returncode == 0


def test_platform_keyed_image_rejects_missing_or_mismatched_platform_labels(
    tmp_path: Path,
) -> None:
    def labels(value: dict[str, object], platform: str) -> dict[str, str]:
        selected = value[platform]
        assert isinstance(selected, dict)
        config = selected["config"]
        assert isinstance(config, dict)
        found = config["Labels"]
        assert isinstance(found, dict)
        return cast(dict[str, str], found)

    def remove_arm64(value: dict[str, object]) -> None:
        value.pop("linux/arm64")

    def mismatch_source(value: dict[str, object]) -> None:
        labels(value, "linux/amd64")["org.opencontainers.image.source"] = (
            "https://example.invalid/untrusted"
        )

    def mismatch_revision(value: dict[str, object]) -> None:
        labels(value, "linux/arm64")["org.opencontainers.image.revision"] = "e" * 40

    mutations: dict[str, Callable[[dict[str, object]], None]] = {
        "missing-arm64": remove_arm64,
        "mismatched-source": mismatch_source,
        "mismatched-revision": mismatch_revision,
    }
    for name, mutate in mutations.items():
        value = platform_image()
        mutate(value)
        completed = invoke(tmp_path, qualification(), platform_provenance(), value)
        assert completed.returncode != 0, name
