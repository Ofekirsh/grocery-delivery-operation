from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass
class Candidate:
    """
    Selector output: which order to consider next, plus lightweight context.
    """
    order_id: str
    meta: Dict[str, Any]


class VipEarliestDueSelector:
    """
    Phase 1 selector: choose the next order by
      1) VIP first (True > False)
      2) Earliest due time (ascending)
      3) Optional tie-breakers: higher cold fraction / larger effective volume
      4) Stable final tie-break on order_id (lexicographic)

    Expectations (no helper shims; strict field names):
      - The planner `state` exposes:
          remaining_orders() -> Iterable[str]
          order_features(order_id) -> an object `f` with attributes:
              f.vip : bool
              f.due_dt : datetime            # must be set (bind 'HH:MM' to a date upstream)
              f.cold_fraction : float        # αᵢ ∈ [0,1]
              f.effective_volume_m3 : float  # vᵢᵉᶠᶠ
              f.weight_kg : float            # wᵢ
    """

    name: str = "vip_due"

    def __init__(
        self,
        *,
        prefer_high_alpha: bool = False,
        prefer_large: bool = False,
    ) -> None:
        """
        Args:
            prefer_high_alpha: among ties on VIP & due, prefer higher cold_fraction.
            prefer_large: among remaining ties, prefer larger effective volume.
        """
        self.prefer_high_alpha = prefer_high_alpha
        self.prefer_large = prefer_large

    def select_next(self, state: Any) -> Optional[Candidate]:
        order_ids: Iterable[str] = state.remaining_orders()
        order_ids = list(order_ids)
        if not order_ids:
            return None

        rows = []
        for oid in order_ids:
            f = state.order_features(oid)

            # Strict attribute access (no duck-typing helpers).
            vip: bool = bool(f.vip)
            due: datetime = f.due_dt
            if not isinstance(due, datetime):
                raise AttributeError("order_features(…) must provide a datetime in `due_dt`.")

            alpha: float = float(f.cold_fraction)
            v_eff: float = float(f.effective_volume_m3)
            weight: float = float(f.weight_kg)

            rows.append((oid, vip, due, alpha, v_eff, weight))

        # sort by: VIP desc → due asc → optional alpha desc → optional v_eff desc → order_id asc
        def sort_key(row: Tuple[str, bool, datetime, float, float, float]):
            oid, vip, due, alpha, v_eff, _w = row
            k_vip = -int(vip)                             # VIP first
            k_due = due                                   # earlier due first
            k_alpha = -alpha if self.prefer_high_alpha else 0.0
            k_veff = -v_eff if self.prefer_large else 0.0
            k_oid = oid                                   # stable fallback
            return (k_vip, k_due, k_alpha, k_veff, k_oid)

        rows.sort(key=sort_key)
        oid, vip, due, alpha, v_eff, weight = rows[0]

        meta = {
            "vip": vip,
            "due": due.strftime("%H:%M"),
            "alpha": alpha,
            "v_eff": v_eff,
            "weight": weight,
            "rule": "VIP→Due"
                    + ("+α" if self.prefer_high_alpha else "")
                    + ("+size" if self.prefer_large else ""),
        }
        return Candidate(order_id=oid, meta=meta)
