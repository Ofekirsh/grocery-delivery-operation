# src/planning/placer_orchestrator.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Any, Literal, Callable
import os
import csv

from src.heuristics.placers.base import StateView, FeasibilityService, Policy, PackingPolicy, AssignOrder
from src.heuristics.placers.best_fit_reefer import assign_to_best_reefer
from src.heuristics.placers.best_fit_dry import assign_bucket_b_order, assign_bucket_c_order
from src.quality_metrics.tracker import DayTracker


def determine_bucket(alpha_i: float, *, alpha_threshold: float) -> str:
    """
    Return 'A' (cold mandatory), 'B' (mixed/flexible), or 'C' (dry only)
    based on cold fraction αᵢ and a threshold α*.
    """
    if alpha_i <= 1e-12:
        return "C"
    if alpha_i >= alpha_threshold:
        return "A"
    return "B"


@dataclass
class PlacerOrchestrator:
    """
    Tiny runner for placer (Phase 2): given an order_id, route to A/B/C and call the right placer.
    On success/failure, write to DayTracker. Stateless apart from injected deps.
    """
    state: StateView
    feas: FeasibilityService
    policy: Policy
    packing: PackingPolicy
    tracker: DayTracker
    commit_hook: Optional[Callable[[AssignOrder, Any], None]] = None

    reefer_scheme_A: Sequence[Literal] = ("cold", "volume", "weight")
    reefer_scheme_B: Sequence[Literal] = ("cold", "volume", "weight")
    dry_scheme_B: Sequence[Literal] = ("volume", "weight")
    dry_scheme_C: Sequence[Literal] = ("volume", "weight")

    def run_one(self, order_id: str) -> Optional[AssignOrder]:
        """Route order to A/B/C placer and record outcome in DayTracker."""
        f = self.state.order_features(order_id)
        bucket = determine_bucket(float(f.cold_fraction if hasattr(f, "cold_fraction") else 0.0),
                                  alpha_threshold=self.policy.alpha_threshold)

        decision: Optional[AssignOrder] = None
        if bucket == "A":
            decision = assign_to_best_reefer(
                self.state, self.feas, self.policy, order_id,
                packing_policy=self.packing,
                ranking_scheme=self.reefer_scheme_A,
            )
        elif bucket == "B":
            decision = assign_bucket_b_order(
                self.state, self.feas, self.policy, order_id,
                packing_policy=self.packing,
                reefer_scheme=self.reefer_scheme_B,
                dry_scheme=self.dry_scheme_B,
            )
        else:  # "C"
            decision = assign_bucket_c_order(
                self.state, self.feas, self.policy, order_id,
                packing_policy=self.packing,
                dry_scheme=self.dry_scheme_C,
            )

        # Record outcome
        is_vip = bool(getattr(f, "vip", False))
        if decision is not None:

            self.apply_decision(
                decision,
                features=f,
            )
        else:
            self.tracker.on_failure(
                order_id, is_vip=is_vip,
                due_missed=False, delay_min=None,
                reason=f"infeasible_in_bucket_{bucket}"
            )

        return decision

    def run_many(self, order_ids: Iterable[str]) -> List[Optional[AssignOrder]]:
        """
        Execute Phase-2 placement for a fixed sequence of order IDs
        (e.g., your Phase-1 priority queue). Returns decisions in the same order.
        """
        decisions: List[Optional[AssignOrder]] = []
        for oid in order_ids:
            decisions.append(self.run_one(oid))
        return decisions

    def run_loop(
            self,
            selector: Any,
            *,
            max_iters: Optional[int] = None,
            remove_from_state: bool = True,
    ) -> List[Optional[AssignOrder]]:
        """
        Pull orders from a Phase-1 selector until empty (or max_iters).
        Expects selector.select_next(state) -> object with .order_id (like your Candidate).
        Optionally calls state.remove_order(order_id) if available.
        """
        out: List[Optional[AssignOrder]] = []
        it = 0
        while True:
            cand = selector.select_next(self.state)
            if not cand:
                break
            oid = getattr(cand, "order_id", None)
            if not oid:
                break

            out.append(self.run_one(oid))

            if remove_from_state:
                # Try best-effort removal without coupling to concrete types.
                if hasattr(self.state, "remove_order") and callable(getattr(self.state, "remove_order")):
                    self.state.remove_order(oid)  # type: ignore[attr-defined]
                elif hasattr(self.state, "remaining_orders"):
                    try:
                        rem = getattr(self.state, "remaining_orders")
                        if isinstance(rem, list):
                            try:
                                rem.remove(oid)
                            except ValueError:
                                pass
                    except Exception:
                        pass

            it += 1
            if max_iters is not None and it >= max_iters:
                break
        return out

    # ----------------------------- Side effects ---------------------------- #
    def _ensure_tracker_truck_open(self, truck_id: str) -> None:
        # If already registered, nothing to do
        if getattr(self.tracker, "trucks", None) and truck_id in self.tracker.trucks:
            return

        # Pull specs from your depot (available via SimpleStateView)
        depot = getattr(self.state, "_depot", None)
        if depot is None or not hasattr(depot, "get_truck"):
            # If you prefer, raise explicitly; but we just no-op safely:
            return

        t = depot.get_truck(truck_id)
        is_reefer = ("reefer" in str(getattr(t, "type", "")).lower())
        Q = float(getattr(t, "total_capacity_m3", 0.0))
        Qc = float(getattr(t, "cold_capacity_m3", 0.0))
        W = float(getattr(t, "weight_limit_kg", 0.0))
        cost = float(getattr(t, "fixed_cost", 0.0))
        tau_min = float(getattr(t, "min_utilization", 0.0))

        self.tracker.open_truck(
            truck_id,
            is_reefer=is_reefer,
            Q=Q,
            Q_cold=Qc,
            W=W,
            fixed_cost=cost,
            tau_min=tau_min,
        )

    def apply_decision(self, decision: AssignOrder, *, features: Any | None = None) -> None:
        """
        Commit an accepted decision:
          1) Mutate your concrete state (via commit_hook or best-effort fallback).
          2) Update the DayTracker (on_assign).
        This ensures subsequent feasibility checks see updated residuals.
        """
        # Feature view (demand) for tracker and fallback mutations
        f = features or self.state.order_features(decision.order_id)

        # 0) make sure tracker knows this truck is opened
        self._ensure_tracker_truck_open(decision.truck_id)

        if hasattr(self.state, "_open"):
            try:
                self.state._open.add(decision.truck_id)
            except Exception:
                pass

        v_eff = float(getattr(f, "effective_volume_m3", 0.0))
        q_cold = float(getattr(f, "cold_volume_m3", 0.0))
        w = float(getattr(f, "weight_kg", 0.0))
        q = float(getattr(f, "volume_m3", 0.0))

        # 1) Mutate concrete state if caller provided a hook
        if self.commit_hook is not None:
            self.commit_hook(decision, f)
        else:
            # Best-effort fallback: if this looks like SimpleStateView, update Truck runtime directly.
            depot = getattr(self.state, "_depot", None)
            if depot is not None and hasattr(depot, "get_truck"):
                try:
                    t = depot.get_truck(decision.truck_id)
                    t.used_volume_m3 += v_eff
                    t.used_weight_kg += w
                    if hasattr(t, "used_cold_m3"):
                        t.used_cold_m3 += q_cold
                    if hasattr(t, "assigned_orders") and isinstance(t.assigned_orders, list):
                        t.assigned_orders.append(decision.order_id)
                    if q_cold > 0.0 and hasattr(t, "type") and str(t.type).lower() == "dry":
                        setattr(t, "used_cooler_m3", float(getattr(t, "used_cooler_m3", 0.0)) + q_cold)

                except Exception:
                    # If mutation fails, we still keep DayTracker consistent.
                    pass

            # 2) Book portable-cooler usage in DayTracker when cold goes onto a DRY truck
            is_dry = (getattr(self.state.truck_features(decision.truck_id), "type", "") == "dry")
            if is_dry and q_cold > 0.0:
                # ensure ledger exists then increment
                trk = self.tracker.trucks.get(decision.truck_id, {})
                trk["cooler_used_m3"] = float(trk.get("cooler_used_m3", 0.0)) + q_cold
                self.tracker.trucks[decision.truck_id] = trk

        # 3) Update DayTracker (VIP / due-met not modeled yet; pass None)
        self.tracker.on_assign(
            decision.order_id,
            decision.truck_id,
            q=q,
            q_cold=q_cold,
            w=w,
            v_eff=v_eff,
            is_vip=bool(getattr(f, "vip", False)),
            due_met=None,
            delay_min=None,
            cold_on_dry=(q_cold > 0 and getattr(self.state.truck_features(decision.truck_id), "type", "") == "dry"),
        )

        # If packing plan includes placements, log them for CSV
        plan = getattr(decision, "packing", None)
        if plan is not None and hasattr(plan, "placements"):
            self.tracker.record_placement(
                decision.order_id,
                decision.truck_id,
                plan.placements
            )

    def maybe_depart_trucks(
            self,
            strategy: Literal["none", "min_util", "time"] = "none",
            *,
            min_util_slack: float = 0.0,
            depart_time: Optional[str] = None,
    ) -> List[str]:
        """
        Optionally mark trucks as departed under a simple policy.

        - "none": do nothing.
        - "min_util": depart trucks whose U_vol ≥ τ_min + min_util_slack.
        - "time": depart all currently opened trucks and stamp a provided `depart_time` (HH:MM).

        Returns the list of truck_ids that were just marked departed.
        """
        departed: List[str] = []
        if strategy == "none":
            return departed

        # We use DayTracker's ledger (since it knows τ_min and used loads).
        for tid, t in getattr(self.tracker, "trucks", {}).items():
            if t.get("departed", False) or not t.get("opened", False):
                continue

            if strategy == "min_util":
                Q = float(t.get("Q", 0.0))
                used_v = float(t.get("used_v_eff", 0.0))
                tau_min = float(t.get("tau_min", 0.0))
                u = 0.0 if Q <= 0 else (used_v / Q)
                if u + 1e-9 >= tau_min + float(min_util_slack):
                    self.tracker.on_departure(tid, when=None)
                    departed.append(tid)

            elif strategy == "time":
                self.tracker.on_departure(tid, when=depart_time)
                departed.append(tid)

        return departed

    def finalize_day(self) -> dict:
        """
        Freeze and return a full KPI snapshot for the day (per-truck + fleet).
        """
        return self.tracker.summarize_day()

    def export_reports(self, dirpath: str) -> dict[str, str]:
        """
        Write simple CSVs for CEO-friendly review:
          - <dir>/per_truck.csv
          - <dir>/fleet.csv
        Uses `summarize_day()`; no dependency on internal tracker CSV helpers.
        Returns a mapping of label -> filepath.
        """
        os.makedirs(dirpath, exist_ok=True)
        snapshot = self.tracker.summarize_day()

        # Per-truck
        per_truck_fp = os.path.join(dirpath, "per_truck.csv")
        per_truck_rows = snapshot.get("per_truck", [])
        if per_truck_rows:
            headers = list(per_truck_rows[0].keys())
            with open(per_truck_fp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                w.writeheader()
                for row in per_truck_rows:
                    w.writerow(row)
        else:
            with open(per_truck_fp, "w", newline="") as f:
                f.write("")

        # Fleet
        fleet_fp = os.path.join(dirpath, "fleet.csv")
        fleet_row = snapshot.get("fleet", {})
        if fleet_row:
            headers = list(fleet_row.keys())
            with open(fleet_fp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                w.writeheader()
                w.writerow(fleet_row)
        else:
            with open(fleet_fp, "w", newline="") as f:
                f.write("")

        return {"per_truck": per_truck_fp, "fleet": fleet_fp}

    def set_alpha_threshold(self, alpha: float) -> None:
        """Adjust the A/B/C split without rebuilding the orchestrator."""
        self.alpha_threshold = float(alpha)
