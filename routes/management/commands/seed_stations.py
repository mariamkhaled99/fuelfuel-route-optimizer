import csv
import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from routes.models import FuelPrice, FuelStation

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = (
    "FuelFuelRouteOptimizer/1.0 "
    "(https://github.com/mariamkhaled99/fuelfuel-route-optimizer)"
)
REQUEST_INTERVAL_SECONDS = 1
PRICE_QUANTUM = Decimal("0.0001")
COORDINATE_QUANTUM = Decimal("0.000001")
REQUIRED_COLUMNS = (
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
)


@dataclass(frozen=True)
class StationSeed:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int | None
    price_per_gallon: Decimal

    @property
    def geocoding_query(self) -> str:
        return ", ".join(
            value for value in (self.address, self.city, self.state, "USA") if value
        )


def load_station_rows(csv_path: Path) -> tuple[int, list[StationSeed]]:
    stations: dict[int, StationSeed] = {}
    row_count = 0

    try:
        source = csv_path.open(encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise CommandError(f"Cannot open station CSV {csv_path}: {exc}") from exc

    with source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise CommandError(f"Station CSV {csv_path} has no header row.")

        missing_columns = set(REQUIRED_COLUMNS) - set(reader.fieldnames)
        if missing_columns:
            raise CommandError(
                "Station CSV is missing required columns: "
                + ", ".join(sorted(missing_columns))
            )

        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            try:
                opis_id = int(row["OPIS Truckstop ID"])
                rack_id = int(row["Rack ID"]) if row["Rack ID"].strip() else None
                price = Decimal(row["Retail Price"]).quantize(PRICE_QUANTUM)
            except (AttributeError, InvalidOperation, TypeError, ValueError) as exc:
                raise CommandError(
                    f"Invalid station data on CSV line {line_number}: {exc}"
                ) from exc

            if (
                opis_id < 0
                or opis_id > 2_147_483_647
                or (rack_id is not None and rack_id < 0)
                or price < 0
                or price >= Decimal("1000")
            ):
                raise CommandError(
                    f"Identifier or price is outside the model's supported range "
                    f"on CSV line {line_number}."
                )

            values = {
                "name": row["Truckstop Name"].strip(),
                "address": row["Address"].strip(),
                "city": row["City"].strip(),
                "state": row["State"].strip(),
            }
            if not values["name"] or not values["city"] or not values["state"]:
                raise CommandError(
                    f"Station name, city, and state are required "
                    f"on CSV line {line_number}."
                )
            if (
                len(values["name"]) > 255
                or len(values["address"]) > 255
                or len(values["city"]) > 100
                or len(values["state"]) > 2
            ):
                raise CommandError(
                    f"Station text exceeds a model field limit "
                    f"on CSV line {line_number}."
                )

            stations[opis_id] = StationSeed(
                opis_id=opis_id,
                rack_id=rack_id,
                price_per_gallon=price,
                **values,
            )

    if not stations:
        raise CommandError(f"Station CSV {csv_path} contains no station rows.")
    return row_count, list(stations.values())


class NominatimGeocoder:
    def __init__(
        self,
        *,
        url: str,
        user_agent: str,
        cache_path: Path,
    ) -> None:
        self.url = url
        self.cache_path = cache_path
        self.cache: dict[str, tuple[Decimal, Decimal] | None] = {}
        self._last_request_at: float | None = None
        self.request_count = 0
        self.cache_hits = 0
        self.user_agent = user_agent
        self._client: httpx.Client | None = None
        self._cache_writer = None
        self._load_cache()

    def __enter__(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_writer = self.cache_path.open("a", encoding="utf-8")
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent},
            timeout=20,
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._cache_writer is not None:
            self._cache_writer.close()
        if self._client is not None:
            self._client.close()

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return

        with self.cache_path.open(encoding="utf-8") as cache_file:
            for line_number, line in enumerate(cache_file, start=1):
                try:
                    record = json.loads(line)
                    query = record["query"]
                    coordinates = record["coordinates"]
                    if not isinstance(query, str):
                        raise TypeError("query must be a string")
                    if coordinates is None:
                        result = None
                    else:
                        result = (
                            Decimal(coordinates[0]),
                            Decimal(coordinates[1]),
                        )
                    self.cache[query] = result
                except (
                    IndexError,
                    InvalidOperation,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    raise CommandError(
                        f"Invalid Nominatim cache record on line {line_number}: {exc}"
                    ) from exc

    def geocode(self, query: str) -> tuple[Decimal, Decimal] | None:
        if query in self.cache:
            self.cache_hits += 1
            return self.cache[query]

        if self._cache_writer is None or self._client is None:
            raise RuntimeError("NominatimGeocoder must be used as a context manager.")

        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            time.sleep(max(0, REQUEST_INTERVAL_SECONDS - elapsed))
        self._last_request_at = time.monotonic()

        response = self._client.get(
            self.url,
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "us",
            },
        )
        response.raise_for_status()

        try:
            results = response.json()
            if not isinstance(results, list):
                raise TypeError("Expected a list from Nominatim.")
            if results:
                latitude = Decimal(results[0]["lat"]).quantize(COORDINATE_QUANTUM)
                longitude = Decimal(results[0]["lon"]).quantize(COORDINATE_QUANTUM)
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    raise ValueError("Nominatim returned out-of-range coordinates.")
                coordinates = latitude, longitude
            else:
                coordinates = None
        except (IndexError, InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise CommandError(
                f"Invalid Nominatim response for {query!r}: {exc}"
            ) from exc

        self.cache[query] = coordinates
        json.dump(
            {
                "query": query,
                "coordinates": (
                    [str(value) for value in coordinates]
                    if coordinates is not None
                    else None
                ),
            },
            self._cache_writer,
        )
        self._cache_writer.write("\n")
        self._cache_writer.flush()
        self.request_count += 1
        return coordinates


class Command(BaseCommand):
    help = "Seed fuel stations and prices, geocoding locations with Nominatim."

    def add_arguments(self, parser):
        default_csv = settings.BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
        default_cache = settings.BASE_DIR / "data" / ".nominatim-cache.jsonl"
        parser.add_argument(
            "csv_path",
            nargs="?",
            type=Path,
            default=default_csv,
            help=f"Station CSV file (default: {default_csv}).",
        )
        parser.add_argument(
            "--nominatim-url",
            default=NOMINATIM_URL,
            help="Nominatim Search API endpoint; change to use another service.",
        )
        parser.add_argument(
            "--user-agent",
            default=USER_AGENT,
            help="Identifying User-Agent sent with each geocoding request.",
        )
        parser.add_argument(
            "--cache-file",
            type=Path,
            default=default_cache,
            help=f"Persistent JSONL geocoding cache (default: {default_cache}).",
        )

    def handle(
        self,
        csv_path: Path,
        nominatim_url: str,
        user_agent: str,
        cache_file: Path,
        **options,
    ) -> None:
        row_count, stations = load_station_rows(csv_path)
        self.stdout.write(
            f"Loaded {row_count} rows for {len(stations)} unique stations. "
            "Saving station and price data before geocoding."
        )

        stations_by_query: dict[str, list[StationSeed]] = {}
        with transaction.atomic():
            for seed in stations:
                station, _ = FuelStation.objects.update_or_create(
                    opis_id=seed.opis_id,
                    defaults={
                        "name": seed.name,
                        "address": seed.address,
                        "city": seed.city,
                        "state": seed.state,
                        "rack_id": seed.rack_id,
                    },
                )
                price = station.prices.order_by("pk").first()
                if price is None:
                    FuelPrice.objects.create(
                        station=station,
                        price_per_gallon=seed.price_per_gallon,
                    )
                elif price.price_per_gallon != seed.price_per_gallon:
                    price.price_per_gallon = seed.price_per_gallon
                    price.save(update_fields=("price_per_gallon",))

                stations_by_query.setdefault(seed.geocoding_query, []).append(seed)

        self.stdout.write(
            f"Saved {len(stations)} stations and prices. "
            "Geocoding uncached addresses sequentially "
            "(at most one request/second)."
        )
        with NominatimGeocoder(
            url=nominatim_url,
            user_agent=user_agent,
            cache_path=cache_file,
        ) as geocoder:
            matched = 0
            unmatched = 0
            for query_number, (query, seeds) in enumerate(
                stations_by_query.items(), start=1
            ):
                location = geocoder.geocode(query)
                if location is None:
                    unmatched += 1
                else:
                    matched += 1
                    FuelStation.objects.filter(
                        opis_id__in=[seed.opis_id for seed in seeds]
                    ).update(latitude=location[0], longitude=location[1])

                if query_number % 25 == 0 or query_number == len(stations_by_query):
                    self.stdout.write(
                        f"Processed {query_number}/{len(stations_by_query)} "
                        "location queries "
                        f"({geocoder.request_count} requests, "
                        f"{geocoder.cache_hits} cache hits)."
                    )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded {len(stations)} stations and prices; "
                    f"{matched} location queries matched, {unmatched} had no result; "
                    f"{geocoder.request_count} requests made, "
                    f"{geocoder.cache_hits} cache hits."
                )
            )
