from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple, Union

from .common import TruckType


# -------------------------
# Helper: time validation
# -------------------------

def _validate_hhmm(s: str, *, field_name: str) -> None:
    try:
        datetime.strptime(s, "%H:%M")
    except ValueError as e:
        raise ValueError(f"{field_name} must be 'HH:MM' (24h). Got '{s}'.") from e


# -------------------------
# Items (catalog) config
# -------------------------

@dataclass
class ItemGenConfig:
    """
    Controls generation of the item (catalog) table.
    Later we can add ItemSpec[] for explicit, hand-crafted items.
    """
    num_items: int = 12
    cold_ratio: float = 0.40                 # fraction of items that are cold
    weight_kg: Tuple[float, float] = (0.5, 10.0)
    volume_m3: Tuple[float, float] = (0.001, 0.020)
    padding: Tuple[float, float] = (0.00, 0.10)  # padding factor range [0..1]

    def validate(self) -> None:
        if not (0.0 <= self.cold_ratio <= 1.0):
            raise ValueError("items.cold_ratio must be in [0,1].")
        lo, hi = self.weight_kg
        if not (0 < lo <= hi):
            raise ValueError("items.weight_kg must satisfy 0 < min <= max.")
        lo, hi = self.volume_m3
        if not (0 < lo <= hi):
            raise ValueError("items.volume_m3 must satisfy 0 < min <= max.")
        lo, hi = self.padding
        if not (0.0 <= lo <= hi <= 1.0):
            raise ValueError("items.padding must satisfy 0 <= min <= max <= 1.")


# -------------------------
# Customers config
# -------------------------

@dataclass
class CustomerGenConfig:
    """
    Controls generation of customers.
    """
    num_customers: int = 10
    vip_fraction: float = 0.25               # probability each customer is VIP

    def validate(self) -> None:
        if not (0.0 <= self.vip_fraction <= 1.0):
            raise ValueError("customers.vip_fraction must be in [0,1].")
        if self.num_customers < 1:
            raise ValueError("customers.num_customers must be >= 1.")


# -------------------------
# Orders config
# -------------------------

@dataclass
class OrderGenConfig:
    """
    Controls generation of orders (daily).
    - items_per_order: number of DISTINCT item types per order
    - qty_per_item: quantity range per item type (inclusive)
    - due window: earliest..latest, both 'HH:MM', latest <= '22:00' by your requirement
    """
    num_orders: int = 20
    items_per_order: Tuple[int, int] = (2, 4)
    qty_per_item: Tuple[int, int] = (1, 4)
    earliest_due: str = "10:00"
    latest_due: str = "22:00"
    max_cold_fraction: float = 0.60          # optional clamp on α_i

    def validate(self) -> None:
        if self.num_orders < 0:
            raise ValueError("orders.num_orders must be >= 0.")
        a, b = self.items_per_order
        if not (1 <= a <= b):
            raise ValueError("orders.items_per_order must satisfy 1 <= min <= max.")
        qa, qb = self.qty_per_item
        if not (1 <= qa <= qb):
            raise ValueError("orders.qty_per_item must satisfy 1 <= min <= max.")
        _validate_hhmm(self.earliest_due, field_name="orders.earliest_due")
        _validate_hhmm(self.latest_due, field_name="orders.latest_due")
        if self.earliest_due > self.latest_due:
            raise ValueError("orders.earliest_due must be <= orders.latest_due.")
        if not (0.0 <= self.max_cold_fraction <= 1.0):
            raise ValueError("orders.max_cold_fraction must be in [0,1].")


# -------------------------
# Trucks config
# -------------------------

@dataclass
class TruckSpec:
    """
    Explicit truck definition (overrides the template/range generation if provided).
    - For DRY trucks, set cold_capacity_m3 = 0.
    """
    id: str
    type: TruckType
    total_capacity_m3: float
    weight_limit_kg: float
    fixed_cost: float
    min_utilization: float
    reserve_fraction: float
    cold_capacity_m3: float = 0.0            # ignored for DRY

    def validate(self) -> None:
        if self.type == TruckType.DRY and self.cold_capacity_m3 not in (0, 0.0):
            raise ValueError(f"TruckSpec {self.id}: DRY trucks must have cold_capacity_m3 = 0.")
        if not (0.0 <= self.reserve_fraction < 1.0):
            raise ValueError(f"TruckSpec {self.id}: reserve_fraction must be in [0,1).")
        if not (0.0 <= self.min_utilization <= 1.0):
            raise ValueError(f"TruckSpec {self.id}: min_utilization must be in [0,1].")
        if self.total_capacity_m3 <= 0 or self.weight_limit_kg <= 0:
            raise ValueError(f"TruckSpec {self.id}: capacities and weight must be > 0.")


@dataclass
class TruckGenConfig:
    """
    Template/range-based generation for trucks, with an optional explicit override list.

    If `truck_specs` is provided and non-empty, it is used as-is and the counts/ranges are ignored.
    """
    num_trucks_cold: int = 2
    num_trucks_dry: int = 2

    total_capacity_m3: Tuple[float, float] = (20.0, 35.0)
    cold_capacity_m3: Tuple[float, float] = (8.0, 15.0)     # only for cold trucks
    weight_limit_kg: Tuple[float, float] = (8000.0, 12000.0)
    fixed_cost: Tuple[float, float] = (380.0, 620.0)
    reserve_fraction: Tuple[float, float] = (0.05, 0.08)

    min_util_cold: float = 0.60
    min_util_dry: float = 0.75

    truck_specs: List[TruckSpec] = field(default_factory=list)  # explicit trucks

    def validate(self) -> None:
        lo, hi = self.total_capacity_m3
        if not (0 < lo <= hi):
            raise ValueError("trucks.total_capacity_m3 must satisfy 0 < min <= max.")
        lo, hi = self.cold_capacity_m3
        if not (0 < lo <= hi):
            raise ValueError("trucks.cold_capacity_m3 must satisfy 0 < min <= max.")
        lo, hi = self.weight_limit_kg
        if not (0 < lo <= hi):
            raise ValueError("trucks.weight_limit_kg must satisfy 0 < min <= max.")
        lo, hi = self.fixed_cost
        if not (0 < lo <= hi):
            raise ValueError("trucks.fixed_cost must satisfy 0 < min <= max.")
        lo, hi = self.reserve_fraction
        if not (0.0 <= lo <= hi < 1.0):
            raise ValueError("trucks.reserve_fraction must satisfy 0 <= min <= max < 1.")
        if not (0.0 <= self.min_util_cold <= 1.0):
            raise ValueError("trucks.min_util_cold must be in [0,1].")
        if not (0.0 <= self.min_util_dry <= 1.0):
            raise ValueError("trucks.min_util_dry must be in [0,1].")
        for spec in self.truck_specs:
            spec.validate()


# -------------------------
# Depots config
# -------------------------

@dataclass
class DepotGenConfig:
    """
    Controls depot creation and which trucks are available today.
    availability:
      - "all": expose all trucks as available
      - ("sample", k): randomly sample k trucks as available (<= total)
    """
    num_depots: int = 1
    availability: object = "all"   # str or tuple

    def validate(self) -> None:
        if self.num_depots < 1:
            raise ValueError("depots.num_depots must be >= 1.")
        if isinstance(self.availability, tuple):
            if len(self.availability) != 2 or self.availability[0] != "sample":
                raise ValueError("depots.availability tuple must be ('sample', k).")
            k = self.availability[1]
            if not (isinstance(k, int) and k >= 1):
                raise ValueError("depots.availability sample k must be an integer >= 1.")
        elif self.availability != "all":
            raise ValueError("depots.availability must be 'all' or ('sample', k).")


# -------------------------
# Top-level instance config
# -------------------------

@dataclass
class InstanceGenConfig:
    """
    Top-level configuration for instance generation.

    This class is flexible: you can pass sub-configs either as actual
    dataclass instances OR as plain dicts, e.g.:

        InstanceGenConfig(
            items=dict(num_items=18, cold_ratio=0.5),
            customers=dict(num_customers=12, vip_fraction=0.3),
            orders=dict(num_orders=20, items_per_order=(2,4), qty_per_item=(1,4),
                        earliest_due="09:00", latest_due="22:00"),
            trucks=dict(
                num_trucks_cold=2, num_trucks_dry=3,
                truck_specs=[  # dicts or TruckSpec objects both work
                    dict(id="T101", type="Reefer", total_capacity_m3=24, cold_capacity_m3=12,
                         weight_limit_kg=9500, fixed_cost=520, min_utilization=0.6, reserve_fraction=0.06),
                ]
            ),
            depots=dict(num_depots=1, availability="all"),
        )
    """
    seed: int = 123
    items: Union[ItemGenConfig, dict] = field(default_factory=ItemGenConfig)
    customers: Union[CustomerGenConfig, dict] = field(default_factory=CustomerGenConfig)
    orders: Union[OrderGenConfig, dict] = field(default_factory=OrderGenConfig)
    trucks: Union[TruckGenConfig, dict] = field(default_factory=TruckGenConfig)
    depots: Union[DepotGenConfig, dict] = field(default_factory=DepotGenConfig)

    # Coerce dicts → dataclasses for nested configs
    def __post_init__(self):
        if isinstance(self.items, dict):
            self.items = ItemGenConfig(**self.items)
        if isinstance(self.customers, dict):
            self.customers = CustomerGenConfig(**self.customers)
        if isinstance(self.orders, dict):
            self.orders = OrderGenConfig(**self.orders)
        if isinstance(self.trucks, dict):
            self.trucks = TruckGenConfig(**self.trucks)
        if isinstance(self.depots, dict):
            self.depots = DepotGenConfig(**self.depots)

    def validate(self) -> None:
        if not isinstance(self.seed, int):
            raise ValueError("seed must be an integer.")
        self.items.validate()
        self.customers.validate()
        self.orders.validate()
        self.trucks.validate()
        self.depots.validate()
