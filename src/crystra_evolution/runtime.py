from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Self
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from crystra_evolution.app import create_app
from crystra_evolution.compute import EvolutionComputeService
from crystra_evolution.evidence.client import EvidenceHttpClient
from crystra_evolution.resolution.service import (
    DeliveryObservationResolver,
    ResolutionLimits,
    SelectionPopulationResolver,
)
from crystra_evolution.workflow_sources.archive import ExactWorkflowArchiveValidator
from crystra_evolution.workflow_sources.github import GitHubWorkflowSource
from crystra_evolution.workflow_sources.resolution import (
    WorkflowResolutionConfig,
    WorkflowSourceConfig,
    WorkflowSourceResolver,
)

Identity = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
Repository = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"),
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeWorkflowSource(_ClosedModel):
    source_id: Identity
    repository: Repository


class RuntimeLimits(_ClosedModel):
    max_deliveries_per_side: int = Field(default=500, ge=1, le=500)
    max_pages_per_traversal: int = Field(default=20, ge=1, le=20)
    max_input_records_per_side: int = Field(default=100_000, ge=1, le=100_000)
    side_deadline_seconds: float = Field(default=120, gt=0, le=120)
    workflow_request_timeout_seconds: float = Field(default=10, gt=0, le=10)
    workflow_total_deadline_seconds: float = Field(default=30, gt=0, le=30)


class RuntimeConfiguration(_ClosedModel):
    schema_version: str = Field(pattern=r"^evolution\.runtime@1\.0\.0$")
    evidence_base_url: str
    workflow_sources: tuple[RuntimeWorkflowSource, ...] = Field(min_length=1, max_length=8)
    limits: RuntimeLimits = Field(default_factory=RuntimeLimits)

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        parsed = urlsplit(self.evidence_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("evidence_base_url must be one exact HTTP origin")
        identities = tuple(source.source_id for source in self.workflow_sources)
        if len(set(identities)) != len(identities):
            raise ValueError("Workflow source identities must be unique")
        return self


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def load_configuration() -> RuntimeConfiguration:
    configured_path = os.environ.get("CRYSTRA_EVOLUTION_CONFIG")
    if not configured_path:
        raise RuntimeError("CRYSTRA_EVOLUTION_CONFIG must name an explicit JSON file")
    path = Path(configured_path)
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_strict_object_pairs)
        return RuntimeConfiguration.model_validate(value)
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeError("Evolution runtime configuration is invalid") from error


def build_app(configuration: RuntimeConfiguration) -> FastAPI:
    evidence_transport = httpx.AsyncClient(
        base_url=configuration.evidence_base_url.rstrip("/"), timeout=15
    )
    source_transport = httpx.AsyncClient(
        headers={"accept": "application/vnd.github+json", "user-agent": "crystra-evolution/0.1.0"}
    )
    evidence = EvidenceHttpClient(evidence_transport)
    source_configuration = tuple(
        WorkflowSourceConfig(source.source_id, source.repository)
        for source in configuration.workflow_sources
    )
    workflow_configuration = WorkflowResolutionConfig(
        sources=source_configuration,
        request_timeout_seconds=configuration.limits.workflow_request_timeout_seconds,
        total_deadline_seconds=configuration.limits.workflow_total_deadline_seconds,
    )
    checker = ExactWorkflowArchiveValidator(Path("/opt/workflow-dsl"))
    sources = {
        source.source_id: GitHubWorkflowSource(source, source_transport, checker)
        for source in source_configuration
    }
    workflows = WorkflowSourceResolver(workflow_configuration, sources)
    limits = ResolutionLimits(
        max_deliveries_per_side=configuration.limits.max_deliveries_per_side,
        max_pages_per_traversal=configuration.limits.max_pages_per_traversal,
        max_input_records_per_side=configuration.limits.max_input_records_per_side,
        side_deadline_seconds=configuration.limits.side_deadline_seconds,
    )
    service = EvolutionComputeService(
        SelectionPopulationResolver(evidence, workflows, limits=limits),
        DeliveryObservationResolver(evidence, limits=limits),
        limits=limits,
    )
    app = create_app(service)

    async def close_transports() -> None:
        await evidence_transport.aclose()
        await source_transport.aclose()

    app.router.add_event_handler("shutdown", close_transports)
    return app


def main() -> None:
    uvicorn.run(build_app(load_configuration()), host="0.0.0.0", port=8000, access_log=False)
