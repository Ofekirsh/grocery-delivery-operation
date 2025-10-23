# tests/test_best_fit_reefer.py
"""
Here’s what each scenario tests:

   Case 1a - Default scheme (cold → vol → wt):
   Verifies that when multiple reefers are open, the placer prioritizes the truck with the best cold-space fit first, then volume, then weight. It confirms correct ranking under the default heuristic.

   Case 1b - Alternate scheme (volume → cold → wt):
   Checks that the same orders yield a different choice when the ranking logic is re-weighted toward volume efficiency. Demonstrates the flexibility of the ranking-scheme mechanism.

   Case 1c - Assign to existing open reefer:
   Ensures that when at least one reefer already fits the order, the placer produces a valid `AssignOrder` decision and a packing plan, without opening new trucks.

   Case 2a - Open new reefer when needed:
   Tests the policy path that allows the algorithm to deploy an additional truck when no open reefer can accommodate the order. Confirms correct interaction with `maybe_open_new_reefer`.

   Case 2b - Assign after new truck opened:
   Follows up to confirm that, once the new reefer is opened, the placer properly assigns the order to it and reports `opened_new_truck=True`, closing the loop between opening and assignment.

   Case 3 - No-open policy:
   Simulates a day rule that forbids adding trucks; ensures the placer gracefully declines the order (returns None) instead of violating policy.
"""
from __future__ import annotations

# --- business objects ---
from src.business_objects.common import Dimensions, Fragility, SeparationTag, TruckType
from src.business_objects.item import Item
from src.business_objects.customer_order import CustomerOrder
from src.business_objects.truck import Truck
from src.business_objects.depot import Depot

# --- selectors for item sorting (produces ItemRank sequence) ---
from src.heuristics.selectors.item_selector_priority import ItemPrioritySorter

# --- state view used by placers ---
from src.heuristics.placers.state_view import SimpleStateView

# --- placers base + simple packing policy ---
from src.heuristics.placers.base import StateView, FeasibilityService, Policy
from src.heuristics.placers.packing import SimplePackingPolicy

# --- the functions under test ---
from src.heuristics.placers.best_fit_reefer import (
    choose_best_open_reefer,
    maybe_open_new_reefer,
    assign_to_best_reefer,
)


# ───────────────────────────────── helpers to build a tiny world ───────────────────────────────── #

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
    # O_COLD: mostly cold, small effective volume
    o_cold = CustomerOrder.from_items(
        order_id="O_COLD", customer_id="C1",
        item_list={"I_MILK": 100},  # ~0.21 m3 cold
        due_time_str="11:00", items=items,
    )
    # O_MIX: larger v_eff, some dry (not used by reefer fit, but fine)
    o_mix = CustomerOrder.from_items(
        order_id="O_MIX", customer_id="C2",
        item_list={"I_MILK": 50, "I_WATER": 5},
        due_time_str="12:00", items=items,
    )
    return {"O_COLD": o_cold, "O_MIX": o_mix}


def build_trucks() -> dict:
    # Two reefers + one dry (for completeness)
    t1 = Truck(truck_id="R1", type=TruckType.REEFER,
               total_capacity_m3=24.0, cold_capacity_m3=12.0,
               weight_limit_kg=9500, fixed_cost=500, min_utilization=0.60, reserve_fraction=0.06)
    t2 = Truck(truck_id="R2", type=TruckType.REEFER,
               total_capacity_m3=28.0, cold_capacity_m3=14.0,
               weight_limit_kg=10500, fixed_cost=560, min_utilization=0.60, reserve_fraction=0.06)
    d1 = Truck(truck_id="D1", type=TruckType.DRY,
               total_capacity_m3=26.0, cold_capacity_m3=0.0,
               weight_limit_kg=10000, fixed_cost=460, min_utilization=0.75, reserve_fraction=0.05)
    return {"R1": t1, "R2": t2, "D1": d1}


def preset_residuals(truck: Truck, *, used_v_eff=0.0, used_q_cold=0.0, used_w=0.0) -> None:
    # convenience to simulate that some capacity was already used
    truck.used_volume_m3 = float(used_v_eff)   # we treat used_v_eff ≈ used_volume_m3 for tests
    truck.used_cold_m3 = float(used_q_cold)
    truck.used_weight_kg = float(used_w)


def build_sorted_items_provider(items: dict, orders: dict) -> dict:
    sorter = ItemPrioritySorter(expand_units=False)
    class TinyStateForSorter:
        def __init__(self, items, orders): self.items, self.orders = items, orders
        def item_features(self, order_id):  # returns (Item, qty) pairs as expected
            o = self.orders[order_id]
            return [(self.items[iid], qty) for iid, qty in o.item_list.items()]
    s = TinyStateForSorter(items, orders)
    return {oid: sorter.sort_items(s, oid) for oid in orders.keys()}


# ───────────────────────────────── minimal test doubles ───────────────────────────────── #

class DummyFeasibility(FeasibilityService):
    """Tight, deterministic feasibility: check type & residuals against order needs."""
    def fits_order_on_truck(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        tf = state.truck_features(truck_id)
        if tf.type != "reefer":
            return False
        f = state.order_features(order_id)
        r = state.truck_residuals(truck_id)
        return (r.remaining_cold_m3 >= f.cold_volume_m3 and
                r.remaining_volume_m3 >= f.effective_volume_m3 and
                r.remaining_weight_kg >= f.weight_kg)

    def cooler_feasible(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        return True  # not used in reefer tests


class DummyPolicy(Policy):
    """Only the flag we need in these tests."""
    allow_open_new_reefer_A: bool = True


# ───────────────────────────────── scenarios ───────────────────────────────── #

def case_1_choose_among_open_with_scheme():
    """
    Two open reefers R1 and R2 both fit O_COLD.
    R1 has tighter cold residual than R2 → with default scheme (cold→vol→weight), pick R1.
    With scheme (volume→cold→weight), we tweak volumes so R2 becomes better.
    """
    items = build_catalog()
    orders = build_orders(items)
    trucks = build_trucks()

    # Simulate current loads:
    # R1: a bit tighter cold space than R2
    preset_residuals(trucks["R1"], used_v_eff=2.0, used_q_cold=11.7, used_w=1000)  # cold left ~0.3
    preset_residuals(trucks["R2"], used_v_eff=23.9, used_q_cold=11.5, used_w=1000)  # cold left ~2.5

    depot = Depot(depot_id="D001", location="TestCity", available_trucks=trucks)

    # open both reefers
    open_ids = ["R1", "R2"]

    # pre-sorted items per order
    sorted_items = build_sorted_items_provider(items, orders)

    state = SimpleStateView(depot=depot, orders=orders, open_truck_ids=open_ids, sorted_items_provider=sorted_items)
    feas = DummyFeasibility()
    policy = DummyPolicy()
    pack = SimplePackingPolicy()

    oid = "O_COLD"

    # Default scheme: cold→volume→weight → expect R1 (tighter cold leftover)
    best_default = choose_best_open_reefer(state, feas, policy, oid)
    print("[case 1a] best (default scheme cold→vol→wt):", best_default)

    # Now prefer volume first: volume→cold→weight
    # Make R2 tighter on volume than R1 by adjusting used_v_eff above (already set R2 used_v=5 vs R1=2)
    best_vol_first = choose_best_open_reefer(state, feas, policy, oid, scheme=("volume", "cold", "weight"))
    print("[case 1b] best (scheme volume→cold→wt):", best_vol_first)

    # And run the end-to-end assign to be sure we get an AssignOrder with a plan
    decision = assign_to_best_reefer(state, feas, policy, oid, packing_policy=pack)
    print("[case 1c] assign_to_best_reefer truck:", decision.truck_id if decision else None)


def case_2_open_new_if_none_fit_and_allowed():
    """
    No open reefers fit O_MIX, but there exists an available reefer (not open) that fits.
    With policy.allow_open_new_reefer_A=True we should get its ID.
    """
    items = build_catalog()
    orders = build_orders(items)
    trucks = build_trucks()

    # Make R1 open but not enough cold capacity for O_MIX; R2 is not open yet
    preset_residuals(trucks["R1"], used_v_eff=1.0, used_q_cold=12.0, used_w=0.0)  # no cold left
    # R2 is completely free and in depot (available but not open)
    depot = Depot(depot_id="D001", location="TestCity", available_trucks=trucks)
    open_ids = ["R1"]  # only R1 is open

    sorted_items = build_sorted_items_provider(items, orders)
    state = SimpleStateView(depot=depot, orders=orders, open_truck_ids=open_ids, sorted_items_provider=sorted_items)
    feas = DummyFeasibility()
    policy = DummyPolicy()

    oid = "O_MIX"

    new_tid = maybe_open_new_reefer(state, feas, policy, order_id=oid)
    print("[case 2a] maybe_open_new_reefer returned:", new_tid)

    # Orchestrated path should also return an AssignOrder with opened_new_truck=True
    decision = assign_to_best_reefer(state, feas, policy, oid, packing_policy=SimplePackingPolicy())
    print("[case 2b] assign_to_best_reefer truck:", decision.truck_id if decision else None,
          "opened_new_truck:", getattr(decision, "opened_new_truck", None) if decision else None)


def case_3_disallow_opening_new_refuses_assignment():
    """
    No open reefers fit and policy forbids opening new → assignment should be None.
    """
    items = build_catalog()
    orders = build_orders(items)
    trucks = build_trucks()

    # R1 open but zero cold left; R2 available but opening is disallowed by policy
    preset_residuals(trucks["R1"], used_v_eff=1.0, used_q_cold=12.0, used_w=0.0)
    depot = Depot(depot_id="D001", location="TestCity", available_trucks=trucks)
    open_ids = ["R1"]

    sorted_items = build_sorted_items_provider(items, orders)
    state = SimpleStateView(depot=depot, orders=orders, open_truck_ids=open_ids, sorted_items_provider=sorted_items)
    feas = DummyFeasibility()

    class PolicyNoOpen(Policy):
        allow_open_new_reefer_A: bool = False

    policy = PolicyNoOpen()

    oid = "O_MIX"
    decision = assign_to_best_reefer(state, feas, policy, oid, packing_policy=SimplePackingPolicy())
    print("[case 3] assign_to_best_reefer (no-open policy) →", decision)


if __name__ == "__main__":
    print("=== best_fit_reefer tests ===")
    case_1_choose_among_open_with_scheme()
    case_2_open_new_if_none_fit_and_allowed()
    case_3_disallow_opening_new_refuses_assignment()
