# src/heuristics/selectors/order_selector_vip_due.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Tuple, Sequence, Literal


# ---- configurable ranking dimensions (lexicographic, left→right) ----
RankDim = Literal["vip", "due", "alpha", "v_eff", "weight", "order_id"]


@dataclass
class OrderRankRow:
    """
    A single line in the ranked order queue (for audit/CSV).
    `sort_key` is the exact tuple used for lexicographic sorting.
    """
    rank: int
    order_id: str
    vip: bool
    due: str          # "HH:MM"
    alpha: float      # cold fraction
    v_eff: float
    weight: float
    sort_key: Tuple


class OrderLevelSelector:
    """
    Generic order-level selector that ranks all open orders
    according to a configurable priority `scheme` (e.g., ("vip", "due", "alpha", "v_eff")).

    You control the priority with `scheme`, a sequence of RankDim:
        - "vip"      : VIP first (True before False)          ↓ (desc as -int(vip))
        - "due"      : earlier due-time first                 ↑ (ascending datetime)
        - "alpha"    : higher cold fraction first             ↓
        - "v_eff"    : larger effective volume first          ↓
        - "weight"   : heavier first                          ↓
        - "order_id" : lexicographic tiebreaker               ↑

    Example default (classic behavior): ("vip", "due", "alpha", "v_eff", "order_id")
    """

    def __init__(
        self,
        *,
        scheme: Sequence[RankDim] = ("vip", "due", "alpha", "v_eff", "order_id"),
    ) -> None:
        self.scheme: Tuple[RankDim, ...] = tuple(scheme)
        self.last_rank: List[OrderRankRow] = []

        # quick sanity: no duplicates, only known dims
        allowed = {"vip", "due", "alpha", "v_eff", "weight", "order_id"}
        seen = set()
        for d in self.scheme:
            if d not in allowed:
                raise ValueError(f"Unknown rank dimension '{d}'. Allowed: {sorted(allowed)}")
            if d in seen:
                raise ValueError(f"Duplicate rank dimension '{d}' in scheme.")
            seen.add(d)

    # ------------------------- public API ------------------------- #

    def rank_orders(self, state: Any) -> List[OrderRankRow]:
        """
        Build and store the full ranked queue.

        Expects `state` to expose:
          - remaining_orders() -> Iterable[str]
          - order_features(order_id) -> object f with:
                f.vip : bool
                f.due_dt : datetime
                f.cold_fraction : float
                f.effective_volume_m3 : float
                f.weight_kg : float
        """
        order_ids = list(state.remaining_orders())
        if not order_ids:
            self.last_rank = []
            return self.last_rank

        rows = []
        for oid in order_ids:
            f = state.order_features(oid)

            # strict fields (fail fast if missing)
            vip: bool = bool(f.vip)
            due: datetime = f.due_dt
            if not isinstance(due, datetime):
                raise AttributeError("order_features(...).due_dt must be a datetime")

            alpha: float = float(f.cold_fraction)
            v_eff: float = float(f.effective_volume_m3)
            weight: float = float(f.weight_kg)

            key = self._make_sort_key(oid, vip, due, alpha, v_eff, weight)
            rows.append((oid, vip, due, alpha, v_eff, weight, key))

        rows.sort(key=lambda r: r[-1])

        self.last_rank = [
            OrderRankRow(
                rank=i + 1,
                order_id=oid,
                vip=vip,
                due=due.strftime("%H:%M"),
                alpha=alpha,
                v_eff=v_eff,
                weight=weight,
                sort_key=key,
            )
            for i, (oid, vip, due, alpha, v_eff, weight, key) in enumerate(rows)
        ]
        return self.last_rank

    # ------------------------ internals -------------------------- #

    def _make_sort_key(
        self,
        oid: str,
        vip: bool,
        due: datetime,
        alpha: float,
        v_eff: float,
        weight: float,
    ) -> Tuple:
        """
        Map the configured `scheme` to a lexicographic tuple.
        Directions (fixed): vip↓, due↑, alpha↓, v_eff↓, weight↓, order_id↑
        """
        key_parts: List[object] = []
        for dim in self.scheme:
            if dim == "vip":
                key_parts.append(-int(vip))        # True first
            elif dim == "due":
                key_parts.append(due)              # earlier first
            elif dim == "alpha":
                key_parts.append(-alpha)           # higher first
            elif dim == "v_eff":
                key_parts.append(-v_eff)           # larger first
            elif dim == "weight":
                key_parts.append(-weight)          # heavier first
            elif dim == "order_id":
                key_parts.append(oid)              # lexicographic
        return tuple(key_parts)
