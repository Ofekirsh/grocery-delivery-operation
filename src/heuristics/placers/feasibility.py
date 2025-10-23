from __future__ import annotations

from .base import StateView, FeasibilityService, Policy

EPS = 1e-9


class SimpleFeasibility(FeasibilityService):
    """
    Capacity gates + cooler feasibility for cold-in-dry.
    """

    def fits_order_on_truck(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        f = state.order_features(order_id)
        r = state.truck_residuals(truck_id)
        t = state.truck_features(truck_id)

        # volume & weight must fit everywhere
        if r.remaining_volume_m3 < f.effective_volume_m3:
            return False
        if r.remaining_weight_kg < f.weight_kg:
            return False

        if f.cold_volume_m3 > 0:
            if t.type == "reefer":
                if r.remaining_cold_m3 < f.cold_volume_m3:
                    return False
            else:  # dry truck with portable cooler
                if not self.cooler_feasible(state, order_id, truck_id, policy):
                    return False
        return True

    def cooler_feasible(self, state: StateView, order_id: str, truck_id: str, policy: Policy) -> bool:
        # gate by policy
        if not bool(getattr(policy, "allow_cold_in_dry_B", False)):
            return False

        tfeat = state.truck_features(truck_id)
        if str(getattr(tfeat, "type", "")).lower() != "dry":
            return False

        of = state.order_features(order_id)
        q_cold = float(of.cold_volume_m3)
        if q_cold <= 0.0:
            # called only for cold-in-dry paths; treat as "no cooler needed"
            return False  # or True if you call this unconditionally elsewhere

        r = state.truck_residuals(truck_id)

        # try residual view first
        remaining_cooler = None
        if hasattr(r, "remaining_cooler_m3"):
            remaining_cooler = float(getattr(r, "remaining_cooler_m3"))

        if remaining_cooler is None:
            used = float(getattr(r, "cooler_used_m3", 0.0))
            cap = float(
                getattr(tfeat, "cooler_capacity_m3",
                        getattr(policy, "per_truck_cooler_m3", 0.0))
            )
            remaining_cooler = max(0.0, cap - used)

        return (remaining_cooler + EPS) >= q_cold

