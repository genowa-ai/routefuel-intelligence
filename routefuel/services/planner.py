from django.conf import settings
from django.db.models import Avg
from django.core.cache import cache
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from rest_framework.exceptions import APIException
from routefuel.models import FuelStation
from .geometry import METERS_PER_MILE, build_route_segments, project_point_to_route
from .geocoding import geocode_us_location
from .optimizer import CandidateStop, optimize_fuel_stops
from .routing import get_driving_route

US_STATE_CODES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"}


class FuelDataNotReady(APIException):
    status_code = 503
    default_detail = "Fuel station coordinates have not been prepared. Run the documented import and coordinate-enrichment commands."
    default_code = "fuel_data_not_ready"


def route_candidates(coordinates, total_miles, corridor_miles):
    if not FuelStation.objects.filter(latitude__isnull=False, longitude__isnull=False, state__in=US_STATE_CODES).exists():
        raise FuelDataNotReady()
    latitudes = [point[1] for point in coordinates]
    longitudes = [point[0] for point in coordinates]
    max_abs_lat = max(abs(min(latitudes)), abs(max(latitudes)))
    import math
    cos_lat = max(0.2, math.cos(math.radians(max_abs_lat)))
    lat_margin = corridor_miles / 69.0
    lon_margin = corridor_miles / (69.172 * cos_lat)
    queryset = FuelStation.objects.filter(
        latitude__gte=min(latitudes) - lat_margin,
        latitude__lte=max(latitudes) + lat_margin,
        longitude__gte=min(longitudes) - lon_margin,
        longitude__lte=max(longitudes) + lon_margin,
        state__in=US_STATE_CODES,
        latitude__isnull=False,
        longitude__isnull=False,
    ).order_by("retail_price")
    if not queryset.exists():
        return []

    lengths, cumulative = build_route_segments(coordinates)
    # The simplified GeoJSON geometry can be shorter than OSRM's road-network
    # distance. Scale mile markers to the OSRM-reported route distance.
    geometry_miles = cumulative[-1] if cumulative else 0.0
    mile_scale = (total_miles / geometry_miles) if geometry_miles > 0 else 1.0
    # Project each distinct city representative point once instead of every row.
    by_city_coordinate = {}
    for station in queryset:
        key = (round(station.longitude, 5), round(station.latitude, 5))
        if key not in by_city_coordinate:
            route_mile, offset = project_point_to_route(key, coordinates, lengths, cumulative)
            by_city_coordinate[key] = (route_mile * mile_scale, offset)
    candidates = []
    seen_positions = {}
    for station in queryset:
        key = (round(station.longitude, 5), round(station.latitude, 5))
        route_mile, offset = by_city_coordinate[key]
        if offset > corridor_miles or route_mile < 0 or route_mile > total_miles:
            continue
        candidate = CandidateStop(station, route_mile, offset, float(station.retail_price))
        position_key = round(route_mile, 1)
        current = seen_positions.get(position_key)
        if current is None or candidate.price < current.price:
            seen_positions[position_key] = candidate
    candidates = list(seen_positions.values())
    candidates.sort(key=lambda c: c.route_mile)
    return candidates


def _build_segment_estimates(stops, total_miles, mpg, cost_basis_price, status, fallback_price=None):
    """Return transparent per-leg cost estimates and their reconciled total.

    Distances are built from shared endpoints rather than independently rounded
    next-leg fields. Segment costs use Decimal arithmetic with half-up cent
    rounding, and the response total is the sum of those displayed line items.
    """
    if status != "ok":
        return [], None

    # Use the same two-decimal route distance exposed in the route response.
    displayed_total_miles = round(max(0.0, float(total_miles)), 2)
    if stops:
        stop_markers = [float(stop["route_mile_marker"]) for stop in stops]
        boundaries = [0.0, *stop_markers, displayed_total_miles]
        # Opening segment uses the first selected station price. Each following
        # leg uses the price at the station from which that leg begins.
        prices = [float(stops[0]["retail_price_per_gallon"])] + [
            float(stop["retail_price_per_gallon"]) for stop in stops
        ]
    else:
        # Use the optimizer's selected basis when available. If a non-standard
        # successful result omits it, use the exact fallback supplied to the
        # optimizer rather than introducing a second hard-coded price assumption.
        if cost_basis_price is not None:
            basis = float(cost_basis_price)
        elif fallback_price is not None:
            basis = float(fallback_price)
        elif displayed_total_miles <= 1e-9:
            basis = 0.0
        else:
            raise ValueError(
                "A non-zero route without fuel stops requires an explicit cost basis."
            )
        boundaries = [0.0, displayed_total_miles]
        prices = [basis]

    segments = []
    segment_costs = []
    mpg_decimal = Decimal(str(mpg)) if mpg else Decimal("0")
    cent = Decimal("0.01")

    for index, price in enumerate(prices):
        start_mile = boundaries[index]
        end_mile = boundaries[index + 1]
        distance = max(0.0, end_mile - start_mile)
        distance_decimal = Decimal(str(distance))
        price_decimal = Decimal(str(price))
        gallons_decimal = distance_decimal / mpg_decimal if mpg_decimal else Decimal("0")
        # Currency uses explicit decimal half-up rounding, avoiding Python's
        # binary-float and bankers-rounding behavior at half-cent boundaries.
        segment_cost = (gallons_decimal * price_decimal).quantize(
            cent, rounding=ROUND_HALF_UP
        )
        segment_costs.append(segment_cost)
        segments.append({
            "start_route_mile": round(start_mile, 3),
            "end_route_mile": round(end_mile, 3),
            "distance_miles": round(distance, 3),
            "gallons": round(float(gallons_decimal), 6),
            "price_per_gallon_usd": round(float(price_decimal), 8),
            "estimated_cost_usd": float(segment_cost),
        })

    # The API total is the sum of the displayed segment amounts, each rounded
    # to cents above. This makes the line items auditable and exactly reconcilable.
    total_cost = sum(segment_costs, start=Decimal("0.00"))
    return segments, float(total_cost)


def plan_fuel_route(start_location, finish_location):
    normalized_request = "|".join([" ".join(start_location.lower().split()), " ".join(finish_location.lower().split()), str(settings.FUEL_ROUTE_CORRIDOR_MILES), str(settings.FUEL_ROUTE_MAX_RANGE_MILES), str(settings.FUEL_ROUTE_MPG)])
    plan_cache_key = "fuel-plan:v1:" + hashlib.sha256(normalized_request.encode("utf-8")).hexdigest()
    cached_plan = cache.get(plan_cache_key)
    if cached_plan:
        return cached_plan
    start = geocode_us_location(start_location)
    finish = geocode_us_location(finish_location)
    route = get_driving_route(start, finish)
    distance_miles = route["distance_meters"] / METERS_PER_MILE
    candidates = route_candidates(route["geometry"]["coordinates"], distance_miles, settings.FUEL_ROUTE_CORRIDOR_MILES)
    avg_value = FuelStation.objects.filter(state__in=US_STATE_CODES).aggregate(value=Avg("retail_price"))["value"]
    average_price = float(avg_value) if avg_value is not None else 3.50
    estimate = optimize_fuel_stops(
        distance_miles, candidates,
        mpg=settings.FUEL_ROUTE_MPG,
        max_range_miles=settings.FUEL_ROUTE_MAX_RANGE_MILES,
        fallback_price=average_price,
    )
    if estimate["status"] == "unreachable":
        estimate["note"] += f" Current corridor width: {settings.FUEL_ROUTE_CORRIDOR_MILES:g} miles."

    # Build the user-visible segment breakdown from one shared set of mile markers.
    # This keeps displayed distances continuous and makes the displayed total equal
    # the sum of the individually rounded segment costs.
    stops = estimate["stops"]
    segment_estimates, displayed_total_cost = _build_segment_estimates(
        stops=stops,
        total_miles=distance_miles,
        mpg=settings.FUEL_ROUTE_MPG,
        cost_basis_price=estimate.get("cost_basis_price"),
        status=estimate["status"],
        fallback_price=average_price,
    )
    if estimate["status"] == "ok":
        # Align each stop's next-leg fields to the same displayed segment used by
        # the cost breakdown, avoiding gaps caused by independent rounding.
        for index, stop in enumerate(stops):
            following_segment = segment_estimates[index + 1]
            stop["miles_to_next_stop_or_destination"] = following_segment["distance_miles"]
            stop["estimated_gallons_for_next_leg"] = following_segment["gallons"]

    geometry = route["geometry"]
    result = {
        "start": {"input": start_location, "resolved_name": start["display_name"], "coordinates": {"latitude": start["latitude"], "longitude": start["longitude"]}},
        "finish": {"input": finish_location, "resolved_name": finish["display_name"], "coordinates": {"latitude": finish["latitude"], "longitude": finish["longitude"]}},
        "route": {"distance_miles": round(distance_miles, 2), "duration_minutes": round(route["duration_seconds"] / 60, 1), "geometry": geometry, "geometry_format": "GeoJSON LineString [longitude, latitude]", "source": "OSRM / OpenStreetMap"},
        "vehicle_assumptions": {"max_range_miles": settings.FUEL_ROUTE_MAX_RANGE_MILES, "miles_per_gallon": settings.FUEL_ROUTE_MPG, "estimated_total_gallons_consumed": estimate["estimated_gallons"], "initial_tank_level": "unspecified; total cost estimates the fuel consumed on the full route"},
        "fuel_plan": {"status": estimate["status"], "optimal_stops": estimate["stops"], "number_of_stops": len(estimate["stops"]), "estimated_total_fuel_cost_usd": displayed_total_cost, "cost_basis_price_per_gallon_usd": estimate.get("cost_basis_price"), "cost_estimation_note": (estimate.get("note") or "") + (" Segment costs use the returned route-mile markers and displayed station prices; the reported total is the sum of segment costs rounded to cents. Stop selection is optimized using the underlying station-price and route-distance precision." if estimate["status"] == "ok" else "No feasible fuel-stop sequence was found; fuel cost and segment estimates are unavailable."), "candidate_stations_considered": len(candidates), "corridor_width_miles": settings.FUEL_ROUTE_CORRIDOR_MILES, "segment_estimates": segment_estimates},
        "data_quality": {"fuel_price_records": FuelStation.objects.count(), "coordinate_method": "2026 US Census Gazetteer place representative point matched to CSV city/state", "station_coordinates_are_exact": False, "warning": "The provided CSV has no station latitude/longitude. Fuel stations are positioned using their city's Census representative point, so the stop location and road offset are approximate. The source file also includes Canadian provinces; this USA-only route plan excludes stations outside US state codes."},
        "map": {
            "type": "FeatureCollection",
            "features": _map_features(geometry, estimate["stops"], start, finish),
        },
    }
    cache.set(plan_cache_key, result, 60 * 60)
    return result


def _map_features(geometry, stops, start, finish):
    features = [{"type": "Feature", "properties": {"kind": "route", "label": "Driving route"}, "geometry": geometry}]
    for kind, label, location in (("start", "Start", start), ("finish", "Finish", finish)):
        features.append({"type": "Feature", "properties": {"kind": kind, "label": label, "resolved_name": location["display_name"]}, "geometry": {"type": "Point", "coordinates": [location["longitude"], location["latitude"]]}})
    for index, stop in enumerate(stops, 1):
        features.append({
            "type": "Feature",
            "properties": {"kind": "fuel_stop", "stop_number": index, "name": stop["name"], "city": stop["city"], "state": stop["state"], "price_per_gallon": stop["retail_price_per_gallon"], "route_mile_marker": stop["route_mile_marker"], "coordinate_precision": stop["coordinate_precision"]},
            "geometry": {"type": "Point", "coordinates": [stop["coordinates"]["longitude"], stop["coordinates"]["latitude"]]},
        })
    return features