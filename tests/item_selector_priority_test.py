from src.business_objects.item import Item
from src.business_objects.customer_order import CustomerOrder
from src.heuristics.selectors.item_selector_priority import ItemPrioritySorter
from src.business_objects.common import Dimensions, Fragility, SeparationTag


class TinyState:
    def __init__(self, items, orders):
        self.items = items
        self.orders = orders

    # ItemPrioritySorter expects (item, qty) pairs
    def item_features(self, order_id: str):
        order = self.orders[order_id]
        return [(self.items[iid], qty) for iid, qty in order.item_list.items()]


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
        "I_BLEACH": Item(
            item_id="I_BLEACH",
            name="Bleach 4L",
            category_cold=False,
            unit_weight_kg=4.3,
            unit_volume_m3=0.006,
            dims_m=Dimensions(0.15, 0.15, 0.30),
            fragility=Fragility.REGULAR,
            max_stack_load_kg=60,
            is_liquid=True,
            upright_only=True,
            separation_tag=SeparationTag.HAZARDOUS,
            padding_factor=0.0,
        ),
    }


def build_orders(items: dict) -> dict:
    return {
        "O001": CustomerOrder.from_items(
            order_id="O001",
            customer_id="C001",
            item_list={"I_MILK": 2, "I_TOWELS": 1, "I_WATER": 1},
            due_time_str="12:00",
            items=items,   # NOTE: use 'products' if that's the parameter name in your code
        ),
        "O002": CustomerOrder.from_items(
            order_id="O002",
            customer_id="C002",
            item_list={"I_FISH": 3, "I_WATER": 2},
            due_time_str="14:00",
            items=items,
        ),
        "O003": CustomerOrder.from_items(
            order_id="O003",
            customer_id="C003",
            item_list={"I_TOWELS": 2, "I_BLEACH": 1},
            due_time_str="15:30",
            items=items,
        ),
    }


def make_state() -> TinyState:
    items = build_catalog()
    orders = build_orders(items)
    return TinyState(items, orders)


def print_sorted_for_orders(state: TinyState, sorter: ItemPrioritySorter, order_ids) -> None:
    for oid in order_ids:
        print(f"\nSorted items for order {oid}:")
        sorted_items = sorter.sort_items(state, oid)
        for iid, qty in sorted_items:
            print(f"  {iid:10s}  qty={qty}")


if __name__ == "__main__":
    state = make_state()
    sorter = ItemPrioritySorter(expand_units=False)
    print_sorted_for_orders(state, sorter, ["O001", "O002", "O003"])
