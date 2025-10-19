from __future__ import annotations

from dataclasses import dataclass
from .common import Dimensions, Fragility, SeparationTag


@dataclass
class Item:
    """
    Catalog item with handling and safety attributes.

    Notes
    -----
    - `unit_volume_m3` should ALREADY include any packaging padding you want to reserve
      (or rely on `padding_factor` to inflate it downstream).
    - `padding_factor` is a fractional extra space reservation (e.g., 0.05 for +5%).
    """
    item_id: str
    name: str
    category_cold: bool              # True → Cold, False → Dry
    unit_weight_kg: float
    unit_volume_m3: float
    dims_m: Dimensions
    fragility: Fragility
    max_stack_load_kg: float
    is_liquid: bool
    upright_only: bool
    separation_tag: SeparationTag
    padding_factor: float = 0.0      # fraction; applied by packing/planning layer

    def effective_unit_volume(self) -> float:
        """Volume inflated by padding (if any)."""
        return float(self.unit_volume_m3 * (1.0 + max(0.0, self.padding_factor)))
