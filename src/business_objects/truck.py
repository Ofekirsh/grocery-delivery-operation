from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from .common import TruckType


@dataclass
class Truck:
    """
    Vehicle resource with capacity, cold-chain, and utilization policy.

    The scheduling/assignment layers can write to the runtime fields:
    - assigned_orders
    - used_volume_m3 / used_cold_m3 / used_weight_kg
    - departure_time / schedule
    """
    truck_id: str
    type: TruckType
    total_capacity_m3: float
    cold_capacity_m3: float          # 0 for DRY
    weight_limit_kg: float
    fixed_cost: float
    min_utilization: float           # τ_min
    reserve_fraction: float          # r (fraction of volume intentionally kept unused)

    # runtime (mutable) fields populated by planners:
    assigned_orders: List[str] = field(default_factory=list, repr=False)
    used_volume_m3: float = field(default=0.0, repr=False)
    used_cold_m3: float = field(default=0.0, repr=False)
    used_weight_kg: float = field(default=0.0, repr=False)
    departure_time: Optional[str] = field(default=None, repr=False)
    schedule: List[Tuple[str, str]] = field(default_factory=list, repr=False)  # (order_id, eta 'HH:MM')

    cooler_capacity_m3: float = 0.0  # optional, used for dry trucks with built-in coolers
    # ---------- convenience ----------
    def residual_volume_m3(self) -> float:
        """Remaining usable volume after reserve is honored."""
        available = self.total_capacity_m3 * (1.0 - max(0.0, self.reserve_fraction))
        return max(0.0, available - self.used_volume_m3)

    def residual_cold_m3(self) -> float:
        if self.type == TruckType.DRY:
            return 0.0
        return max(0.0, self.cold_capacity_m3 - self.used_cold_m3)

    def residual_weight_kg(self) -> float:
        return max(0.0, self.weight_limit_kg - self.used_weight_kg)

    def utilization(self) -> float:
        if self.total_capacity_m3 <= 0:
            return 0.0
        return float(self.used_volume_m3 / self.total_capacity_m3)

    def reset_runtime(self) -> None:
        """Clear all mutable, per-day fields."""
        self.assigned_orders.clear()
        self.used_volume_m3 = 0.0
        self.used_cold_m3 = 0.0
        self.used_weight_kg = 0.0
        self.departure_time = None
        self.schedule.clear()
