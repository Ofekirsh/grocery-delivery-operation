# src/heuristic/selectors/selection_state.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Tuple, Iterator

from src.business_objects.customer_order import CustomerOrder
from src.business_objects.customer import Customer
from src.business_objects.item import Item


@dataclass(frozen=True)
class _OrderFeatView:
    vip: bool
    due_dt: datetime
    cold_fraction: float
    effective_volume_m3: float
    weight_kg: float


class SelectionState:
    """
    Read-only adapter used by Phase-1 selectors.

    Exposes:
      - remaining_orders() -> Iterable[str]
      - remove_order(order_id)        # optional convenience
      - order_features(order_id) -> object with fields:
            vip, due_dt, cold_fraction, effective_volume_m3, weight_kg
      - item_features(order_id) -> Iterable[(Item, int)]
    """

    def __init__(
        self,
        *,
        orders: Dict[str, CustomerOrder],
        customers: Dict[str, Customer],
        items: Dict[str, Item],
        day_start: datetime,
    ) -> None:
        self._orders = orders
        self._customers = customers
        self._items = items
        self._remaining: List[str] = list(orders.keys())

        # ensure due_dt is bound (HH:MM -> today) for all orders
        for o in self._orders.values():
            if o.due_dt is None:
                o.set_due_today(day_start)

    # ------------------- selector-facing API ------------------- #

    def remaining_orders(self) -> Iterable[str]:
        # return a copy to keep it read-only for callers
        return list(self._remaining)

    def remove_order(self, order_id: str) -> None:
        if order_id in self._remaining:
            self._remaining.remove(order_id)

    def order_features(self, order_id: str) -> _OrderFeatView:
        o = self._orders[order_id]
        c = self._customers.get(o.customer_id)
        vip = bool(c.vip) if c is not None else False

        return _OrderFeatView(
            vip=vip,
            due_dt=o.due_dt,  # set in __init__
            cold_fraction=float(o.cold_fraction),
            effective_volume_m3=float(o.effective_volume_m3),
            weight_kg=float(o.weight_kg),
        )

    def item_features(self, order_id: str) -> Iterable[Tuple[Item, int]]:
        """
        What the ItemLevelSorter expects: an iterable of (Item, qty) pairs.
        """
        o = self._orders[order_id]
        def _iter() -> Iterator[Tuple[Item, int]]:
            for iid, qty in o.item_list.items():
                yield (self._items[iid], int(qty))
        return _iter()
