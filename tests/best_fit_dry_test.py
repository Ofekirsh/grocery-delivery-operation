# tests/best_fit_dry_test.py
from __future__ import annotations

# --- business objects ---
from src.business_objects.common import Dimensions, Fragility, SeparationTag, TruckType
from src.business_objects.item import Item
from src.business_objects.customer_order import CustomerOrder
from src.business_objects.truck import Truck
from src.business_objects.depot import Depot

# --- sorter (produces ItemRank) ---
from src.heuristics.selectors.item_selector_priority import ItemPrioritySorter

# --- state view + packing policy ---
from src.heuristics.placers.state_view import SimpleStateView
from src.heuristics.placers.packing import SimplePackingPolicy

# --- the bucket-B orchestration under test ---
from src.heuristics.placers.best_fit_dry import (
    choose_best_open_dry,
    maybe_open_new_dry,
    assign_bucket_b_order,
)

# --- we reuse reefer chooser implicitly through assign_bucket_b_order ---
from src.heuristics.placers.best_fit_reefer import choose_best_open_reefer  # noqa


# ───────────────────────── helpers to build a tiny world ───────────────────────── #

def build_catalog() -> dict:
    return {
        "I_MILK": Item(
            item_id="I_MILK", name="Milk",
            category_cold=True, unit_weight_kg=1.05, unit_volume_m3=0.0021,
            dims_m=Dimensions(0.08, 0.08, 0.22),
            fragility=Fragility.DELICATE, max_stack_load_kg=5,
            is_liquid=True, upright_only=True, separation_tag=SeparationTag.FOOD,
            padding_factor=0.05,
        ),
        "I_WATER": Item(
            item_id="I_WATER", name="Bottled Water",
            category_cold=False, unit_weight_kg=9.6, unit_volume_m3=0.022,
            dims_m=Dimensions(0.25, 0.25, 0.35),
            fragility=Fragility.REGULAR, max_stack_load_kg=150,
            is_liquid=True, upright_only=False, separation_tag=SeparationTag.FOOD,
            padding_factor=0.0,
        ),
    }


def build_orders(items: dict) -> dict:
    # Mixed order with small cold portion (Bucket B candidate)
    o_mix = CustomerOrder.from_items(
        order_id="O_B_MIX", customer_id="C1",
        item_list={"I_MILK": 40, "I_WATER": 3},  # some cold, some dry
        due_time_str="12:00", items=items,
    )
    # Dry-only order (Bucket C candidate)
    o_dry = CustomerOrder.from_items(
        order_id="O_C_DRY", customer_id="C2",
        item_list={"I_WATER": 10},  # no cold
        due_time_str="13:00", items=items,
    )
    return {"O_B_MIX": o_mix, "O_C_DRY": o_dry}


def build_trucks() -> dict:
    r1 = Truck(truck_id="R1", type=TruckType.REEFER,
               total_capacity_m3=24.0, cold_capacity_m3=12.0,
               weight_limit_kg=9500, fixed_cost=500, min_utilization=0.60, reserve_fraction=0.06)
    d1 = Truck(truck_id="D1", type=TruckType.DRY,
               total_capacity_m3=20.0, cold_capacity_m3=0.0,
               weight_limit_kg=7000, fixed_cost=380, min_utilization=0.75, reserve_fraction=0.05)
    d2 = Truck(truck_id="D2", type=TruckType.DRY,
               total_capacity_m3=26.0, cold_capacity_m3=0.0,
               weight_limit_kg=10000, fixed_cost=460, min_utilization=0.75, reserve_fraction=0.05)
    return {"R1": r1, "D1": d1, "D2": d2}


def preset_residuals(truck: Truck, *, used_v_eff=0.0, used_q_cold=0.0, used_w=0.0) -> None:
    truck.used_volume_m3 = float(used_v_eff)
    truck.used_cold_m3 = float(used_q_cold)
    truck.used_weight_kg = float(used_w)


def build_sorted_items_provider(items: dict, orders: dict) -> dict:
    sorter = ItemPrioritySorter()
    class Adapter:
        def __init__(self, items, orders): self.items, self.orders = items, orders
        def item_features(self, order_id):
            o = self.orders[order_id]
            return [(self.items[iid], qty) for iid, qty in o.item_list.items()]
    a = Adapter(items, orders)
    return {oid: sorter.sort_items(a, oid) for oid in orders.keys()}


# ───────────────────────── minimal feasibility + policy ───────────────────────── #

from src.heuristics.placers.base import StateView, FeasibilityService, Policy

class DummyFeasibility(FeasibilityService):
    """
    - fits_order_on_truck:
        • For reefers: needs cold, vol, weight residuals.
        • For dry: needs vol, weight. (cold checked via cooler_feasible if order has cold.)
    - cooler_feasible:
        • Allow cold-in-dry if order.cold_volume_m3 ≤ policy.per_truck_cooler_m3.
          (No tracking of “used cooler” in this tiny test.)
    """
    def fits_order_on_truck(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        f = state.order_features(order_id)
        r = state.truck_residuals(truck_id)
        tf = state.truck_features(truck_id)

        if tf.type == "reefer":
            return (r.remaining_cold_m3 >= f.cold_volume_m3 and
                    r.remaining_volume_m3 >= f.effective_volume_m3 and
                    r.remaining_weight_kg >= f.weight_kg)
        else:  # dry
            return (r.remaining_volume_m3 >= f.effective_volume_m3 and
                    r.remaining_weight_kg >= f.weight_kg)

    def cooler_feasible(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        f = state.order_features(order_id)
        need_cold = float(f.cold_volume_m3)
        cap = float(getattr(policy, "per_truck_cooler_m3", 0.0))
        return need_cold <= cap + 1e-9


class PolicyB(Policy):
    """Policy knobs for Bucket B tests."""
    allow_open_new_dry_B: bool = True
    per_truck_cooler_m3: float = 0.40   # allow ~0.40 m3 cold-in-dry


# ───────────────────────── scenarios ───────────────────────── #

def scenario_1_existing_reefer_wins():
    """
    Bucket B order: try existing reefer first (no opening).
    R1 has adequate cold/vol/weight → should assign to R1.
    """
    items = build_catalog()
    orders = build_orders(items)
    trucks = build_trucks()
    # Leave R1 largely empty so it fits.
    preset_residuals(trucks["R1"], used_v_eff=0.0, used_q_cold=0.0, used_w=0.0)

    depot = Depot(depot_id="D", location="X", available_trucks=trucks)
    open_ids = ["R1"]      # R1 is open
    sorted_items = build_sorted_items_provider(items, orders)
    state = SimpleStateView(depot=depot, orders=orders, open_truck_ids=open_ids, sorted_items_provider=sorted_items)

    decision = assign_bucket_b_order(
        state, DummyFeasibility(), PolicyB(), "O_B_MIX",
        packing_policy=SimplePackingPolicy()
    )
    print("[B-1] assign_bucket_b_order →", decision.truck_id if decision else None)


def scenario_2_fallback_to_open_dry_with_cooler():
    """
    No reefer fits (R1 has no cold left). Fall back to DRY:
    D1 is open and has volume/weight; cooler capacity is sufficient → assign to D1.
    """
    items = build_catalog()
    orders = build_orders(items)
    trucks = build_trucks()

    # R1 has zero cold residual (so it cannot take the Bucket B order)
    preset_residuals(trucks["R1"], used_q_cold=trucks["R1"].cold_capacity_m3)
    # D1 is open with enough vol/weight
    depot = Depot(depot_id="D", location="X", available_trucks=trucks)
    open_ids = ["D1"]      # only D1 open (dry)
    sorted_items = build_sorted_items_provider(items, orders)
    state = SimpleStateView(depot=depot, orders=orders, open_truck_ids=open_ids, sorted_items_provider=sorted_items)

    decision = assign_bucket_b_order(
        state, DummyFeasibility(), PolicyB(), "O_B_MIX",
        packing_policy=SimplePackingPolicy()
    )
    print("[B-2] assign_bucket_b_order →", decision.truck_id if decision else None)


def scenario_3_open_new_dry_if_allowed():
    """
    No reefer fits and no open dry fits, but policy allows opening dry.
    D2 is available (not open) → placer should return D2.
    """
    items = build_catalog()
    orders = build_orders(items)
    trucks = build_trucks()

    # R1: no cold left
    preset_residuals(trucks["R1"], used_q_cold=trucks["R1"].cold_capacity_m3)
    # D1 open but make it "full" on volume
    preset_residuals(trucks["D1"], used_v_eff=trucks["D1"].total_capacity_m3 * (1.0 - trucks["D1"].reserve_fraction))
    depot = Depot(depot_id="D", location="X", available_trucks=trucks)
    open_ids = ["D1"]       # D1 open (but full)
    sorted_items = build_sorted_items_provider(items, orders)
    state = SimpleStateView(depot=depot, orders=orders, open_truck_ids=open_ids, sorted_items_provider=sorted_items)

    decision = assign_bucket_b_order(
        state, DummyFeasibility(), PolicyB(), "O_B_MIX",
        packing_policy=SimplePackingPolicy()
    )
    print("[B-3] assign_bucket_b_order →", decision.truck_id if decision else None)


def scenario_4_disallow_open_new_dry_returns_none():
    """
    Same as scenario 3, but policy forbids opening a new dry → return None.
    """
    class PolicyNoOpen(PolicyB):
        allow_open_new_dry_B: bool = False

    items = build_catalog()
    orders = build_orders(items)
    trucks = build_trucks()

    # R1: no cold left
    preset_residuals(trucks["R1"], used_q_cold=trucks["R1"].cold_capacity_m3)
    # D1 open but "full"
    preset_residuals(trucks["D1"], used_v_eff=trucks["D1"].total_capacity_m3 * (1.0 - trucks["D1"].reserve_fraction))
    depot = Depot(depot_id="D", location="X", available_trucks=trucks)
    open_ids = ["D1"]
    sorted_items = build_sorted_items_provider(items, orders)
    state = SimpleStateView(depot=depot, orders=orders, open_truck_ids=open_ids, sorted_items_provider=sorted_items)

    decision = assign_bucket_b_order(
        state, DummyFeasibility(), PolicyNoOpen(), "O_B_MIX",
        packing_policy=SimplePackingPolicy()
    )
    print("[B-4] assign_bucket_b_order →", decision)


if __name__ == "__main__":
    print("=== best_fit_dry (Bucket B) tests ===")
    scenario_1_existing_reefer_wins()
    scenario_2_fallback_to_open_dry_with_cooler()
    scenario_3_open_new_dry_if_allowed()
    scenario_4_disallow_open_new_dry_returns_none()
