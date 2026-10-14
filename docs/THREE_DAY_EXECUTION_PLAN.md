# Three-day execution plan and submission checklist

Planning assumption: work starts Tuesday, October 13, 2026 at approximately 12:55 p.m. East Africa Time. A strict 72-hour window would end Friday, October 16, 2026 at approximately 12:55 p.m. EAT. Use the employer's actual receipt timestamp if it differs.

## Day 1 — working path end-to-end

**Goal:** route API, fuel plan, map and tests running locally.

- [ ] Create virtual environment and install dependencies.
- [ ] Run migrations and import the supplied CSV (expected input has 8,151 rows).
- [ ] Run the Census Gazetteer enrichment command; inspect number matched and unmatched report.
- [ ] Run tests and resolve all failures.
- [ ] Run the server and test `POST /api/v1/route-fuel/` in Postman.
- [ ] Open `/map/` and verify route geometry, endpoints, stop markers and cost summary.
- [ ] Test short route (e.g. Austin to Dallas), medium route and a cross-country route that requires several stops.

## Day 2 — validation and correctness

- [ ] Validate stop-chain feasibility: each consecutive planned leg, from route start to first stop and from last stop to destination, must be <= 500 miles.
- [ ] Check station prices and output route mile markers manually on at least three routes.
- [ ] Test bad/ambiguous/non-US inputs, same start/finish, upstream timeout, no candidates, and unmatched coordinate areas.
- [ ] Confirm cached repeat requests avoid repeated geocoding and routing requests.
- [ ] Confirm the price selection uses retail price, not rack ID or a hardcoded value.
- [ ] Verify no secrets, local database or virtual environment are staged in Git.

## Day 3 — polish and submit

- [ ] Run the full test suite from a clean environment.
- [ ] Verify README steps work from a fresh clone, including coordinate enrichment.
- [ ] Push all final code and the CSV to the correct GitHub repository; check that the repo opens to the reviewer.
- [ ] Import the Postman collection and prepare its request body before recording.
- [ ] Record the Loom walkthrough (script below; keep it under 5 minutes).
- [ ] Paste the GitHub URL and Loom URL into the original assessment message. Do not submit only a local zip.
- [ ] Recheck the employer's actual 72-hour deadline before sending.

## Suggested Loom script (4:30 max)

**0:00–0:30 — Problem and architecture**
"This API accepts a US start and finish, calls Nominatim for cached location lookup, and makes one OSRM driving-route request. Fuel prices come from the supplied CSV and are queried locally."

**0:30–1:10 — Repository tour**
Show `routefuel/services/planner.py`, `geometry.py`, `optimizer.py`, the CSV import and coordinate-enrichment management commands, and the tests. Mention the source CSV lacked station coordinates and the Census place-point approximation is explicit in the response.

**1:10–2:50 — Live Postman request**
POST `http://127.0.0.1:8000/api/v1/route-fuel/` with the example body. Show distance, duration, route geometry, fuel stops/prices, gallons, estimated total cost and the GeoJSON FeatureCollection. Briefly point out the 500-mile constraint and the cost-model note.

**2:50–3:45 — Map UI**
Open `http://127.0.0.1:8000/map/`, submit the same start/finish, and show the route line, stop markers and cost estimate.

**3:45–4:30 — Tests and limits**
Run `python manage.py test`. Explain caching, one OSRM request per uncached route, the public demo service caveat, and approximate station coordinates. End with the GitHub repository URL on screen.
