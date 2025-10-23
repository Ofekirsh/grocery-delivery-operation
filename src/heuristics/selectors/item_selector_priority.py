# src/heuristics/selectors/item_selector_priority.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple, Literal


# ----------------------------- types -----------------------------

# Per-order, per-item ranked line used by placers (compatible with your StateView)
@dataclass
class ItemRank:
    item_id: str
    qty: int
    features: Dict[str, float]  # e.g., {"cold01":1, "w_ij":..., "v_ij_eff":..., ...}

# Full audit row (with rank and sort_key) for CSV/debug
@dataclass
class ItemRankRow:
    rank: int
    item_id: str
    qty: int
    cold01: float
    w_ij: float
    v_ij_eff: float
    liquid01: float
    stack_limit: float
    fragile_score: float
    upright01: float
    sort_key: Tuple


# Rank dimensions: default directions are fixed as noted
RankDim = Literal[
    "cold",         # cold01 ↓ (True first)
    "weight",       # w_ij ↓
    "v_eff",        # v_ij_eff ↓
    "liquid",       # liquid01 ↓ (True first)
    "stack_limit",  # stack_limit ↓
    "fragile",      # fragile_score ↑ (less fragile first)
    "upright",      # upright01 ↑ (non-upright first)
    "item_id"       # item_id ↑ (lexicographic)
]


class ItemLevelSorter:
    """
    Item-level priority sorter for a *single order*.

    You control the lexicographic priority via `scheme` (left→right).
    Directions are fixed per dimension:
      - "cold"        : cold01 desc (cold items first)
      - "weight"      : w_ij desc (heavier first)
      - "v_eff"       : v_ij_eff desc (larger first)
      - "liquid"      : liquid01 desc (liquids earlier)
      - "stack_limit" : stack_limit desc (can bear weight earlier)
      - "fragile"     : fragile_score asc (less fragile earlier)
      - "upright"     : upright01 asc (non-upright earlier)
      - "item_id"     : item_id asc (stable fallback)

    Expected state API (strict):
      state.item_features(order_id) -> Iterable[tuple[Item, int]]
        where Item exposes:
          - item_id: str
          - unit_weight_kg: float
          - unit_volume_m3: float
          - padding_factor: float
          - category_cold: bool
          - is_liquid: bool
          - max_stack_load_kg: float
          - upright_only: bool
          - fragility: enum/str containing "regular"/"delicate"/"fragile"
          - effective_unit_volume() -> float   (optional; otherwise derive via volume*(1+padding))
    """

    name: str = "item_level_sorter"

    def __init__(
        self,
        *,
        scheme: Sequence[RankDim] = ("cold", "weight", "v_eff", "liquid", "stack_limit", "fragile", "upright", "item_id"),
    ) -> None:
        self.scheme: Tuple[RankDim, ...] = tuple(scheme)
        self.last_rank_rows: List[ItemRankRow] = []

        allowed = {"cold", "weight", "v_eff", "liquid", "stack_limit", "fragile", "upright", "item_id"}
        seen = set()
        for d in self.scheme:
            if d not in allowed:
                raise ValueError(f"Unknown rank dimension '{d}'. Allowed: {sorted(allowed)}")
            if d in seen:
                raise ValueError(f"Duplicate rank dimension '{d}' in scheme.")
            seen.add(d)

    # ----------------------------- API -----------------------------

    def rank_items(self, state: Any, order_id: str) -> List[ItemRank]:
        """
        Compute the ranked sequence of items for `order_id`.
        Returns ItemRank list (for placers) and stores full rows in `last_rank_rows` for audit.
        """
        feats = self._get_item_features(state, order_id)
        rows_raw: List[Tuple[str, int, float, float, float, float, float, float, float]] = []
        # tuple layout: (item_id, qty, cold01, w_ij, v_ij_eff, liquid01, stack_limit, fragile_score, upright01)

        for item, qty in feats:
            iid = str(item.item_id)
            qty = int(qty)

            # weights/volumes per line item
            w_unit = float(item.unit_weight_kg)
            v_unit = float(getattr(item, "effective_unit_volume", None)()  # type: ignore
                           if hasattr(item, "effective_unit_volume")
                           else item.unit_volume_m3 * (1.0 + float(item.padding_factor)))
            v_nominal = float(item.unit_volume_m3)

            w_ij = qty * w_unit
            v_ij_eff = qty * v_unit
            cold01 = 1.0 if bool(item.category_cold) and v_nominal * qty > 0.0 else 0.0

            # handling attributes
            liquid01 = 1.0 if bool(item.is_liquid) else 0.0
            stack_limit = float(item.max_stack_load_kg)
            upright01 = 1.0 if bool(item.upright_only) else 0.0

            # fragility score: regular=0, delicate=1, fragile=2
            frag_text = str(getattr(item, "fragility", "regular")).lower()
            if "fragile" in frag_text and "very" in frag_text:
                fragile_score = 2.0
            elif "fragile" in frag_text:
                fragile_score = 2.0
            elif "delicate" in frag_text:
                fragile_score = 1.0
            else:
                fragile_score = 0.0

            rows_raw.append((iid, qty, cold01, w_ij, v_ij_eff, liquid01, stack_limit, fragile_score, upright01))

        # build keys per scheme, then sort
        keyed: List[Tuple[Tuple, Tuple]] = []
        for r in rows_raw:
            key = self._make_sort_key_tuple(r)
            keyed.append((key, r))

        keyed.sort(key=lambda x: x[0])

        # produce outputs
        self.last_rank_rows = []
        ranked: List[ItemRank] = []
        for i, (key, (iid, qty, cold01, w_ij, v_ij_eff, liquid01, stack_limit, fragile_score, upright01)) in enumerate(keyed):
            self.last_rank_rows.append(
                ItemRankRow(
                    rank=i + 1,
                    item_id=iid,
                    qty=qty,
                    cold01=float(cold01),
                    w_ij=float(w_ij),
                    v_ij_eff=float(v_ij_eff),
                    liquid01=float(liquid01),
                    stack_limit=float(stack_limit),
                    fragile_score=float(fragile_score),
                    upright01=float(upright01),
                    sort_key=key,
                )
            )
            ranked.append(
                ItemRank(
                    item_id=iid,
                    qty=qty,
                    features={
                        "cold01": float(cold01),
                        "w_ij": float(w_ij),
                        "v_ij_eff": float(v_ij_eff),
                        "liquid01": float(liquid01),
                        "stack_limit": float(stack_limit),
                        "fragile_score": float(fragile_score),
                        "upright01": float(upright01),
                    },
                )
            )

        return ranked

    # --------------------------- internals --------------------------

    def _make_sort_key_tuple(
        self,
        row: Tuple[str, int, float, float, float, float, float, float, float]
    ) -> Tuple:
        """
        Map the configured `scheme` to a lexicographic tuple.
        Directions are fixed as documented in the class docstring.
        """
        (iid, qty, cold01, w_ij, v_ij_eff, liquid01, stack_limit, fragile_score, upright01) = row

        key_parts: List[object] = []
        for dim in self.scheme:
            if dim == "cold":
                key_parts.append(-cold01)           # cold first
            elif dim == "weight":
                key_parts.append(-w_ij)             # heavier first
            elif dim == "v_eff":
                key_parts.append(-v_ij_eff)         # larger first
            elif dim == "liquid":
                key_parts.append(-liquid01)         # liquids earlier
            elif dim == "stack_limit":
                key_parts.append(-stack_limit)      # can bear more earlier
            elif dim == "fragile":
                key_parts.append(fragile_score)     # less fragile earlier
            elif dim == "upright":
                key_parts.append(upright01)         # non-upright earlier
            elif dim == "item_id":
                key_parts.append(iid)               # stable fallback
        return tuple(key_parts)

    @staticmethod
    def _get_item_features(state: Any, order_id: str) -> Iterable[Tuple[Any, int]]:
        """
        Strict adapter: require (Item, qty) pairs from state.
        """
        if not hasattr(state, "item_features") or not callable(state.item_features):
            raise AttributeError("state must expose item_features(order_id) -> Iterable[(Item, int)]")
        feats = state.item_features(order_id)
        return feats
