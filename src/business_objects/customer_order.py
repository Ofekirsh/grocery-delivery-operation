from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Mapping
from .item import Item



@dataclass
class CustomerOrder:
    """
    A daily order placed by a customer.

    Aggregates
    -----------
    qᵢ           = total volume (m³)
    qᵢᶜᵒˡᵈ       = total cold volume (m³)
    wᵢ           = total weight (kg)
    vᵢᵉᶠᶠ        = effective (padded) volume (m³)
    αᵢ           = cold fraction = qᵢᶜᵒˡᵈ / qᵢ

    Fields
    -------
    item_list : dict(product_id -> quantity)
        Items composing this order.
    """

    # Identifiers
    order_id: str
    customer_id: str

    # Items
    item_list: Dict[str, int]

    # Time window
    due_time_str: str

    # Aggregates (computed)
    total_volume_m3: float = 0.0
    cold_volume_m3: float = 0.0
    weight_kg: float = 0.0
    effective_volume_m3: float = 0.0
    cold_fraction: float = 0.0  # αᵢ ∈ [0,1]

    # Runtime
    due_dt: Optional[datetime] = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------ #
    # Time utilities
    # ------------------------------------------------------------------ #

    def set_due_today(self, day_start: datetime) -> None:
        """Bind the 'HH:MM' due time to a specific date (day_start's date)."""
        hh, mm = map(int, self.due_time_str.split(":"))
        self.due_dt = day_start.replace(hour=hh, minute=mm, second=0, microsecond=0)

    @property
    def is_cold(self) -> bool:
        return self.cold_volume_m3 > 0.0

    # ------------------------------------------------------------------ #
    # Aggregation logic
    # ------------------------------------------------------------------ #

    def compute_from_items(self, items: Mapping[str, Item]) -> None:
        """
        Compute (qᵢ, qᵢᶜᵒˡᵈ, wᵢ, vᵢᵉᶠᶠ, αᵢ) from item_list and product catalog.
        """
        q_i = 0.0
        q_i_cold = 0.0
        w_i = 0.0
        v_i_eff = 0.0

        for pid, qty in self.item_list.items():
            if qty <= 0:
                continue
            if pid not in items:
                raise KeyError(f"Item '{pid}' not found in catalog for order '{self.order_id}'.")

            prod = items[pid]
            unit_vol = float(prod.unit_volume_m3)
            unit_wt = float(prod.unit_weight_kg)
            unit_v_eff = float(prod.effective_unit_volume()) if hasattr(prod, "effective_unit_volume") else unit_vol

            q_ij = qty * unit_vol
            w_ij = qty * unit_wt
            v_ij_eff = qty * unit_v_eff

            q_i += q_ij
            w_i += w_ij
            v_i_eff += v_ij_eff

            if getattr(prod, "category_cold", False):
                q_i_cold += q_ij

        self.total_volume_m3 = q_i
        self.cold_volume_m3 = q_i_cold
        self.weight_kg = w_i
        self.effective_volume_m3 = v_i_eff
        self.cold_fraction = (q_i_cold / q_i) if q_i > 1e-12 else 0.0  # αᵢ

        if self.cold_fraction < 0.0 or self.cold_fraction > 1.0:
            raise ValueError(f"Computed cold fraction αᵢ={self.cold_fraction:.2f} out of [0,1] range.")

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #

    def totals_dict(self) -> Dict[str, float]:
        """Return computed aggregates for logging or CSV export."""
        return {
            "q_i_total_volume_m3": float(self.total_volume_m3),
            "q_i_cold_volume_m3": float(self.cold_volume_m3),
            "w_i_weight_kg": float(self.weight_kg),
            "v_i_eff_volume_m3": float(self.effective_volume_m3),
            "alpha_i_cold_fraction": float(self.cold_fraction),
        }

    @classmethod
    def from_items(
        cls,
        order_id: str,
        customer_id: str,
        item_list: Dict[str, int],
        due_time_str: str,
        items: Mapping[str, Item],
    ) -> "CustomerOrder":
        """Convenience constructor that auto-computes all aggregates."""
        obj = cls(order_id=order_id, customer_id=customer_id, item_list=item_list, due_time_str=due_time_str)
        obj.compute_from_items(items)
        return obj

    # ------------------------------------------------------------------ #
    # JSON constructors
    # ------------------------------------------------------------------ #
    @classmethod
    def from_json(
        cls,
        data: dict,
        items: Mapping[str, Item],
        *,
        recompute: bool = True,
    ) -> "CustomerOrder":
        """
        Build a CustomerOrder from a JSON dict.

        Expected keys (export-compatible):
            - "order_id": str
            - "customer_id": str
            - "item_list" OR "items": {item_id: qty, ...}
            - "due_time_str": "HH:MM"

        Options:
            recompute: if True (default), recompute all aggregates (qᵢ, qᵢᶜᵒˡᵈ, wᵢ, vᵢᵉᶠᶠ, αᵢ)
                       from the provided `items` catalog, ignoring any aggregate
                       numbers that might be present in the JSON.

        Notes on notation:
            qᵢ        = total volume (m³)
            qᵢᶜᵒˡᵈ    = cold volume (m³)
            wᵢ        = weight (kg)
            vᵢᵉᶠᶠ     = effective (padded) volume (m³)
            αᵢ        = cold fraction = qᵢᶜᵒˡᵈ / qᵢ
        """
        oid = str(data["order_id"])
        cid = str(data["customer_id"])

        # Accept either "item_list" or "items" in JSON
        raw_items = data.get("item_list") or data.get("items")
        if not isinstance(raw_items, dict):
            raise TypeError("orders JSON must include 'item_list' (or 'items') as a dict of item_id -> qty")

        # Coerce all quantities to int and ids to str
        ilist: Dict[str, int] = {}
        for k, v in raw_items.items():
            ilist[str(k)] = int(v)

        due = str(data.get("due_time_str") or data.get("due") or "23:59")

        obj = cls(
            order_id=oid,
            customer_id=cid,
            item_list=ilist,
            due_time_str=due,
        )

        if recompute:
            obj.compute_from_items(items)
        else:
            # If you really want to trust saved aggregates in JSON:
            obj.total_volume_m3 = float(data.get("total_volume_m3", obj.total_volume_m3))
            obj.cold_volume_m3 = float(data.get("cold_volume_m3", obj.cold_volume_m3))
            obj.weight_kg = float(data.get("weight_kg", obj.weight_kg))
            obj.effective_volume_m3 = float(data.get("effective_volume_m3", obj.effective_volume_m3))
            if obj.total_volume_m3 > 1e-12:
                obj.cold_fraction = obj.cold_volume_m3 / obj.total_volume_m3
            else:
                obj.cold_fraction = 0.0

        return obj

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def __post_init__(self) -> None:
        if not isinstance(self.item_list, dict):
            raise TypeError("item_list must be a dict mapping item_id -> quantity.")
        for pid, qty in self.item_list.items():
            if not isinstance(pid, str):
                raise TypeError("item_list keys must be item_id strings.")
            if not isinstance(qty, int):
                raise TypeError("item_list values must be integer quantities.")


def load_orders_from_json_list(json_list: list[dict], items: Mapping[str, Item]) -> dict[str, CustomerOrder]:
    orders: dict[str, CustomerOrder] = {}
    for rec in json_list:
        o = CustomerOrder.from_json(rec, items, recompute=True)
        orders[o.order_id] = o
    return orders
