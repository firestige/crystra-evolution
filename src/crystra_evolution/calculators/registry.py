from types import MappingProxyType

from crystra_evolution.catalog import CATALOG_COORDINATES

from .delivery_cycle_time_ms import SLOT as DELIVERY_CYCLE_TIME_MS
from .delivery_stage_reach import SLOT as DELIVERY_STAGE_REACH
from .delivery_terminal_outcome_rate import SLOT as DELIVERY_TERMINAL_OUTCOME_RATE
from .operational_attributable_cost import SLOT as OPERATIONAL_ATTRIBUTABLE_COST
from .operational_latency_ms import SLOT as OPERATIONAL_LATENCY_MS
from .operational_token_usage import SLOT as OPERATIONAL_TOKEN_USAGE
from .operational_usage_availability import SLOT as OPERATIONAL_USAGE_AVAILABILITY
from .protocol import CalculatorSlot
from .role_model_task_outcome_rate import SLOT as ROLE_MODEL_TASK_OUTCOME_RATE
from .role_template_rework_rate import SLOT as ROLE_TEMPLATE_REWORK_RATE
from .role_template_trajectory_partial_cost import SLOT as ROLE_TEMPLATE_TRAJECTORY_PARTIAL_COST
from .task_cohort_comparison_eligibility import SLOT as TASK_COHORT_COMPARISON_ELIGIBILITY
from .trajectory_partial_cost import SLOT as TRAJECTORY_PARTIAL_COST

_SLOTS = (
    ROLE_TEMPLATE_REWORK_RATE,
    ROLE_TEMPLATE_TRAJECTORY_PARTIAL_COST,
    ROLE_MODEL_TASK_OUTCOME_RATE,
    OPERATIONAL_LATENCY_MS,
    TRAJECTORY_PARTIAL_COST,
    TASK_COHORT_COMPARISON_ELIGIBILITY,
    DELIVERY_STAGE_REACH,
    DELIVERY_TERMINAL_OUTCOME_RATE,
    DELIVERY_CYCLE_TIME_MS,
    OPERATIONAL_TOKEN_USAGE,
    OPERATIONAL_ATTRIBUTABLE_COST,
    OPERATIONAL_USAGE_AVAILABILITY,
)

if tuple(slot.coordinate for slot in _SLOTS) != CATALOG_COORDINATES:
    raise RuntimeError("calculator slots do not match the bound Evaluation Catalog")
CALCULATOR_SLOTS: MappingProxyType[str, CalculatorSlot] = MappingProxyType(
    {slot.coordinate: slot for slot in _SLOTS}
)
