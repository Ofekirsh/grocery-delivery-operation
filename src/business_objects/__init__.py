"""
Domain model package for grocery-loading-planner.

This package defines the core business objects:
- Depot
- Customer
- CustomerOrder
- Truck
- Item

It also exposes shared enums and the Dimensions type from common.py.
"""

from .common import (
    TruckType,
    Fragility,
    SeparationTag,
    Dimensions,
)
from .depot import Depot
from .customer import Customer
from .customer_order import CustomerOrder
from .truck import Truck
from .item import Item

__all__ = [
    # common
    "TruckType",
    "Fragility",
    "SeparationTag",
    "Dimensions",
    # entities
    "Depot",
    "Customer",
    "CustomerOrder",
    "Truck",
    "Item",
]
