from __future__ import annotations

import asyncio
import json
import subprocess
import tarfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from crystra_evolution.workflow_sources.resolution import (
    SourceFailure,
    WorkflowCandidate,
    WorkflowCandidateRole,
)

MAX_ARCHIVE_MEMBERS = 4096
MAX_EXPANDED_BYTES = 512 * 1024 * 1024


def _strict_json(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    value = json.loads(path.read_bytes(), object_pairs_hook=object_pairs)
    if not isinstance(value, dict):
        raise ValueError("Workflow document must be an object")
    return value


def _safe_members(archive: tarfile.TarFile) -> tuple[tarfile.TarInfo, ...]:
    members = tuple(archive.getmembers())
    if not members or len(members) > MAX_ARCHIVE_MEMBERS:
        raise ValueError("archive member bound exceeded")
    expanded = 0
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.issym()
            or member.islnk()
            or not (member.isfile() or member.isdir())
        ):
            raise ValueError("unsafe archive member")
        expanded += member.size
        if expanded > MAX_EXPANDED_BYTES:
            raise ValueError("expanded archive bound exceeded")
    return members


def _document(root: Path, relative: object) -> dict[str, Any]:
    if not isinstance(relative, str):
        raise ValueError("document path is invalid")
    target = (root / relative).resolve()
    if root.resolve() not in target.parents:
        raise ValueError("document path escapes Package")
    return _strict_json(target)


def _locate_package(material: Path) -> Path:
    roots = (material, *(entry for entry in material.iterdir() if entry.is_dir()))
    candidates = {
        candidate.parent
        for root in roots
        for candidate in (root / "package.json", root / "definition/package.json")
        if candidate.is_file()
    }
    if len(candidates) != 1:
        raise ValueError("archive must contain one Package")
    return candidates.pop()


class ExactWorkflowArchiveValidator:
    def __init__(self, checker_root: Path, *, node_binary: str = "node") -> None:
        self._checker_root = checker_root
        self._node_binary = node_binary

    async def validate(
        self,
        *,
        archive: bytes,
        archive_digest: str,
        package_name: str,
        exact_version: str,
    ) -> WorkflowCandidate:
        return await asyncio.to_thread(
            self._validate_sync,
            archive=archive,
            archive_digest=archive_digest,
            package_name=package_name,
            exact_version=exact_version,
        )

    def _validate_sync(
        self,
        *,
        archive: bytes,
        archive_digest: str,
        package_name: str,
        exact_version: str,
    ) -> WorkflowCandidate:
        if "sha256:" + sha256(archive).hexdigest() != archive_digest:
            raise SourceFailure("INVALID_ARCHIVE")
        try:
            with TemporaryDirectory(prefix="crystra-evolution-workflow-") as temporary:
                temporary_root = Path(temporary)
                archive_path = temporary_root / "candidate.tar.gz"
                archive_path.write_bytes(archive)
                material = temporary_root / "material"
                material.mkdir()
                with tarfile.open(archive_path, mode="r:gz") as opened:
                    members = _safe_members(opened)
                    opened.extractall(material, members=members, filter="data")
                package_root = _locate_package(material)
                checker = self._checker_root / "generated/tools/check-example.cjs"
                checked = subprocess.run(
                    [self._node_binary, str(checker), str(package_root)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if checked.returncode != 0:
                    raise ValueError("Workflow DSL checker rejected archive")
                return self._candidate(
                    package_root,
                    archive_digest=archive_digest,
                    package_name=package_name,
                    exact_version=exact_version,
                )
        except SourceFailure:
            raise
        except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
            raise SourceFailure("INVALID_WORKFLOW") from error

    @staticmethod
    def _candidate(
        root: Path, *, archive_digest: str, package_name: str, exact_version: str
    ) -> WorkflowCandidate:
        package = _strict_json(root / "package.json")
        coordinate = package["package"]
        documents = package["documents"]
        if coordinate["name"] != package_name or coordinate["version"] != exact_version:
            raise ValueError("Package coordinate mismatch")
        snapshot = _strict_json(root / "snapshot.json")["snapshot"]
        actions = _document(root, documents["actions"])["actions"]
        routes = _document(root, documents["routes"])["routes"]
        action_by_id = {item["id"]: item for item in actions}
        route_by_id = {item["id"]: item for item in routes}
        snapshot_resources = {item["id"]: item for item in snapshot["resources"]}
        roles: dict[str, WorkflowCandidateRole] = {}
        for binding in snapshot["routeBindings"]:
            action = action_by_id[binding["action"]]
            role_id = action["responsibleAuthority"]["role"]
            route = route_by_id[binding["route"]]
            prompt_identity = route["resources"]["rolePrompt"]["id"]
            prompt_digest = snapshot_resources[prompt_identity]["contentIdentity"]
            candidate_role = WorkflowCandidateRole(role_id, prompt_identity, prompt_digest)
            prior = roles.get(role_id)
            if prior is not None and prior != candidate_role:
                raise ValueError("Role has conflicting prompt identity")
            roles[role_id] = candidate_role
        definition = snapshot["definition"]
        return WorkflowCandidate(
            package_name=package_name,
            exact_package_version=exact_version,
            package_digest=coordinate["digest"],
            workflow_id=definition["id"],
            workflow_version=definition["version"],
            snapshot_id=snapshot["id"],
            snapshot_digest=snapshot["digest"],
            archive_digest=archive_digest,
            roles=tuple(roles[key] for key in sorted(roles, key=str.encode)),
        )
