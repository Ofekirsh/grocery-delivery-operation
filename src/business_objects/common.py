from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class TruckType(str, Enum):
    """Supported truck types."""
    REEFER = "Reefer"
    DRY = "Dry"


class Fragility(str, Enum):
    """Fragility classes for handling and stacking logic."""
    REGULAR = "Regular"
    DELICATE = "Delicate"
    FRAGILE = "Fragile"


class SeparationTag(str, Enum):
    """
    Basic segregation tags for safety and food rules.
    Extend as needed (e.g., RAW / RTE) at the routing/packing layers.
    """
    FOOD = "Food"
    NON_FOOD = "Non-Food"
    ALLERGEN = "Allergen"
    HAZARDOUS = "Hazardous"


@dataclass(frozen=True)
class Dimensions:
    """
    Physical dimensions in meters (length × width × height).
    Use for 3D placement or basic footprint checks (future module).
    """
    L: float
    W: float
    H: float

    def volume_m3(self) -> float:
        """Geometric volume in cubic meters."""
        return float(self.L * self.W * self.H)

    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.L, self.W, self.H)
