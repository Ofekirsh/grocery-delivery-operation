from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
from .truck import Truck


@dataclass
class Depot:
    """
    Central facility for a delivery day.
    `available_trucks` holds *instances* that can be mutated by planners
    (loads, schedules…), so pass copies if you need isolation across runs.
    """
    depot_id: str
    location: str
    available_trucks: Dict[str, Truck]

    def truck_ids(self):
        return list(self.available_trucks.keys())

    def get_truck(self, truck_id: str) -> Truck:
        return self.available_trucks[truck_id]
