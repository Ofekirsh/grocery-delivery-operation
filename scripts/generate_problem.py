"""
Generate synthetic grocery delivery instances.

Usage:
    python scripts/generate_example.py --output problems/problem_1 --seed 123
    python scripts/generate_example.py --scenario small
    python scripts/generate_example.py --scenario large --orders 50
"""

import argparse
from src.business_objects.config import InstanceGenConfig
from src.business_objects.generators import make_objects, save_json_files

# Predefined scenarios
SCENARIOS = {
    "small": InstanceGenConfig(
        seed=42,
        items=dict(num_items=10, cold_ratio=0.4, weight_kg=(0.5, 9.0), volume_m3=(0.001, 0.02)),
        customers=dict(num_customers=5, vip_fraction=0.2),
        orders=dict(num_orders=8, items_per_order=(1, 3), qty_per_item=(1, 3)),
        trucks=dict(num_trucks_cold=1, num_trucks_dry=2),
        depots=dict(num_depots=1, availability="all"),
    ),
    "medium": InstanceGenConfig(
        seed=123,
        items=dict(num_items=20, cold_ratio=0.45, weight_kg=(0.5, 9.0), volume_m3=(0.001, 0.02)),
        customers=dict(num_customers=10, vip_fraction=0.30),
        orders=dict(num_orders=20, items_per_order=(2, 4), qty_per_item=(1, 4)),
        trucks=dict(num_trucks_cold=2, num_trucks_dry=3),
        depots=dict(num_depots=1, availability=("sample", 4)),
    ),
    "large": InstanceGenConfig(
        seed=999,
        items=dict(num_items=50, cold_ratio=0.5, weight_kg=(0.5, 9.0), volume_m3=(0.001, 0.02)),
        customers=dict(num_customers=30, vip_fraction=0.25),
        orders=dict(num_orders=60, items_per_order=(3, 8), qty_per_item=(1, 5)),
        trucks=dict(num_trucks_cold=8, num_trucks_dry=12),
        depots=dict(num_depots=1, availability=("sample", 15)),
    ),
}


def main():
    parser = argparse.ArgumentParser(description="Generate grocery delivery example")
    parser.add_argument("--output", default="../problems/problem_1", help="Output directory name")
    parser.add_argument("--scenario", choices=["small", "medium", "large"], default="small", help="Use predefined scenario")
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--orders", type=int, help="Override number of orders")
    parser.add_argument("--customers", type=int, help="Override number of customers")

    args = parser.parse_args()

    # Load configuration
    if args.scenario:
        cfg = SCENARIOS[args.scenario]
        print(f"Using '{args.scenario}' scenario")
    else:
        # Default configuration
        cfg = SCENARIOS["medium"]

    # Apply overrides
    if args.seed:
        cfg.seed = args.seed
    if args.orders:
        cfg.orders["num_orders"] = args.orders
    if args.customers:
        cfg.customers["num_customers"] = args.customers

    # Generate objects
    print(f"\nGenerating with seed={cfg.seed}...")
    objs = make_objects(cfg)

    print(f"✓ Generated {len(objs['items'])} items, {len(objs['customers'])} customers, "
          f"{len(objs['orders'])} orders, {len(objs['trucks'])} trucks\n")

    # Show preview
    print("Sample Customers:")
    for cid, c in list(objs["customers"].items())[:3]:
        print(f"  {cid}: {c.name}, VIP={c.vip}")

    print("\nSample Order:")
    first_order = next(iter(objs["orders"].values()))
    print(f"  {first_order}")

    # Save to JSON
    save_json_files(objs, output_dir=args.output)
    print(f"\n✓ Saved to '{args.output}/' directory")


if __name__ == "__main__":
    main()