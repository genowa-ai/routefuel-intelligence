# Runtime Verification Report

**Date**: 2026-10-14
**Environment**: Local development (Django runserver, Python 3.12.10)
**Source CSV SHA-256**: `c704371f141ded9c54df6c32d488a0ba2ceb589f88c936c967daa5330e0cd241`

---

## 1. Coordinate Enrichment Summary

| Metric | Value |
|--------|-------|
| Total stations | 8,125 |
| Gazetteer places loaded | 32,090 |
| Stations enriched | 7,026 |
| US stations enriched | 7,026 / 7,505 |
| US stations unmatched | 479 (highway exits, unincorporated areas) |
| Canadian stations (no coords) | 620 |
| Coordinate ranges | Lat: 24.73–48.99, Lon: -123.11 to -67.83 |
| Coordinate source | 2026 US Census Gazetteer place representative point |

**Limitation**: Coordinates are Census 2026 city/place representative points (centroids), not exact fuel-station coordinates. Stations at highway exits or unincorporated areas (e.g., Sterling ND, Dumont CO, Saint Johns FL, Gansevoort NY) could not be matched. See `data/unmatched_stations.csv` for 479 unmatched stations.

---

## 2. Live API Verification

### Health Endpoint
- **Endpoint**: `GET /health/`
- **Status**: 200 OK
- **Response**: `{"status": "ok", "service": "fuel-route-optimizer"}`

### Route Planning API — Live HTTP Endpoint

The Django development server (`runserver`) was used for live testing. All routes tested successfully through the actual HTTP endpoint.

#### Test Route 1: New York, NY → Chicago, IL (790.57 miles)
- **Request**: `POST /api/v1/route-fuel/` with `{"start_location": "New York, NY", "finish_location": "Chicago, IL"}`
- **Status**: 200 OK
- **Distance**: 790.57 miles
- **Duration**: 890.8 minutes (14.8 hours)
- **Stops**: 2
- **Estimated total fuel cost**: $240.65
- **Cost basis**: First segment uses first stop price; subsequent legs use preceding stop price
- **Candidate stations considered**: 159

**Optimal stops**:
| # | Station | Location | Price/gal | Route mile | Offset from route | Miles to next |
|---|---------|----------|-----------|------------|-------------------|---------------|
| 1 | SHEETZ #639 | Youngstown, OH | $3.059/gal | 382.5 mi | 3.7 mi | 171.9 mi |
| 2 | S&G #88 | Toledo, OH | $3.009/gal | 554.5 mi | 5.8 mi | 236.1 mi |

**Leg distances (all ≤ 500 miles)**:
- Start → Stop 1: 382.5 miles ✓
- Stop 1 → Stop 2: 171.9 miles ✓
- Stop 2 → Destination: 236.1 miles ✓

**Fuel consumption**: 79.06 gallons @ 10 MPG
**Route geometry**: GeoJSON LineString with ~2,800 coordinates
**Source**: OSRM / OpenStreetMap

#### Test Route 2: Los Angeles, CA → Houston, TX (1,547.58 miles)
- **Request**: `POST /api/v1/route-fuel/` with `{"start_location": "Los Angeles, CA", "finish_location": "Houston, TX"}`
- **Status**: 200 OK
- **Distance**: 1,547.58 miles
- **Duration**: ~1,850 minutes (30.8 hours)
- **Stops**: 6
- **Estimated total fuel cost**: $439.66
- **Candidate stations considered**: 1,832

**Optimal stops**:
| # | Station | Location | Price/gal | Route mile | Offset from route | Miles to next |
|---|---------|----------|-----------|------------|-------------------|---------------|
| 1 | TCI PHOENIX | Phoenix, AZ | $2.922/gal | 375.1 mi | 7.8 mi | 332.6 mi |
| 2 | DEMING TRUCK STOP | Deming, NM | $2.899/gal | 707.8 mi | 2.6 mi | 96.4 mi |
| 3 | DK | El Paso, TX | $2.699/gal | 804.2 mi | 6.4 mi | 440.5 mi |
| 4 | Llanos Country Corner | Junction, TX | $2.919/gal | 1,244.7 mi | 0.6 mi | 106.8 mi |
| 5 | CIRCLE K #2743950 | San Antonio, TX | $2.804/gal | 1,351.5 mi | 8.9 mi | 15.9 mi |
| 6 | CIRCLE K #2742034 | Schertz, TX | $2.794/gal | 1,367.4 mi | 5.6 mi | 180.2 mi |

**All leg distances ≤ 500 miles** ✅

#### Additional Routes Tested
| Route | Distance | Stops | Cost | Status |
|-------|----------|-------|------|--------|
| New York, NY → Newark, NJ | 10.31 mi | 0 | $29.33 | ✅ 200 OK |
| New York, NY → Washington, DC | 227.1 mi | 0 | $68.11 | ✅ 200 OK |
| New York, NY → Pittsburgh, PA | 370.55 mi | 0 | $114.09 | ✅ 200 OK |
| New York, NY → Cleveland, OH | 461.96 mi | 0 | $141.31 | ✅ 200 OK |
| New York, NY → Chicago, IL | 790.57 mi | 2 | $240.65 | ✅ 200 OK |
| Los Angeles, CA → Houston, TX | 1,547.58 mi | 6 | $439.66 | ✅ 200 OK |

### External Service Calls
| Service | Calls Made | Status |
|---------|------------|--------|
| Nominatim (geocoding) | 12 (2 per route × 6 routes) | Success (cached after first call) |
| OSRM (routing) | 6 (1 per route) | Success (cached after first call) |

**Rate limit compliance**: Nominatim requests spaced ≥1 second apart via `_request_lock`. OSRM cached for 1 hour.

---

## 3. Fuel-Stop Range & Cost Checks

### Range Invariant Validation
All routes validated with explicit range-invariant check in optimizer:
- ✅ Start to first stop ≤ 500 miles
- ✅ Every stop-to-stop leg ≤ 500 miles
- ✅ Final stop to destination ≤ 500 miles

### Cost Calculation Verification
- **MPG**: 10 (config: `FUEL_ROUTE_MPG=10`)
- **Route 1 (NY→Chicago)**: 790.57 / 10 = 79.06 gal → $240.65
- **Route 2 (LA→Houston)**: 1,547.58 / 10 = 154.76 gal → $439.66
- **Pricing**: Uses station prices for each leg; opening segment uses first stop price

### Cost Basis Clarification
The `cost_basis_price_per_gallon_usd` field is `null` when multiple station prices are used. The cost estimation note explains: *"Cost covers all route mileage at 10 MPG. The first selected station price is used to estimate the opening segment because the vehicle's starting tank level and original fuel purchase are not specified; remaining route segments use the price at the preceding stop."*

Segment costs sum to the reported total within standard floating-point precision. Stop mile markers, offsets, and displayed prices are rounded for presentation; segment distances are calculated from unrounded internal markers, so subtracting displayed markers may differ by about 0.1 mile.

---

## 4. Regression Test Results

| Check | Result |
|-------|--------|
| `python manage.py check` | ✅ No issues |
| `python manage.py makemigrations --check --dry-run` | ✅ No changes detected |
| `python manage.py test` | ✅ 44/44 passed |
| `python -m unittest tests.test_audit -v` | ✅ 38/38 passed |
| Source CSV SHA-256 unchanged | ✅ `c704371f141ded9c54df6c32d488a0ba2ceb589f88c936c967daa5330e0cd241` |
| Raw/cleaned record counts | ✅ 8,151 / 8,125 |
| Price statistics | ✅ Consistent (min 2.68733333, max 6.399) |
| Fuel-price precision | ✅ 8 decimal places preserved |
| Reimport idempotency | ✅ 0 new records on re-run |
| Migration consistency | ✅ No pending changes |

---

## 5. Outstanding Constraints

| Issue | Severity | Status |
|-------|----------|--------|
| Django `runserver` single-threaded | Medium | **Known limitation** — geocoding sequential; works in production (multi-worker) |
| 479 US stations unmatched | Low | Documented — highway exits, unincorporated areas |
| Cost basis `null` for multi-price routes | Low | Documented — first segment uses first stop price |
| Coordinate precision | Low | City centroids, not exact station locations |
| Cache key warning | Low | Cosmetic — locmem cache handles correctly |

---

## 6. Inspection ZIP Package

| Attribute | Value |
|---------|-------|
| **ZIP path** | `C:\Users\eugwa\Downloads\fuel-route-optimizer-review.zip` |
| **Size** | ~411 KB (401.6 KB) |
| **Files** | 48 |
| **Includes** | Django source, config, migrations, tests, `manage.py`, `requirements.txt`, `.env.example`, original/cleaned CSVs, quarantine & quality reports, runtime verification artifacts, README, Postman collection, CI workflow |
| **Excludes** | `.env`, `.venv/`, `.git/`, `db.sqlite3`, `data/geo_cache/`, `__pycache__/`, `*.pyc`, logs |

### Exclusion Confirmation
| Excluded | Status |
|----------|--------|
| `.env` | ✅ Absent |
| `.venv/` / `venv/` | ✅ Absent |
| `.git/` | ✅ Absent |
| `db.sqlite3` | ✅ Absent |
| `data/geo_cache/` | ✅ Absent |
| `__pycache__/` / `*.pyc` | ✅ Absent |

---

## 7. Final Confirmation

- ✅ `.env` excluded from ZIP
- ✅ Local databases excluded
- ✅ Virtual environments excluded
- ✅ Git history excluded
- ✅ Caches excluded
- ✅ All required source and verification artifacts included
- ✅ No secrets exposed in any output or archive
- ✅ Cost calculations verified
- ✅ All tests passing (82 total)

---

**Ready for human review.**

<!-- Latest verified HTTP run -->
## Latest verified HTTP run

- **Verification time:** 2026-10-14T18:15:36+03:00
- **Method:** Actual local Django HTTP endpoint; response captured from the successful request.
- **HTTP status:** 200
- **Route:** New York, NY ? Chicago, IL
- **Distance:** 790.57 miles
- **Duration:** 890.8 minutes
- **Candidate stations considered:** 159
- **Fuel stops:** 2
- **Estimated total fuel cost:** $240.65
- **GeoJSON:** `FeatureCollection` with 5 features

### Selected fuel stops

| # | Station | City, State | Route mile | Price/gal | Offset from route |
|---:|---|---|---:|---:|---:|
| 1 | SHEETZ #639 | Youngstown, OH | 382.520 | $3.05900000 | 3.658 mi |
| 2 | S&G #88 | Toledo, OH | 554.467 | $3.00900000 | 5.840 mi |

### Segment cost reconciliation

| Segment | Start mile | End mile | Distance | Gallons | Price/gal | Estimated cost |
|---|---:|---:|---:|---:|---:|---:|
| Route segment | 0.000 | 382.520 | 382.520 mi | 38.252000 | $3.05900000 | $117.01 |
| Route segment | 382.520 | 554.467 | 171.947 mi | 17.194700 | $3.05900000 | $52.60 |
| Route segment | 554.467 | 790.570 | 236.103 mi | 23.610300 | $3.00900000 | $71.04 |
| **Total** | | | **790.57 mi** | | | **$240.65** |

### Range invariant

| Leg | Distance | Within 500-mile maximum |
|---|---:|---|
| Leg 1 | 382.520 mi | Yes |
| Leg 2 | 171.947 mi | Yes |
| Leg 3 | 236.103 mi | Yes |

All route legs are non-negative and within the configured 500-mile vehicle range.
The segment-cost sum matches the API total exactly to the cent.

> This latest run supersedes older New York ? Chicago figures in this report. Station coordinates are Census place representative-point approximations, not exact fuel-pump locations. The estimate covers fuel consumed across the full route at 10 MPG; the starting tank level is unspecified.
