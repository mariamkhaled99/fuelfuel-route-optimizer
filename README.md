# fuelfuel-route-optimizer

FuelRoute API is a Django-based REST API that calculates an optimal, cost-effective fueling strategy for road trips across the USA.

## Packages

| Package | Why |
| --- | --- |
| `django` | Backend framework |
| `djangorestframework` | Build the API |
| `drf-spectacular` | OpenAPI/Swagger documentation |
| `httpx` | Call the routing API |
| `django-environ` | `.env` configuration |
| `pytest` | Testing |
| `pytest-django` | Django testing with pytest |
| `django-debug-toolbar` | Debug SQL/performance |
| `pylint` | Code quality |
| `black` | Formatting |
| `isort` | Import formatting |
| `django-nplusone` | Detect N+1 queries; optional |
| `psycopg` | PostgreSQL driver |

## Setup and Run

Install dependencies with `uv sync`. Configure PostgreSQL in `.env`; use `.env.example` as a reference. As a PostgreSQL administrator, run `psql -U postgres -d postgres -f data/create_postgres.sql` to create the application role and database. The role is granted `CREATEDB` so pytest can create its dedicated test database.

Test-only connection overrides belong in the ignored `.env.test.local`. `.env.test` remains the non-secret test template; the test database is named `test_fuelfuel_route_optimizer`.

Apply migrations and start the local server:

```powershell
uv run python manage.py migrate
uv run python manage.py runserver
```

The health endpoint is `http://127.0.0.1:8000/api/health/` and returns `{"status":"ok"}` when the service is running. Set `ENABLE_NPLUSONE=True` in `.env` to enable local N+1 profiling; it is disabled in tests and other environments. Django Debug Toolbar is available locally while `DEBUG=True`.

## Seeding fuel stations

Run `uv run python manage.py seed_stations` to load station and retail-price rows
from `data/fuel-prices-for-be-assessment.csv`. You can pass a different CSV path
as the first argument. Duplicate OPIS IDs are consolidated, with the last CSV
row supplying that station's values.

### How station geodata is geocoded

The seed command fills station latitude and longitude from the CSV's address,
city, and state:

1. It builds one search query per distinct `address, city, state, USA` location.
2. It sends each uncached query to the
   [Nominatim Search API](https://nominatim.org/release-docs/develop/api/Search/)
   with `format=jsonv2`, `limit=1`, and `countrycodes=us`.
3. When a result is returned, its latitude and longitude are saved on the
   station. If there is no result, the coordinates are left blank.
4. Both matched and unmatched queries are written to
   `data/.nominatim-cache.jsonl`, so later seed runs reuse them without making
   the same request again.

The geocoder uses the
[Nominatim public-service policy](https://operations.osmfoundation.org/policies/nominatim/):
uncached requests run sequentially at no more than one per second, with an
identifying User-Agent. The full dataset can take hours to geocode. Run only
one process on one machine, do not schedule repeated bulk imports, and do not
exceed the request limit. The public service discourages larger or recurring
bulk geocoding; use another provider or a self-hosted Nominatim instance for
those cases. Use `--nominatim-url` to select a different compatible endpoint.

OpenStreetMap data is © OpenStreetMap contributors and is available under the
[ODbL](https://www.openstreetmap.org/copyright). Attribute OpenStreetMap when
displaying geocoded data.

## API Documentation

- OpenAPI schema: `/api/schema/`
- Swagger UI: [http://127.0.0.1:8000/api/docs/](http://127.0.0.1:8000/api/docs/)
- ReDoc: `/api/redoc/`

Add route endpoints under `routes/urls.py`.

## Tests

Run tests with `uv run pytest`. Pytest uses `core.test_settings` and `--reuse-db` to create the test database on its first database-backed test run and reuse it afterward. Run `uv run pytest --create-db` to recreate it after database migrations change.
