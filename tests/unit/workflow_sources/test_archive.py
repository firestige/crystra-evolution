import asyncio
import tarfile
import time
from hashlib import sha256
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from crystra_evolution.workflow_sources.archive import ExactWorkflowArchiveValidator
from crystra_evolution.workflow_sources.resolution import SourceFailure

REPOSITORY = Path(__file__).parents[3]
CHECKER = REPOSITORY / ".crystra-inputs/contracts/workflow-dsl-2-candidate"
MINIMAL = CHECKER / "generated/examples/minimal"


def archive_minimal(tmp_path: Path) -> bytes:
    target = tmp_path / "minimal.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(MINIMAL, arcname="minimal")
    return target.read_bytes()


@pytest.mark.asyncio
async def test_exact_checker_yields_manifest_comparable_candidate(tmp_path: Path) -> None:
    archive = archive_minimal(tmp_path)

    candidate = await ExactWorkflowArchiveValidator(CHECKER).validate(
        archive=archive,
        archive_digest="sha256:" + sha256(archive).hexdigest(),
        package_name="example-minimal-review",
        exact_version="1.0.0",
    )

    assert candidate.workflow_id == "minimal-review"
    assert candidate.workflow_version == "1.0.0"
    assert [role.role_id for role in candidate.roles] == ["role.facilitator", "role.reviewer"]
    assert all(role.role_prompt_digest.startswith("sha256:") for role in candidate.roles)


@pytest.mark.asyncio
async def test_checker_work_does_not_block_the_asgi_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = archive_minimal(tmp_path)

    def slow_rejection(*args: object, **kwargs: object) -> CompletedProcess[bytes]:
        time.sleep(0.05)
        return CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr("crystra_evolution.workflow_sources.archive.subprocess.run", slow_rejection)
    validation = asyncio.create_task(
        ExactWorkflowArchiveValidator(CHECKER).validate(
            archive=archive,
            archive_digest="sha256:" + sha256(archive).hexdigest(),
            package_name="example-minimal-review",
            exact_version="1.0.0",
        )
    )

    started = time.monotonic()
    await asyncio.wait_for(asyncio.sleep(0.001), timeout=0.02)
    assert time.monotonic() - started < 0.02
    with pytest.raises(SourceFailure, match="INVALID_WORKFLOW"):
        await validation
