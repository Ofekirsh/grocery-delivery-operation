from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, List

from .base import StateView
from src.business_objects.truck import Truck, TruckType
from src.business_objects.customer_order import CustomerOrder
from src.business_objects.depot import Depot
from src.heuristics.selectors.item_selector_priority import ItemRank


@dataclass(frozen=True)
class OrderFeat:
    effective_volume_m3: float
    cold_volume_m3: float
    weight_kg: float


@dataclass(frozen=True)
class TruckFeat:
    type: str  # "reefer" or "dry"


@dataclass(frozen=True)
class TruckResiduals:
    remaining_volume_m3: float
    remaining_cold_m3: float
    remaining_weight_kg: float


class SimpleStateView(StateView):
    """
    Thin, read-only adapter over your business objects.

    You provide:
      - depot: Depot with available_trucks
      - orders: dict[order_id -> CustomerOrder] with aggregates already computed
      - open_truck_ids: which trucks are currently "open" (deployed)
      - sorted_items_provider: dict[order_id -> Sequence[ItemRank]] (from your ItemPrioritySorter)
    """

    def __init__(
        self,
        *,
        depot: Depot,
        orders: Dict[str, CustomerOrder],
        open_truck_ids: Iterable[str],
        sorted_items_provider: Dict[str, Sequence[ItemRank]],
    ) -> None:
        self._depot = depot
        self._orders = orders
        self._open = set(open_truck_ids)
        self._sorted = sorted_items_provider  # order_id -> Sequence[ItemRank]

    # ------------------------ StateView protocol ------------------------ #

    def order_features(self, order_id: str) -> OrderFeat:
        o = self._orders[order_id]
        return OrderFeat(
            effective_volume_m3=float(o.effective_volume_m3),
            cold_volume_m3=float(o.cold_volume_m3),
            weight_kg=float(o.weight_kg),
        )

    def truck_features(self, truck_id: str) -> TruckFeat:
        t = self._truck(truck_id)
        kind = "reefer" if t.type == TruckType.REEFER else "dry"
        return TruckFeat(type=kind)

    def truck_residuals(self, truck_id: str) -> TruckResiduals:
        t = self._truck(truck_id)
        # Use your Truck convenience residuals (honors reserve_fraction for volume)
        return TruckResiduals(
            remaining_volume_m3=float(t.residual_volume_m3()),
            remaining_cold_m3=float(t.residual_cold_m3()),
            remaining_weight_kg=float(t.residual_weight_kg()),
        )

    def open_trucks(self, *, type_filter: Optional[str] = None) -> Iterable[str]:
        if type_filter is None:
            return list(self._open)
        return [tid for tid in self._open if self._type_str(tid) == type_filter]

    def all_available_trucks(self, *, type_filter: Optional[str] = None) -> Iterable[str]:
        ids = list(self._depot.available_trucks.keys())
        if type_filter is None:
            return ids
        return [tid for tid in ids if self._type_str(tid) == type_filter]

    # ---------------------- Used by packing policy ---------------------- #

    def sorted_items(self, order_id: str) -> Sequence[ItemRank]:
        """
        Pre-sorted items for this order (produced by your ItemPrioritySorter).
        The packing policy consumes this and only decides slots (zone/lane/layer).
        """
        return self._sorted[order_id]

    # ----------------------------- internals ---------------------------- #

    def _truck(self, truck_id: str) -> Truck:
        return self._depot.get_truck(truck_id)

    def _type_str(self, truck_id: str) -> str:
        t = self._truck(truck_id)
        return "reefer" if t.type == TruckType.REEFER else "dry"
