from __future__ import annotations

from .base import StateView, FeasibilityService, Policy


class SimpleFeasibility(FeasibilityService):
    """
    Capacity gates + cooler feasibility for cold-in-dry.
    """

    def fits_order_on_truck(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        of = state.order_features(order_id)
        r = state.truck_residuals(truck_id)

        v_eff = float(of.effective_volume_m3)
        q_cold = float(of.cold_volume_m3)
        w_kg  = float(of.weight_kg)

        rem_vol  = float(r.remaining_volume_m3)
        rem_cold = float(r.remaining_cold_m3)   # 0 for dry
        rem_wt   = float(r.remaining_weight_kg)

        if v_eff > rem_vol:
            return False
        if q_cold > rem_cold:
            return False
        if w_kg > rem_wt:
            return False
        return True

    def cooler_feasible(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        """
        Cold-in-dry check:
          - applies only to DRY trucks
          - ensures order's cold volume <= remaining cooler capacity
        Falls back gracefully if state doesn't expose cooler fields.
        """
        # policy gate
        if not bool(getattr(policy, "allow_cold_in_dry_B", False)):
            return False

        # truck must be dry
        tfeat = state.truck_features(truck_id)
        if str(getattr(tfeat, "type", "")).lower() != "dry":
            return False

        # order cold volume
        of = state.order_features(order_id)
        q_cold = float(of.cold_volume_m3)
        if q_cold <= 0.0:
            # nothing cold to justify a cooler placement
            return False

        # remaining cooler capacity: try residuals first
        r = state.truck_residuals(truck_id)
        remaining_cooler = None
        if hasattr(r, "remaining_cooler_m3"):
            remaining_cooler = float(getattr(r, "remaining_cooler_m3"))

        # if not provided, compute from capacity - used with safe fallbacks
        if remaining_cooler is None:
            used = float(getattr(r, "cooler_used_m3", 0.0))

            # prefer a truck-specific cooler capacity if present on features; else policy default
            truck_cap = float(getattr(tfeat, "cooler_capacity_m3",
                                      getattr(policy, "per_truck_cooler_m3", 0.0)))
            remaining_cooler = max(0.0, truck_cap - used)

        return q_cold <= remaining_cooler
