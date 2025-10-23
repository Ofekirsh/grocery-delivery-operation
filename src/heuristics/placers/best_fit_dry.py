# src/heuristics/placers/best_fit_dry.py
from __future__ import annotations
from typing import Optional, Tuple, Sequence, Literal

from .base import StateView, FeasibilityService, Policy, PackingPolicy, AssignOrder
from .best_fit_reefer import choose_best_open_reefer  # reuse the reefer chooser we already have

ReeferRankDim = Literal["cold", "volume", "weight"]
RankDim = Literal["volume", "weight"]  # dry trucks have no native cold capacity
DryRankDim = Literal["volume", "weight"]


def _residual_key_dry(
    *,
    state: StateView,
    order_id: str,
    truck_id: str,
    scheme: Sequence[RankDim],
) -> Optional[Tuple[float, ...]]:
    """
    Build a lexicographic key of 'leftovers' for DRY trucks.
    Smaller is better. Returns None if the truck can't fit the order
    (including cooler feasibility when order has cold volume).
    """
    f = state.order_features(order_id)
    r = state.truck_residuals(truck_id)

    demand = {
        "volume": float(f.effective_volume_m3),
        "weight": float(f.weight_kg),
    }
    resid = {
        "volume": float(r.remaining_volume_m3),
        "weight": float(r.remaining_weight_kg),
    }

    # must fit both requested dims in scheme
    for dim in scheme:
        if resid[dim] - demand[dim] < 0:
            return None

    # lexicographic tuple of leftover per the requested priority
    return tuple(resid[dim] - demand[dim] for dim in scheme)


def choose_best_open_dry(
    state: StateView,
    feas: FeasibilityService,
    policy: Policy,
    order_id: str,
    *,
    scheme: Sequence[RankDim] = ("volume", "weight"),
) -> Optional[str]:
    """
    Among open DRY trucks, pick the best-fitting truck for `order_id` using a
    configurable priority scheme (default: volume → weight).
    For orders with cold volume, feasibility must include cooler checks.
    """
    best: Optional[Tuple[Tuple[float, ...], str]] = None

    for tid in state.open_trucks(type_filter="dry"):
        # Must pass feasibility (this should include cooler feasibility if order has cold volume)
        if not feas.fits_order_on_truck(state, order_id, tid, policy):
            continue

        key = _residual_key_dry(state=state, order_id=order_id, truck_id=tid, scheme=scheme)
        if key is None:
            continue

        if best is None or key < best[0]:
            best = (key, tid)

    return None if best is None else best[1]


def maybe_open_new_dry(
    state: StateView,
    feas: FeasibilityService,
    policy: Policy,
    *,
    order_id: str,
) -> Optional[str]:
    """
    Try to open a new DRY truck for `order_id` if policy and feasibility allow.

    Behavior (Bucket B aware):
      - Gate on policy.allow_open_new_dry_B.
      - Iterate over *available but not-open* DRY trucks.
      - Require feasibility:
          • fits_order_on_truck(...) must pass (vol/weight and any basic rules)
          • If order has cold volume, also require cooler_feasible(...).
      - Return the truck_id of the first feasible candidate; else None.
    """
    # 1) policy gate
    if not getattr(policy, "allow_open_new_dry_B", False):
        return None

    # 2) candidate DRY trucks: available minus currently open
    open_ids = set(state.open_trucks(type_filter="dry"))
    all_dry = set(state.all_available_trucks(type_filter="dry"))
    candidates = sorted(all_dry - open_ids)

    # 3) check feasibility per candidate
    f = state.order_features(order_id)
    order_has_cold = float(getattr(f, "cold_volume_m3", 0.0)) > 0.0

    for tid in candidates:
        # base capacity & rules
        if not feas.fits_order_on_truck(state, order_id, tid, policy):
            continue

        # extra cooler requirement for cold-in-dry
        if order_has_cold:
            if not feas.cooler_feasible(state, order_id, tid, policy):
                continue

        return tid  # first acceptable candidate

    return None


def assign_bucket_b_order(
    state: StateView,
    feas: FeasibilityService,
    policy: Policy,
    order_id: str,
    *,
    packing_policy: PackingPolicy,
    reefer_scheme: Sequence[ReeferRankDim] = ("cold", "volume", "weight"),
    dry_scheme: Sequence[DryRankDim] = ("volume", "weight"),
) -> Optional[AssignOrder]:
    """
    Bucket B orchestration (flexible orders with some cold or dry-only):

      1) Try an EXISTING REEFER (do NOT open a new reefer for B).
      2) If none fit, try OPEN DRY (requires cooler feasibility if order has cold volume).
      3) If none fit and policy allows, MAYBE OPEN NEW DRY (also cooler-checked if needed).

    Returns:
        AssignOrder on success, else None.
    """
    # ---------- step 1: existing reefers only ----------
    reefer_tid = choose_best_open_reefer(
        state=state, feas=feas, policy=policy, order_id=order_id, scheme=reefer_scheme
    )
    if reefer_tid is not None:
        plan = packing_policy.plan(state, reefer_tid, order_id)
        if plan is None:
            return None
        f = state.order_features(order_id)
        r = state.truck_residuals(reefer_tid)
        rationale = (
            f"BucketB: used existing reefer "
            f"(scheme={list(reefer_scheme)}; "
            f"order v_eff={f.effective_volume_m3:.4f}, q_cold={f.cold_volume_m3:.4f}, w={f.weight_kg:.1f}; "
            f"truck ΔQ={r.remaining_volume_m3:.4f}, ΔQ_cold={r.remaining_cold_m3:.4f}, ΔW={r.remaining_weight_kg:.1f})"
        )
        return AssignOrder(order_id=order_id, truck_id=reefer_tid, packing=plan, rationale=rationale)

    # ---------- step 2: open dry trucks ----------
    dry_tid = choose_best_open_dry(
        state=state, feas=feas, policy=policy, order_id=order_id, scheme=dry_scheme
    )
    if dry_tid is not None:
        plan = packing_policy.plan(state, dry_tid, order_id)
        if plan is None:
            return None
        f = state.order_features(order_id)
        r = state.truck_residuals(dry_tid)
        rationale = (
            f"BucketB: used open dry "
            f"(scheme={list(dry_scheme)}; "
            f"order v_eff={f.effective_volume_m3:.4f}, q_cold={f.cold_volume_m3:.4f}, w={f.weight_kg:.1f}; "
            f"truck ΔQ={r.remaining_volume_m3:.4f}, ΔW={r.remaining_weight_kg:.1f})"
        )
        return AssignOrder(order_id=order_id, truck_id=dry_tid, packing=plan, rationale=rationale)

    # ---------- step 3: maybe open new dry (policy-gated) ----------
    new_dry_tid = maybe_open_new_dry(
        state=state, feas=feas, policy=policy, order_id=order_id
    )
    if new_dry_tid is not None:
        plan = packing_policy.plan(state, new_dry_tid, order_id)
        if plan is None:
            return None
        f = state.order_features(order_id)
        r = state.truck_residuals(new_dry_tid)
        rationale = (
            f"BucketB: opened new dry "
            f"(scheme={list(dry_scheme)}; "
            f"order v_eff={f.effective_volume_m3:.4f}, q_cold={f.cold_volume_m3:.4f}, w={f.weight_kg:.1f}; "
            f"truck ΔQ={r.remaining_volume_m3:.4f}, ΔW={r.remaining_weight_kg:.1f})"
        )
        return AssignOrder(order_id=order_id, truck_id=new_dry_tid, packing=plan, rationale=rationale)

    # nothing feasible under policy
    return None


def assign_bucket_c_order(
    state: StateView,
    feas: FeasibilityService,
    policy: Policy,
    order_id: str,
    *,
    packing_policy: PackingPolicy,
    dry_scheme: Sequence[DryRankDim] = ("volume", "weight"),
) -> Optional[AssignOrder]:
    """
    Bucket C (dry-only) placement:
      1) Try OPEN DRY trucks (no cooler logic needed).
      2) If none fit and policy allows, open NEW DRY.
      3) Else return None.
    """
    # 1) open dry
    tid = choose_best_open_dry(state, feas, policy, order_id, scheme=dry_scheme)
    if tid is None:
        # 2) maybe open new dry (policy-gated)
        tid = maybe_open_new_dry(state, feas, policy, order_id=order_id)

    if tid is None:
        return None

    plan = packing_policy.plan(state, tid, order_id)
    if plan is None:
        return None

    f = state.order_features(order_id)
    r = state.truck_residuals(tid)
    rationale = (
        f"BucketC: dry-only; scheme={list(dry_scheme)}; "
        f"order v_eff={f.effective_volume_m3:.4f}, w={f.weight_kg:.1f}; "
        f"truck ΔQ={r.remaining_volume_m3:.4f}, ΔW={r.remaining_weight_kg:.1f}"
    )
    return AssignOrder(order_id=order_id, truck_id=tid, packing=plan, rationale=rationale)



