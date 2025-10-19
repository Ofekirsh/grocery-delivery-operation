# src/bussnes_objects/generators.py
from __future__ import annotations
import os
import json
from datetime import datetime

import random
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Dict, Mapping, Tuple, List

from .common import Dimensions, Fragility, SeparationTag, TruckType
from .item import Item
from .customer import Customer
from .customer_order import CustomerOrder
from .truck import Truck
from .depot import Depot
from .config import (
    InstanceGenConfig,
    TruckSpec,
)


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def make_objects(cfg: InstanceGenConfig) -> Dict[str, object]:
    """
    Generate a complete synthetic instance guided by `cfg`.
    Returns a dict with keys: depots, customers, orders, items, trucks.

    Steps:
      1) Items catalog
      2) Customers (with vip_fraction)
      3) Orders (items per order, qty per item; due in [earliest..latest] and ≤ 22:00)
      4) Trucks (template ranges or explicit TruckSpec overrides)
      5) Depots (availability policy: all or sample)
    """
    cfg.validate()
    rng = random.Random(cfg.seed)

    items = _gen_items(rng, cfg)
    customers = _gen_customers(rng, cfg)
    orders = _gen_orders(rng, cfg, customers=customers, items=items)
    trucks = _gen_trucks(rng, cfg)
    depots = _gen_depots(rng, cfg, trucks=trucks)

    return {
        "depots": depots,
        "customers": customers,
        "orders": orders,
        "items": items,
        "trucks": trucks,
    }


# -------------------------------------------------------------------
# Items
# -------------------------------------------------------------------

def _gen_items(rng: random.Random, cfg: InstanceGenConfig) -> Dict[str, Item]:
    itcfg = cfg.items
    items: Dict[str, Item] = {}
    for i in range(1, itcfg.num_items + 1):
        iid = f"I{i:03d}"
        is_cold = rng.random() < itcfg.cold_ratio
        weight = round(rng.uniform(*itcfg.weight_kg), 2)
        vol = round(rng.uniform(*itcfg.volume_m3), 4)
        pad = round(rng.uniform(*itcfg.padding), 2)

        items[iid] = Item(
            item_id=iid,
            name=f"Item_{i}",
            category_cold=is_cold,
            unit_weight_kg=weight,
            unit_volume_m3=vol,
            dims_m=Dimensions(0.2, 0.2, 0.2),
            fragility=rng.choice(list(Fragility)),
            max_stack_load_kg=rng.choice([5, 10, 20, 50, 100, 150]),
            is_liquid=(rng.random() < 0.2),
            upright_only=(rng.random() < 0.2),
            separation_tag=rng.choice(list(SeparationTag)),
            padding_factor=pad,
        )
    return items


# -------------------------------------------------------------------
# Customers
# -------------------------------------------------------------------

def _gen_customers(rng: random.Random, cfg: InstanceGenConfig) -> Dict[str, Customer]:
    ccfg = cfg.customers
    customers: Dict[str, Customer] = {}
    for i in range(1, ccfg.num_customers + 1):
        cid = f"C{i:03d}"
        customers[cid] = Customer(
            customer_id=cid,
            name=f"Customer_{i}",
            email=f"customer{i}@example.com",
            vip=(rng.random() < ccfg.vip_fraction),
            address=f"Street {i}, City",
        )
    return customers


# -------------------------------------------------------------------
# Orders
# -------------------------------------------------------------------

def _rand_time_between(rng: random.Random, start_hhmm: str, end_hhmm: str) -> str:
    base = datetime.now().replace(second=0, microsecond=0)
    s = datetime.strptime(start_hhmm, "%H:%M").replace(year=base.year, month=base.month, day=base.day)
    e = datetime.strptime(end_hhmm, "%H:%M").replace(year=base.year, month=base.month, day=base.day)
    # clamp to ensure s <= e
    if e < s:
        e = s
    total_minutes = int((e - s).total_seconds() // 60)
    offset = rng.randint(0, max(0, total_minutes))
    return (s + timedelta(minutes=offset)).strftime("%H:%M")


def _gen_orders(
    rng: random.Random,
    cfg: InstanceGenConfig,
    *,
    customers: Mapping[str, Customer],
    items: Mapping[str, Item],
) -> Dict[str, CustomerOrder]:
    ocfg = cfg.orders
    all_customers = list(customers.values())
    item_ids = list(items.keys())
    orders: Dict[str, CustomerOrder] = {}

    for i in range(1, ocfg.num_orders + 1):
        oid = f"O{i:04d}"
        cust = rng.choice(all_customers)

        # number of DISTINCT item types per order
        k_types = rng.randint(*ocfg.items_per_order)
        k_types = min(k_types, len(item_ids))
        chosen = rng.sample(item_ids, k_types)

        # quantity per item type (inclusive range)
        item_list: Dict[str, int] = {iid: rng.randint(*ocfg.qty_per_item) for iid in chosen}

        # due time in [earliest_due, latest_due] and (by your rule) latest ≤ 22:00
        due_str = _rand_time_between(rng, ocfg.earliest_due, ocfg.latest_due)

        # build order and compute aggregates from items
        order = CustomerOrder(
            order_id=oid,
            customer_id=cust.customer_id,
            item_list=item_list,
            due_time_str=due_str,
        )
        order.compute_from_items(items)

        # optional clamp cold fraction (αᵢ) if requested
        if order.total_volume_m3 > 1e-9:
            max_cf = ocfg.max_cold_fraction
            if order.cold_fraction > max_cf:
                order.cold_volume_m3 = max_cf * order.total_volume_m3
                order.cold_fraction = max_cf

        orders[oid] = order

    return orders


# -------------------------------------------------------------------
# Trucks
# -------------------------------------------------------------------

def _gen_trucks(rng: random.Random, cfg: InstanceGenConfig) -> Dict[str, Truck]:
    tcfg = cfg.trucks

    # If explicit specs are provided, use them exactly.
    if tcfg.truck_specs:
        trucks: Dict[str, Truck] = {}
        for spec in tcfg.truck_specs:
            _add_truck_from_spec(trucks, spec)
        return trucks

    # Otherwise, generate from template counts & ranges.
    trucks: Dict[str, Truck] = {}
    # Cold (reefer) trucks
    for i in range(1, tcfg.num_trucks_cold + 1):
        tid = f"TR{i:03d}"
        total = round(rng.uniform(*tcfg.total_capacity_m3), 1)
        cold = round(rng.uniform(*tcfg.cold_capacity_m3), 1)
        trucks[tid] = Truck(
            truck_id=tid,
            type=TruckType.REEFER,
            total_capacity_m3=total,
            cold_capacity_m3=cold,
            weight_limit_kg=round(rng.uniform(*tcfg.weight_limit_kg), 1),
            fixed_cost=round(rng.uniform(*tcfg.fixed_cost), 2),
            min_utilization=tcfg.min_util_cold,
            reserve_fraction=round(rng.uniform(*tcfg.reserve_fraction), 2),
        )

    # Dry trucks
    for i in range(1, tcfg.num_trucks_dry + 1):
        tid = f"TD{i:03d}"
        total = round(rng.uniform(*tcfg.total_capacity_m3), 1)
        trucks[tid] = Truck(
            truck_id=tid,
            type=TruckType.DRY,
            total_capacity_m3=total,
            cold_capacity_m3=0.0,
            weight_limit_kg=round(rng.uniform(*tcfg.weight_limit_kg), 1),
            fixed_cost=round(rng.uniform(*tcfg.fixed_cost), 2),
            min_utilization=tcfg.min_util_dry,
            reserve_fraction=round(rng.uniform(*tcfg.reserve_fraction), 2),
        )
    return trucks


def _add_truck_from_spec(trucks: Dict[str, Truck], spec: TruckSpec) -> None:
    trucks[spec.id] = Truck(
        truck_id=spec.id,
        type=spec.type,
        total_capacity_m3=spec.total_capacity_m3,
        cold_capacity_m3=(spec.cold_capacity_m3 if spec.type == TruckType.REEFER else 0.0),
        weight_limit_kg=spec.weight_limit_kg,
        fixed_cost=spec.fixed_cost,
        min_utilization=spec.min_utilization,
        reserve_fraction=spec.reserve_fraction,
    )


# -------------------------------------------------------------------
# Depots
# -------------------------------------------------------------------

def _gen_depots(rng: random.Random, cfg: InstanceGenConfig, *, trucks: Mapping[str, Truck]) -> Dict[str, Depot]:
    dcfg = cfg.depots
    depots: Dict[str, Depot] = {}

    all_truck_ids = list(trucks.keys())
    for i in range(1, dcfg.num_depots + 1):
        did = f"D{i:03d}"

        if dcfg.availability == "all":
            avail_ids = all_truck_ids
        elif isinstance(dcfg.availability, tuple) and dcfg.availability[0] == "sample":
            k = min(dcfg.availability[1], len(all_truck_ids))
            avail_ids = rng.sample(all_truck_ids, k)
        else:
            # Fallback safety; config.validate() should prevent reaching here
            avail_ids = all_truck_ids

        depots[did] = Depot(
            depot_id=did,
            location=f"Depot_{i} City",
            available_trucks={tid: trucks[tid] for tid in avail_ids},
        )

    return depots


# -------------------------------------------------------------------
# Optional: JSON helpers (handy if you want to export)
# -------------------------------------------------------------------

def export_as_jsonable_dicts(objs: Dict[str, object]) -> Dict[str, List[dict]]:
    """
    Convert generated dataclass objects into plain dicts so you can dump to JSON.
    Runtime fields on Truck and datetime fields on Order are stripped.
    """
    depots = []
    for d in objs["depots"].values():
        depots.append({
            "depot_id": d.depot_id,
            "location": d.location,
            "available_trucks": list(d.available_trucks.keys()),
        })

    customers = [asdict(c) for c in objs["customers"].values()]

    orders = []
    for o in objs["orders"].values():
        data = asdict(o)
        data.pop("due_dt", None)
        orders.append(data)

    items = [asdict(it) for it in objs["items"].values()]

    trucks = []
    for t in objs["trucks"].values():
        td = asdict(t)
        # strip runtime fields
        td.pop("assigned_orders", None)
        td.pop("used_volume_m3", None)
        td.pop("used_cold_m3", None)
        td.pop("used_weight_kg", None)
        td.pop("departure_time", None)
        td.pop("schedule", None)
        trucks.append(td)

    return {
        "depots": depots,
        "customers": customers,
        "orders": orders,
        "items": items,
        "trucks": trucks,
    }


def save_json_files(objs: Dict[str, object], output_dir: str) -> None:
    """
    Save generated business objects as separate JSON files inside a given directory.

    Creates:
        items.json
        customers.json
        orders.json
        trucks.json
        depots.json

    Parameters
    ----------
    objs : Dict[str, object]
        Dictionary returned from `make_objects(cfg)`.
    output_dir : str
        Name or path of directory to save files into.
        (If it does not exist, it will be created.)
    """
    # Convert all dataclasses → plain dicts
    jsonable = export_as_jsonable_dicts(objs)

    # Ensure directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Loop over each category and dump JSON
    for name, data in jsonable.items():
        filename = os.path.join(output_dir, f"{name}.json")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(data)} records to {filename}")
