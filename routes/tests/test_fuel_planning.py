from decimal import Decimal
from types import SimpleNamespace

import pytest

from routes.services.fuel_planning import (
    FuelStopPlanningError,
    _calculate_fuel_stop_plan,
)


def make_station(
    station_id,
    longitude,
    price,
    *,
    latitude=0,
):
    """Create a lightweight priced station for planner tests."""
    station = SimpleNamespace(
        pk=station_id,
        latitude=Decimal(str(latitude)),
        longitude=Decimal(str(longitude)),
    )
    station.prices = [
        SimpleNamespace(price_per_gallon=Decimal(str(price))),
    ]
    return station


def straight_route(miles):
    """Build an equatorial GeoJSON LineString with the requested route length."""
    longitude = miles / 69.0934
    return {
        "type": "LineString",
        "coordinates": [[0, 0], [longitude, 0]],
    }


def calculate(route_miles, stations, *, max_range=500, mpg=10, initial_fuel=50):
    """Run the planner against a straight route using convenient test defaults."""
    return _calculate_fuel_stop_plan(
        route_geometry=straight_route(route_miles),
        route_distance_miles=Decimal(str(route_miles)),
        max_range_miles=Decimal(str(max_range)),
        mpg=Decimal(str(mpg)),
        initial_fuel_gallons=Decimal(str(initial_fuel)),
        stations=stations,
    )


def test_short_trip_within_range_needs_no_fuel_stops():
    """A trip within the starting fuel range should not require a stop."""
    assert calculate(400, []) == []


def test_long_trip_picks_cheapest_reachable_station_then_repeats():
    """Long trips should select affordable reachable stations for each leg."""
    stations = [
        make_station(1, 400 / 69.0934, "4.00"),
        make_station(2, 300 / 69.0934, "2.00"),
        make_station(3, 800 / 69.0934, "3.00"),
        make_station(4, 1200 / 69.0934, "1.50"),
    ]

    plan = calculate(1600, stations)

    assert [item.station.pk for item in plan] == [2, 3, 4]
    assert [item.sequence for item in plan] == [1, 2, 3]
    assert [item.distance_from_start_miles for item in plan] == [
        Decimal("300.00"),
        Decimal("800.00"),
        Decimal("1200.00"),
    ]
    assert [item.gallons_to_buy for item in plan] == [
        Decimal("30.000"),
        Decimal("50.000"),
        Decimal("40.000"),
    ]


def test_equal_price_prefers_farthest_reachable_station():
    """When reachable prices tie, choose the station farthest along the route."""
    stations = [
        make_station(1, 250 / 69.0934, "3.00"),
        make_station(2, 450 / 69.0934, "3.00"),
    ]

    plan = calculate(900, stations)

    assert plan[0].station.pk == 2


def test_initial_fuel_limits_first_stop_and_is_refilled_to_full_tank():
    """Use the reduced first-leg range and refill the tank at the first stop."""
    stations = [
        make_station(1, 300 / 69.0934, "2.00"),
        make_station(2, 450 / 69.0934, "1.00"),
        make_station(3, 800 / 69.0934, "3.00"),
    ]

    plan = calculate(1100, stations, initial_fuel=35)

    assert [item.station.pk for item in plan] == [1, 2, 3]
    assert [item.gallons_to_buy for item in plan] == [
        Decimal("45.000"),
        Decimal("15.000"),
        Decimal("35.000"),
    ]


def test_partial_starting_tank_requires_a_stop_on_a_shorter_trip():
    """A short trip still needs a stop when initial fuel cannot reach the end."""
    stations = [make_station(1, 300 / 69.0934, "2.00")]

    plan = calculate(400, stations, initial_fuel=35)

    assert [item.station.pk for item in plan] == [1]


def test_station_outside_route_corridor_is_ignored():
    """Stations farther than the allowed route corridor cannot be selected."""
    stations = [
        make_station(1, 400 / 69.0934, "1.00", latitude=1),
    ]

    with pytest.raises(FuelStopPlanningError, match="No priced stations"):
        calculate(700, stations)


def test_missing_reachable_station_errors_instead_of_returning_partial_plan():
    """Raise an error when no reachable station can complete the itinerary."""
    stations = [
        make_station(1, 450 / 69.0934, "2.00"),
    ]

    with pytest.raises(FuelStopPlanningError, match="No station within range"):
        calculate(1300, stations)


def test_route_geometry_must_be_geojson_linestring():
    """Reject route geometry that is not a valid GeoJSON LineString."""
    with pytest.raises(FuelStopPlanningError, match="GeoJSON LineString"):
        _calculate_fuel_stop_plan(
            route_geometry={"type": "Point", "coordinates": [0, 0]},
            route_distance_miles=Decimal("800"),
            max_range_miles=500,
            mpg=10,
            initial_fuel_gallons=50,
            stations=[],
        )


@pytest.mark.parametrize(
    ("max_range", "mpg", "message"),
    [
        (0, 10, "Maximum range"),
        (500, 0, "Vehicle MPG"),
        (500, 10, "Initial fuel"),
    ],
)
def test_invalid_trip_consumption_parameters_raise(max_range, mpg, message):
    """Reject invalid range, fuel efficiency, and starting-fuel values."""
    initial_fuel = -1 if message == "Initial fuel" else 50
    with pytest.raises(FuelStopPlanningError, match=message):
        calculate(
            800,
            [],
            max_range=max_range,
            mpg=mpg,
            initial_fuel=initial_fuel,
        )
