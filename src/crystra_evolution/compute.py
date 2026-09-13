from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from fractions import Fraction
from typing import Literal, Protocol

from crystra_evolution.api.models import (
    CatalogBinding,
    CompareRequest,
    CompareResponse,
    ComputeRequest,
    ComputeResponse,
    DeltaEntry,
    EvaluationSelection,
    EvidenceBinding,
    ExactValue,
    InputReference,
    MetricSlice,
    ResolvedEvaluationContext,
    SideError,
    SideResult,
    SingleRequest,
    SingleResponse,
)
from crystra_evolution.application import (
    ResolutionBoundExceeded,
    UpstreamContractMismatch,
    UpstreamUnavailable,
)
from crystra_evolution.calculators import (
    delivery_cycle_time_ms,
    delivery_stage_reach,
    delivery_terminal_outcome_rate,
    operational_attributable_cost,
    operational_latency_ms,
    operational_token_usage,
    operational_usage_availability,
    role_model_task_outcome_rate,
    role_template_rework_rate,
    role_template_trajectory_partial_cost,
    task_cohort_comparison_eligibility,
    trajectory_partial_cost,
)
from crystra_evolution.catalog import CATALOG_SEMANTIC_DIGEST
from crystra_evolution.domain.models import (
    DeliveryMetricUnit,
    OperationalCallUnit,
    ReportedUsageUnit,
    RoleModelTaskUnit,
    RoleTemplateDeliveryUnit,
    RoleTemplateUsageUnit,
    TaskMetricUnit,
)
from crystra_evolution.domain.ports import FactReading
from crystra_evolution.normalization.delivery import normalize_delivery
from crystra_evolution.normalization.operational import normalize_model_calls
from crystra_evolution.normalization.task import normalize_task
from crystra_evolution.normalization.usage import normalize_reported_usage
from crystra_evolution.resolution.service import (
    ResolutionLimits,
    ResolvedDeliveryObservation,
    ResolvedSelectionPopulation,
)


class PopulationResolver(Protocol):
    async def resolve(
        self, selection: EvaluationSelection, *, as_of: datetime
    ) -> ResolvedSelectionPopulation: ...


class ObservationResolver(Protocol):
    async def resolve(self, *, delivery_id: str) -> ResolvedDeliveryObservation: ...


type SideFailure = UpstreamUnavailable | UpstreamContractMismatch | ResolutionBoundExceeded


def _unique_bindings(items: tuple[EvidenceBinding, ...]) -> tuple[EvidenceBinding, ...]:
    by_key: dict[tuple[str, str], EvidenceBinding] = {}
    for item in items:
        key = (item.route, repr(sorted(item.canonical_filter.items())))
        prior = by_key.get(key)
        if prior is not None and prior != item:
            raise ValueError("conflicting Evidence binding for one route/filter")
        by_key[key] = item
    return tuple(by_key.values())


def _unique_references(items: tuple[InputReference, ...]) -> tuple[InputReference, ...]:
    by_key: dict[tuple[str, str], InputReference] = {}
    for item in items:
        key = (item.kind, item.identity)
        prior = by_key.get(key)
        if prior is not None and prior != item:
            raise ValueError("conflicting input provenance for one identity")
        by_key[key] = item
    return tuple(by_key.values())


def _population_state(
    tasks: tuple[TaskMetricUnit, ...],
    trace_states: tuple[str, ...],
) -> Literal["COMPLETE", "PARTIAL", "OPEN", "MIXED", "EXPIRED"]:
    if "EXPIRED" in trace_states:
        return "EXPIRED"
    if "PARTIAL" in trace_states:
        return "PARTIAL"
    if any(not task.covered for task in tasks):
        return "PARTIAL"
    classifications = {task.classification for task in tasks}
    if "OPEN_DELIVERY" in classifications:
        return "OPEN"
    if "MIXED_DELIVERY_OUTCOMES" in classifications:
        return "MIXED"
    return "COMPLETE"


class EvolutionComputeService:
    def __init__(
        self,
        population: PopulationResolver,
        observations: ObservationResolver,
        *,
        now: Callable[[], datetime] | None = None,
        limits: ResolutionLimits | None = None,
    ) -> None:
        self._population = population
        self._observations = observations
        self._now = now or (lambda: datetime.now(UTC))
        self._limits = limits or ResolutionLimits()

    async def compute(self, request: ComputeRequest) -> ComputeResponse:
        if isinstance(request, SingleRequest):
            return SingleResponse(
                api_version=1,
                mode="SINGLE",
                result=await self._compute_side_bounded(request.selection),
            )
        if isinstance(request, CompareRequest):
            return await self._compute_compare(request)
        raise TypeError("unsupported Evolution compute request")

    async def _compute_side_bounded(self, selection: EvaluationSelection) -> SideResult:
        try:
            async with asyncio.timeout(self._limits.side_deadline_seconds):
                return await self._compute_side(selection)
        except TimeoutError as error:
            raise ResolutionBoundExceeded("side resolution deadline exceeded") from error

    async def _compute_side(self, selection: EvaluationSelection) -> SideResult:
        as_of = self._now()
        population = await self._population.resolve(selection, as_of=as_of)

        selected_delivery_ids = {
            membership.delivery_id
            for task in population.task_population
            for membership in task.memberships
        }
        if len(selected_delivery_ids) > self._limits.max_deliveries_per_side:
            raise ResolutionBoundExceeded("unique Delivery bound exceeded")

        observations: dict[str, ResolvedDeliveryObservation] = {}
        for task in population.task_population:
            for membership in task.memberships:
                if membership.delivery_id not in observations:
                    observations[membership.delivery_id] = await self._observations.resolve(
                        delivery_id=membership.delivery_id
                    )
                    input_count = sum(
                        len(item.facts) + len(item.trace_nodes) for item in observations.values()
                    )
                    if input_count > self._limits.max_input_records_per_side:
                        raise ResolutionBoundExceeded("Fact and Trace input record bound exceeded")

        observed_facts_by_delivery = {
            delivery_id: tuple(fact for fact in observation.facts if fact.recorded_at <= as_of)
            for delivery_id, observation in observations.items()
        }
        observed_nodes_by_delivery = {
            delivery_id: tuple(
                node for node in observation.trace_nodes if node.recorded_at <= as_of
            )
            for delivery_id, observation in observations.items()
        }
        retention_excluded_delivery_ids = {
            delivery_id
            for delivery_id, observation in observations.items()
            if observation.trace_state in {"PARTIAL", "EXPIRED"}
            or any(fact.expiry == "EXPIRED" for fact in observed_facts_by_delivery[delivery_id])
            or any(node.expiry == "EXPIRED" for node in observed_nodes_by_delivery[delivery_id])
        }
        active_delivery_ids = selected_delivery_ids - retention_excluded_delivery_ids
        facts_by_delivery = {
            delivery_id: facts
            for delivery_id, facts in observed_facts_by_delivery.items()
            if delivery_id in active_delivery_ids
        }
        nodes_by_delivery = {
            delivery_id: nodes
            for delivery_id, nodes in observed_nodes_by_delivery.items()
            if delivery_id in active_delivery_ids
        }
        try:
            deliveries = tuple(
                normalize_delivery(delivery_id, facts)
                for delivery_id, facts in sorted(facts_by_delivery.items())
            )
        except ValueError as error:
            raise UpstreamContractMismatch("Evidence normalization conflict") from error
        calls_by_delivery = {
            delivery_id: normalize_model_calls(nodes)
            for delivery_id, nodes in nodes_by_delivery.items()
        }
        calls = tuple(
            call
            for delivery_id in sorted(calls_by_delivery, key=str.encode)
            for call in calls_by_delivery[delivery_id]
        )
        usage = tuple(
            item
            for delivery_id, facts in sorted(facts_by_delivery.items())
            for item in normalize_reported_usage(delivery_id, facts)
        )

        tasks = tuple(
            normalize_task(task.task_id, active_memberships, deliveries)
            for task in population.task_population
            if (
                active_memberships := tuple(
                    item.delivery_id
                    for item in task.memberships
                    if item.delivery_id in active_delivery_ids
                )
            )
            or not task.memberships
        )
        task_by_id = {task.task_id: task for task in tasks}
        resolved_task_population = tuple(
            entry.model_copy(
                update={
                    "terminal_reading": (
                        task_by_id[entry.task_id].terminal_outcome
                        if entry.task_id in task_by_id
                        else None
                    ),
                    "exclusions": tuple(
                        sorted(
                            {
                                *(
                                    ()
                                    if entry.task_id not in task_by_id
                                    or task_by_id[entry.task_id].classification == "ELIGIBLE"
                                    else (task_by_id[entry.task_id].classification,)
                                ),
                                *(
                                    ("EXPIRED_DELIVERY",)
                                    if any(
                                        membership.delivery_id in retention_excluded_delivery_ids
                                        for membership in entry.memberships
                                    )
                                    else ()
                                ),
                            }
                        )
                    ),
                }
            )
            for entry in population.task_population
        )
        role_model_units = self._role_model_units(population, task_by_id, calls_by_delivery)
        delivery_by_id = {delivery.delivery_id: delivery for delivery in deliveries}
        role_template_units = self._role_template_units(
            population, delivery_by_id, calls_by_delivery, facts_by_delivery
        )
        role_template_usage = self._role_template_usage_units(role_template_units, usage)
        delivery_ids = tuple(item.delivery_id for item in deliveries)
        trace_states = tuple(observation.trace_state for observation in observations.values()) + (
            ("EXPIRED",) if retention_excluded_delivery_ids else ()
        )
        # The current public Fact response does not expose the Usage Event's native
        # Span identity. Call-scoped Usage therefore remains an explicit coverage
        # hole instead of being guessed by Delivery or time.
        results = (
            role_template_rework_rate.calculate(role_template_units),
            role_template_trajectory_partial_cost.calculate(
                role_template_units, role_template_usage
            ),
            role_model_task_outcome_rate.calculate(role_model_units),
            operational_latency_ms.calculate(calls),
            trajectory_partial_cost.calculate(delivery_ids, usage),
            task_cohort_comparison_eligibility.calculate(tasks),
            delivery_stage_reach.calculate(deliveries),
            delivery_terminal_outcome_rate.calculate(deliveries),
            delivery_cycle_time_ms.calculate(deliveries),
            operational_token_usage.calculate(calls),
            operational_attributable_cost.calculate(calls, ()),
            operational_usage_availability.calculate(calls, ()),
        )

        observation_bindings = tuple(
            binding
            for delivery_id in sorted(observations, key=str.encode)
            for binding in observations[delivery_id].evidence_bindings
        )
        observation_refs = tuple(
            sorted(
                (
                    *(
                        InputReference(
                            kind="FACT",
                            identity=fact.fact_id,
                            provenance_ref=fact.accepted_digest,
                        )
                        for facts in observed_facts_by_delivery.values()
                        for fact in facts
                    ),
                    *(
                        InputReference(
                            kind="TRACE_NODE",
                            identity=node.resource_id,
                            provenance_ref=node.source_identity,
                        )
                        for nodes in observed_nodes_by_delivery.values()
                        for node in nodes
                    ),
                ),
                key=lambda item: (item.kind.encode(), item.identity.encode()),
            )
        )
        receipt = ResolvedEvaluationContext(
            context_version=1,
            selection=selection,
            as_of=as_of,
            resolved_at=self._now(),
            task_population=resolved_task_population,
            catalog=CatalogBinding(
                catalog_id="agentops.evaluation.metric-catalog",
                version="2.0.0",
                semantic_digest=CATALOG_SEMANTIC_DIGEST,
                observation_profile="1.0.0",
            ),
            evidence_bindings=_unique_bindings(
                (*population.evidence_bindings, *observation_bindings)
            ),
            input_refs=_unique_references((*population.input_refs, *observation_refs)),
            workflow_resolutions=population.workflow_resolutions,
            population_state=_population_state(tasks, trace_states),
        )
        return SideResult(tag="SIDE_RESULT", receipt=receipt, metric_results=results)

    @staticmethod
    def _role_model_units(
        population: ResolvedSelectionPopulation,
        tasks: dict[str, TaskMetricUnit],
        calls_by_delivery: dict[str, tuple[OperationalCallUnit, ...]],
    ) -> tuple[RoleModelTaskUnit, ...]:
        result = []
        for entry in population.task_population:
            task = tasks.get(entry.task_id)
            if task is None:
                continue
            if task.classification != "ELIGIBLE" or task.terminal_outcome is None:
                continue
            task_calls = tuple(
                call
                for membership in entry.memberships
                for call in calls_by_delivery.get(membership.delivery_id, ())
            )
            for cohort in sorted({call.cohort for call in task_calls if call.cohort is not None}):
                assert cohort is not None
                provider, model, role, runtime = cohort
                cohort_calls = tuple(call for call in task_calls if call.cohort == cohort)
                result.append(
                    RoleModelTaskUnit(
                        task_id=task.task_id,
                        provider=provider,
                        model=model,
                        role=role,
                        runtime=runtime,
                        terminal_outcome=task.terminal_outcome,
                        provenance_refs=tuple(
                            sorted(
                                {
                                    *task.provenance_refs,
                                    *(ref for call in cohort_calls for ref in call.provenance_refs),
                                }
                            )
                        ),
                    )
                )
        return tuple(result)

    @staticmethod
    def _role_template_units(
        population: ResolvedSelectionPopulation,
        deliveries: dict[str, DeliveryMetricUnit],
        calls_by_delivery: dict[str, tuple[OperationalCallUnit, ...]],
        facts_by_delivery: dict[str, tuple[FactReading, ...]],
    ) -> tuple[RoleTemplateDeliveryUnit, ...]:
        manifest_by_delivery = {
            reading.delivery_id: reading for reading in population.manifest_readings
        }
        result: dict[tuple[str, tuple[str, str, str]], RoleTemplateDeliveryUnit] = {}
        for entry in population.task_population:
            for membership in entry.memberships:
                delivery = deliveries.get(membership.delivery_id)
                if delivery is None or delivery.terminal_outcome is None:
                    continue
                manifest = manifest_by_delivery.get(membership.delivery_id)
                if manifest is None:
                    continue
                observed_roles = {
                    call.role
                    for call in calls_by_delivery.get(membership.delivery_id, ())
                    if call.role is not None
                }
                for binding in manifest.roles:
                    if binding.role_id not in observed_roles:
                        continue
                    template = (
                        binding.role_id,
                        binding.role_prompt_identity,
                        binding.role_prompt_digest,
                    )
                    key = (membership.delivery_id, template)
                    delivery_facts = facts_by_delivery.get(membership.delivery_id, ())
                    repair_observed, repair_expired = EvolutionComputeService._repair_reading(
                        delivery_facts
                    )
                    result[key] = RoleTemplateDeliveryUnit(
                        delivery_id=membership.delivery_id,
                        role_id=template[0],
                        role_prompt_identity=template[1],
                        role_prompt_digest=template[2],
                        repair_observed=repair_observed,
                        repair_expired=repair_expired,
                        provenance_refs=tuple(
                            sorted(
                                {
                                    *delivery.provenance_refs,
                                    manifest.accepted_digest,
                                    *(
                                        fact.accepted_digest
                                        for fact in delivery_facts
                                        if fact.kind == "FINDING_FIX"
                                    ),
                                }
                            )
                        ),
                    )
        return tuple(result[key] for key in sorted(result))

    @staticmethod
    def _role_template_usage_units(
        deliveries: tuple[RoleTemplateDeliveryUnit, ...],
        usage: tuple[ReportedUsageUnit, ...],
    ) -> tuple[RoleTemplateUsageUnit, ...]:
        result = []
        for delivery in deliveries:
            for item in usage:
                if item.delivery_id != delivery.delivery_id:
                    continue
                result.append(
                    RoleTemplateUsageUnit(
                        delivery_id=delivery.delivery_id,
                        role_id=delivery.role_id,
                        role_prompt_identity=delivery.role_prompt_identity,
                        role_prompt_digest=delivery.role_prompt_digest,
                        kind=item.kind,
                        unit=item.unit,
                        source=item.source,
                        source_id=item.source_id,
                        value=item.value,
                        provenance_refs=tuple(
                            sorted({*delivery.provenance_refs, *item.provenance_refs})
                        ),
                        lower_bound=item.lower_bound,
                    )
                )
        return tuple(result)

    @staticmethod
    def _repair_observed(facts: tuple[FactReading, ...]) -> bool | None:
        return EvolutionComputeService._repair_reading(facts)[0]

    @staticmethod
    def _repair_reading(facts: tuple[FactReading, ...]) -> tuple[bool | None, bool]:
        repairs = tuple(fact for fact in facts if fact.kind == "FINDING_FIX")
        if not repairs:
            return False, False
        active = tuple(fact for fact in repairs if fact.expiry == "ACTIVE")
        for fact in active:
            if fact.availability != "AVAILABLE":
                continue
            for relationship in fact.relationships:
                if (
                    relationship.kind == "FINDING_FIX"
                    and relationship.source.kind == "FIX"
                    and relationship.target.kind == "FINDING_TARGET"
                ):
                    return True, False
        if active:
            return None, False
        return None, True

    async def _compute_compare(self, request: CompareRequest) -> CompareResponse:
        left: SideResult | SideError
        right: SideResult | SideError
        left_failure: SideFailure | None = None
        right_failure: SideFailure | None = None
        try:
            left = await self._compute_side_bounded(request.left)
        except (UpstreamUnavailable, UpstreamContractMismatch, ResolutionBoundExceeded) as error:
            left_failure = error
            left = self._side_error(error)
        try:
            right = await self._compute_side_bounded(request.right)
        except (UpstreamUnavailable, UpstreamContractMismatch, ResolutionBoundExceeded) as error:
            right_failure = error
            right = self._side_error(error)

        if left_failure is not None and right_failure is not None:
            raise left_failure
        if isinstance(left, SideError) or isinstance(right, SideError):
            successful = right if isinstance(left, SideError) else left
            assert isinstance(successful, SideResult)
            deltas = tuple(
                DeltaEntry(
                    metric_coordinate=coordinate,
                    slice_key=metric_slice.slice_key,
                    state="SIDE_UNRESOLVED",
                    withholding_reason="SIDE_UNRESOLVED",
                )
                for coordinate, metric_slice in self._slice_items(successful)
            )
            return CompareResponse(
                api_version=1,
                mode="COMPARE",
                status="PARTIAL_COMPARE",
                left=left,
                right=right,
                deltas=deltas,
            )

        return CompareResponse(
            api_version=1,
            mode="COMPARE",
            status="FULL_COMPARE",
            left=left,
            right=right,
            deltas=self._full_deltas(left, right),
        )

    @staticmethod
    def _side_error(
        error: UpstreamUnavailable | UpstreamContractMismatch | ResolutionBoundExceeded,
    ) -> SideError:
        retryable = isinstance(error, UpstreamUnavailable)
        return SideError(
            tag="SIDE_ERROR",
            code=(
                "UPSTREAM_UNAVAILABLE"
                if retryable
                else "RESOLUTION_BOUND_EXCEEDED"
                if isinstance(error, ResolutionBoundExceeded)
                else "UPSTREAM_INCOMPATIBLE"
            ),
            retryable=retryable,
            detail=str(error),
        )

    @staticmethod
    def _slice_items(side: SideResult) -> tuple[tuple[str, MetricSlice], ...]:
        return tuple(
            (f"{result.metric_id}@{result.metric_version}", metric_slice)
            for result in side.metric_results
            for metric_slice in result.slices
        )

    @staticmethod
    def _slice_identity(coordinate: str, metric_slice: MetricSlice) -> tuple[str, str]:
        return (
            coordinate,
            json.dumps(metric_slice.slice_key, sort_keys=True, separators=(",", ":")),
        )

    @classmethod
    def _full_deltas(cls, left: SideResult, right: SideResult) -> tuple[DeltaEntry, ...]:
        left_slices = {
            cls._slice_identity(coordinate, metric_slice): metric_slice
            for coordinate, metric_slice in cls._slice_items(left)
        }
        right_slices = {
            cls._slice_identity(coordinate, metric_slice): metric_slice
            for coordinate, metric_slice in cls._slice_items(right)
        }
        entries = []
        for coordinate, encoded_key in sorted(set(left_slices) | set(right_slices)):
            before = left_slices.get((coordinate, encoded_key))
            after = right_slices.get((coordinate, encoded_key))
            slice_key = json.loads(encoded_key)
            if before is None or after is None:
                entries.append(
                    DeltaEntry(
                        metric_coordinate=coordinate,
                        slice_key=slice_key,
                        state="WITHHELD",
                        withholding_reason="SLICE_MISSING",
                    )
                )
                continue
            if (
                before.state != "AVAILABLE"
                or after.state != "AVAILABLE"
                or before.value is None
                or after.value is None
            ):
                entries.append(
                    DeltaEntry(
                        metric_coordinate=coordinate,
                        slice_key=slice_key,
                        state="WITHHELD",
                        withholding_reason="VALUE_WITHHELD",
                    )
                )
                continue
            if (
                before.value.kind != after.value.kind
                or before.value.unit != after.value.unit
                or before.compatibility != after.compatibility
                or before.value.kind == "BOOLEAN"
            ):
                entries.append(
                    DeltaEntry(
                        metric_coordinate=coordinate,
                        slice_key=slice_key,
                        state="WITHHELD",
                        withholding_reason="INCOMPATIBLE",
                    )
                )
                continue
            delta = cls._subtract(after.value, before.value)
            numeric = Fraction(delta.value)
            entries.append(
                DeltaEntry(
                    metric_coordinate=coordinate,
                    slice_key=slice_key,
                    state="AVAILABLE",
                    value=delta,
                    direction=(
                        "INCREASE" if numeric > 0 else "DECREASE" if numeric < 0 else "NO_CHANGE"
                    ),
                )
            )
        return tuple(entries)

    @staticmethod
    def _subtract(after: ExactValue, before: ExactValue) -> ExactValue:
        difference = Fraction(after.value) - Fraction(before.value)
        if after.kind == "RATIO" or (after.kind == "DURATION_MS" and difference.denominator != 1):
            value: int | str = (
                str(difference.numerator)
                if difference.denominator == 1
                else f"{difference.numerator}/{difference.denominator}"
            )
        else:
            if difference.denominator != 1:
                raise ValueError("non-rational metric produced a fractional Delta")
            value = difference.numerator
        return ExactValue(kind=after.kind, value=value, unit=after.unit)
