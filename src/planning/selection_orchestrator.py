# src/planning/selection_orchestrator.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import os
import csv

from src.heuristics.selectors.order_selector_vip_due import OrderLevelSelector
from src.heuristics.selectors.item_selector_priority import ItemLevelSorter
from src.quality_metrics.tracker import DayTracker


@dataclass
class SelectionOrchestrator:
    """
    Phase-1 orchestrator: build and log the priority queues before placement.
      1) Rank orders globally (VIP → due → α → size, …)
      2) Rank items within each order (cold → weight → v_eff, …)
      3) Record both rankings to DayTracker for transparency and reproducibility.
    """
    state: Any
    tracker: DayTracker
    order_selector: OrderLevelSelector
    item_sorter: ItemLevelSorter

    _order_queue_ids: List[str] = field(default_factory=list, init=False, repr=False)
    _ranked_items_by_order: Dict[str, list] = field(default_factory=dict, init=False, repr=False)

    def run(self, *, run_id: Optional[str] = None, reset_logs: bool = True) -> List[str]:
        """
        Execute Phase-1 selection:
          - Rank all orders (OrderLevelSelector.rank_orders)
          - Rank items within each ranked order (ItemLevelSorter.rank_items)
          - Log both to DayTracker

        Returns:
            Ordered list of order_ids (your Phase-1 queue).
        """
        # ---- 1) Order ranking ----
        ranked_orders = self.order_selector.rank_orders(self.state)

        # capture selector meta safely
        selector_name = getattr(self.order_selector, "name", "order_selector")
        order_scheme = list(getattr(self.order_selector, "scheme", ()))  # e.g., ["vip","due","alpha","v_eff"]

        # record into tracker (append or reset per flag)
        self.tracker.record_order_queue(
            ranked_orders,
            selector_name=selector_name,
            order_scheme=order_scheme,
            run_id=run_id,
            reset=reset_logs,
        )

        # ---- 2) Item ranking per order ----
        sorter_name = getattr(self.item_sorter, "name", "item_sorter")
        item_scheme = list(getattr(self.item_sorter, "scheme", ()))  # e.g., ["cold01","w_ij","v_ij_eff",...]

        ordered_ids: List[str] = []
        ranked_items_by_order: Dict[str, list] = {}

        for row in ranked_orders:
            order_id = row.order_id
            ordered_ids.append(order_id)

            ranked_items = self.item_sorter.rank_items(self.state, order_id)
            ranked_items_by_order[order_id] = ranked_items

            item_rows = []
            for idx, ir in enumerate(ranked_items, start=1):
                f = ir.features or {}
                item_rows.append({
                    "rank": idx,
                    "item_id": ir.item_id,
                    "qty": int(ir.qty),
                    "cold01": float(f.get("cold01", 0.0)),
                    "w_ij": float(f.get("w_ij", 0.0)),
                    "v_ij_eff": float(f.get("v_ij_eff", 0.0)),
                    "liquid01": float(f.get("liquid01", 0.0)),
                    "stack_limit": float(f.get("stack_limit", 0.0)),
                    "fragile_score": float(f.get("fragile_score", 0.0)),
                    "upright01": float(f.get("upright01", 0.0)),
                    "sep_tag": str(f.get("sep_tag", "Non-Food")),
                    "sort_key": "",  # optional; fill if your sorter exposes it
                })

            self.tracker.record_item_queue(
                order_id,
                item_rows,
                sorter_name=sorter_name,
                item_scheme=item_scheme,
                run_id=run_id,
                reset=False,
            )

        # Stash results for Phase-2
        self._order_queue_ids = ordered_ids
        self._ranked_items_by_order = ranked_items_by_order

        return ordered_ids

        # ---------- getters for Phase-2 ----------

    def get_order_queue_ids(self) -> List[str]:
        """Order IDs in ranked sequence (Phase-1 output)."""
        return list(self._order_queue_ids)

    def get_ranked_items_map(self) -> Dict[str, list]:
        """Map[order_id -> ranked item rows] for use by packing/state adapters."""
        return dict(self._ranked_items_by_order)

    def export_reports(self, dirpath: str) -> Dict[str, str]:
        """
        Export Phase-1 selection results to CSV:
          - order_queue.csv  (global order ranking with meta columns)
          - item_rankings.csv (flattened per-order item ranking)

        Returns:
            dict(label -> filepath)
        """
        os.makedirs(dirpath, exist_ok=True)
        exported: Dict[str, str] = {}

        # Pull flattened logs from tracker
        sel_logs = self.tracker.selection_logs()
        order_rows = sel_logs.get("orders", [])
        item_rows = sel_logs.get("items", [])

        # ---- Order queue CSV ----
        order_fp = os.path.join(dirpath, "order_queue.csv")
        if order_rows:
            headers = list(order_rows[0].keys())
            with open(order_fp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                w.writeheader()
                w.writerows(order_rows)
        else:
            # create an empty file for consistency
            with open(order_fp, "w", newline="") as f:
                f.write("")
        exported["order_queue"] = order_fp

        # ---- Item rankings CSV ----
        item_fp = os.path.join(dirpath, "item_rankings.csv")
        if item_rows:
            headers = list(item_rows[0].keys())
            with open(item_fp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                w.writeheader()
                w.writerows(item_rows)
        else:
            with open(item_fp, "w", newline="") as f:
                f.write("")
        exported["item_rankings"] = item_fp

        return exported
