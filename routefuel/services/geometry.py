import math

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344


def haversine_miles(point_a, point_b):
    """Distance between (longitude, latitude) pairs."""
    lon1, lat1 = point_a
    lon2, lat2 = point_b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def build_route_segments(coordinates):
    """Build route-segment lengths and cumulative mile markers."""
    if len(coordinates) < 2:
        raise ValueError("Route geometry must contain at least two coordinates")
    lengths = [haversine_miles(coordinates[i - 1], coordinates[i]) for i in range(1, len(coordinates))]
    cumulative = [0.0]
    for length in lengths:
        cumulative.append(cumulative[-1] + length)
    return lengths, cumulative


def project_point_to_route(point, coordinates, lengths=None, cumulative=None):
    """Return (route_mile, offset_mile) for a point near a route polyline.

    Segment projection uses a local equirectangular plane, which is sufficiently
    accurate for the short station-to-road offsets used by this assessment.
    """
    if lengths is None or cumulative is None:
        lengths, cumulative = build_route_segments(coordinates)
    lon, lat = point
    best_offset = float("inf")
    best_mile = 0.0
    for i in range(len(coordinates) - 1):
        lon1, lat1 = coordinates[i]
        lon2, lat2 = coordinates[i + 1]
        mean_lat = math.radians((lat + lat1 + lat2) / 3.0)
        scale_x = 69.172 * math.cos(mean_lat)
        scale_y = 69.0
        ax, ay = (lon1 - lon) * scale_x, (lat1 - lat) * scale_y
        bx, by = (lon2 - lon) * scale_x, (lat2 - lat) * scale_y
        vx, vy = bx - ax, by - ay
        denom = vx * vx + vy * vy
        fraction = 0.0 if denom == 0 else max(0.0, min(1.0, -(ax * vx + ay * vy) / denom))
        px, py = ax + fraction * vx, ay + fraction * vy
        offset = math.hypot(px, py)
        if offset < best_offset:
            best_offset = offset
            best_mile = cumulative[i] + lengths[i] * fraction
    return best_mile, best_offset
