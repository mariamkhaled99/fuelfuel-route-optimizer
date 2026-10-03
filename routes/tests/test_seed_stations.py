import json
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.core.management.base import CommandError

from routes.management.commands.seed_stations import (
    NominatimGeocoder,
    load_station_rows,
)


def test_load_station_rows_consolidates_duplicate_ids_using_last_row(tmp_path):
    csv_path = tmp_path / "stations.csv"
    csv_path.write_text(
        "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
        '7,First name,"I-44, EXIT 283 & US-69",Big Cabin,OK,307,3.00733333\n'
        "7,Updated name,US-69,Big Cabin,OK,,3.10\n",
        encoding="utf-8",
    )

    row_count, stations = load_station_rows(csv_path)

    assert row_count == 2
    assert len(stations) == 1
    assert stations[0].name == "Updated name"
    assert stations[0].rack_id is None
    assert stations[0].price_per_gallon == Decimal("3.1000")
    assert stations[0].geocoding_query == "US-69, Big Cabin, OK, USA"


def test_load_station_rows_rejects_missing_columns(tmp_path):
    csv_path = tmp_path / "stations.csv"
    csv_path.write_text("OPIS Truckstop ID,Truckstop Name\n", encoding="utf-8")

    with pytest.raises(CommandError, match="missing required columns"):
        load_station_rows(csv_path)


@patch("routes.management.commands.seed_stations.httpx.Client")
def test_geocoder_uses_search_api_and_persists_cache(client_factory, tmp_path):
    cache_path = tmp_path / "nominatim.jsonl"
    client = client_factory.return_value
    response = Mock()
    response.json.return_value = [{"lat": "36.5354999", "lon": "-95.2260001"}]
    client.get.return_value = response

    with NominatimGeocoder(
        url="https://nominatim.example/search",
        user_agent="FuelFuelRouteOptimizer/tests",
        cache_path=cache_path,
    ) as geocoder:
        coordinates = geocoder.geocode("I-44, Big Cabin, OK, USA")
        assert geocoder.geocode("I-44, Big Cabin, OK, USA") == coordinates

    assert coordinates == (Decimal("36.535500"), Decimal("-95.226000"))
    client.get.assert_called_once_with(
        "https://nominatim.example/search",
        params={
            "q": "I-44, Big Cabin, OK, USA",
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "us",
        },
    )
    assert json.loads(cache_path.read_text(encoding="utf-8")) == {
        "query": "I-44, Big Cabin, OK, USA",
        "coordinates": ["36.535500", "-95.226000"],
    }

    with NominatimGeocoder(
        url="https://nominatim.example/search",
        user_agent="FuelFuelRouteOptimizer/tests",
        cache_path=cache_path,
    ) as geocoder:
        assert geocoder.geocode("I-44, Big Cabin, OK, USA") == coordinates
    assert client_factory.call_count == 2
    assert client.get.call_count == 1


@patch("routes.management.commands.seed_stations.httpx.Client")
def test_geocoder_caches_no_result(client_factory, tmp_path):
    cache_path = tmp_path / "nominatim.jsonl"
    client = client_factory.return_value
    client.get.return_value.json.return_value = []

    with NominatimGeocoder(
        url="https://nominatim.example/search",
        user_agent="FuelFuelRouteOptimizer/tests",
        cache_path=cache_path,
    ) as geocoder:
        assert geocoder.geocode("Unknown, USA") is None

    with NominatimGeocoder(
        url="https://nominatim.example/search",
        user_agent="FuelFuelRouteOptimizer/tests",
        cache_path=cache_path,
    ) as geocoder:
        assert geocoder.geocode("Unknown, USA") is None
    assert client.get.call_count == 1


@patch("routes.management.commands.seed_stations.time.sleep")
@patch(
    "routes.management.commands.seed_stations.time.monotonic",
    side_effect=(10, 10.25, 11),
)
@patch("routes.management.commands.seed_stations.httpx.Client")
def test_geocoder_spaces_uncached_requests_by_at_least_one_second(
    client_factory, _monotonic, sleeper, tmp_path
):
    client = client_factory.return_value
    client.get.return_value.json.return_value = []

    with NominatimGeocoder(
        url="https://nominatim.example/search",
        user_agent="FuelFuelRouteOptimizer/tests",
        cache_path=tmp_path / "nominatim.jsonl",
    ) as geocoder:
        geocoder.geocode("First, USA")
        geocoder.geocode("Second, USA")

    sleeper.assert_called_once_with(0.75)
    assert client.get.call_count == 2
