# src/quality_metrics/tracker.py
from __future__ import annotations
import os
import csv
from pathlib import Path
from typing import Optional, Dict, Set, Tuple, Iterable, Any, Sequence
from datetime import datetime

from src.quality_metrics.kpis import (
    u_vol_k, u_w_k, u_cold_k, u_bn_k,
    under_min_flag, cap_violation_flag,
    e_pack, n_trucks_opened, c_total, c_per_vol, c_per_w,
    cv_uvol, miss_vip, miss_due, avg_delay, vip_ontime,
    under_min_count, cap_violations_count, splits_count
)


class DayTracker:
    """
    Incremental KPI accumulator for a single planning day.

    Usage pattern:
      - call open_truck(...) once per deployed truck (at first assignment time)
      - call on_assign(...) for every order→truck assignment
      - optionally call bump_cooler_usage(...) when placing cold-in-dry via coolers
      - optionally call on_departure(...) when a truck leaves (snapshots utils)
      - call summarize_day() (or snapshot()) at any time for KPIs
    """

    def __init__(self) -> None:
        # per-truck ledger: truck_id -> dict of static capacity + dynamic loads
        self.trucks: Dict[str, Dict] = {}

        # per-order ledger: order_id -> dict of properties and assignment counts
        self.orders: Dict[str, Dict] = {}

        # sets/counters for day-level stats
        self.opened_trucks: Set[str] = set()
        self.departed_trucks: Set[str] = set()
        self.cold_on_dry_pairs: Set[Tuple[str, str]] = set()  # (order_id, truck_id)

        # day totals (for E_pack, cost-per-X, etc.)
        self.sum_q: float = 0.0
        self.sum_v_eff: float = 0.0
        self.sum_w: float = 0.0
        self.c_total: float = 0.0

        # lateness / misses
        self.n_missed_vip: int = 0
        self.n_missed_due: int = 0

        self.assignment_rows = []  # list of dict rows for item-level placements

        self.order_queue_log: list[dict] = []
        self.item_queue_log: dict[str, list[dict]] = {}
        self.order_queue_meta: dict = {}
        self.item_queue_meta: dict = {}

    def open_truck(self, truck_id: str, *, is_reefer: bool, Q: float, Q_cold: float,
                   W: float, fixed_cost: float, tau_min: float) -> None:
        """
        Register a new truck as opened for the day.

        This initializes its runtime ledger and adds its fixed cost to the day's total.

        Args:
            truck_id: Unique identifier of the truck.
            is_reefer: True if the truck is refrigerated.
            Q: Total volume capacity (m³).
            Q_cold: Cold capacity (m³; 0 for dry trucks).
            W: Weight limit (kg).
            fixed_cost: Fixed daily deployment cost.
            tau_min: Minimum required utilization threshold (fraction).
        """
        if truck_id in self.trucks:
            raise ValueError(f"Truck '{truck_id}' already opened.")

        self.trucks[truck_id] = {
            "is_reefer": bool(is_reefer),
            "Q": float(Q),
            "Q_cold": float(Q_cold),
            "W": float(W),
            "fixed_cost": float(fixed_cost),
            "tau_min": float(tau_min),
            # runtime
            "used_v_eff": 0.0,
            "used_q": 0.0,
            "used_q_cold": 0.0,
            "used_w": 0.0,
            "cooler_used_m3": 0.0,
            "opened": True,
        }

        self.opened_trucks.add(truck_id)
        self.c_total += float(fixed_cost)


    def on_assign(self, order_id: str, truck_id: str, *,
                  q: float, q_cold: float, w: float, v_eff: float,
                  is_vip: bool, due_met: Optional[bool] = None,
                  delay_min: Optional[float] = None,
                  cold_on_dry: bool = False) -> None:
        """
        Record that an order (or part of it) was loaded onto a truck.

        Notation:
            qᵢ        – total volume of order i
            qᵢᶜᵒˡᵈ    – cold volume
            wᵢ        – weight
            vᵢᵉᶠᶠ     – effective (padded) volume
            αᵢ = qᵢᶜᵒˡᵈ / qᵢ   (cold fraction, tracked upstream)

        This updates:
            - Truck runtime loads (used volume, cold volume, weight)
            - Order-level assignment counters and lateness info
            - Day-level totals (sum_q, sum_v_eff, sum_w, missed counts, cost)
        """
        if truck_id not in self.trucks:
            raise KeyError(f"Truck '{truck_id}' not registered (call open_truck first).")

        t = self.trucks[truck_id]

        # --- update truck loads ---
        t["used_q"] += float(q)
        t["used_q_cold"] += float(q_cold)
        t["used_w"] += float(w)
        t["used_v_eff"] += float(v_eff)

        # --- update order ledger ---
        # Is this the first time we’re assigning this order to any truck today? for example: The order is too large for one truck.
        # In our problem we dont allow to split but in maybe in the feature we change it.
        if order_id not in self.orders:
            self.orders[order_id] = {
                "q": float(q),
                "q_cold": float(q_cold),
                "w": float(w),
                "v_eff": float(v_eff),
                "is_vip": bool(is_vip),
                "assigned_truck_count": 0,
                "due_met": due_met,
                "delay_min": delay_min,
                "placed": True,
                "reason": None,
            }

        self.orders[order_id]["assigned_truck_count"] += 1

        # --- day totals ---
        self.sum_q += float(q)
        self.sum_v_eff += float(v_eff)
        self.sum_w += float(w)

        if is_vip and due_met is False:
            self.n_missed_vip += 1
        if due_met is False:
            self.n_missed_due += 1
        if cold_on_dry:
            self.cold_on_dry_pairs.add((order_id, truck_id))

    def on_failure(self, order_id: str, *, is_vip: bool,
                   due_missed: bool, delay_min: float | None = None,
                   reason: str = "unspecified") -> None:
        """
        Register that an order was not successfully planned.

        Args:
            order_id: The order identifier.
            is_vip: Whether the order is VIP (affects VIP-miss KPI).
            due_missed: True if deadline was missed.
            delay_min: Lateness in minutes (optional; used for AVG_DELAY).
            reason: Short tag explaining the failure (e.g., 'capacity', 'cooler_limit', 'no_split').

        Notes:
            - Creates the order ledger entry if it doesn't exist.
            - Marks the order as not placed, stores reason and lateness.
            - Increments day counters for missed due and missed VIP when applicable.
        """
        rec = self.orders.get(order_id)
        if rec is None:
            rec = {
                "q": 0.0, "q_cold": 0.0, "w": 0.0, "v_eff": 0.0,
                "is_vip": bool(is_vip),
                "assigned_truck_count": 0,
                "due_met": None,
                "delay_min": None,
                "placed": False,
                "reason": reason,
            }
            self.orders[order_id] = rec
        else:
            # If it existed (e.g., partial attempts), mark as not placed final.
            # situation where the order was already partially recorded earlier, and now you’re marking it as failed
            # overall (for example, it was attempted, maybe even partially packed, but finally rejected).
            rec["placed"] = False
            rec["reason"] = reason
            rec["is_vip"] = bool(is_vip) or bool(rec.get("is_vip", False))

        if due_missed:
            rec["due_met"] = False
            rec["delay_min"] = None if delay_min is None else float(delay_min)
            self.n_missed_due += 1
            if is_vip:
                self.n_missed_vip += 1

    def on_departure(self, truck_id: str, when: str | None = None) -> None:
        """
        Mark a truck as departed and freeze its final load stats for reporting.

        Args:
            truck_id: The truck identifier.
            when: Optional HH:MM (or any timestamp string) to record the departure time.

        Behavior:
            - Marks the truck as 'departed' (no more assignments should be added afterwards).
            - Stores an optional departure time string for auditing.
            - Captures per-truck utilizations at departure for faster KPI reporting.
        """
        if truck_id not in self.trucks:
            raise KeyError(f"Truck '{truck_id}' not registered (call open_truck first).")

        t = self.trucks[truck_id]
        if t.get("departed", False):
            return  # idempotent: already departed

        # Snapshot utilizations at departure
        Q, W, Qc = float(t["Q"]), float(t["W"]), float(t["Q_cold"])
        used_v, used_w, used_qc = float(t["used_v_eff"]), float(t["used_w"]), float(t["used_q_cold"])

        uvol = u_vol_k(used_v, Q)
        uw = u_w_k(used_w, W)
        uc = u_cold_k(used_qc, Qc)
        ubn = u_bn_k(uvol, uw)

        # Stamp final stats and mark departed
        t["u_vol_at_departure"] = uvol
        t["u_w_at_departure"] = uw
        t["u_cold_at_departure"] = uc
        t["u_bn_at_departure"] = ubn
        t["departure_time"] = when
        t["departed"] = True

        # Track in a set for quick queries like "how many departed"
        if not hasattr(self, "departed_trucks"):
            self.departed_trucks = set()
        self.departed_trucks.add(truck_id)

    def record_placement(self, order_id: str, truck_id: str,
                         placements: Iterable[tuple[str, int, Dict[str, Any]]],
                         *, when: Optional[str] = None) -> None:
        """
        Append flat rows describing where each (item_id, qty) was placed.

        Row fields:
          time, order_id, truck_id, item_id, qty, zone, lane, layer, pos
        """
        ts = when or datetime.now().strftime("%Y-%m-%d %H:%M")
        for (item_id, qty, slot) in placements:
            self.assignment_rows.append({
                "time": ts,
                "order_id": order_id,
                "truck_id": truck_id,
                "item_id": item_id,
                "qty": int(qty),
                "zone": slot.get("zone"),
                "lane": slot.get("lane"),
                "layer": slot.get("layer"),
                "pos": slot.get("pos"),
            })

    def selection_logs(self):
        return {
            "orders": getattr(self, "order_queue_log", []),
            "items": [row for rows in getattr(self, "item_queue_log", {}).values() for row in rows],
        }

    def record_order_queue(
            self,
            ranked_rows,
            *,
            selector_name: str,
            order_scheme: Sequence[str],
            run_id: str | None = None,
            reset: bool = False,
    ) -> None:
        """
        Append the ranked order queue for audit/CSV export.

        ranked_rows: iterable of objects or dicts with fields:
          rank, order_id, vip, due, alpha, v_eff, weight, sort_key
        selector_name: e.g. "order_vip_due"
        order_scheme: e.g. ("vip", "due", "alpha")
        run_id: optional tag if you log multiple queues in a day (e.g., "morning", "rerun-2")
        reset: if True, clears existing queue before appending
        """
        if reset:
            self.order_queue_log = []

        # capture/refresh meta
        self.order_queue_meta = {
            "selector": selector_name,
            "scheme": list(order_scheme),
            "run_id": run_id,
        }

        def _get(r, k, default=None):
            return r[k] if isinstance(r, dict) and k in r else getattr(r, k, default)

        for r in ranked_rows:
            due = _get(r, "due")
            due_str = due.strftime("%H:%M") if hasattr(due, "strftime") else str(due)
            self.order_queue_log.append({
                "run_id": run_id,
                "rank": int(_get(r, "rank", 0)),
                "order_id": str(_get(r, "order_id", "")),
                "vip": bool(_get(r, "vip", False)),
                "due": due_str,
                "alpha": float(_get(r, "alpha", 0.0)),
                "v_eff": float(_get(r, "v_eff", 0.0)),
                "weight": float(_get(r, "weight", 0.0)),
                "sort_key": str(_get(r, "sort_key", "")),
            })

    def record_item_queue(
            self,
            order_id: str,
            ranked_rows,
            *,
            sorter_name: str,
            item_scheme: Sequence[str],
            run_id: str | None = None,
            reset: bool = False,
    ) -> None:
        """
        Append the ranked item sequence for a given order.

        ranked_rows: iterable with fields:
          rank, item_id, qty, cold01, w_ij, v_ij_eff, liquid01, stack_limit, fragile_score, upright01, sort_key
        sorter_name: e.g. "item_priority"
        item_scheme: e.g. ("cold01","w_ij","v_ij_eff","liquid01","stack_limit","fragile_score↑","upright01↑")
        run_id: optional tag to correlate with order queue runs
        reset: if True, clears existing rows for this order before appending
        """
        if reset or order_id not in self.item_queue_log:
            self.item_queue_log[order_id] = []

        # capture/refresh meta (global for items)
        self.item_queue_meta = {
            "sorter": sorter_name,
            "scheme": list(item_scheme),
            "run_id": run_id,
        }

        def _get(r, k, default=None):
            return r[k] if isinstance(r, dict) and k in r else getattr(r, k, default)

        out = self.item_queue_log[order_id]
        for r in ranked_rows:
            out.append({
                "run_id": run_id,
                "order_id": str(order_id),
                "rank": int(_get(r, "rank", 0)),
                "item_id": str(_get(r, "item_id", "")),
                "qty": int(_get(r, "qty", 0)),
                "cold01": float(_get(r, "cold01", 0.0)),
                "w_ij": float(_get(r, "w_ij", 0.0)),
                "v_ij_eff": float(_get(r, "v_ij_eff", 0.0)),
                "liquid01": float(_get(r, "liquid01", 0.0)),
                "stack_limit": float(_get(r, "stack_limit", 0.0)),
                "fragile_score": float(_get(r, "fragile_score", 0.0)),
                "upright01": float(_get(r, "upright01", 0.0)),
                "sort_key": str(_get(r, "sort_key", "")),
            })

    def export_selection_meta_json(self, dirpath: str) -> dict[str, str]:
        """
        Write small JSON sidecars with selection metadata:
          - <dir>/order_queue_meta.json
          - <dir>/item_queue_meta.json
        """
        import json, os
        os.makedirs(dirpath, exist_ok=True)
        order_meta_fp = os.path.join(dirpath, "order_queue_meta.json")
        item_meta_fp = os.path.join(dirpath, "item_queue_meta.json")
        with open(order_meta_fp, "w") as f:
            json.dump(self.order_queue_meta or {}, f, indent=2)
        with open(item_meta_fp, "w") as f:
            json.dump(self.item_queue_meta or {}, f, indent=2)
        return {"orders_meta": order_meta_fp, "items_meta": item_meta_fp}

    def summarize_day(self) -> dict:
        """
        Build an end-of-day summary with per-truck KPIs and fleet-level KPIs.

        Uses pure formulas from src.metrics.kpis:
          - Per truck: U_k^{vol}, U_k^{wt}, U_k^{cold}, U_k^{bottleneck}, under-min flag, cap-violation flag
          - Fleet/day: E^{pack}, N_trucks, C_total, C_per_vol, C_per_w, CV(U^{vol}),
                       misses (VIP/due), AVG_DELAY, VIP_ONTIME, COLD_ON_DRY, UNDER_MIN, CAP_VIOLS, SPLITS

        Returns:
            dict with keys:
              - "per_truck": List[dict] per opened truck
              - "fleet": Dict[str, Any] aggregate day metrics
        """

        per_truck = []
        uvol_list = []
        tau_list = []
        cap_tuples = []
        fixed_costs = []
        opened_flags = []

        # Per-truck metrics for trucks that were opened
        for tid, t in self.trucks.items():
            if not t.get("opened", False):
                continue

            Q = float(t.get("Q", 0.0))
            Qc = float(t.get("Q_cold", 0.0))
            W = float(t.get("W", 0.0))
            used_v = float(t.get("used_v_eff", 0.0))
            used_q = float(t.get("used_q", 0.0))
            used_qc = float(t.get("used_q_cold", 0.0))
            used_w = float(t.get("used_w", 0.0))
            tau_min = float(t.get("tau_min", 0.0))
            cost = float(t.get("fixed_cost", 0.0))
            is_reefer = bool(t.get("is_reefer", False))

            uvol = u_vol_k(used_v, Q)
            uw = u_w_k(used_w, W)
            uc = u_cold_k(used_qc, Qc)
            ubn = u_bn_k(uvol, uw)
            under_min = under_min_flag(uvol, tau_min)
            cap_bad = cap_violation_flag(used_v, Q, used_w, W, used_qc, Qc)

            per_truck.append({
                "truck_id": tid,
                "is_reefer": is_reefer,
                "Q": Q, "Q_cold": Qc, "W": W,
                "used_v_eff": used_v, "used_q": used_q, "used_q_cold": used_qc, "used_w": used_w,
                "u_vol": uvol, "u_w": uw, "u_cold": uc, "u_bn": ubn,
                "under_min": under_min,
                "cap_violation": cap_bad,
                "fixed_cost": cost,
                "departed": bool(t.get("departed", False)),
                "departure_time": t.get("departure_time"),
            })

            # Collect for fleet KPIs
            uvol_list.append(uvol)
            tau_list.append(tau_min)
            cap_tuples.append((used_v, Q, used_w, W, used_qc, Qc))
            fixed_costs.append(cost)
            opened_flags.append(1)  # this truck was opened

        # Per-order aggregates for day metrics
        # (orders dict contains both assigned and failures registered via on_failure)
        delays = []
        n_vip_total = 0
        n_vip_missed = 0
        assignments_per_order = {}
        for oid, rec in self.orders.items():
            assignments_per_order[oid] = int(rec.get("assigned_truck_count", 0))
            if rec.get("is_vip"):
                n_vip_total += 1
                if rec.get("due_met") is False:
                    n_vip_missed += 1
            if rec.get("due_met") is False and rec.get("delay_min") is not None:
                delays.append(float(rec["delay_min"]))

        # Fleet/day KPIs
        n_trucks = n_trucks_opened(opened_flags)
        total_cost = c_total(fixed_costs)
        pack_eff = e_pack(self.sum_q, self.sum_v_eff)
        cost_per_vol = c_per_vol(total_cost, self.sum_q)
        cost_per_w = c_per_w(total_cost, self.sum_w)
        cv_u = cv_uvol(uvol_list)
        under_min_cnt = under_min_count(uvol_list, tau_list)
        cap_viol_cnt = cap_violations_count(cap_tuples)
        splits_cnt = splits_count(assignments_per_order)

        fleet = {
            "N_trucks": n_trucks,
            "C_total": total_cost,
            "C_per_vol": cost_per_vol,
            "C_per_w": cost_per_w,
            "E_pack": pack_eff,
            "CV_Uvol": cv_u,
            "MISS_VIP": miss_vip(getattr(self, "n_missed_vip", 0)),
            "MISS_DUE": miss_due(getattr(self, "n_missed_due", 0)),
            "AVG_DELAY": avg_delay(delays),
            "VIP_ONTIME": vip_ontime(n_vip_total, n_vip_missed),
            "COLD_ON_DRY": len(getattr(self, "cold_on_dry_pairs", set())),
            "UNDER_MIN": under_min_cnt,
            "CAP_VIOLS": cap_viol_cnt,
            "SPLITS": splits_cnt,
            # raw sums for convenience
            "SUM_q": float(self.sum_q),
            "SUM_v_eff": float(self.sum_v_eff),
            "SUM_w": float(self.sum_w),
        }

        return {"per_truck": per_truck, "fleet": fleet}

    def snapshot(self) -> dict:
        """
        Alias for summarize_day(), useful during the planning loop to log live KPIs.
        """
        return self.summarize_day()

    def export_csv(self, dir_path: str) -> None:
        """
        Export the current snapshot to CSV files for exec reporting.

        Writes:
          - <dir>/per_truck.csv : one row per opened truck with utilizations, loads, costs
          - <dir>/fleet_summary.csv : a single row with day-level KPIs

        The content mirrors summarize_day(); call this anytime (mid-run or end-of-day).
        """
        snap = self.summarize_day()
        per_truck = snap.get("per_truck", [])
        fleet = snap.get("fleet", {})

        os.makedirs(dir_path, exist_ok=True)

        # ---- per_truck.csv ----
        per_truck_path = os.path.join(dir_path, "per_truck.csv")
        if per_truck:
            # stable column order (fall back to keys of first row)
            truck_cols = [
                "truck_id", "is_reefer",
                "Q", "Q_cold", "W",
                "used_v_eff", "used_q", "used_q_cold", "used_w",
                "u_vol", "u_w", "u_cold", "u_bn",
                "under_min", "cap_violation",
                "fixed_cost", "departed", "departure_time",
            ]
            # include any extra keys that appeared
            extra = [k for k in per_truck[0].keys() if k not in truck_cols]
            truck_cols += extra

            with open(per_truck_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=truck_cols)
                w.writeheader()
                for row in per_truck:
                    w.writerow(row)
        else:
            # write an empty file with header for consistency
            with open(per_truck_path, "w", newline="") as f:
                csv.writer(f).writerow(["no_trucks_opened"])

        # ---- fleet_summary.csv ----
        fleet_path = os.path.join(dir_path, "fleet_summary.csv")
        if fleet:
            cols = [
                "N_trucks", "C_total", "C_per_vol", "C_per_w",
                "E_pack", "CV_Uvol",
                "MISS_VIP", "MISS_DUE", "AVG_DELAY", "VIP_ONTIME",
                "COLD_ON_DRY", "UNDER_MIN", "CAP_VIOLS", "SPLITS",
                "SUM_q", "SUM_v_eff", "SUM_w",
            ]
            # add any unexpected keys to the end
            extra = [k for k in fleet.keys() if k not in cols]
            cols += extra

            with open(fleet_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerow(fleet)
        else:
            with open(fleet_path, "w", newline="") as f:
                csv.writer(f).writerow(["no_data"])

    def export_assignments_csv(self, filepath: str) -> str:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        rows = self.assignment_rows
        if not rows:
            with open(filepath, "w", newline="") as f:
                f.write("")
            return filepath
        headers = list(rows[0].keys())
        with open(filepath, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return filepath

    def export_order_queue_csv(self, path: str | Path) -> None:
        """
        Write the ranked order queue to CSV.
        Columns: rank, order_id, vip, due, alpha, v_eff, weight, sort_key
        """
        rows = self.order_queue_log
        if not rows:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["rank", "order_id", "vip", "due", "alpha", "v_eff", "weight", "sort_key"]
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    def export_item_queue_csv(self, path: str | Path) -> None:
        """
        Write all per-order item rankings to a single CSV.
        Columns: order_id, rank, item_id, qty, cold01, w_ij, v_ij_eff, liquid01, stack_limit, fragile_score, upright01, sort_key
        """
        # flatten
        all_rows: list[dict] = []
        for oid, rows in self.item_queue_log.items():
            all_rows.extend(rows)
        if not all_rows:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "order_id", "rank", "item_id", "qty",
            "cold01", "w_ij", "v_ij_eff", "liquid01",
            "stack_limit", "fragile_score", "upright01",
            "sort_key",
        ]
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(all_rows)

    def export_order_status_csv(self, filepath):
        import csv, os
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        rows = []
        for oid, rec in self.orders.items():
            rows.append({
                "order_id": oid,
                "placed": bool(rec.get("placed", False)),
                "assigned_truck_count": int(rec.get("assigned_truck_count", 0)),
                "reason": rec.get("reason"),
                "is_vip": bool(rec.get("is_vip", False)),
                "due_met": rec.get("due_met"),
                "delay_min": rec.get("delay_min"),
            })
        if not rows:
            open(filepath, "w").close();
            return filepath
        with open(filepath, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader();
            w.writerows(rows)
        return filepath







