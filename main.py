# src/main.py
from src.business_objects.config import InstanceGenConfig
from src.business_objects.generators import make_objects, save_json_files


def main():
    # ------------------------------------------------------------
    # Define full configuration
    # ------------------------------------------------------------
    cfg = InstanceGenConfig(
        seed=123,
        items=dict(
            num_items=20,
            cold_ratio=0.45,
            weight_kg=(0.5, 9.0),
            volume_m3=(0.001, 0.02),
            padding=(0.00, 0.08),
        ),
        customers=dict(
            num_customers=10,
            vip_fraction=0.30,  # 30% VIP customers
        ),
        orders=dict(
            num_orders=20,
            items_per_order=(2, 4),  # number of item types per order
            qty_per_item=(1, 4),     # quantity per item type
            earliest_due="09:00",
            latest_due="22:00",      # ensure ≤ 22:00
            max_cold_fraction=0.6,
        ),
        trucks=dict(
            # either generate from templates...
            num_trucks_cold=2,
            num_trucks_dry=3,
            total_capacity_m3=(20.0, 35.0),
            cold_capacity_m3=(8.0, 15.0),
            weight_limit_kg=(8000.0, 12000.0),
            fixed_cost=(400.0, 600.0),
            reserve_fraction=(0.05, 0.08),
            min_util_cold=0.6,
            min_util_dry=0.75,
        ),
        depots=dict(
            num_depots=1,
            availability=("sample", 2),  # randomly choose 2 trucks as available
        ),
    )

    # ------------------------------------------------------------
    # Generate synthetic objects
    # ------------------------------------------------------------
    objs = make_objects(cfg)

    depots = objs["depots"]
    customers = objs["customers"]
    orders = objs["orders"]
    items = objs["items"]
    trucks = objs["trucks"]

    print(f"Generated {len(items)} items, {len(customers)} customers, "
          f"{len(orders)} orders, {len(trucks)} trucks, {len(depots)} depots.\n")

    # Show a few examples
    for cid, c in list(customers.items())[:3]:
        print(f"Customer {cid}: name={c.name}, VIP={c.vip}")

    print("\nSample Order:")
    first_order = next(iter(orders.values()))
    print(first_order)
    print(first_order.totals_dict())

    # ------------------------------------------------------------
    # Export to JSON-ready dicts
    # ------------------------------------------------------------
    save_json_files(objs, output_dir="generated_example_1")


if __name__ == "__main__":
    main()
