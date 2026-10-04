"""Typed data structures shared by the fuel-planning service."""

from dataclasses import dataclass
from decimal import Decimal

from routes.models import FuelStation


@dataclass(frozen=True)
class FuelStopPlan:
    """Represent one calculated fuel stop before it is persisted."""

    station: FuelStation
    sequence: int
    distance_from_start_miles: Decimal
    gallons_to_buy: Decimal
    price_per_gallon: Decimal
    estimated_cost: Decimal


@dataclass(frozen=True)
class _RouteSegment:
    """Represent one route segment and its cumulative distance from the start."""

    start_miles: float
    length_miles: float
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True)
class _StationCandidate:
    """Represent a priced station projected onto the route."""

    station: FuelStation
    price: Decimal
    distance_miles: float
