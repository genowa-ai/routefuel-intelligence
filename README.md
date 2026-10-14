# RouteFuel Intelligence — Data-Driven Fuel Route Analytics

A Django REST API that accepts US start/finish locations, obtains one driving route, recommends price-aware fuel stops while respecting a 500-mile range, estimates fuel consumption at 10 MPG, and returns map-ready GeoJSON. The supplied 8,151-row CSV is included under `data/`.

> **Accuracy note:** the CSV does not contain station latitude/longitude. To avoid thousands of geocoding calls, the enrichment command matches each US station's city/state to the US Census Bureau's 2026 Places Gazetteer and uses the place representative point. This is an approximate proxy for the station location—not an exact pump or highway exit location. API responses expose this limitation. See `docs/DATA_QUALITY_AND_COST_ASSUMPTIONS.md`.

## Stack

- Python 3.12+ (Django 6.1.x supports current Python releases; the project is pinned to Django 6.1.2)
- Django 6.1.2 and Django REST Framework 3.18.1
- SQLite for a zero-configuration assessment database
- OSRM public routing demo for route distance, duration, and GeoJSON geometry
- OpenStreetMap Nominatim for cached start/finish geocoding
- US Census Gazetteer for offline city-coordinate enrichment
- Leaflet map preview at `/map/`

OSRM and Nominatim public services are best-effort services with usage restrictions. Use these for the assessment/demo only, not as guaranteed production infrastructure. Respect attribution and service policies.

## Data integrity and cleaning (run before everything else)

The supplied CSV (`data/fuel-prices-for-be-assessment.csv`) is the immutable source. Moving, copying or re-exporting CSV files across computers and spreadsheet applications can introduce encoding, delimiter, decimal-formatting, newline and data-type issues. The audit script validates the file before ingestion rather than assuming it is clean.

```powershell
python scripts/audit_fuel_csv.py
```

Generated outputs:

- `data/processed/fuel_prices_cleaned.csv` — cleaned, deduplicated, UTF-8 dataset used by the import command.
- `data/processed/fuel_prices_quarantine.csv` — rows that could not be safely normalized (includes source row numbers and reasons).
- `docs/reports/fuel_csv_quality_report.md` — human-readable report.
- `docs/reports/fuel_csv_quality_report.json` — machine-readable report.

Cleaning rules applied by the audit:

- Original source is never modified; a SHA-256 hash is recorded for verification.
- UTF-8 BOM is handled; a fallback encoding is recorded if one is needed.
- Expected header, delimiter and column count are validated; unexpected schemas fail clearly.
- Leading/trailing whitespace is normalized in text fields.
- State codes are normalized to uppercase.
- Only well-understood, documented mojibake repairs are applied (e.g. `â€™` -> `’`).
- Station IDs and Rack IDs are kept as strings.
- Retail prices are parsed with decimal-safe parsing; unusual values are reported, not invented or deleted.
- Source price precision (up to 8 decimal places, e.g. `3.00733333`) is preserved in the cleaned CSV and database.
- Exact duplicate rows are removed from the cleaned output (only completely identical records).
- Repeated station IDs with differing prices are tracked but preserved.
- US states/DC are classified separately from Canadian province codes; unknown codes are retained and reported.
- Malformed or unprocessable rows are quarantined with source row numbers and reasons.

After the audit succeeds, the import command uses the cleaned CSV and fails clearly if it is missing:

```powershell
python manage.py import_fuel_prices
```

Re-running the import does not create duplicate database records because records are deduplicated by a stable `source_key` computed from the cleaned row values.

## Quick start (Windows PowerShell / VS Code)

Open a terminal in the project root.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and replace the `NOMINATIM_USER_AGENT` contact placeholder with a real contact email. Keep `.env` out of Git; `.gitignore` already excludes it.

Then prepare the database and supplied dataset:

```powershell
python scripts/audit_fuel_csv.py
python manage.py migrate
python manage.py import_fuel_prices
python manage.py enrich_station_coordinates
python manage.py test
python manage.py runserver
```

The audit must run before `import_fuel_prices`; the import command fails if the cleaned CSV is missing.

The Gazetteer command downloads the official US Census 2026 National Places ZIP once and caches it under `data/geo_cache/`. The downloaded ZIP is intentionally ignored by Git. If your network blocks this download, download the Gazetteer manually from the [official Census Gazetteer page](https://www.census.gov/geographies/reference-files/2026/geo/gazetter-file.html), then run:

```powershell
python manage.py enrich_station_coordinates --gazetteer-file "C:\path\to\2026_Gaz_place_national.zip"
```

Check that `python manage.py enrich_station_coordinates` reports a substantial number of enriched US rows. Review `data/unmatched_stations.csv` for stations that could not be joined to a Gazetteer place. A missing/unmatched coordinate does not cause fake coordinates to be invented; that station is excluded from route optimization.

Open:

- API: `http://127.0.0.1:8000/api/v1/route-fuel/`
- Interactive map preview: `http://127.0.0.1:8000/map/`
- Health check: `http://127.0.0.1:8000/health/`
- Django admin: `http://127.0.0.1:8000/admin/`

## Django admin

The admin interface is available at `/admin/`. Create a privileged user with:

```powershell
python manage.py createsuperuser
```

Do not hardcode or share default administrator credentials; provide your own username, email and password when prompted. The admin interface manages only models registered with Django admin. Adding a new Django application still requires code, configuration and migrations.

## API contract

`POST /api/v1/route-fuel/`

Request:

```json
{
  "start_location": "Austin, TX",
  "finish_location": "Dallas, TX"
}
```

The location strings should identify locations in the United States. Include a state or ZIP code to improve geocoding accuracy. The request validator rejects empty/equal locations.

The response includes:

- `route.distance_miles`, `route.duration_minutes`, `route.geometry` (OSRM GeoJSON LineString)
- `fuel_plan.optimal_stops` with name, address, price, route mile marker, route offset and approximate point coordinates
- `fuel_plan.estimated_total_fuel_cost_usd`, `fuel_plan.number_of_stops`, and an explicit cost-estimation note
- `vehicle_assumptions` for 500-mile range and 10 MPG
- `map` as a GeoJSON FeatureCollection with route and fuel-stop features
- `data_quality` with source and coordinate accuracy caveat

Errors use standard HTTP statuses: `400` validation/geocoding input issue, `422` no feasible fuel-stop chain in the currently coordinate-enriched route corridor, `429` throttling, and `502`/`503` upstream/data readiness issues.

### Call count and latency strategy

- Up to two Nominatim geocoding requests on a cache miss (each successful result is cached for 30 days; public-service request spacing is respected).
- One OSRM route request on a cache miss (route results are cached for 1 hour).
- Fuel station filtering, projection, and optimization happen locally in SQLite/Python. There is no per-station network geocoding during a route request.

The public Nominatim service's 1-request/second guideline and OSRM demo's best-effort policy mean first-time requests may be slower; repeat requests should be faster due to caching. The Django in-memory cache is per process. For a multi-worker production deployment, replace it with Redis or another shared cache.

## Algorithm overview

1. Geocode the start and finish in the US.
2. Call OSRM once for the fastest driving route, with a GeoJSON geometry.
3. Query only US fuel stations whose approximate coordinates fall inside the route bounding box.
4. Project each distinct city representative point to the nearest route segment and keep candidates within the configured route corridor (default 25 miles).
5. Run a dynamic-programming shortest-path calculation over candidates ordered by route mile marker. Edges longer than 500 miles are forbidden; the objective minimizes estimated route fuel spend using the supplied prices.
6. Return the chosen stops, full-route gallon consumption at 10 MPG, estimated cost and map-ready GeoJSON.

## Configuration

See `.env.example`. Main settings:

- `FUEL_ROUTE_MAX_RANGE_MILES=500`
- `FUEL_ROUTE_MPG=10`
- `FUEL_ROUTE_CORRIDOR_MILES=25`
- `OSRM_BASE_URL=https://router.project-osrm.org`
- `NOMINATIM_BASE_URL=https://nominatim.openstreetmap.org`

The corridor can be widened to capture more candidate locations, but this also increases false positives because station points are city-level approximations. Widening it is not a substitute for exact station coordinates.

## Tests and Postman

```powershell
python manage.py test
```

Import `postman/Fuel-Route-Optimizer.postman_collection.json` into Postman. It includes a health check and a route-planning request. Set `base_url` to `http://127.0.0.1:8000` if Postman does not use the collection variable.

## GitHub submission

From the project root:

```powershell
git init
git add .
git status
git commit -m "Build RouteFuel Intelligence application"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/routefuel-intelligence.git
git push -u origin main
```

If the GitHub repo already exists, add the correct remote instead of repeating `git init`. Before committing, confirm `.env`, `db.sqlite3`, virtual environments, and `data/geo_cache/` are not staged. The supplied source CSV should remain in Git because the assessment requires it; include its source attribution/permission as supplied by the assessor.


## Feature engineering

Feature engineering in RouteFuel Intelligence is deterministic and domain-specific. The planner derives route-relative attributes for candidate fuel stations, including distance from the route geometry, cumulative route-mile marker, and distance to the next stop or destination, then filters candidates using a configurable route corridor. It evaluates feasible refuelling sequences against the 500-mile maximum-leg constraint and 10 MPG vehicle assumption, estimating gallons and segment costs from available retail-price records while preserving price precision. The data pipeline normalizes station fields and removes exact duplicate records; where station-level coordinates are unavailable, Census place representative points provide approximate locations. These engineered inputs support rule-constrained cost optimization; the current application does not train a machine-learning model or predict future fuel prices.

## Setup, operation, and handover

For reproducible installation, local environment configuration, dataset preparation, API usage, Postman verification, and secret-safe delivery, follow [SETUP.md](SETUP.md). The current implementation uses public mapping/routing services and does not need a paid provider API key.
