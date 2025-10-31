"""Utility functions for loading instances and reconstructing data."""

from typing import Dict, List
import json
from pathlib import Path
from src.business_objects.customer_order import load_orders_from_json_list, CustomerOrder
from src.business_objects.customer import Customer
from src.business_objects.common import TruckType
from src.business_objects.truck import Truck
from src.business_objects.depot import Depot
from src.business_objects.item import Item
from src.heuristics.selectors.item_selector_priority import ItemRank


def build_sorted_items_map_from_logs(tracker) -> Dict[str, List[ItemRank]]:
    """
    Reconstruct per-order ranked items from DayTracker selection logs.
    Returns: dict[order_id] -> List[ItemRank] (already in ranked order).
    """
    out: Dict[str, List[ItemRank]] = {}
    # tracker.selection_logs() returns {"orders": [...], "items": [...]}
    item_rows = tracker.selection_logs().get("items", [])
    # rows already include "order_id" and a "rank" column
    # group then sort and rebuild ItemRank objects
    by_order: Dict[str, List[dict]] = {}
    for row in item_rows:
        by_order.setdefault(row["order_id"], []).append(row)

    for oid, rows in by_order.items():
        rows.sort(key=lambda r: int(r["rank"]))
        rebuilt: List[ItemRank] = []
        for r in rows:
            rebuilt.append(
                ItemRank(
                    item_id=str(r["item_id"]),
                    qty=int(r["qty"]),
                    features={
                        "cold01": float(r["cold01"]),
                        "w_ij": float(r["w_ij"]),
                        "v_ij_eff": float(r["v_ij_eff"]),
                        "liquid01": float(r["liquid01"]),
                        "stack_limit": float(r["stack_limit"]),
                        "fragile_score": float(r["fragile_score"]),
                        "upright01": float(r["upright01"]),
                        "sep_tag": str(r["sep_tag"])
                    },
                )
            )
        out[oid] = rebuilt
    return out


def load_instance(base_dir: str = "../problems/problem_1"):
    """
    Load depot, trucks, customers, items, and orders from generated JSONs.

    Returns:
        depot: Depot
        orders: dict[str, CustomerOrder]
        customers: dict[str, Customer]
        items: dict[str, Item]
    """
    base = Path(base_dir)
    if not base.exists():
        raise FileNotFoundError(f"{base} not found")

    # === Depots ===
    depots_data = json.load((base / "depots.json").open())
    depot_entry = depots_data[0]  # assuming one depot
    depot_id = depot_entry["depot_id"]
    depot_location = depot_entry.get("location", "unknown")
    depot_available_trucks =depot_entry["available_trucks"]

    # === Trucks ===
    trucks_data = json.load((base / "trucks.json").open())
    trucks = {}
    for t in trucks_data:
        trucks[t["truck_id"]] = Truck(
            truck_id=t["truck_id"],
            type=TruckType[t["type"].upper()],           # "Reefer"/"Dry" → enum
            total_capacity_m3=t["total_capacity_m3"],
            cold_capacity_m3=t.get("cold_capacity_m3", 0.0),
            weight_limit_kg=t["weight_limit_kg"],
            fixed_cost=t.get("fixed_cost", 0.0),
            min_utilization=t.get("min_utilization", 0.0),
            reserve_fraction=t.get("reserve_fraction", 0.0),
            cooler_capacity_m3=t.get("cooler_capacity_m3", 0.0),

        )
    available_trucks_for_depot = {
        truck_id: trucks[truck_id]
        for truck_id in depot_available_trucks
        if truck_id in trucks
    }

    depot = Depot(
        depot_id=depot_id,
        location=depot_location,
        available_trucks=available_trucks_for_depot,
    )

    # === Items ===
    items_data = json.load((base / "items.json").open())
    items = {i["item_id"]: Item(**i) for i in items_data}

    # === Customers ===
    customers_path = base / "customers.json"
    customers: dict[str, Customer] = {}
    if customers_path.exists():
        customers_data = json.load(customers_path.open())
        for c in customers_data:
            customers[c["customer_id"]] = Customer(
                customer_id=c["customer_id"],
                name=c.get("name", ""),
                email=c.get("email", ""),
                vip=bool(c.get("vip", False) or c.get("VIP", False)),  # tolerate either key
                address=c.get("address", ""),
            )

    # === Orders ===
    orders_data = json.load((base / "orders.json").open())
    orders: dict[str, CustomerOrder] = load_orders_from_json_list(orders_data, items)

    return depot, orders, customers, items