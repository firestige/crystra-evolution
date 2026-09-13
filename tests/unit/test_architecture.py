import ast
import dataclasses
import importlib
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crystra_evolution.calculators.protocol import Calculator
from crystra_evolution.domain.models import NormalizedMetricInput, NormalizedValue
from crystra_evolution.domain.ports import (
    EvidenceTaskReader,
    TaskMembershipPage,
    TaskMembershipSummary,
    TaskPage,
    TaskSummary,
)

ROOT = Path(__file__).parents[2]
PACKAGE = ROOT / "src" / "crystra_evolution"
SLOT_MODULES = tuple(
    path
    for path in (PACKAGE / "calculators").glob("*.py")
    if path.name not in {"__init__.py", "protocol.py", "registry.py"}
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_runtime_dependencies_exclude_database_and_data_engines() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = {item.split("=", 1)[0].lower() for item in project["dependencies"]}

    assert names.isdisjoint(
        {"psycopg", "sqlalchemy", "alembic", "numpy", "pandas", "asyncpg", "motor"}
    )


def test_calculator_slots_do_not_import_transport_storage_or_each_other() -> None:
    forbidden_prefixes = (
        "fastapi",
        "httpx",
        "requests",
        "sqlalchemy",
        "psycopg",
        "crystra_evolution.app",
        "crystra_evolution.application",
        "crystra_evolution.domain.ports",
    )
    slot_names = {f"crystra_evolution.calculators.{path.stem}" for path in SLOT_MODULES}

    for path in SLOT_MODULES:
        imports = imported_modules(path)
        assert not any(item.startswith(forbidden_prefixes) for item in imports)
        assert imports.isdisjoint(slot_names - {f"crystra_evolution.calculators.{path.stem}"})


def test_normalized_calculator_input_is_immutable_and_transport_free() -> None:
    value = NormalizedValue(name="duration_ms", integer=20)
    normalized = NormalizedMetricInput(
        metric_coordinate="operational-latency-ms@1.0.0",
        unit_identity="trace-a/span-a",
        values=(value,),
    )

    assert isinstance(Calculator, type)
    with pytest.raises(dataclasses.FrozenInstanceError):
        normalized.unit_identity = "changed"  # type: ignore[misc]
    assert not hasattr(normalized, "request")
    assert not hasattr(normalized, "client")
    assert not hasattr(normalized, "selection")


def test_task_port_exposes_identity_and_optional_name_without_route_guessing() -> None:
    page = TaskPage(
        tasks=(TaskSummary(task_id="task-a", display_name=None),),
        next_cursor=None,
        route_snapshot="task-route-snapshot",
    )

    assert page.tasks[0].task_id == "task-a"
    assert page.tasks[0].display_name is None
    assert EvidenceTaskReader.__name__ == "EvidenceTaskReader"

    membership = TaskMembershipPage(
        memberships=(
            TaskMembershipSummary(
                task_id="task-a",
                delivery_id="delivery-a",
                manifest_digest="a" * 64,
                accepted_digest="b" * 64,
                profile_version="2.0.0",
                source_identity="event:task-event-a",
                recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
            ),
        ),
        as_of=datetime(2026, 8, 28, tzinfo=UTC),
        next_cursor="cursor-next",
        route_snapshot="task-route-snapshot",
    )
    assert membership.next_cursor == "cursor-next"


def test_package_imports_without_database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(__import__("os").environ):
        if "DATABASE" in name or name.startswith("PG"):
            monkeypatch.delenv(name, raising=False)

    assert importlib.import_module("crystra_evolution.app") is not None


def test_api_and_domain_layers_do_not_import_concrete_calculators() -> None:
    concrete = {path.stem for path in SLOT_MODULES}
    for path in PACKAGE.rglob("*.py"):
        if (PACKAGE / "calculators") in path.parents:
            continue
        imports = imported_modules(path)
        assert not any(
            module.removeprefix("crystra_evolution.calculators.") in concrete
            for module in imports
            if module.startswith("crystra_evolution.calculators.")
        )
