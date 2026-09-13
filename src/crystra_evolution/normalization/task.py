from crystra_evolution.domain.models import DeliveryMetricUnit, TaskMetricUnit


def normalize_task(
    task_id: str,
    membership_delivery_ids: tuple[str, ...],
    deliveries: tuple[DeliveryMetricUnit, ...],
) -> TaskMetricUnit:
    if len(set(membership_delivery_ids)) != len(membership_delivery_ids):
        raise ValueError("Task membership Delivery identities must be unique")
    if not membership_delivery_ids:
        return TaskMetricUnit(task_id, None, "UNDEFINED_TASK_MEMBERSHIP", False, ())
    by_id = {delivery.delivery_id: delivery for delivery in deliveries}
    if len(by_id) != len(deliveries):
        raise ValueError("Delivery readings must be unique")
    if not set(membership_delivery_ids).issubset(by_id):
        return TaskMetricUnit(task_id, None, "MISSING_DELIVERY_READING", False, ())
    members = tuple(by_id[identity] for identity in membership_delivery_ids)
    provenance = tuple(sorted({ref for item in members for ref in item.provenance_refs}))
    outcomes = {item.terminal_outcome for item in members if item.terminal_outcome is not None}
    if any(item.terminal_outcome is None for item in members):
        return TaskMetricUnit(task_id, None, "OPEN_DELIVERY", True, provenance)
    if len(outcomes) != 1:
        return TaskMetricUnit(task_id, None, "MIXED_DELIVERY_OUTCOMES", True, provenance)
    return TaskMetricUnit(task_id, next(iter(outcomes)), "ELIGIBLE", True, provenance)
