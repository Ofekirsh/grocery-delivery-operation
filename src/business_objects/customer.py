from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Customer:
    """
    Customer data (fairly permanent).
    The relation to orders is *referential* (orders store `customer_id`).
    """
    customer_id: str
    name: str
    email: str
    vip: bool
    address: str
