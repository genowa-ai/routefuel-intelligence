from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

@dataclass(frozen=True)
class CandidateStop:
    station: object
    route_mile: float
    route_offset_miles: float
    price: float


def _round_decimal(value, places, rounding=ROUND_HALF_UP):
    """Round a value to the specified decimal places using Decimal with ROUND_HALF_UP."""
    return float(Decimal(str(value)).quantize(Decimal('0.' + '0' * places), rounding=ROUND_HALF_UP))


def optimize_fuel_stops(total_miles, candidates, mpg=10.0, max_range_miles=500.0, fallback_price=3.50):
    """Find the minimum-estimated-cost sequence of stops under the range limit.

    All route miles are costed, since the initial fuel level is not specified.
    The first selected station's price is used to estimate the opening segment;
    subsequent legs are priced using the station from which that leg starts.
    This avoids falsely reporting $0 on short trips, while keeping the assumption
    explicit in the response. Stops are constrained to be no more than max_range
    apart, including start and destination.
    """
    total_miles = max(0.0, float(total_miles))
    gallons = total_miles / mpg
    if total_miles <= 1e-6:
        return {"stops": [], "estimated_fuel_cost": 0.0, "estimated_gallons": 0.0, "cost_basis_price": None, "status": "ok"}

    ordered = sorted(candidates, key=lambda c: (c.route_mile, c.price))
    # Collapse exact-near-identical route positions; station coordinates in the
    # supplied file are city representative points, so location ties are common.
    compact = []
    for item in ordered:
        if item.route_mile <= 0.1 or item.route_mile >= total_miles - 0.1:
            continue
        if compact and abs(item.route_mile - compact[-1].route_mile) < 0.25:
            if item.price < compact[-1].price:
                compact[-1] = item
        else:
            compact.append(item)

    if total_miles <= max_range_miles:
        basis = min((c.price for c in candidates), default=fallback_price)
        if candidates:
            note = "No refueling stop is range-required. Fuel cost is estimated using the lowest available route-corridor price because the starting tank level is unspecified."
        else:
            note = "No refueling stop is range-required. No coordinate-enriched station was found in the route corridor, so cost uses the US dataset-wide mean fuel price because the starting tank level is unspecified."
        return {
            "stops": [],
            "estimated_fuel_cost": round(gallons * basis, 2),
            "estimated_gallons": round(gallons, 2),
            "cost_basis_price": round(basis, 3),
            "status": "ok",
            "note": note
        }

    # dp[j] is minimum cost of all route miles up to candidate j. For the first
    # segment, use the first stop's quoted price; later segments use the price at
    # the preceding stop. Only transitions <= max range are feasible.
    n = len(compact)
    dp = [float("inf")] * n
    parent = [-2] * n
    for j, station in enumerate(compact):
        if station.route_mile <= max_range_miles:
            dp[j] = station.route_mile / mpg * station.price
            parent[j] = -1
        for i in range(j):
            gap = station.route_mile - compact[i].route_mile
            if gap > max_range_miles:
                continue
            candidate_cost = dp[i] + gap / mpg * compact[i].price
            if candidate_cost < dp[j]:
                dp[j] = candidate_cost
                parent[j] = i

    best_cost = float("inf")
    best_last = None
    for i, station in enumerate(compact):
        final_leg = total_miles - station.route_mile
        if final_leg <= max_range_miles and dp[i] + final_leg / mpg * station.price < best_cost:
            best_cost = dp[i] + final_leg / mpg * station.price
            best_last = i

    if best_last is None:
        furthest_reachable = max([c.route_mile for c in compact if c.route_mile <= max_range_miles] or [0.0])
        return {"stops": [], "estimated_fuel_cost": None, "estimated_gallons": round(gallons, 2), "cost_basis_price": None, "status": "unreachable", "furthest_reachable_mile": round(furthest_reachable, 1), "note": "The available coordinate-enriched fuel stations do not form a feasible chain within the 500-mile range. Try a wider route corridor or enrich more station locations."}

    indices = []
    cursor = best_last
    while cursor is not None and cursor >= 0:
        indices.append(cursor)
        cursor = parent[cursor]
    indices.reverse()
    selected = [compact[i] for i in indices]

    # Validate that all legs respect the max range constraint
    # Start to first stop
    if selected[0].route_mile > max_range_miles + 1e-6:
        return {"stops": [], "estimated_fuel_cost": None, "estimated_gallons": round(gallons, 2), "cost_basis_price": None, "status": "unreachable", "note": f"First stop at {selected[0].route_mile:.1f} miles exceeds max range of {max_range_miles} miles."}
    # Stop-to-stop legs
    for idx in range(len(selected) - 1):
        gap = selected[idx + 1].route_mile - selected[idx].route_mile
        if gap > max_range_miles + 1e-6:
            return {"stops": [], "estimated_fuel_cost": None, "estimated_gallons": round(gallons, 2), "cost_basis_price": None, "status": "unreachable", "note": f"Leg from {selected[idx].route_mile:.1f} to {selected[idx+1].route_mile:.1f} miles ({gap:.1f} mi) exceeds max range of {max_range_miles} miles."}
    # Final stop to destination
    final_leg = total_miles - selected[-1].route_mile
    if final_leg > max_range_miles + 1e-6:
        return {"stops": [], "estimated_fuel_cost": None, "estimated_gallons": round(gallons, 2), "cost_basis_price": None, "status": "unreachable", "note": f"Final leg from {selected[-1].route_mile:.1f} to destination ({final_leg:.1f} mi) exceeds max range of {max_range_miles} miles."}

    stops = []
    for idx, stop in enumerate(selected):
        next_mile = selected[idx + 1].route_mile if idx + 1 < len(selected) else total_miles
        next_gap = next_mile - stop.route_mile
        st = stop.station
        stops.append({
            "station_id": st.id,
            "truckstop_id": st.opis_truckstop_id,
            "name": st.name,
            "address": st.address,
            "city": st.city,
            "state": st.state,
            "retail_price_per_gallon": _round_decimal(float(st.retail_price), 8),
            "route_mile_marker": round(stop.route_mile, 3),
            "distance_from_route_miles": round(stop.route_offset_miles, 3),
            "coordinates": {"latitude": st.latitude, "longitude": st.longitude},
            "coordinate_precision": "city_representative_point_approximation",
            "miles_to_next_stop_or_destination": round(next_gap, 3),
            "estimated_gallons_for_next_leg": round(next_gap / mpg, 6),
        })

    # Calculate cost_basis_price with higher precision
    cost_basis = None
    if not selected:
        basis = min((c.price for c in candidates), default=3.50)
        cost_basis = _round_decimal(basis, 8)
    else:
        # Use the first stop's price as basis
        cost_basis = _round_decimal(float(selected[0].station.retail_price), 8)

    return {
        "stops": stops,
        "estimated_fuel_cost": round(best_cost, 2),
        "estimated_gallons": round(gallons, 2),
        "cost_basis_price": _round_decimal(cost_basis, 8) if cost_basis is not None else None,
        "status": "ok",
        "note": "Cost covers all route mileage at 10 MPG. The first selected station price is used to estimate the opening segment because the vehicle's starting tank level and original fuel purchase are not specified; remaining route segments use the price at the preceding stop."
    }