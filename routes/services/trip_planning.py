"""Geocode trip locations, fetch a route, and persist its fuel-stop plan."""

import hashlib
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from routes.models import Trip
from routes.services.fuel_planning import plan_trip_fuel_stops

NOMINATIM_CACHE_SECONDS = 30 * 24 * 60 * 60
NOMINATIM_REQUEST_INTERVAL_SECONDS = 1
NOMINATIM_LOCK_TIMEOUT_SECONDS = 30
METERS_PER_MILE = Decimal("1609.344")
DISTANCE_QUANTUM = Decimal("0.01")
COORDINATE_QUANTUM = Decimal("0.000001")


class TripPlanningProviderError(RuntimeError):
    """Raised when a geocoding or routing provider returns an invalid response."""


class TripLocationNotFoundError(ValueError):
    """Raised when Nominatim cannot find one of the requested U.S. locations."""


class TripRouteNotFoundError(ValueError):
    """Raised when OSRM cannot find a driving route between the locations."""


def _cache_key_for_location(query: str) -> str:
    """Create a stable cache key for a normalized location query."""
    normalized = " ".join(query.casefold().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"trip-geocode:{digest}"


def _acquire_nominatim_lock() -> str:
    """Acquire a cache-backed lock so uncached public geocoding stays rate-limited."""
    token = uuid4().hex
    lock_key = "trip-geocode:nominatim-request-lock"
    deadline = time.monotonic() + NOMINATIM_LOCK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if cache.add(lock_key, token, timeout=NOMINATIM_LOCK_TIMEOUT_SECONDS):
            return token
        time.sleep(0.05)
    raise TripPlanningProviderError(
        "The location service is busy; please retry the request."
    )


def _release_nominatim_lock(token: str) -> None:
    """Release the Nominatim request lock only when it is still owned by this call."""
    lock_key = "trip-geocode:nominatim-request-lock"
    if cache.get(lock_key) == token:
        cache.delete(lock_key)


def _geocode_us_location(query: str, client: httpx.Client) -> tuple[Decimal, Decimal]:
    """Return cached Nominatim latitude/longitude for a U.S.-restricted query."""
    cache_key = _cache_key_for_location(query)
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        if cached_result.get("not_found"):
            raise TripLocationNotFoundError(
                f"Could not find a U.S. location matching '{query}'."
            )
        return Decimal(cached_result["latitude"]), Decimal(cached_result["longitude"])

    token = _acquire_nominatim_lock()
    try:
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            if cached_result.get("not_found"):
                raise TripLocationNotFoundError(
                    f"Could not find a U.S. location matching '{query}'."
                )
            return (
                Decimal(cached_result["latitude"]),
                Decimal(cached_result["longitude"]),
            )

        last_request_at = cache.get("trip-geocode:nominatim-last-request")
        if last_request_at is not None:
            elapsed = time.time() - last_request_at
            time.sleep(max(0, NOMINATIM_REQUEST_INTERVAL_SECONDS - elapsed))

        try:
            response = client.get(
                settings.NOMINATIM_SEARCH_URL,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "us",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TripPlanningProviderError(
                "The location service could not process the request."
            ) from exc
        finally:
            cache.set(
                "trip-geocode:nominatim-last-request",
                time.time(),
                timeout=NOMINATIM_REQUEST_INTERVAL_SECONDS * 2,
            )

        try:
            result = response.json()
            if not isinstance(result, list):
                raise TypeError("Expected a list of geocoding results.")
            if not result:
                cache.set(cache_key, {"not_found": True}, NOMINATIM_CACHE_SECONDS)
                raise TripLocationNotFoundError(
                    f"Could not find a U.S. location matching '{query}'."
                )
            latitude = Decimal(result[0]["lat"]).quantize(COORDINATE_QUANTUM)
            longitude = Decimal(result[0]["lon"]).quantize(COORDINATE_QUANTUM)
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError("Geocoder returned coordinates outside valid ranges.")
        except TripLocationNotFoundError:
            raise
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise TripPlanningProviderError(
                "The location service returned an invalid result."
            ) from exc

        cache.set(
            cache_key,
            {"latitude": str(latitude), "longitude": str(longitude)},
            NOMINATIM_CACHE_SECONDS,
        )
        return latitude, longitude
    finally:
        _release_nominatim_lock(token)


def _fetch_osrm_route(
    origin: tuple[Decimal, Decimal],
    destination: tuple[Decimal, Decimal],
    client: httpx.Client,
) -> tuple[Decimal, dict[str, Any]]:
    """Fetch one driving route and return its distance and GeoJSON geometry."""
    origin_latitude, origin_longitude = origin
    destination_latitude, destination_longitude = destination
    coordinates = (
        f"{origin_longitude},{origin_latitude};"
        f"{destination_longitude},{destination_latitude}"
    )
    url = f"{settings.OSRM_ROUTE_URL.rstrip('/')}/{quote(coordinates, safe=',;.-')}"
    try:
        response = client.get(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TripPlanningProviderError(
            "The routing service could not process the request."
        ) from exc

    try:
        result = response.json()
        routes = result["routes"]
        if result.get("code") != "Ok" or not routes:
            raise TripRouteNotFoundError(
                "No driving route was found between the requested locations."
            )
        route = routes[0]
        distance_meters = Decimal(str(route["distance"]))
        geometry = route["geometry"]
        if (
            distance_meters <= 0
            or not isinstance(geometry, dict)
            or geometry.get("type") != "LineString"
            or not isinstance(geometry.get("coordinates"), list)
            or len(geometry["coordinates"]) < 2
        ):
            raise ValueError("Routing response is missing valid route data.")
        distance_miles = (distance_meters / METERS_PER_MILE).quantize(DISTANCE_QUANTUM)
    except TripRouteNotFoundError:
        raise
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise TripPlanningProviderError(
            "The routing service returned an invalid route."
        ) from exc

    return distance_miles, geometry


def build_trip_plan(origin: str, destination: str) -> dict[str, Any]:
    """Geocode a U.S. trip, request one route, and persist its fueling itinerary."""
    if not settings.NOMINATIM_USER_AGENT.strip():
        raise TripPlanningProviderError(
            "Configure NOMINATIM_USER_AGENT with an identifying application name."
        )

    with httpx.Client(
        headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
        timeout=15,
    ) as client:
        origin_coordinates = _geocode_us_location(origin, client)
        destination_coordinates = _geocode_us_location(destination, client)
        route_distance, route_geometry = _fetch_osrm_route(
            origin_coordinates,
            destination_coordinates,
            client,
        )

    with transaction.atomic():
        trip = Trip.objects.create(
            origin=origin,
            destination=destination,
            origin_latitude=origin_coordinates[0],
            origin_longitude=origin_coordinates[1],
            destination_latitude=destination_coordinates[0],
            destination_longitude=destination_coordinates[1],
            max_range_miles=500,
            mpg=Decimal("10"),
            initial_fuel_gallons=Decimal("50"),
            route_distance_miles=route_distance,
            route_geometry=route_geometry,
        )
        fuel_stops = plan_trip_fuel_stops(trip)

    return {
        "trip_id": trip.pk,
        "origin": {
            "label": trip.origin,
            "latitude": float(trip.origin_latitude),
            "longitude": float(trip.origin_longitude),
        },
        "destination": {
            "label": trip.destination,
            "latitude": float(trip.destination_latitude),
            "longitude": float(trip.destination_longitude),
        },
        "route_distance_miles": trip.route_distance_miles,
        "route_geometry": trip.route_geometry,
        "fuel_stops": [
            {
                "sequence": stop.sequence,
                "station": stop.station.name,
                "address": stop.station.address,
                "city": stop.station.city,
                "state": stop.station.state,
                "latitude": float(stop.station.latitude),
                "longitude": float(stop.station.longitude),
                "distance_from_start_miles": stop.distance_from_start_miles,
                "gallons_to_buy": stop.gallons_to_buy,
                "price_per_gallon": stop.price_per_gallon,
                "estimated_cost": stop.estimated_cost,
            }
            for stop in fuel_stops
        ],
        "total_fuel_cost": trip.estimated_fuel_cost or Decimal("0.00"),
    }
