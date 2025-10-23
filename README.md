
# Grocery Loading Planner

This repository implements a two-phase heuristic planner for grocery delivery operations.
It integrates order and item prioritization (Phase 1) with truck assignment and loading (Phase 2), supported by a detailed tracking and KPI-evaluation framework.

---

##  Phase 1 - Select Next

### **SelectionState**

The **`SelectionState`** encapsulates all relevant operational data at the start of the planning day.
It serves as the shared interface for both the **Order Selector** and the **Item Sorter**.

It provides structured access to:

* **Order-level features:**
  volume, cold fraction, weight, due time, VIP status, etc.
* **Item-level features:**
  cold indicator, fragile/upright flags, weight, stack limit, etc.
* **Reference data:**
  depot configuration, customer attributes, and any precomputed metrics.

The state is immutable during Phase 1 - its role is purely descriptive, not operational.
All ranking operations read from this state but do not modify it.

---

### **Order Selector**

The **Order Selector** ranks all orders globally to decide which should be served first.
It operates based on a **configurable ranking scheme**, allowing different strategic priorities.

Each scheme is a sequence of ranking dimensions applied in order of importance (like SQL `ORDER BY`).
For example:

```python
scheme = ["vip", "due", "alpha", "v_eff"]
selector = OrderLevelSelector(scheme=scheme)
```

Available ranking dimensions include:

* `vip` - prioritize VIP customers
* `due` - earlier due times first
* `alpha` - higher cold fraction first
* `v_eff` - effective volume (smaller first)
* `w` - weight-based tiebreaker

You can freely compose or extend the scheme to match your business rules.
The output is a ranked list of `OrderRank` objects, each with the order ID and its feature summary.

---

### **Item Sorter**

The **Item Sorter** operates *within each ranked order*, producing a local picking or packing priority for its items.
It also uses a customizable **sorting scheme**, similar to the order selector.

Example:

```python
scheme = ["cold01", "fragile", "weight", "v_eff"]
sorter = ItemLevelSorter(scheme=scheme)
```

Supported dimensions include:

* `cold01` - cold items first
* `fragile` - handle delicate items early
* `upright` - prioritize upright-only items
* `stack_limit` - avoid low stack-load items on the bottom
* `weight` or `v_eff` - for balancing and space optimization

The sorter returns a sequence of `ItemRank` objects containing:

* `item_id`
* `qty`
* structured `features` (weight, volume, cold flag, etc.)

---

### **DayTracker Integration**

All Phase 1 outputs are logged to the **DayTracker** for reproducibility and auditability:

* `record_order_queue()` - stores the global order ranking
* `record_item_queue()` - stores per-order item rankings

This makes Phase 1 fully transparent:
you can later inspect or export the prioritized sequences directly as CSV files for analysis or debugging.

---



## Phase 2 - Place Next

### **Placer Orchestrator**

The central controller for Phase 2.

1. Receives ranked orders from Phase 1.
2. Determines the **bucket** (A / B / C) for each order:

   * **A** - Cold mandatory → Reefer only
   * **B** - Mixed/Flexible → Prefer reefer, allow dry + cooler if policy allows
   * **C** - Dry only → Dry trucks
3. Routes each order to the corresponding *placer function*:

   * `assign_to_best_reefer` → Reefer heuristic
   * `assign_bucket_b_order` → Mixed (reefer or dry+cooler)
   * `assign_bucket_c_order` → Dry heuristic
4. Commits accepted placements through `apply_decision`, which:

   * Updates truck loads (`used_volume_m3`, `used_weight_kg`, etc.)
   * Tracks portable-cooler usage (`cooler_used_m3`)
   * Records the assignment in `DayTracker`
   * Logs packing placements for audit

---

### **Heuristic Schemes**

Each placer ranks candidate trucks with a configurable **scheme** of residual criteria (minimize → tighter fit).

| Function                | Default Scheme                                                       | Notes                          |
| ----------------------- | -------------------------------------------------------------------- | ------------------------------ |
| `assign_to_best_reefer` | `("cold","volume","weight")`                                         | Reefer only                    |
| `assign_bucket_b_order` | Reefer → `("cold","volume","weight")` Dry → `("volume","weight")` | Mixed (Reefer or Dry + Cooler) |
| `assign_bucket_c_order` | `("volume","weight")`                                                | Dry only                       |

Example – favor volume before cold:

```python
assign_to_best_reefer(..., ranking_scheme=("volume","cold","weight"))
```

Unknown dims raise `ValueError`; infeasible trucks are filtered before ranking.

---

### **Policy (`src/heuristics/placers/policy.py`)**

Global knobs controlling placement behavior:

| Parameter                  | Description                                              |
| -------------------------- | -------------------------------------------------------- |
| `alpha_threshold`          | Boundary between cold (A), mixed (B), and dry (C) orders |
| `allow_open_new_reefer_A`  | Open a new reefer when no current one fits               |
| `allow_cold_in_dry_B`      | Permit cooler use in dry trucks                          |
| `per_truck_cooler_m3`      | Cooler capacity (m³) for dry trucks                      |
| `allow_open_new_dry_B / C` | Control new-truck openings                               |
| `day_bottleneck`           | Not used - `assign_bucket_c_order` already allows choosing scheme `("volume","weight")` or `("weight","volume")` based on daily bottleneck                |

---

### **Feasibility Service**

Encapsulates all constraint checks:

* volume / weight / cold residuals
* `cooler_feasible()` – verifies that a cold portion can fit into a cooler in dry truck when policy allows

---

### **Loading Policy (`src/heuristics/placers/packing.py`)**

Implements the intra-truck packing logic (`PackingPolicy.plan()`):

* Iterates ranked items and assigns them to:

  * **Zones**: `ambient`, `cold`, `haz`
  * **Lanes**: `left` vs `right` (balancing load)
  * **Layers**: `floor` vs `top` for fragile/upright items
* Returns a structured `PackingPlan` (`placements` + `notes`).

---

## Quality Metrics

| Quality Metric                                            | Description                     |
| ------------------------------------------------- | ------------------------------- |
| `N_trucks`                                        | Trucks opened                   |
| `C_total` / `C_per_vol` / `C_per_w`               | Total & normalized costs        |
| `E_pack`                                          | Packing efficiency              |
| `CV_Uvol`                                         | Volume utilization variance     |
| `MISS_VIP`, `MISS_DUE`                            | Service-level violations        |
| `VIP_ONTIME`                                      | VIP service ratio               |
| `COLD_ON_DRY`, `CAP_VIOLS`, `SPLITS`, `UNDER_MIN` | Policy & constraint breaches    |
| `SUM_q`, `SUM_v_eff`, `SUM_w`                     | Total delivered volume & weight |

---

## Reports

From the `scripts/run.py` driver you can export:

| File              | Generated by                       | Description                                 |
| ----------------- | ---------------------------------- | ------------------------------------------- |
| `assignments.csv` | `tracker.export_assignments_csv()` | Detailed item placement (zone, lane, layer) |
| `per_truck.csv`   | `orchestrator.export_reports()`    | Per-truck KPIs                              |
| `fleet.csv`       | `orchestrator.export_reports()`    | Aggregate fleet KPIs                        |
| `orders.csv`      | `tracker.record_order_queue()`     | Phase-1 order ranking                       |
| `items.csv`       | `tracker.record_item_queue()`      | Phase-1 item ranking                        |

---

## Additional Documentation

- **[Business Objects](src/business_objects/README.md)** - business objects with property definitions
- **[Scripts](scripts/README.md)** - Generate synthetic instances and run heuristics with configurable parameters
