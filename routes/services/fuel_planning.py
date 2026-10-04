import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

from django.db import transaction

from routes.models import FuelStation, Trip, TripFuelStop
from routes.services.fuel_planning_types import (
    FuelStopPlan,
    _RouteSegment,
    _StationCandidate,
)

EARTH_RADIUS_MILES = 3958.7613
ROUTE_CORRIDOR_MILES = 10
DISTANCE_QUANTUM = Decimal("0.01")
GALLON_QUANTUM = Decimal("0.001")
COST_QUANTUM = Decimal("0.01")


class FuelStopPlanningError(ValueError):
    """Raised when a complete fuel-stop itinerary cannot be calculated."""


def _decimal(value, label: str) -> Decimal:
    """Convert a value to a finite Decimal or raise a planning error."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FuelStopPlanningError(f"{label} must be a valid number.") from exc
    if not result.is_finite():
        raise FuelStopPlanningError(f"{label} must be finite.")
    return result


def _coordinates_from_geometry(geometry) -> list[tuple[float, float]]:
    """Validate GeoJSON LineString geometry and return longitude-latitude pairs."""
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise FuelStopPlanningError("Trip route geometry must be a GeoJSON LineString.")

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise FuelStopPlanningError(
            "Trip route geometry must contain at least two coordinates."
        )

    points = []
    for index, coordinate in enumerate(coordinates):
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            raise FuelStopPlanningError(f"Invalid route coordinate at index {index}.")
        longitude = _decimal(coordinate[0], f"Route longitude at index {index}")
        latitude = _decimal(coordinate[1], f"Route latitude at index {index}")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise FuelStopPlanningError(
                f"Route coordinate at index {index} is out of range."
            )
        points.append((float(longitude), float(latitude)))
    return points


def _haversine_miles(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Return the great-circle distance between two coordinates in miles."""
    first_lon, first_lat = map(math.radians, first)
    second_lon, second_lat = map(math.radians, second)
    latitude_delta = second_lat - first_lat
    longitude_delta = second_lon - first_lon
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_lat)
        * math.cos(second_lat)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1, value)))


def _route_segments(geometry, route_distance_miles: Decimal) -> list[_RouteSegment]:
    """Scale LineString segments to the route service's reported total distance."""
    points = _coordinates_from_geometry(geometry)
    measured_lengths = [
        _haversine_miles(first, second) for first, second in zip(points, points[1:])
    ]
    geometry_length = sum(measured_lengths)
    if geometry_length <= 0:
        raise FuelStopPlanningError("Trip route geometry has zero length.")

    route_total = float(route_distance_miles)
    if route_total <= 0:
        raise FuelStopPlanningError("Trip route distance must be greater than zero.")

    scale = route_total / geometry_length
    segments = []
    accumulated = 0.0
    for first, second, measured_length in zip(points, points[1:], measured_lengths):
        length = measured_length * scale
        segments.append(_RouteSegment(accumulated, length, first, second))
        accumulated += length
    return segments


def _station_projection(
    station: FuelStation,
    segments: list[_RouteSegment],
    route_total: float,
) -> tuple[float, float] | None:
    """Project a station onto the nearest route segment if it is in the corridor."""
    station_point = float(station.longitude), float(station.latitude)
    nearest_distance = math.inf
    nearest_route_mile = 0.0

    for segment in segments:
        reference_latitude = math.radians(
            (segment.start[1] + segment.end[1] + station_point[1]) / 3
        )
        longitude_scale = math.cos(reference_latitude)
        start_x = math.radians(segment.start[0] - station_point[0]) * longitude_scale
        start_y = math.radians(segment.start[1] - station_point[1])
        end_x = math.radians(segment.end[0] - station_point[0]) * longitude_scale
        end_y = math.radians(segment.end[1] - station_point[1])

        delta_x = end_x - start_x
        delta_y = end_y - start_y
        length_squared = delta_x * delta_x + delta_y * delta_y
        fraction = (
            0.0
            if length_squared == 0
            else max(
                0.0,
                min(1.0, -(start_x * delta_x + start_y * delta_y) / length_squared),
            )
        )
        nearest_x = start_x + fraction * delta_x
        nearest_y = start_y + fraction * delta_y
        distance = math.hypot(nearest_x, nearest_y) * EARTH_RADIUS_MILES

        if distance < nearest_distance:
            nearest_distance = distance
            nearest_route_mile = segment.start_miles + segment.length_miles * fraction

    if nearest_distance > ROUTE_CORRIDOR_MILES:
        return None
    return min(route_total, max(0.0, nearest_route_mile)), nearest_distance


def _calculate_fuel_stop_plan(
    *,
    route_geometry,
    route_distance_miles,
    max_range_miles,
    mpg,
    initial_fuel_gallons,
    stations: Iterable[FuelStation],
) -> list[FuelStopPlan]:
    """Calculate a complete plan from route details and candidate stations."""
    route_total = _decimal(route_distance_miles, "Route distance")
    max_range = _decimal(max_range_miles, "Maximum range")
    miles_per_gallon = _decimal(mpg, "Vehicle MPG")
    initial_fuel = _decimal(initial_fuel_gallons, "Initial fuel")
    if max_range <= 0:
        raise FuelStopPlanningError("Maximum range must be greater than zero.")
    if miles_per_gallon <= 0:
        raise FuelStopPlanningError("Vehicle MPG must be greater than zero.")
    tank_capacity = max_range / miles_per_gallon
    if initial_fuel < 0 or initial_fuel > tank_capacity:
        raise FuelStopPlanningError(
            "Initial fuel must be between zero and the full-tank capacity."
        )
    if route_total < 0:
        raise FuelStopPlanningError("Route distance cannot be negative.")
    initial_range = initial_fuel * miles_per_gallon
    if route_total <= initial_range:
        return []

    segments = _route_segments(route_geometry, route_total)
    candidates = []
    seen_stations = set()
    for station in stations:
        if station.pk is not None:
            if station.pk in seen_stations:
                continue
            seen_stations.add(station.pk)
        if station.latitude is None or station.longitude is None:
            continue

        station_prices = station.prices
        prices = (
            station_prices.all() if hasattr(station_prices, "all") else station_prices
        )
        if hasattr(prices, "order_by"):
            price = prices.order_by("pk").first()
        else:
            price = next(iter(prices), None)
        if price is None:
            continue

        projection = _station_projection(
            station,
            segments,
            float(route_total),
        )
        if projection is None:
            continue
        route_mile, _offset = projection
        candidates.append(
            _StationCandidate(
                station=station,
                price=_decimal(price.price_per_gallon, "Station fuel price"),
                distance_miles=route_mile,
            )
        )

    if not candidates:
        raise FuelStopPlanningError(
            "No priced stations with coordinates were found within "
            f"{ROUTE_CORRIDOR_MILES} miles of the route."
        )

    plan = []
    current_position = 0.0
    previous_stop = 0.0
    sequence = 1
    while float(route_total) - current_position > float(
        initial_range if sequence == 1 else max_range
    ):
        available_range = initial_range if sequence == 1 else max_range
        reachable = [
            candidate
            for candidate in candidates
            if current_position + 0.01
            < candidate.distance_miles
            <= current_position + float(available_range)
        ]
        if not reachable:
            raise FuelStopPlanningError(
                f"No station within range after mile {current_position:.2f}; "
                "a complete itinerary cannot be planned."
            )

        selected = min(
            reachable,
            key=lambda candidate: (
                candidate.price,
                -candidate.distance_miles,
            ),
        )
        leg_distance = Decimal(str(selected.distance_miles - previous_stop))
        fuel_used = (leg_distance / miles_per_gallon).quantize(
            GALLON_QUANTUM, rounding=ROUND_HALF_UP
        )
        fuel_before_refill = initial_fuel if sequence == 1 else tank_capacity
        gallons = (tank_capacity - fuel_before_refill + fuel_used).quantize(
            GALLON_QUANTUM, rounding=ROUND_HALF_UP
        )
        estimated_cost = (gallons * selected.price).quantize(
            COST_QUANTUM, rounding=ROUND_HALF_UP
        )
        plan.append(
            FuelStopPlan(
                station=selected.station,
                sequence=sequence,
                distance_from_start_miles=Decimal(
                    str(selected.distance_miles)
                ).quantize(DISTANCE_QUANTUM, rounding=ROUND_HALF_UP),
                gallons_to_buy=gallons,
                price_per_gallon=selected.price,
                estimated_cost=estimated_cost,
            )
        )

        previous_stop = selected.distance_miles
        current_position = selected.distance_miles
        sequence += 1

    return plan


def plan_trip_fuel_stops(trip: Trip) -> list[TripFuelStop]:
    """Calculate and atomically persist all recommended fuel stops for a trip."""
    if trip.route_distance_miles is None:
        raise FuelStopPlanningError("Trip must have a route distance before planning.")

    stations = (
        FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            prices__isnull=False,
        )
        .prefetch_related("prices")
        .distinct()
    )
    plan = _calculate_fuel_stop_plan(
        route_geometry=trip.route_geometry,
        route_distance_miles=trip.route_distance_miles,
        max_range_miles=trip.max_range_miles,
        mpg=trip.mpg,
        initial_fuel_gallons=trip.initial_fuel_gallons,
        stations=stations,
    )

    with transaction.atomic():
        trip.fuel_stops.all().delete()
        persisted_stops = TripFuelStop.objects.bulk_create(
            [
                TripFuelStop(
                    trip=trip,
                    station=item.station,
                    sequence=item.sequence,
                    distance_from_start_miles=item.distance_from_start_miles,
                    gallons_to_buy=item.gallons_to_buy,
                    price_per_gallon=item.price_per_gallon,
                    estimated_cost=item.estimated_cost,
                )
                for item in plan
            ]
        )
        trip.estimated_fuel_cost = sum(
            (item.estimated_cost for item in plan), start=Decimal("0.00")
        ).quantize(COST_QUANTUM)
        trip.save(update_fields=("estimated_fuel_cost",))

    return persisted_stops
