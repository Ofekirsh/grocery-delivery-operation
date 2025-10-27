# src/metrics/kpis.py
from __future__ import annotations

from math import fsum, sqrt
from typing import Iterable, Mapping, Sequence, Tuple


EPS = 1e-12


# ───────────────────────────── per-truck KPIs ───────────────────────────── #

def u_vol_k(loaded_v_eff: float, Q_k: float) -> float:
    """
    Truck volume utilization  U_k^{vol}.

    Notation:
        U_k^{vol} = (∑_i v_i^{eff} · x_{ik}) / Q_k

    Args:
        loaded_v_eff: sum of effective volumes loaded on truck k (∑ v_i^{eff} x_{ik})
        Q_k: total volume capacity of truck k

    Returns:
        Utilization in [0, 1] (0 if Q_k <= 0).
    """
    if Q_k <= EPS:
        return 0.0
    return max(0.0, min(1.0, float(loaded_v_eff) / float(Q_k)))


def u_w_k(loaded_w: float, W_k: float) -> float:
    """
    Truck weight utilization  U_k^{wt}.

    Notation:
        U_k^{wt} = (∑_i w_i · x_{ik}) / W_k

    Args:
        loaded_w: sum of weights loaded on truck k (∑ w_i x_{ik})
        W_k: weight limit of truck k

    Returns:
        Utilization (0 if W_k <= 0).
    """
    if W_k <= EPS:
        return 0.0
    return max(0.0, float(loaded_w) / float(W_k))


def u_cold_k(loaded_q_cold: float, Q_k_cold: float) -> float:
    """
    Cold-compartment utilization for reefers  U_k^{cold}.

    Notation:
        U_k^{cold} = (∑_i q_i^{cold} · x_{ik}) / Q_k^{cold}

    Args:
        loaded_q_cold: sum of cold volumes on truck k
        Q_k_cold: refrigerated capacity of truck k (0 for dry trucks)

    Returns:
        Utilization (0 if Q_k_cold <= 0).
    """
    if Q_k_cold <= EPS:
        return 0.0
    return max(0.0, min(1.0, float(loaded_q_cold) / float(Q_k_cold)))


def u_bn_k(u_vol: float, u_w: float) -> float:
    """
    Bottleneck efficiency  U_k^{bottleneck}.

    Notation:
        U_k^{bottleneck} = min( U_k^{vol}, U_k^{wt} )
    """
    return float(min(u_vol, u_w))


def under_min_flag(u_vol: float, tau_min: float) -> int:
    """
    Flag (0/1) if a deployed truck violates minimum utilization.

    Notation:
        1[ U_k^{vol} < τ^{min} ]
    """
    return int(u_vol + EPS < float(tau_min))


def cap_violation_flag(loaded_v_eff: float, Q_k: float,
                       loaded_w: float, W_k: float,
                       loaded_q_cold: float, Q_k_cold: float) -> int:
    """
    Flag (0/1) if any capacity limit is violated on truck k.

    Notation:
        1[ (∑ v_i^{eff} x_{ik} > Q_k) ∨ (∑ w_i x_{ik} > W_k) ∨ (∑ q_i^{cold} x_{ik} > Q_k^{cold}) ]
    """
    v_bad = (Q_k > EPS) and (loaded_v_eff - Q_k > EPS)
    w_bad = (W_k > EPS) and (loaded_w - W_k > EPS)
    c_bad = (Q_k_cold > EPS) and (loaded_q_cold - Q_k_cold > EPS)
    return int(v_bad or w_bad or c_bad)


# ───────────────────────────── fleet/day KPIs ───────────────────────────── #

def e_pack(total_q_geom: float, total_v_eff: float) -> float:
    """
    Packing efficiency  E^{pack}.

    Notation:
        E^{pack} = (∑_i q_i) / (∑_i v_i^{eff})

    Args:
        total_q_geom: sum of geometric volumes ∑ q_i (pre-padding)
        total_v_eff: sum of effective volumes ∑ v_i^{eff} (post-padding)

    Returns:
        Ratio in (0, +inf). Returns 0 if denominator is 0.
    """
    if total_v_eff <= EPS:
        return 0.0
    return max(0.0, float(total_q_geom) / float(total_v_eff))


def n_trucks_opened(y_k: Iterable[int]) -> int:
    """
    Number of deployed trucks.

    Notation:
        N_{trucks} = ∑_k y_k
    """
    return int(sum(int(v) for v in y_k))


def c_total(fixed_costs_for_open_trucks: Iterable[float]) -> float:
    """
    Total fixed deployment cost.

    Notation:
        C_{total} = ∑_k c_k · y_k
    """
    return float(fsum(float(c) for c in fixed_costs_for_open_trucks))


def c_per_vol(c_total_value: float, sum_q: float) -> float:
    """
    Cost per loaded geometric volume.

    Notation:
        C_{vol} = C_{total} / (∑_i q_i)
    """
    if sum_q <= EPS:
        return 0.0
    return float(c_total_value) / float(sum_q)


def c_per_w(c_total_value: float, sum_w: float) -> float:
    """
    Cost per loaded weight.

    Notation:
        C_{wt} = C_{total} / (∑_i w_i)
    """
    if sum_w <= EPS:
        return 0.0
    return float(c_total_value) / float(sum_w)


def cv(values: Sequence[float]) -> float:
    """
    Coefficient of variation for a sequence of non-negative values.

    Notation:
        CV(x) = σ(x) / μ(x)

    Returns:
        0 if μ == 0 or the list is empty.
    """
    n = len(values)
    if n == 0:
        return 0.0
    mean = fsum(values) / n
    if mean <= EPS:
        return 0.0
    var = fsum((x - mean) ** 2 for x in values) / n
    return float(sqrt(var) / mean)


def cv_uvol(uvol_list: Sequence[float]) -> float:
    """
    CV of volume utilizations across opened trucks.

    Notation:
        CV(U^{vol}) = σ(U_k^{vol}) / μ(U_k^{vol})
    """
    return cv(uvol_list)


def miss_vip(n_missed_vip: int) -> int:
    """
    Number of missed VIP deliveries.

    Notation:
        M_{VIP} = # { i : VIP_i = 1 ∧ missed }
    """
    return int(n_missed_vip)


def miss_due(n_missed_due: int) -> int:
    """
    Number of orders with missed due dates.

    Notation:
        M_{due} = # { i : deadline missed }
    """
    return int(n_missed_due)


def avg_delay(delays_minutes: Iterable[float]) -> float:
    """
    Average lateness among delayed orders.

    Notation:
        L̄ = mean( delay_i ), taken over delayed orders only.

    Returns:
        0 if no delayed orders provided.
    """
    delays = [float(d) for d in delays_minutes if d is not None]
    if not delays:
        return 0.0
    return float(fsum(delays) / len(delays))


def vip_ontime(n_vip_total: int, n_vip_missed: int) -> float:
    """
    Share of VIP orders delivered on time.

    Notation:
        S_{VIP} = 1 - M_{VIP} / # { i : VIP_i = 1 }

    Returns:
        Fraction in [0, 1]. If no VIP orders, returns 1.0 by convention.
    """
    if n_vip_total <= 0:
        return 1.0
    n_ontime = max(0, int(n_vip_total) - int(n_vip_missed))
    return float(n_ontime) / float(n_vip_total)


def cold_on_dry(assignments: Iterable[Tuple[bool, bool]]) -> int:
    """
    Count of cold orders assigned to dry trucks.

    Notation:
        V_{cold→dry} = ∑_{i : q_i^{cold} > 0} ∑_{k ∈ K^D} x_{ik}

    Args:
        assignments: iterable of pairs (order_is_cold, truck_is_dry)

    Returns:
        Integer count.
    """
    return sum(1 for is_cold, is_dry in assignments if is_cold and is_dry)


def under_min_count(uvol_list: Iterable[float], tau_min_list: Iterable[float]) -> int:
    """
    Count of deployed trucks below minimum utilization.

    Notation:
        V_{util}^{min} = # { k : y_k = 1 ∧ U_k^{vol} < τ^{min} }
    """
    return sum(int(u + EPS < t) for u, t in zip(uvol_list, tau_min_list))


def cap_violations_count(truck_measures: Iterable[Tuple[float, float, float, float, float, float]]) -> int:
    """
    Count of capacity violations across deployed trucks.

    Notation:
        V_{cap} = # { k : (∑ v_i^{eff} x_{ik} > Q_k) ∨ (∑ w_i x_{ik} > W_k) ∨ (∑ q_i^{cold} x_{ik} > Q_k^{cold}) }

    Args:
        truck_measures: iterable of tuples
            (loaded_v_eff, Q_k, loaded_w, W_k, loaded_q_cold, Q_k_cold)
    """
    return sum(
        cap_violation_flag(v, Q, w, W, qc, Qc)
        for (v, Q, w, W, qc, Qc) in truck_measures
    )


def splits_count(assignments_per_order: Mapping[str, int]) -> int:
    """
    Count orders that are split or unassigned.

    Notation:
        V_{split} = # { i : ∑_k x_{ik} ≠ 1 }

    Args:
        assignments_per_order: map order_id -> number of trucks assigned to that order

    Returns:
        Count of orders where the total assignment is not exactly 1.
    """
    return sum(1 for cnt in assignments_per_order.values() if int(cnt) != 1)

def avg_u_vol(uvol_list: Sequence[float]) -> float:
    """Average volume utilization across all trucks."""
    if not uvol_list:
        return 0.0
    return float(fsum(uvol_list) / len(uvol_list))


def avg_u_w(uw_list: Sequence[float]) -> float:
    """Average weight utilization across all trucks."""
    if not uw_list:
        return 0.0
    return float(fsum(uw_list) / len(uw_list))


def avg_u_cold(ucold_list: Sequence[float]) -> float:
    """Average cold utilization across reefer trucks only."""
    if not ucold_list:
        return 0.0
    return float(fsum(ucold_list) / len(ucold_list))


def avg_u_bn(ubn_list: Sequence[float]) -> float:
    """Average bottleneck efficiency across all trucks."""
    if not ubn_list:
        return 0.0
    return float(fsum(ubn_list) / len(ubn_list))


def cv_u_w(uw_list: Sequence[float]) -> float:
    """CV of weight utilizations across opened trucks."""
    return cv(uw_list)


def cv_u_bn(ubn_list: Sequence[float]) -> float:
    """CV of bottleneck efficiency across opened trucks."""
    return cv(ubn_list)
