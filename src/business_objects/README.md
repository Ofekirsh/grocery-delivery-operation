# Business Objects

This directory contains the business objects for the grocery depot delivery operation.

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