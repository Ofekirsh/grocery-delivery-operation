from __future__ import annotations
from typing import Dict, List
import json
from pathlib import Path
from datetime import datetime

from src.business_objects.customer_order import CustomerOrder
from src.heuristics.selectors.order_selector_vip_due import OrderLevelSelector
from src.heuristics.selectors.item_selector_priority import ItemLevelSorter
from src.heuristics.placers.packing import SimplePackingPolicy
from src.heuristics.placers.feasibility import SimpleFeasibility
from src.heuristics.placers.policy import SimplePolicy
from src.heuristics.placers.state_view import SimpleStateView
from src.planning.selection_orchestrator import SelectionOrchestrator
from src.planning.placer_orchestrator import PlacerOrchestrator
from src.quality_metrics.tracker import DayTracker
from src.business_objects.customer_order import load_orders_from_json_list
from src.heuristics.selectors.select_state import SelectionState
from scripts.utils import load_instance, build_sorted_items_map_from_logs

# ============================================================================
# CONFIGURATION
# ============================================================================

# Paths
INPUT_DIR = "../problems/problem_1"
OUTPUT_DIR = Path("../reports")
SELECTION_OUTPUT = OUTPUT_DIR / "selection"
PLACEMENT_OUTPUT = OUTPUT_DIR / "placement"

# Phase 1: Selection Schemes
ORDER_SCHEME = ("vip", "due", "alpha", "v_eff")
ITEM_SCHEME = ("cold", "weight", "v_eff", "liquid", "stack_limit", "fragile", "upright")

# Phase 2: Placement Policy
ALLOW_OPEN_NEW_REEFER_A = True
ALLOW_COLD_IN_DRY_B = True
PER_TRUCK_COOLER_M3 = 1.5
ALLOW_OPEN_NEW_DRY_C = True
ALPHA_THRESHOLD = 0.1

# Phase 2: Truck Ranking Schemes
REEFER_SCHEME_A = ("cold", "volume", "weight")
REEFER_SCHEME_B = ("cold", "volume", "weight")
DRY_SCHEME_B = ("volume", "weight")
DRY_SCHEME_C = ("volume", "weight")

# Departure Strategy
DEPART_STRATEGY = "min_util"  # or "time"
MIN_UTIL_SLACK = 0.0
DEPART_TIME = None  # or datetime object


# ============================================================================
# MAIN
# ============================================================================

def main():
    # Load instance
    depot, orders, customers, items = load_instance(INPUT_DIR)

    # Bind due_dt for selectors
    today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for o in orders.values():
        o.set_due_today(today0)

    # Initialize tracker
    tracker = DayTracker()

    # ========================================
    # PHASE 1: Select Next
    # ========================================
    sel_state = SelectionState(
        orders=orders,
        customers=customers,
        items=items,
        day_start=today0
    )

    order_selector = OrderLevelSelector(scheme=ORDER_SCHEME)
    item_sorter = ItemLevelSorter(scheme=ITEM_SCHEME)

    sel = SelectionOrchestrator(
        state=sel_state,
        tracker=tracker,
        order_selector=order_selector,
        item_sorter=item_sorter,
    )

    order_queue = sel.run(run_id="day-1", reset_logs=True)
    sel.export_reports(str(SELECTION_OUTPUT))

    sorted_items_provider = build_sorted_items_map_from_logs(tracker)

    # ========================================
    # PHASE 2: Place Next
    # ========================================
    state = SimpleStateView(
        depot=depot,
        orders=orders,
        open_truck_ids=[],
        sorted_items_provider=sorted_items_provider,
        customers=customers
    )

    policy = SimplePolicy(
        allow_open_new_reefer_A=ALLOW_OPEN_NEW_REEFER_A,
        allow_cold_in_dry_B=ALLOW_COLD_IN_DRY_B,
        per_truck_cooler_m3=PER_TRUCK_COOLER_M3,
        allow_open_new_dry_C=ALLOW_OPEN_NEW_DRY_C,
        alpha_threshold=ALPHA_THRESHOLD
    )
    feas = SimpleFeasibility()
    packing = SimplePackingPolicy()

    placer = PlacerOrchestrator(
        state=state,
        feas=feas,
        policy=policy,
        packing=packing,
        tracker=tracker,
        reefer_scheme_A=REEFER_SCHEME_A,
        reefer_scheme_B=REEFER_SCHEME_B,
        dry_scheme_B=DRY_SCHEME_B,
        dry_scheme_C=DRY_SCHEME_C,
    )

    placer.run_many(order_queue)

    placer.maybe_depart_trucks(
        strategy=DEPART_STRATEGY,
        min_util_slack=MIN_UTIL_SLACK,
        depart_time=DEPART_TIME
    )

    # ========================================
    # PHASE 3: Reports
    # ========================================
    snapshot = placer.finalize_day()

    placer.export_reports(str(PLACEMENT_OUTPUT))
    tracker.export_assignments_csv(str(PLACEMENT_OUTPUT / "assignments.csv"))
    tracker.export_order_status_csv(str(PLACEMENT_OUTPUT / "order_status.csv"))

    print(f"\n{'=' * 60}")
    print("Fleet KPIs:", snapshot["fleet"])
    print(f"{'=' * 60}\n")
    print(f"✓ Reports saved to: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()