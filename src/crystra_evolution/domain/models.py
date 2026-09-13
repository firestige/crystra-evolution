from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    name: str
    integer: int | None = None
    decimal: str | None = None
    text: str | None = None
    boolean: bool | None = None

    def __post_init__(self) -> None:
        supplied = sum(
            value is not None for value in (self.integer, self.decimal, self.text, self.boolean)
        )
        if supplied != 1:
            raise ValueError("normalized value requires exactly one typed representation")


@dataclass(frozen=True, slots=True)
class NormalizedMetricInput:
    metric_coordinate: str
    unit_identity: str
    values: tuple[NormalizedValue, ...]


@dataclass(frozen=True, slots=True)
class DeliveryMetricUnit:
    delivery_id: str
    terminal_outcome: str | None
    elapsed_time_ms: int | Fraction | None
    reached_stages: tuple[str, ...]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.elapsed_time_ms is not None and self.elapsed_time_ms < 0:
            raise ValueError("Delivery elapsed time must be nonnegative")
        if len(set(self.reached_stages)) != len(self.reached_stages):
            raise ValueError("Delivery reached stages must be unique")


@dataclass(frozen=True, slots=True)
class OperationalCallUnit:
    call_identity: str
    provider: str | None
    model: str | None
    role: str | None
    runtime: str | None
    duration_ns: int | None
    input_tokens: int | None
    output_tokens: int | None
    provenance_refs: tuple[str, ...]

    @property
    def cohort(self) -> tuple[str, str, str, str] | None:
        values = (self.provider, self.model, self.role, self.runtime)
        if any(value is None for value in values):
            return None
        provider, model, role, runtime = values
        assert all(value is not None for value in (provider, model, role, runtime))
        assert provider is not None and model is not None
        assert role is not None and runtime is not None
        return (provider, model, role, runtime)


@dataclass(frozen=True, slots=True)
class TaskMetricUnit:
    task_id: str
    terminal_outcome: str | None
    classification: str
    covered: bool
    provenance_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleModelTaskUnit:
    task_id: str
    provider: str
    model: str
    role: str
    runtime: str
    terminal_outcome: str
    provenance_refs: tuple[str, ...]

    @property
    def cohort(self) -> tuple[str, str, str, str]:
        return (self.provider, self.model, self.role, self.runtime)


@dataclass(frozen=True, slots=True)
class ReportedUsageUnit:
    usage_identity: str
    delivery_id: str
    kind: str
    unit: str
    source: str
    source_id: str
    value: int
    provenance_refs: tuple[str, ...]
    lower_bound: bool = False

    @property
    def compatibility(self) -> tuple[str, str, str, str]:
        return (self.kind, self.unit, self.source, self.source_id)


@dataclass(frozen=True, slots=True)
class RoleTemplateDeliveryUnit:
    delivery_id: str
    role_id: str
    role_prompt_identity: str
    role_prompt_digest: str
    repair_observed: bool | None
    provenance_refs: tuple[str, ...]
    repair_expired: bool = False

    @property
    def template(self) -> tuple[str, str, str]:
        return (self.role_id, self.role_prompt_identity, self.role_prompt_digest)


@dataclass(frozen=True, slots=True)
class RoleTemplateUsageUnit:
    delivery_id: str
    role_id: str
    role_prompt_identity: str
    role_prompt_digest: str
    kind: str
    unit: str
    source: str
    source_id: str
    value: int
    provenance_refs: tuple[str, ...]
    lower_bound: bool = False

    @property
    def template(self) -> tuple[str, str, str]:
        return (self.role_id, self.role_prompt_identity, self.role_prompt_digest)

    @property
    def compatibility(self) -> tuple[str, str, str, str]:
        return (self.kind, self.unit, self.source, self.source_id)


@dataclass(frozen=True, slots=True)
class OperationalUsageUnit:
    call_identity: str
    source_applicable: bool
    kind: str | None
    unit: str | None
    source: str | None
    source_id: str | None
    value: int | None
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        coordinates = (self.kind, self.unit, self.source, self.source_id)
        if self.source_applicable != all(item is not None for item in coordinates):
            raise ValueError("Usage source applicability and coordinates disagree")
        if not self.source_applicable and self.value is not None:
            raise ValueError("not-applicable Usage cannot contain a value")

    @property
    def compatibility(self) -> tuple[str, str, str, str] | None:
        if not self.source_applicable:
            return None
        assert self.kind is not None and self.unit is not None
        assert self.source is not None and self.source_id is not None
        return (self.kind, self.unit, self.source, self.source_id)
