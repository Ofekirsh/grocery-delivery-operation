# src/heuristics/placers/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple


@dataclass
class LoadingPlan:
    """
    Result of within-truck packing for a single order.
    This can start simple (one logical zone/layer) and grow later.

    placements: arbitrary structure you define, e.g. list of (item_id, qty, slot)
    notes:      human-readable hints for debugging / audits
    """
    placements: List[Tuple[str, int, Dict[str, Any]]]
    notes: List[str]


@dataclass
class AssignOrder:
    """
    High-level action emitted by a Placer.
    The runner will call state.apply(AssignOrder) (or similar) to commit it.
    """
    order_id: str
    truck_id: str
    packing: LoadingPlan
    rationale: Any = ""  # why this truck / tie-break details
    opened_new_truck: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Minimal protocol views (duck-typed) so placers don’t depend on concrete classes
# Joke - A duck-typed protocol says, “if it walks like a duck and quacks like a duck, I don’t care what class it is.
# ──────────────────────────────────────────────────────────────────────────────

class StateView(Protocol):
    """
    Read-only surface a placer needs from the planning state.
    Implement these on your real PlannerState; keep them fast and side-effect free.
    """

    def order_features(self, order_id: str) -> Any:
        """Return an object exposing: cold_fraction, effective_volume_m3, weight_kg, cold_volume_m3."""
        ...

    def truck_features(self, truck_id: str) -> Any:
        """Return static truck info: type ('reefer'/'dry'), capacities, min util, etc."""
        ...

    def truck_residuals(self, truck_id: str) -> Any:
        """Return dynamic residuals (ΔQ_k, ΔQ_k_cold, ΔW_k, cooler usage, etc.)."""
        ...

    def open_trucks(self, *, type_filter: Optional[str] = None) -> Iterable[str]:
        """Return IDs of currently ‘open’ (already deployed) trucks. Optional type filter."""
        ...

    def all_available_trucks(self, *, type_filter: Optional[str] = None) -> Iterable[str]:
        """Return IDs of trucks available to be opened today (not yet deployed)."""
        ...

    def sorted_items(self, order_id):
        pass


class FeasibilityService(Protocol):
    """
    Stateless checks. Keep pure and deterministic.
    Placers call these to gate choices before proposing an AssignOrder.
    """

    def fits_order_on_truck(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        """Check volume / cold / weight limits and basic segregation permissions."""
        ...

    def cooler_feasible(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        """For cold-in-dry policy: verify remaining certified cooler capacity if applicable."""
        ...



class PackingPolicy(Protocol):
    """
    Encapsulates item-level ordering and basic zoning/layering rules.
    Should not change state; just compute a LoadingPlan or raise/return None.
    """

    def plan(self, state: StateView, truck_id: str, order_id: str) -> Optional[LoadingPlan]:
        ...


class Policy(Protocol):
    """
    Tuning knobs and day rules the placer needs.
    Keep this small; add fields as you implement more detail.

    Expected examples:
      - alpha_threshold: float         # A/B/C bucket split (if placer needs it)
      - allow_open_new_reefer_A: bool
      - allow_open_new_reefer_B: bool
      - allow_cold_in_dry_B: bool
      - cooler_capacity_m3: float     # per dry truck or a lookup
      - day_bottleneck: str           # 'volume' or 'weight' (tie-break preference)
    """

    ...


# ──────────────────────────────────────────────────────────────────────────────
# Abstract Placer
# ──────────────────────────────────────────────────────────────────────────────

class Placer(ABC):
    """
    A Placer decides *where and how* to assign a selected order.
    It does not choose *which* order next (that’s the selector’s job).

    Contract:
      - Read-only: inspect StateView + FeasibilityService + Policy + PackingPolicy
      - Propose an AssignOrder action, or return None if no feasible placement was found
      - Never mutate state directly; the runner will apply the returned action
    """

    name: str = "abstract_placer"

    @abstractmethod
    def place(
        self,
        state: StateView,
        order_id: str,
        policy: Policy,
        feasibility: FeasibilityService,
        packing: PackingPolicy,
    ) -> Optional[AssignOrder]:
        """
        Decide the target truck and compute a LoadingPlan for `order_id`.

        Typical flow inside an implementation (for reference):
          1) enumerate candidate trucks (open first; maybe open new if policy allows)
          2) filter by feasibility (capacity, cold/weight/volume, coolers if needed)
          3) select best truck by tie-breaks (e.g., smallest leftover cold → volume → weight)
          4) call packing.plan(...) to get a within-truck LoadingPlan
          5) return AssignOrder(order_id, truck_id, packing, rationale=...)

        Return None if no feasible placement is possible under current policy.
        """
        ...
