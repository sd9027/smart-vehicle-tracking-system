"""Geographic helpers and the preset demo locations around Dehradun."""
import math

# Approximate coordinates of well-known places, used as trip sources/destinations.
# They are for the demo map only; verify against a real map before relying on them.
PLACES: dict[str, dict] = {
    "geu": {"name": "Graphic Era University, Clement Town", "lat": 30.2686, "lng": 77.9945},
    "isbt": {"name": "ISBT Dehradun", "lat": 30.2887, "lng": 77.9990},
    "clock-tower": {"name": "Clock Tower, Dehradun", "lat": 30.3245, "lng": 78.0418},
    "fri": {"name": "Forest Research Institute", "lat": 30.3418, "lng": 77.9997},
    "rajpur-road": {"name": "Rajpur Road", "lat": 30.3550, "lng": 78.0640},
    "selaqui": {"name": "Selaqui Industrial Area", "lat": 30.3700, "lng": 77.8600},
    "prem-nagar": {"name": "Prem Nagar", "lat": 30.3340, "lng": 77.9580},
    "jolly-grant": {"name": "Jolly Grant Airport", "lat": 30.1897, "lng": 78.1803},
    "doiwala": {"name": "Doiwala", "lat": 30.1767, "lng": 78.1167},
    "rishikesh": {"name": "Rishikesh", "lat": 30.1035, "lng": 78.2976},
    "haridwar": {"name": "Haridwar", "lat": 29.9562, "lng": 78.1700},
    "mussoorie": {"name": "Mussoorie", "lat": 30.4598, "lng": 78.0644},
    "roorkee": {"name": "Roorkee", "lat": 29.8649, "lng": 77.8966},
}

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def path_length_km(points: list[tuple[float, float]]) -> float:
    return sum(haversine_km(*points[i], *points[i + 1]) for i in range(len(points) - 1))
