from django.conf import settings
from django.core.cache import cache
import requests
from .geocoding import UpstreamServiceError


def get_driving_route(start: dict, finish: dict) -> dict:
    """Call OSRM once for the route; identical endpoints are cached for 1 hour."""
    key = "osrm-route:v1:{}:{}:{}:{}".format(
        round(start["longitude"], 4), round(start["latitude"], 4),
        round(finish["longitude"], 4), round(finish["latitude"], 4),
    )
    cached = cache.get(key)
    if cached:
        return cached
    coordinates = f'{start["longitude"]},{start["latitude"]};{finish["longitude"]},{finish["latitude"]}'
    url = f"{settings.OSRM_BASE_URL}/route/v1/driving/{coordinates}"
    try:
        response = requests.get(url, params={"overview": "simplified", "geometries": "geojson", "steps": "false", "alternatives": "false"}, headers={"User-Agent": settings.NOMINATIM_USER_AGENT}, timeout=(15.0, 60.0))
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamServiceError(f"Driving route lookup failed: {exc.__class__.__name__}.") from exc
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise UpstreamServiceError("The routing provider could not find a driving route for those locations.")
    route = payload["routes"][0]
    result = {
        "distance_meters": float(route["distance"]),
        "duration_seconds": float(route["duration"]),
        "geometry": route["geometry"],
    }
    cache.set(key, result, 60 * 60)
    return result
