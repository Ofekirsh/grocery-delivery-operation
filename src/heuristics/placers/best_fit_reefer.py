from __future__ import annotations
from typing import Optional, Tuple, Sequence, Literal

from .base import StateView, FeasibilityService, Policy, PackingPolicy, AssignOrder

RankDim = Literal["cold", "volume", "weight"]


def _residual_key(
    *,
    state: StateView,
    order_id: str,
    truck_id: str,
    scheme: Sequence[RankDim],
) -> Optional[Tuple[float, ...]]:
    """
    Build a lexicographic key of 'leftovers' based on the chosen scheme.
    Smaller is better. Returns None if the truck can't fit the order.
    """
    f = state.order_features(order_id)
    r = state.truck_residuals(truck_id)

    demand = {
        "cold":   float(f.cold_volume_m3),
        "volume": float(f.effective_volume_m3),
        "weight": float(f.weight_kg),
    }
    resid = {
        "cold":   float(r.remaining_cold_m3),
        "volume": float(r.remaining_volume_m3),
        "weight": float(r.remaining_weight_kg),
    }

    # must fit all constrained dimensions present in scheme
    for dim in scheme:
        if resid[dim] - demand[dim] < 0:
            return None

    # lexicographic tuple of leftover per the requested priority
    return tuple(resid[dim] - demand[dim] for dim in scheme)


def choose_best_open_reefer(
    state: StateView,
    feas: FeasibilityService,
    policy: Policy,
    order_id: str,
    *,
    scheme: Sequence[RankDim] = ("cold", "volume", "weight"),
) -> Optional[str]:
    """
    Among open reefers, pick best-fitting truck for `order_id` using a configurable
    priority scheme (default: cold → volume → weight). Smaller leftover is better.
    """
    best: Optional[Tuple[Tuple[float, ...], str]] = None

    for tid in state.open_trucks(type_filter="reefer"):
        if not feas.fits_order_on_truck(state, order_id, tid, policy):
            continue

        key = _residual_key(state=state, order_id=order_id, truck_id=tid, scheme=scheme)
        if key is None:
            continue

        if best is None or key < best[0]:
            best = (key, tid)

    return None if best is None else best[1]


def maybe_open_new_reefer(
    state: StateView,
    feas: FeasibilityService,
    policy: Policy,
    *,
    order_id: str,
) -> Optional[str]:
    """
    Try to open a new reefer truck if policy and availability allow.

    Logic:
      - Check policy.allow_open_new_reefer_A.
      - Scan through all available reefers not already open.
      - Pick the first one that can feasibly fit the order
        (volume, cold, and weight constraints satisfied).
      - Return its truck_id if opened, else None.

    Returns:
        str | None – ID of the new reefer opened, or None if not allowed or none fit.
    """
    # 1. policy gate
    if not getattr(policy, "allow_open_new_reefer_A", False):
        return None

    # 2. candidates: all available reefers not already open
    open_ids = set(state.open_trucks(type_filter="reefer"))
    all_ids = set(state.all_available_trucks(type_filter="reefer"))
    candidates = sorted(all_ids - open_ids)

    # 3. find first feasible reefer that can hold this order
    for tid in candidates:
        if feas.fits_order_on_truck(state, order_id, tid, policy):
            # later: planner would call tracker.open_truck(tid, …)
            return tid

    # 4. none fit
    return None


def assign_to_best_reefer(
    state: StateView,
    feas: FeasibilityService,
    policy: Policy,
    order_id: str,
    *,
    packing_policy: PackingPolicy,
    ranking_scheme: Sequence[RankDim] = ("cold", "volume", "weight"),
) -> Optional[AssignOrder]:
    """
    Try to assign `order_id` to the best refrigerated truck.

    Steps:
      1) Among *open* reefers, choose the best-fitting by the given `ranking_scheme`.
      2) If none fit, optionally open a new reefer (per policy) that can fit the order.
      3) Build a PackingPlan via `packing_policy.plan(...)`.
      4) Return an AssignOrder decision describing the action, or None if infeasible.

    Returns:
        AssignOrder | None
          - AssignOrder.truck_id
          - AssignOrder.order_id
          - AssignOrder.plan (PackingPlan)
          - AssignOrder.opened_new_truck (bool)
          - AssignOrder.rationale (dict)
    """
    # 1) try open reefers first
    tid = choose_best_open_reefer(
        state=state, feas=feas, policy=policy, order_id=order_id, scheme=ranking_scheme
    )
    opened_new = False

    # 2) if none, maybe open a new reefer (policy-gated)
    if tid is None:
        tid = maybe_open_new_reefer(state=state, feas=feas, policy=policy, order_id=order_id)
        opened_new = tid is not None

    if tid is None:
        return None  # infeasible under current open fleet and policy

    # 3) build packing plan (items already sorted by your ItemPrioritySorter via StateView)
    plan = packing_policy.plan(state, tid, order_id)
    if plan is None:
        # Very defensive: if a policy refuses to plan (should be rare given feasibility gate)
        return None

    # 4) wrap the decision
    f = state.order_features(order_id)
    r = state.truck_residuals(tid)
    rationale = {
        "scheme": list(ranking_scheme),
        "order": {
            "v_eff": float(f.effective_volume_m3),
            "q_cold": float(f.cold_volume_m3),
            "w": float(f.weight_kg),
        },
        "truck_residuals_before": {
            "ΔQ": float(r.remaining_volume_m3),
            "ΔQ_cold": float(r.remaining_cold_m3),
            "ΔW": float(r.remaining_weight_kg),
        },
        "opened_new_truck": opened_new,
    }

    return AssignOrder(
        truck_id=tid,
        order_id=order_id,
        packing=plan,
        rationale=rationale,
        opened_new_truck=opened_new
    )

