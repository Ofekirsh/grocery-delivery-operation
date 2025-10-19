
# Grocery Loading Planner

This project models the daily logistics of a grocery delivery operation.

---

## Grocery Depot

| Property             | Description                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------ |
| **Depot ID**         | Unique identifier for each depot.                                                          |
| **Location**         | Central facility where all customer orders are prepared and loaded onto trucks.            |
| **Available trucks** | Set of all vehicles (refrigerated and dry) currently operational and ready for deployment. |

---

## Customer

| Property              | Description                                                                                                                    |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Customer ID**       | Unique identifier for each customer.                                                                                           |
| **Name**              | Full name of the customer.                                                                                                     |
| **Email address**     | Contact email for notifications and delivery updates.                                                                          |
| **Priority (VIP)**    | Whether the customer is high-priority and must be served first.                                                                |
| **Customer order(s)** | Associated order objects linked to this customer. *(In each Customer Order, a `Customer ID` field provides the reverse link.)* |
| **Address**           | Delivery address of the customer’s supermarket or store.                                                                       |

---

## Customer Order

| Property             | Description                                                                     |
| -------------------- | ------------------------------------------------------------------------------- |
| **Order ID**         | Unique reference linked to a customer (via Customer ID).                        |
| **Customer ID**      | Reference to the associated customer.                                           |
| **Total volume**     | Total required space, including packaging allowances for fragile items (in m³). |
| **Cold volume**      | Portion of the order requiring refrigeration (in m³).                           |
| **Weight**           | Total order weight (in kg).                                                     |
| **Item list**        | Collection of Item IDs and quantities included in the order.                    |
| **Due date**         | Requested delivery deadline (HH:MM).                                            |
| **Cold fraction αᵢ** | Calculated as `cold volume / total volume`, a number between 0 and 1.           |

---

## Truck

| Property                                  | Description                                                     |
| ----------------------------------------- | --------------------------------------------------------------- |
| **Truck ID**                              | Unique identifier for each vehicle.                             |
| **Type**                                  | “Reefer” (refrigerated) or “Dry”.                               |
| **Total capacity (Qₖ)**                   | Maximum loading volume (m³).                                    |
| **Cold capacity (Qₖ_cold)**               | Refrigerated space (m³) available in reefer trucks.             |
| **Weight limit (Wₖ)**                     | Maximum permissible load weight (kg).                           |
| **Fixed deployment cost (cₖ)**            | Operating cost incurred if the truck is deployed.               |
| **Minimum utilization threshold (τ_min)** | Minimum fraction of capacity required before departure.         |
| **Reserve capacity fraction (r)**         | Portion intentionally left unused for flexibility (e.g., 5-8%). |

---

## Item

| Property                   | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| **Item ID**                | Unique identifier for each catalog product.                  |
| **Item name**              | Commercial name used in stores.                              |
| **Category**               | “Cold” or “Dry”.                                             |
| **Weight (kg)**            | Per-unit weight.                                             |
| **Volume (m³)**            | Per-unit volume.                                             |
| **Dimensions (L×W×H)**     | Physical size in meters.                                     |
| **Fragility level**        | Regular, delicate, or fragile.                               |
| **Max stack load (kg)**    | Maximum allowable weight stacked on top.                     |
| **Liquid (Y/N)**           | Whether it can spill.                                        |
| **Upright (Y/N)**          | Must stay vertical.                                          |
| **Separation tag**         | Safety classification (Food, Non-Food, Allergen, Hazardous). |
| **Space factor (padding)** | Extra space reserved for packaging or handling.              |

---

## How to Generate an Example

1. **Define a configuration**
   In `main.py`, set parameters such as:

   * number of items, customers, and orders
   * number of cold vs. dry trucks
   * VIP customer fraction
   * due-date window
   * depot availability mode (`"all"` or `("sample", k)`)

2. **Generate objects**
   Run:

   ```bash
   python src.main
   ```

   The program uses `make_objects(cfg)` to create a realistic daily scenario, printing summaries of each table.

3. **Export to JSON**
   The script automatically calls:

   ```python
   save_json_files(objs, output_dir="generated_example_1")
   ```

   This creates a folder containing:

   ```
   generated_example_1/
   ├── items.json
   ├── customers.json
   ├── orders.json
   ├── trucks.json
   └── depots.json
   ```

   Each file is a clean JSON representation of the generated data - ready for loading into your heuristic or optimization model.

---