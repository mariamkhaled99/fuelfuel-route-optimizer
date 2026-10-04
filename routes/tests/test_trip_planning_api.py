"""Tests for trip-plan API, routing integration, and browser map view."""

from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from routes.services.trip_planning import (
    _fetch_osrm_route,
    build_trip_plan,
)


def test_trip_planning_api_returns_geojson_route_and_stops(client):
    """Return the route-plan service result inside the standard API envelope."""
    result = {
        "trip_id": 42,
        "origin": {"label": "Tulsa, OK", "latitude": 36.15, "longitude": -95.99},
        "destination": {
            "label": "Dallas, TX",
            "latitude": 32.78,
            "longitude": -96.80,
        },
        "route_distance_miles": Decimal("258.00"),
        "route_geometry": {
            "type": "LineString",
            "coordinates": [[-95.99, 36.15], [-96.80, 32.78]],
        },
        "fuel_stops": [],
        "total_fuel_cost": Decimal("0.00"),
    }

    with patch("routes.views.trip_planning.build_trip_plan", return_value=result):
        response = client.post(
            "/api/trips/plan/",
            {"origin": "Tulsa, OK", "destination": "Dallas, TX"},
            content_type="application/json",
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["route_geometry"] == result["route_geometry"]
    assert response.json()["data"]["fuel_stops"] == []


def test_trip_planning_api_validates_required_location_inputs(client):
    """Reject an incomplete request before calling any map provider."""
    with patch("routes.views.trip_planning.build_trip_plan") as build_trip:
        response = client.post(
            "/api/trips/plan/",
            {"origin": "Tulsa, OK"},
            content_type="application/json",
        )

    assert response.status_code == 400
    assert response.json()["success"] is False
    build_trip.assert_not_called()


def test_trip_planner_page_contains_interactive_geojson_map(client):
    """Serve the browser template that displays returned route GeoJSON."""
    response = client.get("/api/trip-planner/")

    assert response.status_code == 200
    assert b"L.geoJSON(trip.route_geometry" in response.content
    assert b"/api/trips/plan/" in response.content


def test_build_trip_plan_geocodes_endpoints_and_requests_one_route():
    """Geocode two endpoints, make one routing call, and save the plan."""
    origin = (Decimal("36.150000"), Decimal("-95.990000"))
    destination = (Decimal("32.780000"), Decimal("-96.800000"))
    geometry = {
        "type": "LineString",
        "coordinates": [[-95.99, 36.15], [-96.80, 32.78]],
    }
    trip = SimpleNamespace(
        pk=42,
        origin="Tulsa, OK",
        destination="Dallas, TX",
        origin_latitude=origin[0],
        origin_longitude=origin[1],
        destination_latitude=destination[0],
        destination_longitude=destination[1],
        route_distance_miles=Decimal("258.00"),
        route_geometry=geometry,
        estimated_fuel_cost=Decimal("0.00"),
    )

    with (
        patch(
            "routes.services.trip_planning._geocode_us_location",
            side_effect=[origin, destination],
        ) as geocode,
        patch(
            "routes.services.trip_planning._fetch_osrm_route",
            return_value=(Decimal("258.00"), geometry),
        ) as fetch_route,
        patch("routes.services.trip_planning.Trip.objects.create", return_value=trip),
        patch(
            "routes.services.trip_planning.plan_trip_fuel_stops",
            return_value=[],
        ) as plan_stops,
        patch(
            "routes.services.trip_planning.transaction.atomic",
            return_value=nullcontext(),
        ),
    ):
        result = build_trip_plan("Tulsa, OK", "Dallas, TX")

    assert geocode.call_count == 2
    fetch_route.assert_called_once()
    plan_stops.assert_called_once_with(trip)
    assert result["route_geometry"] == geometry
    assert result["total_fuel_cost"] == Decimal("0.00")


def test_osrm_route_distance_is_converted_and_geojson_is_returned():
    """Convert OSRM meters to miles while preserving GeoJSON coordinates."""
    response = Mock()
    response.json.return_value = {
        "code": "Ok",
        "routes": [
            {
                "distance": 160934.4,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-95.99, 36.15], [-96.80, 32.78]],
                },
            }
        ],
    }
    client = Mock()
    client.get.return_value = response

    miles, geometry = _fetch_osrm_route(
        (Decimal("36.15"), Decimal("-95.99")),
        (Decimal("32.78"), Decimal("-96.80")),
        client,
    )

    assert miles == Decimal("100.00")
    assert geometry == response.json.return_value["routes"][0]["geometry"]
    requested_url = client.get.call_args.args[0]
    assert "-95.99,36.15;-96.80,32.78" in requested_url
