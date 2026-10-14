# Data quality and fuel-cost assumptions

## Input data constraints

The supplied CSV contains 8,151 records and these seven fields: OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, and Retail Price. It has no station latitude/longitude. Its state column also includes Canadian province abbreviations (AB, BC, MB, NB, NS, ON, QC, SK, YT); these records are retained in the imported table but excluded from a USA-only route plan.

## Coordinate approximation

`enrich_station_coordinates` matches US rows to the Census Bureau 2026 Places Gazetteer by state abbreviation and normalized city/place name. Gazetteer points represent their associated place, not the exact fuel station. As a result:

- a station can appear displaced from the actual exit/road;
- stations with unmatched cities are written to `data/unmatched_stations.csv` and excluded;
- the 25-mile route corridor is intentionally configurable, but increasing it can admit false positives;
- use exact station coordinates in a production-quality version, sourced from the fuel data owner or a licensed station-location dataset.

This design avoids doing thousands of per-station geocoder calls and keeps all station filtering local during route requests.

## Cost model

- Vehicle efficiency is fixed at 10 miles/gallon as specified.
- Max drive range between planned refueling points is fixed at 500 miles.
- Fuel cost is estimated for all miles of the route rather than assuming the vehicle starts with a free, full tank. The original tank level and price of any starting fuel were not specified.
- The optimizer minimizes a route-segment cost estimate, assigning the opening segment the first selected stop's quoted price and subsequent segments the price at the preceding selected stop. This is stated in `fuel_plan.cost_estimation_note` and is an estimate, not a transactional purchase prediction.
- For routes <= 500 miles, no stop is required by range; the total trip cost uses the lowest available candidate price in the route corridor. This yields a meaningful estimate rather than a misleading $0 result.
- For long routes, if the coordinate-enriched candidate stations do not form a chain of legs each <= 500 miles, the API returns HTTP 422 with a specific diagnostic note.

A more physically exact implementation would require tank level/capacity, precise station coordinates, and a model of refill quantities. Those inputs were not provided, so the assessment version states its assumptions instead of inventing them.
