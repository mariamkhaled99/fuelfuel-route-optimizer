"""Service entry points for route planning."""

from routes.services.fuel_planning import plan_trip_fuel_stops
from routes.services.trip_planning import build_trip_plan

__all__ = ["build_trip_plan", "plan_trip_fuel_stops"]
