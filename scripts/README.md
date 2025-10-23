# Scripts

## Generating Examples

Generate synthetic delivery instances using predefined scenarios or custom parameters.

### Quick Start
```bash
# Generate small sized example (default)
python scripts/generate_example.py

# Use predefined scenarios
python scripts/generate_example.py --scenario small
python scripts/generate_example.py --scenario large --output problems/large_problem

# Custom parameters
python scripts/generate_example.py --seed 42 --orders 30 --customers 15
```

### Available Scenarios

| Scenario | Items | Customers | Orders | Trucks (Cold/Dry) |
|----------|-------|-----------|--------|-------------------|
| `small`  | 10    | 5         | 8      | 1 / 2             |
| `medium` | 20    | 10        | 20     | 2 / 3             |
| `large`  | 50    | 30        | 60     | 8 / 12            |

### Output

Creates a directory with JSON files:
```
problems/problem_1/
   ├── items.json
   ├── customers.json
   ├── orders.json
   ├── trucks.json
   └── depots.json
```



### Key parameters (edit in `generate_problem.py`):
- **Items:** `num_items`, `cold_ratio` (0.0-1.0), `weight_kg`, `volume_m3`, `padding`
- **Customers:** `num_customers`, `vip_fraction` (0.0-1.0)
- **Orders:** `num_orders`, `items_per_order` (min, max), `qty_per_item` (min, max), `earliest_due`, `latest_due`, `max_cold_fraction`
- **Trucks:** `num_trucks_cold`, `num_trucks_dry`, `total_capacity_m3`, `cold_capacity_m3`, `weight_limit_kg`, `fixed_cost`, `min_util_cold`, `min_util_dry`
- **Depots:** `availability="all"` or `availability=("sample", k)` to limit available trucks

---

