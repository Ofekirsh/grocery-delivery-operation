# src/heuristics/placers/packing.py
from __future__ import annotations
from typing import Optional, List, Tuple, Dict, Any, Sequence

from .base import LoadingPlan, PackingPolicy, StateView
from src.heuristics.selectors.item_selector_priority import ItemRank


class SimplePackingPolicy(PackingPolicy):
    """
    STEP 1 (typed): consume pre-sorted Sequence[ItemRank] and map to slots.
    Single zone ('main'), lane 'left', layer 1. No geometry/constraints yet.
    """

    def plan(self, state: StateView, truck_id: str, order_id: str) -> Optional[LoadingPlan]:
        seq: Sequence[ItemRank] = state.sorted_items(order_id)  # must be ItemRank objects


        placements: List[Tuple[str, int, Dict[str, Any]]] = []
        notes: List[str] = [f"simple-pack: order {order_id} → truck {truck_id}, zone='main', layer=1"]

        # simple per-zone lane weights and top-layer counters
        lane_weight = {"cold": {"left": 0.0, "right": 0.0},
                       "ambient": {"left": 0.0, "right": 0.0},
                       "haz": {"left": 0.0, "right": 0.0}}
        top_layer_next = {"cold": 2, "ambient": 2, "haz": 2}  # start top at 2; floor is layer=1

        for idx, ir in enumerate(seq):
            if not isinstance(ir, ItemRank):
                raise TypeError("state.sorted_items(order_id) must return Sequence[ItemRank]")

            f = ir.features or {}
            # --- features with safe defaults ---
            w = float(f.get("w", 0.0))  # line weight
            q_cold = float(f.get("q_cold", 0.0))  # line cold volume
            fragile_score = float(f.get("fragile_score", 0))  # 0 regular, 1 delicate, 2 fragile
            upright01 = int(f.get("upright01", 0))  # 1 = upright-only
            sep_tag = str(f.get("sep_tag", "non_food")).lower()  # "hazardous"/"food"/"non_food"/...

            # --- zone selection (Separation + Cold) ---
            if sep_tag == "hazardous":
                zone = "haz"  # isolated
            elif q_cold > 0.0:
                zone = "cold"  # reefer zone
            else:
                zone = "ambient"

            # --- lane by balance (put weight on the lighter lane) ---
            left_w = lane_weight[zone]["left"]
            right_w = lane_weight[zone]["right"]
            lane = "left" if left_w <= right_w else "right"

            # --- layer: floor for most; fragile/upright to top layer ---
            if (fragile_score >= 1) or (upright01 == 1):
                layer = top_layer_next[zone]  # assign to current top layer
                top_layer_next[zone] = layer + 1  # grow top for later fragile/upright
                note_layer = "top"
            else:
                layer = 1  # floor/base
                note_layer = "floor"

            # record placement and update balance
            slot = {"zone": zone, "lane": lane, "layer": layer, "pos": idx}
            placements.append((ir.item_id, int(ir.qty), slot))
            lane_weight[zone][lane] += w

            # optional notes for debug/audit
            notes.append(
                f"{ir.item_id} x{ir.qty} → {zone}/{lane}/{note_layer} (w={w:.1f}, α>0? {q_cold > 0.0}, haz={sep_tag == 'hazardous'})")

        return LoadingPlan(placements=placements, notes=notes)
