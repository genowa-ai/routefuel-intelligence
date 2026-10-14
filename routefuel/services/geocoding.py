import hashlib
import threading
import time
from django.conf import settings
from django.core.cache import cache
import requests
from rest_framework.exceptions import APIException, ValidationError

# Nominatim's public instance asks clients to stay below 1 request/second.
_last_request_at = 0.0
_request_lock = threading.Lock()

class UpstreamServiceError(APIException):
    status_code = 502
    default_detail = "A required free mapping service is temporarily unavailable. Please retry."
    default_code = "mapping_service_unavailable"


def geocode_us_location(location: str) -> dict:
    """Geocode one US location; cache successful results for 30 days."""
    # Use a stable, whitespace-free key compatible with production cache backends.
    normalized_location = " ".join(location.casefold().split())
    key_digest = hashlib.sha256(
        normalized_location.encode("utf-8")
    ).hexdigest()
    key = f"geocode-us:{key_digest}"
    cached = cache.get(key)
    if cached:
        return cached

    global _last_request_at
    with _request_lock:
        # Keep uncached Nominatim requests at least 1.05 seconds apart.
        elapsed = time.monotonic() - _last_request_at
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        try:
            # Record the attempt so failed requests also respect the interval.
            _last_request_at = time.monotonic()
            response = requests.get(
                f"{settings.NOMINATIM_BASE_URL}/search",
                params={
                    "q": location,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "us",
                    "addressdetails": 1,
                },
                headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
                timeout=(10.0, 30.0),
            )
            response.raise_for_status()
            results = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise UpstreamServiceError(f"Location lookup failed: {exc.__class__.__name__}.") from exc

    if not results:
        raise ValidationError({"location": f"Could not resolve '{location}' to a location in the United States. Try including city, state, or ZIP code."})
    result = results[0]
    address = result.get("address", {})
    if address.get("country_code", "us").lower() != "us":
        raise ValidationError({"location": f"'{location}' did not resolve to a US location."})
    record = {
        "display_name": result.get("display_name", location),
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
    }
    cache.set(key, record, 60 * 60 * 24 * 30)
    return record
