from __future__ import annotations
from dataclasses import dataclass

@dataclass
class SimplePolicy:
    """
    Minimal day-level knobs read by placers.
    Add fields here gradually as you need them.
    """

    # Bucket A (cold-mandatory) — can we open a new reefer if none of the open ones fit?
    allow_open_new_reefer_A: bool = True

    # (for later, Bucket B cold-in-dry logic; unused by reefer placer step)
    allow_cold_in_dry_B: bool = False
    per_truck_cooler_m3: float = 0.0

    # (for later, Bucket C tie-break preference)
    day_bottleneck: str = "volume"   # or "weight"
