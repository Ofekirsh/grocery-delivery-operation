from datetime import datetime
from src.business_objects.item import Item
from src.business_objects.customer_order import CustomerOrder
from src.business_objects.common import Dimensions, Fragility, SeparationTag
from src.heuristics.selectors.order_selector_vip_due import VipEarliestDueSelector


# ─────────────────────────── helpers ─────────────────────────── #

class FeatureView:
    """Read-only view exposing exactly what the selector expects."""
    def __init__(self, *, vip: bool, due_dt: datetime, cold_fraction: float,
                 effective_volume_m3: float, weight_kg: float) -> None:
        self.vip = vip
        self.due_dt = due_dt
        self.cold_fraction = cold_fraction
        self.effective_volume_m3 = effective_volume_m3
        self.weight_kg = weight_kg


class TinyState:
    """
    Minimal state adapter exposing:
      - remaining_orders() -> Iterable[str]
      - order_features(order_id) -> FeatureView
    """
    def __init__(self, items, customers, orders):
        self.items = items
        self.customers = customers  # dict[cust_id] -> {"vip": bool}
        self.orders = orders        # dict[oid] -> CustomerOrder
        self._remaining = list(orders.keys())

        # bind each order's due_dt to today's date
        today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for o in self.orders.values():
            o.set_due_today(today0)

    def remaining_orders(self):
        return list(self._remaining)

    def order_features(self, order_id: str) -> FeatureView:
        o = self.orders[order_id]
        vip_flag = bool(self.customers[o.customer_id]["vip"])
        return FeatureView(
            vip=vip_flag,
            due_dt=o.due_dt,
            cold_fraction=o.cold_fraction,
            effective_volume_m3=o.effective_volume_m3,
            weight_kg=o.weight_kg,
        )

    # for this demo we remove selected orders to build the full queue
    def remove_order(self, order_id: str) -> None:
        self._remaining = [x for x in self._remaining if x != order_id]


def build_catalog() -> dict:
    return {
        "I_MILK": Item(
            item_id="I_MILK",
            name="Milk",
            category_cold=True,
            unit_weight_kg=1.05,
            unit_volume_m3=0.0021,
            dims_m=Dimensions(0.08, 0.08, 0.22),
            fragility=Fragility.DELICATE,
            max_stack_load_kg=5,
            is_liquid=True,
            upright_only=True,
            separation_tag=SeparationTag.FOOD,
            padding_factor=0.05,
        ),
        "I_TOWELS": Item(
            item_id="I_TOWELS",
            name="Paper Towels",
            category_cold=False,
            unit_weight_kg=1.2,
            unit_volume_m3=0.03,
            dims_m=Dimensions(0.30, 0.25, 0.25),
            fragility=Fragility.REGULAR,
            max_stack_load_kg=80,
            is_liquid=False,
            upright_only=False,
            separation_tag=SeparationTag.NON_FOOD,
            padding_factor=0.0,
        ),
        "I_WATER": Item(
            item_id="I_WATER",
            name="Bottled Water",
            category_cold=False,
            unit_weight_kg=9.6,
            unit_volume_m3=0.022,
            dims_m=Dimensions(0.25, 0.25, 0.35),
            fragility=Fragility.REGULAR,
            max_stack_load_kg=150,
            is_liquid=True,
            upright_only=False,
            separation_tag=SeparationTag.FOOD,
            padding_factor=0.0,
        ),
        "I_FISH": Item(
            item_id="I_FISH",
            name="Fresh Fish",
            category_cold=True,
            unit_weight_kg=1.4,
            unit_volume_m3=0.0028,
            dims_m=Dimensions(0.10, 0.20, 0.05),
            fragility=Fragility.DELICATE,
            max_stack_load_kg=5,
            is_liquid=False,
            upright_only=True,
            separation_tag=SeparationTag.FOOD,
            padding_factor=0.05,
        ),
    }


def build_customers() -> dict:
    # customer_id → {"vip": bool}
    return {
        "C001":{"vip":True},
        "C002":{"vip":False},
        "C003":{"vip":False},
        "C004":{"vip":False},
        "C005":{"vip":False}
    }


def build_orders(items: dict) -> dict:
    return {
        # VIP (will always come first regardless of tie-breakers)
        "O001": CustomerOrder.from_items(
            order_id="O001", customer_id="C001",
            item_list={"I_MILK": 2, "I_TOWELS": 1},
            due_time_str="12:00", items=items,
        ),

        # --- Tie case A: same VIP (False) and same due ("12:30"), different α ---
        # Higher α (cold-heavy): should win when prefer_high_alpha=True
        "O102": CustomerOrder.from_items(
            order_id="O102", customer_id="C002",
            item_list={"I_FISH": 2},       # cold → higher alpha
            due_time_str="12:30", items=items,
        ),
        # Lower α (dry-only): should lose when prefer_high_alpha=True
        "O101": CustomerOrder.from_items(
            order_id="O101", customer_id="C003",
            item_list={"I_TOWELS": 2},     # dry → alpha = 0
            due_time_str="12:30", items=items,
        ),

        # --- Tie case B: same VIP (False) and same due ("13:00"), same α (=0), different size ---
        # Larger v_eff (bottled water) should win when prefer_large=True
        "O201": CustomerOrder.from_items(
            order_id="O201", customer_id="C004",
            item_list={"I_WATER": 5},      # dry, big v_eff
            due_time_str="12:30", items=items,
        ),
        # Smaller v_eff (paper towels)
        "O202": CustomerOrder.from_items(
            order_id="O202", customer_id="C005",
            item_list={"I_TOWELS": 1},     # dry, smaller v_eff
            due_time_str="13:00", items=items,
        ),
    }



def build_priority_queue(state: TinyState, selector: VipEarliestDueSelector):
    """Repeatedly call the selector to build a full order queue."""
    queue = []
    while state.remaining_orders():
        cand = selector.select_next(state)
        if not cand:
            break
        queue.append((cand.order_id, cand.meta))
        state.remove_order(cand.order_id)
    return queue


if __name__ == "__main__":
    items = build_catalog()
    customers = build_customers()
    orders = build_orders(items)

    # Plain VIP→Due
    state_plain = TinyState(items, customers, orders)
    sel_plain = VipEarliestDueSelector()
    print("== VIP→Due priority queue ==")
    for oid, meta in build_priority_queue(state_plain, sel_plain):
        print(f"{oid}  vip={meta['vip']}  due={meta['due']}  α={meta['alpha']:.2f}  v_eff={meta['v_eff']:.4f}")

    # Prefer higher α in ties
    state_alpha = TinyState(items, customers, orders)
    sel_alpha = VipEarliestDueSelector(prefer_high_alpha=True)
    print("\n== VIP→Due + prefer higher α (cold fraction) in ties ==")
    for oid, meta in build_priority_queue(state_alpha, sel_alpha):
        print(f"{oid}  vip={meta['vip']}  due={meta['due']}  α={meta['alpha']:.2f}  v_eff={meta['v_eff']:.4f}")

    # Prefer larger v_eff in ties
    state_large = TinyState(items, customers, orders)
    sel_large = VipEarliestDueSelector(prefer_large=True)
    print("\n== VIP→Due + prefer larger v_eff in ties ==")
    for oid, meta in build_priority_queue(state_large, sel_large):
        print(f"{oid}  vip={meta['vip']}  due={meta['due']}  α={meta['alpha']:.2f}  v_eff={meta['v_eff']:.4f}")