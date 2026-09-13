from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from crystra_evolution.workflow_sources.resolution import (
    SourceFailure,
    WorkflowCandidate,
    WorkflowSourceConfig,
)

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_RELEASE_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTOR_BYTES = 64 * 1024
PAGE_SIZE = 100
MAX_RELEASE_PAGES = 10


class WorkflowArchiveValidator(Protocol):
    async def validate(
        self,
        *,
        archive: bytes,
        archive_digest: str,
        package_name: str,
        exact_version: str,
    ) -> WorkflowCandidate: ...


@dataclass(frozen=True, slots=True)
class _Asset:
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class _Release:
    tag: str
    draft: bool
    assets: tuple[_Asset, ...]


@dataclass(frozen=True, slots=True)
class _Descriptor:
    package_digest: str
    archive_digest: str
    archive_bytes: int
    provenance_name: str | None = None
    provenance_digest: str | None = None
    contract_revision: str | None = None


def _strict_json(body: bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    return json.loads(body, object_pairs_hook=object_pairs)


def _https_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def _release(value: object) -> _Release | None:
    if not isinstance(value, dict):
        return None
    tag = value.get("tag_name")
    draft = value.get("draft")
    assets = value.get("assets")
    if not isinstance(tag, str) or not isinstance(draft, bool) or not isinstance(assets, list):
        return None
    parsed_assets: list[_Asset] = []
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return None
        url = _https_url(item.get("browser_download_url"))
        if url is None:
            return None
        parsed_assets.append(_Asset(item["name"], url))
    return _Release(tag=tag, draft=draft, assets=tuple(parsed_assets))


def _one_asset(assets: tuple[_Asset, ...], name: str) -> _Asset | None:
    matches = tuple(item for item in assets if item.name == name)
    return matches[0] if len(matches) == 1 else None


def _object(value: object, keys: set[str]) -> dict[str, Any] | None:
    return value if isinstance(value, dict) and set(value) == keys else None


def _descriptor(
    body: bytes,
    *,
    package_name: str,
    exact_version: str,
    archive_name: str,
    checksum_name: str,
    provenance_name: str | None,
) -> _Descriptor | None:
    try:
        value = _strict_json(body)
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    schema_version = value.get("schemaVersion")
    keys = (
        {"schemaVersion", "revision", "tag", "package", "archive", "checksum"}
        if schema_version == "workflow-package.package-release@1.0.0"
        else {"schemaVersion", "tag", "package", "archive", "checksum", "provenance", "contract"}
    )
    root = _object(value, keys)
    if root is None:
        return None
    package = _object(root["package"], {"name", "version", "digest"})
    archive = _object(root["archive"], {"name", "sha256", "bytes"})
    checksum = _object(root["checksum"], {"name"})

    def digest_pattern(item: object) -> bool:
        return (
            isinstance(item, str)
            and len(item) == 71
            and item.startswith("sha256:")
            and all(character in "0123456789abcdef" for character in item[7:])
        )

    valid = (
        root["schemaVersion"]
        in {
            "workflow-package.package-release@1.0.0",
            "workflow-package.package-release@2.0.0",
        }
        and root["tag"] == f"workflow-package/{package_name}/v{exact_version}"
        and (
            root["schemaVersion"] == "workflow-package.package-release@2.0.0"
            or (
                isinstance(root["revision"], str)
                and len(root["revision"]) == 40
                and all(character in "0123456789abcdef" for character in root["revision"])
            )
        )
        and package is not None
        and package["name"] == package_name
        and package["version"] == exact_version
        and digest_pattern(package["digest"])
        and archive is not None
        and archive["name"] == archive_name
        and digest_pattern(archive["sha256"])
        and isinstance(archive["bytes"], int)
        and not isinstance(archive["bytes"], bool)
        and 1 <= archive["bytes"] <= MAX_ARCHIVE_BYTES
        and checksum is not None
        and checksum["name"] == checksum_name
    )
    if not valid or package is None or archive is None:
        return None
    if root["schemaVersion"] == "workflow-package.package-release@1.0.0":
        return _Descriptor(package["digest"], archive["sha256"], archive["bytes"])
    provenance = _object(root["provenance"], {"name", "sha256"})
    contract = _object(root["contract"], {"repository", "revision", "minVersion", "maxVersion"})
    versions = contract is not None and all(
        isinstance(contract[key], str) and re.fullmatch(r"\d+\.\d+\.\d+", contract[key]) is not None
        for key in ("minVersion", "maxVersion")
    )
    if (
        provenance is None
        or provenance_name is None
        or provenance["name"] != provenance_name
        or not digest_pattern(provenance["sha256"])
        or contract is None
        or contract["repository"] != "firestige/crystra-contracts"
        or not isinstance(contract["revision"], str)
        or len(contract["revision"]) != 40
        or not all(character in "0123456789abcdef" for character in contract["revision"])
        or not versions
    ):
        return None
    return _Descriptor(
        package["digest"],
        archive["sha256"],
        archive["bytes"],
        provenance["name"],
        provenance["sha256"],
        contract["revision"],
    )


def _valid_provenance(
    body: bytes,
    *,
    repository: str,
    archive_name: str,
    archive_digest: str,
    contract_revision: str,
) -> bool:
    try:
        value = _strict_json(body)
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return False
    root = _object(value, {"schemaVersion", "subject", "source", "contract", "builder"})
    if root is None or root["schemaVersion"] != "workflow-package.provenance@1.0.0":
        return False
    subject = _object(root["subject"], {"name", "sha256"})
    source = _object(root["source"], {"repository", "revision"})
    contract = _object(root["contract"], {"repository", "revision"})
    builder = _object(root["builder"], {"workflow"})
    return bool(
        subject is not None
        and subject["name"] == archive_name
        and subject["sha256"] == archive_digest
        and source is not None
        and source["repository"] == repository
        and isinstance(source["revision"], str)
        and len(source["revision"]) == 40
        and all(character in "0123456789abcdef" for character in source["revision"])
        and contract is not None
        and contract["repository"] == "firestige/crystra-contracts"
        and contract["revision"] == contract_revision
        and builder is not None
        and builder["workflow"] == ".github/workflows/release-candidate.yml"
    )


class GitHubWorkflowSource:
    def __init__(
        self,
        configuration: WorkflowSourceConfig,
        transport: httpx.AsyncClient,
        validator: WorkflowArchiveValidator,
    ) -> None:
        self._configuration = configuration
        self._transport = transport
        self._validator = validator

    async def _bytes(
        self,
        url: str,
        *,
        limit: int,
        timeout_seconds: float,
        missing_is_not_found: bool = False,
    ) -> bytes:
        try:
            async with self._transport.stream("GET", url, timeout=timeout_seconds) as response:
                if response.status_code == 404 and missing_is_not_found:
                    raise SourceFailure("NOT_FOUND")
                if not 200 <= response.status_code < 300:
                    raise SourceFailure("SOURCE_UNAVAILABLE")
                chunks: list[bytes] = []
                length = 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > limit:
                        raise ValueError("bounded response exceeded")
                    chunks.append(chunk)
                return b"".join(chunks)
        except SourceFailure:
            raise
        except httpx.HTTPError as error:
            raise SourceFailure("SOURCE_UNAVAILABLE") from error

    async def _fetch_historical_exact(
        self,
        releases: list[_Release],
        *,
        package_name: str,
        exact_version: str,
        timeout_seconds: float,
    ) -> WorkflowCandidate:
        matches = tuple(item for item in releases if item.tag == exact_version)
        if not matches:
            raise SourceFailure("NOT_FOUND")
        if len(matches) != 1:
            raise SourceFailure("INVALID_DESCRIPTOR")
        selected = matches[0]
        descriptor_asset = _one_asset(
            selected.assets, f"workflow-package-release-{exact_version}.json"
        )
        if descriptor_asset is None:
            raise SourceFailure("INVALID_DESCRIPTOR")
        descriptor_body = await self._bytes(
            descriptor_asset.url,
            limit=MAX_DESCRIPTOR_BYTES,
            timeout_seconds=timeout_seconds,
        )
        try:
            value = _strict_json(descriptor_body)
        except (ValueError, UnicodeError, json.JSONDecodeError) as error:
            raise SourceFailure("INVALID_DESCRIPTOR") from error
        root = _object(value, {"schemaVersion", "revision", "tag", "assets"})
        if (
            root is None
            or root["schemaVersion"] != "workflow-package.release@1.0.0"
            or root["tag"] != exact_version
            or not isinstance(root["revision"], str)
            or re.fullmatch(r"[a-f0-9]{40}", root["revision"]) is None
            or not isinstance(root["assets"], list)
        ):
            raise SourceFailure("INVALID_DESCRIPTOR")
        records = [
            item
            for item in root["assets"]
            if isinstance(item, dict) and item.get("package") == package_name
        ]
        if len(records) != 1:
            raise SourceFailure("NOT_FOUND" if not records else "INVALID_DESCRIPTOR")
        record = _object(
            records[0], {"name", "sha256", "bytes", "package", "version", "packageDigest"}
        )
        if (
            record is None
            or record["version"] != exact_version
            or not isinstance(record["name"], str)
            or record["name"] != f"workflow-package-{package_name}-{exact_version}.tar.gz"
            or not isinstance(record["sha256"], str)
            or re.fullmatch(r"sha256:[a-f0-9]{64}", record["sha256"]) is None
            or not isinstance(record["packageDigest"], str)
            or re.fullmatch(r"sha256:[a-f0-9]{64}", record["packageDigest"]) is None
            or not isinstance(record["bytes"], int)
            or isinstance(record["bytes"], bool)
            or not 1 <= record["bytes"] <= MAX_ARCHIVE_BYTES
        ):
            raise SourceFailure("INVALID_DESCRIPTOR")
        archive_asset = _one_asset(selected.assets, record["name"])
        if archive_asset is None:
            raise SourceFailure("INVALID_DESCRIPTOR")
        try:
            archive = await self._bytes(
                archive_asset.url,
                limit=MAX_ARCHIVE_BYTES,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as error:
            raise SourceFailure("INVALID_ARCHIVE") from error
        archive_digest = "sha256:" + sha256(archive).hexdigest()
        if not archive or len(archive) != record["bytes"] or archive_digest != record["sha256"]:
            raise SourceFailure("INVALID_ARCHIVE")
        try:
            candidate = await self._validator.validate(
                archive=archive,
                archive_digest=archive_digest,
                package_name=package_name,
                exact_version=exact_version,
            )
        except SourceFailure:
            raise
        except Exception as error:
            raise SourceFailure("INVALID_WORKFLOW") from error
        if candidate.package_digest != record["packageDigest"]:
            raise SourceFailure("INVALID_DESCRIPTOR")
        return candidate

    async def fetch_exact(
        self, *, package_name: str, exact_version: str, timeout_seconds: float
    ) -> WorkflowCandidate:
        releases: list[_Release] = []
        base = f"https://api.github.com/repos/{self._configuration.repository}/releases"
        for page in range(1, MAX_RELEASE_PAGES + 1):
            try:
                body = await self._bytes(
                    f"{base}?per_page={PAGE_SIZE}&page={page}",
                    limit=MAX_RELEASE_RESPONSE_BYTES,
                    timeout_seconds=timeout_seconds,
                    missing_is_not_found=True,
                )
                values = _strict_json(body)
            except SourceFailure:
                raise
            except (ValueError, UnicodeError, json.JSONDecodeError) as error:
                raise SourceFailure("INVALID_DESCRIPTOR") from error
            if not isinstance(values, list):
                raise SourceFailure("INVALID_DESCRIPTOR")
            parsed = tuple(_release(value) for value in values)
            if any(value is None for value in parsed):
                raise SourceFailure("INVALID_DESCRIPTOR")
            releases.extend(value for value in parsed if value is not None and not value.draft)
            if len(values) < PAGE_SIZE:
                break
            if page == MAX_RELEASE_PAGES:
                raise SourceFailure("SOURCE_UNAVAILABLE")

        tag = f"workflow-package/{package_name}/v{exact_version}"
        matches = tuple(item for item in releases if item.tag == tag)
        if not matches:
            return await self._fetch_historical_exact(
                releases,
                package_name=package_name,
                exact_version=exact_version,
                timeout_seconds=timeout_seconds,
            )
        if len(matches) != 1 or len(matches[0].assets) not in {3, 4}:
            raise SourceFailure("INVALID_DESCRIPTOR")
        selected = matches[0]
        archive_name = f"workflow-package-{package_name}-{exact_version}.tar.gz"
        descriptor_name = f"workflow-package-{package_name}-{exact_version}.json"
        checksum_name = f"{archive_name}.sha256"
        provenance_name = f"workflow-package-{package_name}-{exact_version}.provenance.json"
        archive_asset = _one_asset(selected.assets, archive_name)
        descriptor_asset = _one_asset(selected.assets, descriptor_name)
        checksum_asset = _one_asset(selected.assets, checksum_name)
        provenance_asset = _one_asset(selected.assets, provenance_name)
        if archive_asset is None or descriptor_asset is None or checksum_asset is None:
            raise SourceFailure("INVALID_DESCRIPTOR")
        if len(selected.assets) == 4 and provenance_asset is None:
            raise SourceFailure("INVALID_DESCRIPTOR")
        try:
            descriptor_body = await self._bytes(
                descriptor_asset.url,
                limit=MAX_DESCRIPTOR_BYTES,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as error:
            raise SourceFailure("INVALID_DESCRIPTOR") from error
        metadata = _descriptor(
            descriptor_body,
            package_name=package_name,
            exact_version=exact_version,
            archive_name=archive_name,
            checksum_name=checksum_name,
            provenance_name=provenance_asset.name if provenance_asset is not None else None,
        )
        if metadata is None:
            raise SourceFailure("INVALID_DESCRIPTOR")
        if metadata.provenance_name is not None:
            if (
                provenance_asset is None
                or metadata.provenance_digest is None
                or metadata.contract_revision is None
            ):
                raise SourceFailure("INVALID_DESCRIPTOR")
            try:
                provenance_body = await self._bytes(
                    provenance_asset.url,
                    limit=MAX_DESCRIPTOR_BYTES,
                    timeout_seconds=timeout_seconds,
                )
            except ValueError as error:
                raise SourceFailure("INVALID_DESCRIPTOR") from error
            actual_provenance_digest = "sha256:" + sha256(provenance_body).hexdigest()
            if actual_provenance_digest != metadata.provenance_digest:
                raise SourceFailure("CHECKSUM_MISMATCH")
            if not _valid_provenance(
                provenance_body,
                repository=self._configuration.repository,
                archive_name=archive_name,
                archive_digest=metadata.archive_digest,
                contract_revision=metadata.contract_revision,
            ):
                raise SourceFailure("INVALID_DESCRIPTOR")
        try:
            checksum = await self._bytes(
                checksum_asset.url, limit=1024, timeout_seconds=timeout_seconds
            )
        except ValueError as error:
            raise SourceFailure("CHECKSUM_MISMATCH") from error
        expected_checksum = f"{metadata.archive_digest[7:]}  {archive_name}\n".encode()
        if checksum != expected_checksum:
            raise SourceFailure("CHECKSUM_MISMATCH")
        try:
            archive = await self._bytes(
                archive_asset.url,
                limit=MAX_ARCHIVE_BYTES,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as error:
            raise SourceFailure("INVALID_ARCHIVE") from error
        actual_digest = "sha256:" + sha256(archive).hexdigest()
        if (
            not archive
            or len(archive) != metadata.archive_bytes
            or actual_digest != metadata.archive_digest
        ):
            raise SourceFailure("INVALID_ARCHIVE")
        try:
            candidate = await self._validator.validate(
                archive=archive,
                archive_digest=actual_digest,
                package_name=package_name,
                exact_version=exact_version,
            )
        except SourceFailure:
            raise
        except Exception as error:
            raise SourceFailure("INVALID_WORKFLOW") from error
        if candidate.package_digest != metadata.package_digest:
            raise SourceFailure("INVALID_DESCRIPTOR")
        return candidate
