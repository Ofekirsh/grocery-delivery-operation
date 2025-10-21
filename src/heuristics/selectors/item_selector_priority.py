from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass
class ItemRank:
    item_id: str
    qty: int
    features: Dict[str, float]


class ItemPrioritySorter:
    """
    Item-level priority sort for a chosen order (i).
    Produces a stable sequence that reflects bottom→top / back→front loading.

    Sorting keys (in this order):
      1) cold-first:          1[q_ij_cold > 0]          (desc)
      2) heavier first:       w_ij                      (desc)
      3) larger first:        v_ij_eff                  (desc)
      4) liquids earlier:     liquid_ij                 (desc, True > False)
      5) can bear weight:     stack_limit_ij            (desc)
      6) less fragile first:  fragile_ij                (asc; non-fragile first)
      7) non-upright first:   upright_ij                (asc; True means later)

    Duck-typing expectations on `state`:
      - state.item_features(order_id) -> Iterable[feat], where each feat exposes at least:
          product_id/item_id (str) via one of: item_id, product_id, pid
          qty (int) via one of: qty, quantity, count
          q_ij_cold (float) via one of: q_cold, q_ij_cold, cold_volume
          w_ij (float) via one of: weight, w, w_ij
          v_ij_eff (float) via one of: v_eff, v_ij_eff, effective_volume
          liquid (bool) via one of: is_liquid, liquid
          stack_limit (float) via one of: max_stack_load_kg, stack_limit
          fragile flag/score via one of: fragile, fragility_level (map text→score)
          upright (bool) via one of: upright, upright_only
    """

    name: str = "item_priority"

    def __init__(self, *, expand_units: bool = False) -> None:
        """
        Args:
            expand_units: if True, repeat each item_id 'qty' times in the result sequence.
                          if False (default), return (item_id, qty) pairs in sorted order.
        """
        self.expand_units = expand_units

    def sort_items(self, state: Any, order_id: str) -> List[Tuple[str, int]]:
        feats = self._get_item_features(state, order_id)
        if not feats:
            return []

        rows: List[Tuple[str, int, float, float, float, int, float, int, int]] = []
        # tuple: (item_id, qty, cold01, w, v_eff, liquid01, stack_limit, fragile_score, upright01)

        for item, qty in feats:  # feats: Iterable[tuple[Item, int]]
            iid = item.item_id
            qty = int(qty)

            # per-order totals for this line item
            w = qty * float(item.unit_weight_kg)
            unit_v_eff = float(item.effective_unit_volume() if hasattr(item, "effective_unit_volume")
                               else item.unit_volume_m3 * (1.0 + float(item.padding_factor)))
            v_eff = qty * unit_v_eff
            cold_vol = qty * float(item.unit_volume_m3) if item.category_cold else 0.0

            # handling attributes straight from Item
            liquid = bool(item.is_liquid)
            stack_limit = float(item.max_stack_load_kg)
            upright = bool(item.upright_only)

            # simple numeric score: regular=0, delicate=1, fragile=2
            if hasattr(item, "fragility") and item.fragility is not None:
                frag = str(item.fragility).lower()
            else:
                frag = "regular"
            fragile_score = 2.0 if "fragile" in frag and "very" in frag else (
                2.0 if "fragile" in frag else (1.0 if "delicate" in frag else 0.0))

            cold01 = 1.0 if cold_vol > 0.0 else 0.0
            liquid01 = 1 if liquid else 0
            upright01 = 1 if upright else 0

            rows.append((iid, qty, cold01, w, v_eff, liquid01, stack_limit, fragile_score, upright01))

        # sort by: cold desc → weight desc → v_eff desc → liquid desc → stack_limit desc → fragile asc → upright asc → item_id asc
        rows.sort(key=lambda r: (
            -r[2],          # cold01 desc
            -r[3],          # w desc
            -r[4],          # v_eff desc
            -r[5],          # liquid desc
            -r[6],          # stack_limit desc
            r[7],           # fragile_score asc (less fragile first)
            r[8],           # upright01 asc (non-upright first)
            r[0],           # stable by item_id
        ))

        if not self.expand_units:
            return [(iid, qty) for (iid, qty, *_rest) in rows]

        expanded: List[Tuple[str, int]] = []
        for iid, qty, *_ in rows:
            expanded.extend([(iid, 1)] * max(0, qty))
        return expanded

    # ------------------------------ internals ------------------------------ #

    @staticmethod
    def _get_item_features(state: Any, order_id: str) -> Iterable[Any]:
        if hasattr(state, "item_features") and callable(state.item_features):
            return state.item_features(order_id)
        raise AttributeError("state must expose item_features(order_id) -> iterable of feature objects")



