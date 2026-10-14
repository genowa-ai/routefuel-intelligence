# RouteFuel Intelligence â€” Setup and Operation

RouteFuel Intelligence is a Django REST application for data-driven fuel-price analysis, driving-route planning, fuel-stop optimization, and estimated trip fuel cost. This repository includes the Django backend, browser-based Leaflet frontend, assessment dataset, audit pipeline, test suites, and Postman collection.

## 1. Requirements

- Python 3.12 compatible with the pinned requirements.
- PowerShell on Windows or an equivalent Python shell.
- Internet access for uncached route/geocoding requests and first-time Census Gazetteer coordinate enrichment.

## 2. API-key and secret requirements

The current implementation does **not** require a paid third-party mapping API key. It uses the public OSRM demo routing service, OpenStreetMap Nominatim geocoding, and OpenStreetMap map tiles. These public services are subject to usage policies, rate limits, availability constraints, and attribution requirements; they are not guaranteed production services.

`DJANGO_SECRET_KEY` is a Django application secret, not a mapping-service API key. Generate a new secret for the client's installation and keep it private. `NOMINATIM_USER_AGENT` must identify the application and include a real maintainer contact. The contact is not a secret. Never share or commit the real `.env`; commit only `.env.example`.

If a future deployment switches to a paid or authenticated service, the provider's actual credential can be configured through an environment variable. Do not add a fictitious API key to this project: the current code does not read one.

## 3. First-time setup from a GitHub clone

Open PowerShell in the repository root (the folder containing `manage.py`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Generate a Django secret:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Open `.env` and replace `DJANGO_SECRET_KEY` with the generated value. Replace the sample email in `NOMINATIM_USER_AGENT` with a real contact address. Do not paste `.env` into GitHub, chat, email, or the delivery ZIP.

## 4. Prepare the dataset and database

For a new checkout with an empty local database, run:

```powershell
python scripts/audit_fuel_csv.py
python manage.py migrate
python manage.py import_fuel_prices
python manage.py enrich_station_coordinates
```

The supplied source CSV lives at `data/fuel-prices-for-be-assessment.csv`. The audit produces cleaned and quarantined outputs and a data-quality report. Import the cleaned rows into SQLite before running coordinate enrichment. Coordinate enrichment uses US Census place representative points; these are approximate city-level proxies, not exact fuel-pump or highway-exit coordinates. Unmatched stations are not assigned invented coordinates.

Do not repeat data preparation on every launch. For an already initialized local database, start with the verification section below unless the dataset needs to be rebuilt.

## 5. Verify and launch

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m unittest tests.test_audit -v
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

While the server is running, open:

- Browser frontend: `http://127.0.0.1:8000/map/`
- Health check: `http://127.0.0.1:8000/health/`
- Route API: `http://127.0.0.1:8000/api/v1/route-fuel/`
- Django admin: `http://127.0.0.1:8000/admin/`

The development server is for local demonstration. A GitHub repository stores the source code; it does not itself host the running web application. Public access through a browser requires a separate hosting/deployment step and production configuration.

## 6. Example API request from PowerShell

Keep the development server running in one terminal, then use another terminal:

```powershell
$body = @{ start_location = 'New York, NY'; finish_location = 'Chicago, IL' } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/route-fuel/' -Method Post -ContentType 'application/json' -Body $body
```

The response contains route distance, duration and geometry, recommended fuel stops, fuel and cost estimates, vehicle assumptions, data-quality notes, and map-ready GeoJSON. Current assessment assumptions are 10 MPG and a maximum 500-mile driving leg. Costs are estimates rather than guaranteed purchase prices.

## 7. Postman demonstration

The ready-to-import collection is `postman/Fuel-Route-Optimizer.postman_collection.json`. In Postman, choose **Import** and select that file from this repository. Importing loads it into Postman; it does not move or replace the file. Run its health check and route request against `http://127.0.0.1:8000`. PowerShell requests and automated tests remain available if Postman is not installed.

## 8. Configuration reference

- `DJANGO_SECRET_KEY`: private Django signing secret.
- `DEBUG`: use `True` only for local development; use `False` for production.
- `ALLOWED_HOSTS`: Django host allowlist.
- `NOMINATIM_USER_AGENT`: application identifier plus real contact email.
- `NOMINATIM_BASE_URL`, `OSRM_BASE_URL`: public geocoding/routing service URLs.
- `FUEL_PRICE_CSV`, `FUEL_PRICE_CSV_CLEANED`: source and cleaned dataset paths.
- `CENSUS_GAZETTEER_URL`: public coordinate-enrichment source.
- `FUEL_ROUTE_CORRIDOR_MILES`: candidate station corridor (default 25 miles).
- `FUEL_ROUTE_MAX_RANGE_MILES`: maximum vehicle leg (default 500 miles).
- `FUEL_ROUTE_MPG`: vehicle efficiency assumption (default 10 MPG).

## 9. Secret-safe Git workflow

Before committing, inspect `git status --short` and confirm `.env`, SQLite files, logs, `.venv`, and generated caches are not staged. Verify after Git initialization with `git check-ignore -v .env db.sqlite3 server.log server_output.log`. Commit the dataset and necessary source/docs, but exclude local secrets and machine-specific generated files. Stage files deliberately and inspect `git diff --cached --name-only` before committing.

## 10. Known limitations

- Fuel-station coordinate points are approximate city representative locations because the supplied source CSV does not include exact station coordinates.
- OSRM, Nominatim, and public map tiles are best-effort public services subject to their service policies and limits.
- The current application optimizes routes and estimates trip fuel costs from supplied prices and configured assumptions. It does **not** currently train a machine-learning model or forecast future fuel prices; do not claim those capabilities unless they are implemented and evaluated.
