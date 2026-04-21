import concurrent.futures
import gzip
import hashlib
import http.client
import math
import os
import threading
import time
import json as _json
import urllib.parse
import urllib.request
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from itertools import accumulate, pairwise
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import elevation

from .schemas import (DarknessTransition, EvidenceForLlm, JourneyAnalysisResponse, JourneyRiskSummary,
    RouteSummary, SampledPoint, SegmentRisk, SpeedZoneChange, SurfaceChange,
    TopRiskyPart, TrafficIncident)

from .presentation import build_journey_presentation

_FINLAND_TZ = ZoneInfo("Europe/Helsinki")

GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_FIELD_MASK = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"


def _route_id(request):
    raw = f"{request.departure}|{request.destination}|{request.departure_time.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _decode_polyline(encoded):
    result, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = value = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                value |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            deltas.append(~(value >> 1) if (value & 1) else (value >> 1))
        lat += deltas[0]
        lng += deltas[1]
        result.append((lat / 1e5, lng / 1e5))
    return result


def _haversine_km(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _sample_points_from_polyline(
    decoded,
    total_distance_km,
    total_duration_s,
    departure_time,
    sampling_minutes):

    if not decoded:
        return []

    cum_dist = [0.0, *accumulate(
        _haversine_km(a[0], a[1], b[0], b[1]) for a, b in pairwise(decoded))]
    polyline_total = cum_dist[-1] or 1e-9

    sampling_s = sampling_minutes * 60
    n_samples = max(2, int(total_duration_s // sampling_s) + 1)

    points = []
    for i in range(n_samples):
        elapsed_s = min(i * sampling_s, total_duration_s)
        progress = elapsed_s / total_duration_s if total_duration_s > 0 else 0.0
        target_dist = progress * polyline_total
        seg = max(0, min(bisect_left(cum_dist, target_dist) - 1, len(cum_dist) - 2))
        seg_len = cum_dist[seg + 1] - cum_dist[seg]
        frac = (target_dist - cum_dist[seg]) / seg_len if seg_len > 0 else 0.0
        lat = decoded[seg][0] + frac * (decoded[seg + 1][0] - decoded[seg][0])
        lon = decoded[seg][1] + frac * (decoded[seg + 1][1] - decoded[seg][1])
        points.append(SampledPoint(
            index=i,
            lat=round(lat, 6),
            lon=round(lon, 6),
            elapsed_minutes=round(elapsed_s / 60, 1),
            elapsed_seconds=round(elapsed_s, 1),
            estimated_timestamp=departure_time + timedelta(seconds=elapsed_s),
            cumulative_distance_km=round(progress * total_distance_km, 2)))

    if points and points[-1].elapsed_seconds < total_duration_s:
        points.append(SampledPoint(
            index=len(points),
            lat=round(decoded[-1][0], 6),
            lon=round(decoded[-1][1], 6),
            elapsed_minutes=round(total_duration_s / 60, 1),
            elapsed_seconds=round(total_duration_s, 1),
            estimated_timestamp=departure_time + timedelta(seconds=total_duration_s),
            cumulative_distance_km=round(total_distance_km, 2)))

    return points


def _fetch_google_route(request):
    api_key = os.environ.get("GOOGLE_ROUTES_API_KEY", "")
    if not api_key:
        raise EnvironmentError()

    body = {
        "origin": {"address": request.departure},
        "destination": {"address": request.destination},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE"}
    req = urllib.request.Request(
        GOOGLE_ROUTES_URL, data=_json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _FIELD_MASK})
    with urllib.request.urlopen(req, timeout=15) as resp:
        route = _json.loads(resp.read())["routes"][0]

    distance_m = route["distanceMeters"]
    duration_s = int(route["duration"].rstrip("s"))
    encoded_poly = route["polyline"]["encodedPolyline"]
    total_distance_km = round(distance_m / 1000, 2)
    sampled = _sample_points_from_polyline(_decode_polyline(encoded_poly), total_distance_km, duration_s,
                                            request.departure_time, request.sampling_minutes)
    return RouteSummary(
        route_id=_route_id(request),
        departure=request.departure,
        destination=request.destination,
        departure_time=request.departure_time,
        total_distance_km=total_distance_km,
        estimated_duration_minutes=round(duration_s / 60, 1),
        sampled_point_count=len(sampled),
        encoded_polyline=encoded_poly), sampled


def _stub_route(request):
    total_distance_km = 180.0
    duration_s = 7800.0
    duration_minutes = duration_s / 60
    n_points = min(max(2, int(duration_minutes // request.sampling_minutes) + 1), 8)
    step_s = request.sampling_minutes * 60
    points = [
        SampledPoint(
            index=i,
            lat=60.17 + i * 0.15,
            lon=24.94 + i * 0.20,
            elapsed_minutes=round(i * request.sampling_minutes, 1),
            elapsed_seconds=round(i * step_s, 1),
            estimated_timestamp=request.departure_time + timedelta(seconds=i * step_s),
            cumulative_distance_km=round(i * total_distance_km / max(n_points - 1, 1), 2))
        for i in range(n_points)]
    return RouteSummary(
        route_id=_route_id(request),
        departure=request.departure,
        destination=request.destination,
        departure_time=request.departure_time,
        total_distance_km=total_distance_km,
        estimated_duration_minutes=duration_minutes,
        sampled_point_count=len(points)), points


def get_route(request):
    provider = os.environ.get("ROUTE_PROVIDER", "").lower()
    ors_key = os.environ.get("ORS_API_KEY", "")

    if provider == "google":
        return _fetch_google_route(request)
    if provider == "stub":
        return _stub_route(request)
    if provider == "ors" or ors_key:
        return _fetch_ors_route(request)

    if os.environ.get("GOOGLE_ROUTES_API_KEY"):
        return _fetch_google_route(request)

    return _stub_route(request)

_ORS_BASE = "https://api.openrouteservice.org"
_ORS_DEFAULT_PROFILE = "driving-hgv"


def _post_ors_directions(profile, body, api_key):
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key,
        "Accept": "application/json, application/geo+json"}
    req = urllib.request.Request(
        f"{_ORS_BASE}/v2/directions/{profile}",
        data=_json.dumps(body).encode(),
        headers=headers,
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return _json.loads(resp.read())


def fetch_route_options(departure, destination):
    api_key = os.environ.get("ORS_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ORS_API_KEY not set")
    profile = os.environ.get("ORS_PROFILE", _ORS_DEFAULT_PROFILE)
    dep_lat, dep_lon = _ors_geocode(departure, api_key)
    dst_lat, dst_lon = _ors_geocode(destination, api_key)

    body = {
        "coordinates": [[dep_lon, dep_lat], [dst_lon, dst_lat]],
        "geometry": True,
        "instructions": False,
        "radiuses": [1000, 1000],
        "alternative_routes": {
            "target_count": 3,
            "weight_factor": 1.6,
            "share_factor": 0.6}}
    try:
        data = _post_ors_directions(profile, body, api_key)
    except urllib.error.HTTPError:
        del body["alternative_routes"]
        data = _post_ors_directions(profile, body, api_key)

    return [{
            "index": i,
            "distance_km": round(r["summary"]["distance"] / 1000, 2),
            "duration_minutes": round(r["summary"]["duration"] / 60, 1),
            "encoded_polyline": r["geometry"]}
        for i, r in enumerate(data.get("routes", []))]


def _ors_geocode(place, api_key):
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "text": place,
        "size": 1,
        "boundary.country": "FI",
        "layers": "locality,address,neighbourhood,borough"})
    
    url = f"{_ORS_BASE}/geocode/search?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = _json.loads(resp.read())

    features = data.get("features", [])
    if not features:
        raise EnvironmentError(f"ORS geocoding found no results for: {place!r}")
    coords = features[0]["geometry"]["coordinates"]
    return (coords[1], coords[0])


_reverse_geo_cache = {}


def _reverse_geocode(lat, lon):
    key = (round(lat, 3), round(lon, 3))
    if key in _reverse_geo_cache:
        return _reverse_geo_cache[key]

    api_key = os.environ.get("ORS_API_KEY", "")
    if not api_key:
        return ""

    name = ""
    try:
        params = urllib.parse.urlencode({
            "api_key": api_key,
            "point.lat": lat,
            "point.lon": lon,
            "size": 1,
            "layers": "street,address,locality",
            "boundary.country": "FI"})
        req = urllib.request.Request(f"{_ORS_BASE}/geocode/reverse?{params}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            features = _json.loads(resp.read()).get("features", [])
        if features:
            props = features[0].get("properties", {})
            street = props.get("street") or props.get("name") or ""
            locality = props.get("locality") or props.get("localadmin") or ""
            name = f"{street}, {locality}" if street and locality else street or locality
    except Exception:
        pass

    _reverse_geo_cache[key] = name
    return name


def _batch_reverse_geocode(locations):
    if not locations:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(locations), 6)) as ex:
        return list(ex.map(lambda ll: _reverse_geocode(*ll), locations))

_ors_route_cache = {}


def _fetch_ors_route(request):
    api_key = os.environ.get("ORS_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "ORS_API_KEY environment variable is not set. "
            "Get a free key at https://openrouteservice.org/dev/#/signup"
        )
    profile = os.environ.get("ORS_PROFILE", _ORS_DEFAULT_PROFILE)

    dep_lat, dep_lon = _ors_geocode(request.departure, api_key)
    dst_lat, dst_lon = _ors_geocode(request.destination, api_key)
    route_idx = getattr(request, "route_index", 0) or 0

    ors_cache_key = (round(dep_lat, 4), round(dep_lon, 4),
                     round(dst_lat, 4), round(dst_lon, 4),
                     profile, route_idx)
    cached = _ors_route_cache.get(ors_cache_key)
    if cached:
        distance_m, duration_s, encoded_poly = cached
    else:
        body = {
            "coordinates": [[dep_lon, dep_lat], [dst_lon, dst_lat]],
            "geometry": True,
            "instructions": False,
            "radiuses": [1000, 1000]}
        if route_idx > 0:
            body["alternative_routes"] = {"target_count": route_idx + 1, "weight_factor": 1.6, "share_factor": 0.6}
        routes = _post_ors_directions(profile, body, api_key).get("routes") or []
        if not routes:
            raise EnvironmentError(f"ORS returned no routes for {request.departure} -> {request.destination}")
        route = routes[min(route_idx, len(routes) - 1)]
        distance_m = route["summary"]["distance"]
        duration_s = route["summary"]["duration"]
        encoded_poly = route["geometry"]
        _ors_route_cache[ors_cache_key] = (distance_m, duration_s, encoded_poly)

    total_distance_km = round(distance_m / 1000, 2)
    decoded = _decode_polyline(encoded_poly)
    sampled = _sample_points_from_polyline(decoded, total_distance_km, duration_s,
                                            request.departure_time, request.sampling_minutes)

    return RouteSummary(
        route_id=_route_id(request),
        departure=request.departure,
        destination=request.destination,
        departure_time=request.departure_time,
        total_distance_km=total_distance_km,
        estimated_duration_minutes=round(duration_s / 60, 1),
        sampled_point_count=len(sampled),
        encoded_polyline=encoded_poly), sampled


def _stub_road_attributes(points):
    return [{"segment_id": i, "speed_limit_kmh": 80.0, "road_width_m": 7.0, "road_lit": False,
             "road_attribute_source": "stub", "road_attribute_match_distance_m": None}
            for i, _ in enumerate(pairwise(points))]

_DIGIROAD_DEFAULT_WFS_URL = "https://avoinapi.vaylapilvi.fi/vaylatiedot/digiroad/wfs"
_DIGIROAD_SPEED_LIMIT_LAYER = "digiroad:dr_nopeusrajoitus"
_DIGIROAD_ROAD_WIDTH_LAYER = "digiroad:dr_leveys"
_DIGIROAD_LIT_ROAD_LAYER = "digiroad:dr_valaistu_tie"
_DIGIROAD_SPEED_LIMIT_FIELD = "arvo"
_DIGIROAD_ROAD_WIDTH_FIELD = "arvo"
_DIGIROAD_BBOX_BUFFER_DEG = 0.005
_DIGIROAD_MAX_MATCH_DISTANCE_M = 100.0


def _wfs_get_feature_url(base_url, layer, bbox, max_features=5000):
    min_lat, min_lon, max_lat, max_lon = bbox
    return (
        f"{base_url}?service=WFS&version=1.1.0&request=GetFeature"
        f"&typeName={layer}"
        f"&bbox={min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326"
        f"&outputFormat=application/json"
        f"&srsName=EPSG:4326"
        f"&maxFeatures={max_features}")


def _haversine_m(lat1, lon1, lat2, lon2):
    return _haversine_km(lat1, lon1, lat2, lon2) * 1000.0


def _points_bbox(points, buffer_deg):
    lats = [p.lat for p in points]
    lons = [p.lon for p in points]
    return (min(lats) - buffer_deg, min(lons) - buffer_deg, max(lats) + buffer_deg, max(lons) + buffer_deg)


def _point_to_segment_distance_m(plat, plon, alat, alon, blat, blon):
    cos_lat = math.cos(math.radians(plat))
    px, py = 0.0, 0.0
    ax = (alon - plon) * cos_lat
    ay = alat - plat
    bx = (blon - plon) * cos_lat
    by = blat - plat

    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return _haversine_m(plat, plon, alat, alon)

    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    proj_lon = alon + t * (blon - alon)
    proj_lat = alat + t * (blat - alat)
    return _haversine_m(plat, plon, proj_lat, proj_lon)


def _min_distance_to_geometry_m(lat, lon, geometry):
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Point" and len(coords) >= 2:
        return _haversine_m(lat, lon, coords[1], coords[0])
    lines = [coords] if gtype == "LineString" and coords else list(coords) if gtype == "MultiLineString" and coords else []
    distances = [
        _point_to_segment_distance_m(lat, lon, a[1], a[0], b[1], b[0])
        for line in lines for a, b in pairwise(line)]
    return min(distances) if distances else None

_WFS_MEM_CACHE_TTL_S = float(os.environ.get("DIGIROAD_CACHE_TTL_S", "3600"))
_WFS_DISK_CACHE_TTL_S = float(os.environ.get("DIGIROAD_DISK_CACHE_TTL_S", "86400"))
_WFS_DISK_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "_wfs_disk_cache")
_wfs_cache = {}
_wfs_cache_lock = threading.Lock()


def _disk_cache_path(url):
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return os.path.join(_WFS_DISK_CACHE_DIR, url_hash + ".json.gz")


def _disk_cache_read(url):
    path = _disk_cache_path(url)
    try:
        if not os.path.exists(path) or time.time() - os.path.getmtime(path) > _WFS_DISK_CACHE_TTL_S:
            return None
        with open(path, "rb") as f:
            return _json.loads(gzip.decompress(f.read())).get("features", [])
    except Exception:
        return None


def _disk_cache_write(url, features):
    try:
        os.makedirs(_WFS_DISK_CACHE_DIR, exist_ok=True)
        with open(_disk_cache_path(url), "wb") as f:
            f.write(gzip.compress(_json.dumps({"features": features}).encode()))
    except Exception:
        pass


def _fetch_wfs_features(base_url, layer, bbox):
    url = _wfs_get_feature_url(base_url, layer, bbox)
    now = time.monotonic()

    with _wfs_cache_lock:
        cached = _wfs_cache.get(url)
        if cached is not None:
            ts, features = cached
            if now - ts < _WFS_MEM_CACHE_TTL_S:
                return features

    disk_features = _disk_cache_read(url)
    if disk_features is not None:
        with _wfs_cache_lock:
            _wfs_cache[url] = (now, disk_features)
        return disk_features

    features = []
    try:
        parsed = urllib.parse.urlparse(url)
        conn = http.client.HTTPSConnection(parsed.hostname, timeout=25)
        conn.request("GET", parsed.path + "?" + parsed.query, headers={"Accept-Encoding": "gzip"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        if resp.status == 200 and raw:
            if resp.getheader("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            features = _json.loads(raw).get("features", [])
    except Exception:
        pass

    with _wfs_cache_lock:
        _wfs_cache[url] = (now, features)
        for k in [k for k, (ts, _) in _wfs_cache.items() if now - ts >= _WFS_MEM_CACHE_TTL_S]:
            del _wfs_cache[k]
    if features:
        _disk_cache_write(url, features)

    return features

_GRID_CELL_DEG = 0.01


def _feature_representative_point(geom):
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])
    if gtype == "Point" and len(coords) >= 2:
        return (coords[1], coords[0])
    line = coords if gtype == "LineString" else (coords[0] if gtype == "MultiLineString" and coords else None)
    if line:
        mid = line[len(line) // 2]
        return (mid[1], mid[0])
    return None


def _build_feature_grid(features):
    grid = {}
    for feat in features:
        pt = _feature_representative_point(feat.get("geometry") or {})
        if pt is None:
            continue
        grid.setdefault((int(pt[0] / _GRID_CELL_DEG), int(pt[1] / _GRID_CELL_DEG)), []).append(feat)
    return grid


def _grid_query(grid, lat, lon):
    row = int(lat / _GRID_CELL_DEG)
    col = int(lon / _GRID_CELL_DEG)
    return [
        feat
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        for feat in grid.get((row + dr, col + dc), [])
    ]

def _nearest_feature_value(lat, lon, features, value_field, max_distance_m, grid=None):
    candidates = _grid_query(grid, lat, lon) if grid is not None else features
    scored = []
    for feat in candidates:
        geom = feat.get("geometry")
        if geom is None:
            continue
        dist_m = _min_distance_to_geometry_m(lat, lon, geom)
        if dist_m is None or dist_m > max_distance_m:
            continue
        raw = feat.get("properties", {}).get(value_field)
        try:
            scored.append((dist_m, float(raw)))
        except (ValueError, TypeError):
            pass
    if not scored:
        return None, None
    best_dist, best_val = min(scored, key=lambda p: p[0])
    return best_val, round(best_dist, 1)


def _is_near_lit_road(lat, lon, lit_features, max_distance_m, grid=None):
    candidates = _grid_query(grid, lat, lon) if grid is not None else lit_features
    return any(
        (d := _min_distance_to_geometry_m(lat, lon, geom)) is not None and d <= max_distance_m
        for feat in candidates if (geom := feat.get("geometry")) is not None)


_WFS_ROUTE_CHUNK_POINTS = 12


def _route_chunk_bboxes(points, chunk_size=_WFS_ROUTE_CHUNK_POINTS):
    if len(points) <= chunk_size:
        return [_points_bbox(points, _DIGIROAD_BBOX_BUFFER_DEG)]

    step = max(1, chunk_size - 2)
    return [
        _points_bbox(points[start:min(start + chunk_size, len(points))], _DIGIROAD_BBOX_BUFFER_DEG)
        for start in range(0, len(points) - 1, step)
    ]


def _compute_road_attributes(points):
    base_url = os.environ.get("DIGIROAD_WFS_URL", _DIGIROAD_DEFAULT_WFS_URL)
    speed_layer = os.environ.get("DIGIROAD_SPEED_LIMIT_LAYER", _DIGIROAD_SPEED_LIMIT_LAYER)
    width_layer = os.environ.get("DIGIROAD_ROAD_WIDTH_LAYER", _DIGIROAD_ROAD_WIDTH_LAYER)
    lit_layer = _DIGIROAD_LIT_ROAD_LAYER
    speed_field = os.environ.get("DIGIROAD_SPEED_LIMIT_FIELD", _DIGIROAD_SPEED_LIMIT_FIELD)
    width_field = os.environ.get("DIGIROAD_ROAD_WIDTH_FIELD", _DIGIROAD_ROAD_WIDTH_FIELD)
    max_dist = float(os.environ.get("DIGIROAD_MAX_MATCH_DISTANCE_M", _DIGIROAD_MAX_MATCH_DISTANCE_M))

    chunk_bboxes = _route_chunk_bboxes(points)
    layers = [speed_layer, width_layer, lit_layer]
    layer_features = {l: [] for l in layers}
    layer_seen = {l: set() for l in layers}
    fetch_pairs = [(layer, bbox) for layer in layers for bbox in chunk_bboxes]

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(fetch_pairs), 6)) as ex:
        future_to_layer = {ex.submit(_fetch_wfs_features, base_url, layer, bbox): layer for layer, bbox in fetch_pairs}
        for fut in concurrent.futures.as_completed(future_to_layer):
            layer = future_to_layer[fut]
            try:
                features = fut.result()
            except Exception:
                continue
            for feat in features:
                fid = feat.get("id", "")
                if fid and fid in layer_seen[layer]:
                    continue
                if fid:
                    layer_seen[layer].add(fid)
                layer_features[layer].append(feat)

    speed_features = layer_features[speed_layer]
    width_features = layer_features[width_layer]
    lit_features = layer_features[lit_layer]

    speed_grid = _build_feature_grid(speed_features)
    width_grid = _build_feature_grid(width_features)
    lit_grid = _build_feature_grid(lit_features)

    results = []
    for i, (a, b) in enumerate(pairwise(points)):
        mid_lat = (a.lat + b.lat) / 2
        mid_lon = (a.lon + b.lon) / 2

        speed_val, speed_dist = _nearest_feature_value(
            mid_lat, mid_lon, speed_features, speed_field, max_dist,
            grid=speed_grid)
        width_val, width_dist = _nearest_feature_value(
            mid_lat, mid_lon, width_features, width_field, max_dist,
            grid=width_grid)

        if width_val is not None:
            width_val = round(width_val / 100.0, 1)
            eff_speed = speed_val if speed_val is not None else 80.0
            min_plausible_width = 5.5 if eff_speed >= 80 else 5.0 if eff_speed >= 60 else 3.5
            if width_val < min_plausible_width:
                width_val = width_dist = None

        match_dist = min((d for d in (speed_dist, width_dist) if d is not None), default=None)

        road_lit = _is_near_lit_road(mid_lat, mid_lon, lit_features, max_dist, grid=lit_grid)

        results.append({
            "segment_id": i,
            "speed_limit_kmh": speed_val if speed_val is not None else 80.0,
            "road_width_m": width_val if width_val is not None else 7.0,
            "road_lit": road_lit,
            "road_attribute_source": "digiroad_wfs" if speed_val is not None else "default",
            "road_attribute_match_distance_m": match_dist,
        })

    return results


def get_road_attributes(points):
    wfs_url = os.environ.get("DIGIROAD_WFS_URL", _DIGIROAD_DEFAULT_WFS_URL)
    return _compute_road_attributes(points) if wfs_url and wfs_url != "stub" else _stub_road_attributes(points)


def _stub_road_weather(points):
    return [_WX_EMPTY | {"segment_id": i, "weather_source": "stub", "road_weather": "dry", "surface_condition": "dry"}
            for i, _ in enumerate(pairwise(points))]

_DIGITRAFFIC_BASE = "https://tie.digitraffic.fi/api/weather/v1"
_DIGITRAFFIC_BBOX_BUFFER_DEG = 0.02
_DIGITRAFFIC_MAX_MATCH_DISTANCE_M = float(
    os.environ.get("DIGITRAFFIC_MAX_MATCH_DISTANCE_M", "5000")
)
_DIGITRAFFIC_MAX_FORECAST_OFFSET_S = int(
    os.environ.get("DIGITRAFFIC_MAX_FORECAST_OFFSET_S", "43200")
)
_DIGITRAFFIC_USABLE_DISTANCE_M = float(
    os.environ.get("DIGITRAFFIC_USABLE_DISTANCE_M", "3000")
)
_DIGITRAFFIC_USABLE_TIME_DELTA_S = float(
    os.environ.get("DIGITRAFFIC_USABLE_TIME_DELTA_S", "3600")
)
_DIGITRAFFIC_CACHE_TTL_S = float(os.environ.get("DIGITRAFFIC_CACHE_TTL_S", "300"))
_digitraffic_cache = {}
_digitraffic_cache_lock = threading.Lock()


def _fetch_digitraffic_json(path):
    url = f"{_DIGITRAFFIC_BASE}{path}"
    now = time.monotonic()

    with _digitraffic_cache_lock:
        cached = _digitraffic_cache.get(url)
        if cached is not None:
            ts, data = cached
            if now - ts < _DIGITRAFFIC_CACHE_TTL_S:
                return data

    try:
        conn = http.client.HTTPSConnection("tie.digitraffic.fi", timeout=15)
        full_path = f"/api/weather/v1{path}"
        conn.request("GET", full_path, headers={
            "Accept-Encoding": "gzip",
            "Digitraffic-User": "HazardAnalysis/risk-pipeline",})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()

        if resp.status != 200:
            return None

        if resp.getheader("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        data = _json.loads(raw)
    except Exception:
        return None

    with _digitraffic_cache_lock:
        _digitraffic_cache[url] = (now, data)
        for k in [k for k, (ts, _) in _digitraffic_cache.items() if now - ts >= _DIGITRAFFIC_CACHE_TTL_S]:
            del _digitraffic_cache[k]

    return data


_DT_MAINTENANCE_TASKS = ["PLOUGHING_AND_SLUSH_REMOVAL", "SALTING", "SPOT_SANDING", "LINE_SANDING", "REMOVAL_OF_BULGE_ICE"]
_DT_MAINTENANCE_HOURS_BACK = int(os.environ.get("DIGITRAFFIC_MAINTENANCE_HOURS_BACK", "24"))
_DT_MAINTENANCE_MAX_DIST_M = float(os.environ.get("DIGITRAFFIC_MAINTENANCE_MAX_DIST_M", "500"))


def _fetch_maintenance(points, departure_time):
    if os.environ.get("DIGITRAFFIC_WEATHER", "").lower() == "stub" or not points:
        return []
    min_lat, min_lon, max_lat, max_lon = _points_bbox(points, _DIGITRAFFIC_BBOX_BUFFER_DEG)
    since = (departure_time.astimezone(timezone.utc) - timedelta(hours=_DT_MAINTENANCE_HOURS_BACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
    from urllib.parse import urlencode
    q = [("xMin", f"{min_lon:.5f}"), ("yMin", f"{min_lat:.5f}"),
         ("xMax", f"{max_lon:.5f}"), ("yMax", f"{max_lat:.5f}"),
         ("endFrom", since)] + [("taskId", t) for t in _DT_MAINTENANCE_TASKS]
    try:
        conn = http.client.HTTPSConnection("tie.digitraffic.fi", timeout=15)
        conn.request("GET", "/api/maintenance/v1/tracking/routes/latest?" + urlencode(q),
                     headers={"Accept-Encoding": "gzip", "Digitraffic-User": "HazardAnalysis/risk-pipeline"})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        if resp.status != 200:
            return []
        if resp.getheader("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        data = _json.loads(raw)
    except Exception:
        return []
    out = []
    for f in data.get("features", []):
        props = f.get("properties") or {}
        ts = props.get("time"); tasks = props.get("tasks") or []
        geom = f.get("geometry") or {}; coords = geom.get("coordinates")
        if not ts or not tasks or not coords:
            continue
        if geom.get("type") == "LineString":
            for c in coords:
                if isinstance(c, list) and len(c) >= 2:
                    out.append({"lat": c[1], "lon": c[0], "time": ts, "tasks": tasks})
        elif isinstance(coords, list) and len(coords) >= 2:
            out.append({"lat": coords[1], "lon": coords[0], "time": ts, "tasks": tasks})
    return out


def _attach_maintenance(seg, sampled_points, features, departure_time):
    if not features:
        return seg
    p1 = sampled_points[seg.from_point_index]; p2 = sampled_points[seg.to_point_index]
    mlat = (p1.lat + p2.lat) / 2.0; mlon = (p1.lon + p2.lon) / 2.0
    seg_ts = p1.estimated_timestamp or departure_time
    if seg_ts.tzinfo is None:
        seg_ts = seg_ts.replace(tzinfo=timezone.utc)
    best = None
    for f in features:
        d = _haversine_m(mlat, mlon, f["lat"], f["lon"])
        if d > _DT_MAINTENANCE_MAX_DIST_M:
            continue
        try:
            ftime = datetime.fromisoformat(f["time"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ftime.tzinfo is None:
            ftime = ftime.replace(tzinfo=timezone.utc)
        age_min = (seg_ts - ftime).total_seconds() / 60.0
        if age_min < 0 or age_min > _DT_MAINTENANCE_HOURS_BACK * 60:
            continue
        if best is None or age_min < best[0]:
            best = (age_min, d, f["tasks"][0])
    if best is None:
        return seg
    return seg.model_copy(update={
        "recent_maintenance_task": best[2],
        "recent_maintenance_age_minutes": int(best[0]),
        "recent_maintenance_distance_m": int(best[1])})


def _pick_best_forecast(forecasts, target_ts):
    target = target_ts if target_ts.tzinfo else target_ts.replace(tzinfo=timezone.utc)
    candidates = []
    for fc in forecasts or []:
        ts = fc.get("time")
        if not ts:
            continue
        try:
            fc_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if fc_time.tzinfo is None:
            fc_time = fc_time.replace(tzinfo=timezone.utc)
        delta = abs((fc_time - target).total_seconds())
        if delta <= _DIGITRAFFIC_MAX_FORECAST_OFFSET_S:
            candidates.append((fc.get("type") != "FORECAST", delta, fc))
    if not candidates:
        return None, None
    _, delta, fc = min(candidates, key=lambda x: (x[0], x[1]))
    return fc, delta


def _map_overall_condition(condition):
    return {
        "NORMAL_CONDITION": "normal",
        "POOR_CONDITION": "poor",
        "EXTREMELY_POOR_CONDITION": "extremely_poor",
    }.get(condition, "unknown")


def _weather_confidence(dist_m, time_delta_s):
    if dist_m is None or time_delta_s is None:
        return "none"
    if dist_m < 1000 and time_delta_s < 1800:
        return "high"
    if (dist_m <= _DIGITRAFFIC_USABLE_DISTANCE_M
            and time_delta_s <= _DIGITRAFFIC_USABLE_TIME_DELTA_S):
        return "medium"
    return "low"


_WX_EMPTY = {
    "road_weather": "unknown", "surface_condition": "unknown", "grip": None, "grip_proxy": None,
    "overall_road_condition": None, "friction_condition": None, "winter_slipperiness": None,
    "road_temperature_c": None, "air_temperature_c": None, "wind_speed_ms": None,
    "weather_match_distance_m": None, "weather_forecast_time": None, "weather_reliability": None,
    "weather_section_id": None, "weather_forecast_type": None, "weather_time_delta_minutes": None,
    "weather_usable_for_scoring": False, "weather_confidence": "none"}


def _compute_road_weather(points, departure_time):
    min_lat, min_lon, max_lat, max_lon = _points_bbox(points, _DIGITRAFFIC_BBOX_BUFFER_DEG)
    bbox_qs = f"?xMin={min_lon}&yMin={min_lat}&xMax={max_lon}&yMax={max_lat}"

    sections_geojson = _fetch_digitraffic_json(f"/forecast-sections-simple{bbox_qs}") or {}
    forecasts_data = _fetch_digitraffic_json(f"/forecast-sections-simple/forecasts{bbox_qs}") or {}

    section_geometries = {
        str(sid): geom
        for feat in sections_geojson.get("features", []) if isinstance(sections_geojson, dict)
        if (sid := feat.get("id") or feat.get("properties", {}).get("id"))
        if (geom := feat.get("geometry"))}

    section_forecasts = {
        sid: forecasts
        for sec in forecasts_data.get("forecastSections", []) if isinstance(forecasts_data, dict)
        if (sid := str(sec.get("id", "")))
        if (forecasts := sec.get("forecasts", []))}

    usable_ids = set(section_geometries) & set(section_forecasts)

    results = []
    for i, (a, b) in enumerate(pairwise(points)):
        mid_lat = (a.lat + b.lat) / 2
        mid_lon = (a.lon + b.lon) / 2

        segment_ts = a.estimated_timestamp
        if segment_ts is None:
            segment_ts = departure_time

        best_sid = None
        best_dist = None
        for sid in usable_ids:
            dist = _min_distance_to_geometry_m(mid_lat, mid_lon, section_geometries[sid])
            if dist is None:
                continue
            if dist > _DIGITRAFFIC_MAX_MATCH_DISTANCE_M:
                continue
            if best_dist is None or dist < best_dist:
                best_sid = sid
                best_dist = round(dist, 1)

        if best_sid is None:
            results.append(_WX_EMPTY | {"segment_id": i, "weather_source": "digitraffic_no_match"})
            continue

        fc, time_delta_s = _pick_best_forecast(section_forecasts[best_sid], segment_ts)

        if fc is None:
            results.append(_WX_EMPTY | {"segment_id": i, "weather_source": "digitraffic_no_forecast",
                                         "weather_match_distance_m": best_dist, "weather_section_id": best_sid})
            continue

        time_delta_min = round(time_delta_s / 60, 1) if time_delta_s is not None else None
        usable = (best_dist is not None and best_dist <= _DIGITRAFFIC_USABLE_DISTANCE_M
                  and time_delta_s is not None and time_delta_s <= _DIGITRAFFIC_USABLE_TIME_DELTA_S)

        reason = fc.get("forecastConditionReason") or {}
        overall_cond = fc.get("overallRoadCondition")
        road_cond = reason.get("roadCondition")
        winter_slip = reason.get("winterSlipperiness")
        fc_type = fc.get("type", "unknown")

        results.append(_WX_EMPTY | {
            "segment_id": i,
            "road_weather": _map_overall_condition(overall_cond),
            "surface_condition": (road_cond or "unknown").lower(),
            "overall_road_condition": overall_cond,
            "friction_condition": reason.get("frictionCondition"),
            "winter_slipperiness": bool(winter_slip) if winter_slip is not None else None,
            "road_temperature_c": fc.get("roadTemperature"),
            "air_temperature_c": fc.get("temperature"),
            "wind_speed_ms": fc.get("windSpeed"),
            "weather_source": f"digitraffic_{fc_type.lower()}",
            "weather_match_distance_m": best_dist,
            "weather_forecast_time": fc.get("time"),
            "weather_reliability": fc.get("reliability"),
            "weather_section_id": best_sid,
            "weather_forecast_type": fc_type,
            "weather_time_delta_minutes": time_delta_min,
            "weather_usable_for_scoring": usable,
            "weather_confidence": _weather_confidence(best_dist, time_delta_s)})

    return results


def get_road_weather(points, departure_time):
    mode = os.environ.get("DIGITRAFFIC_WEATHER", "live")
    return _stub_road_weather(points) if mode == "stub" else _compute_road_weather(points, departure_time)


def _compute_darkness(points):
    results = []
    for i, (a, b) in enumerate(pairwise(points)):
        ts = (a.estimated_timestamp or datetime.now(timezone.utc))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_FINLAND_TZ)
        sun_elev = elevation(Observer(latitude=(a.lat + b.lat) / 2, longitude=(a.lon + b.lon) / 2, elevation=0), ts)
        results.append({
            "segment_id": i,
            "is_dark": sun_elev < -6.0,
            "is_twilight": -6.0 <= sun_elev < 0.0,
            "solar_elevation_deg": round(sun_elev, 2)})
    return results

_INCIDENT_MAX_DISTANCE_M = 5000
_MOOSE_SEASON_FACTOR = {
    1: 0.2, 2: 0.2, 3: 0.2, 4: 0.5,
    5: 1.0, 6: 1.0, 7: 0.5, 8: 0.5,
    9: 1.0, 10: 1.0, 11: 1.0, 12: 0.5}


def _all_incident_coords(geometry):
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates") or []
    if gtype == "Point":
        return [(coords[1], coords[0])] if len(coords) >= 2 else []
    flat = coords if gtype in ("MultiPoint", "LineString") else [c for line in coords for c in line] if gtype == "MultiLineString" else []
    return [(c[1], c[0]) for c in flat if len(c) >= 2]


def _incident_corridor_match(geometry, sampled_points):
    all_coords = _all_incident_coords(geometry)
    if not all_coords:
        return (float("inf"), 0.0, 0.0)

    best_dist = float("inf")
    best_lat, best_lon = all_coords[0]

    step = max(1, len(all_coords) // 300)

    for i in range(0, len(all_coords), step):
        lat, lon = all_coords[i]
        for si in range(0, len(sampled_points), 3):
            sp = sampled_points[si]
            d = _haversine_m(lat, lon, sp.lat, sp.lon)
            if d < best_dist:
                best_dist = d
                best_lat = lat
                best_lon = lon
                if d < 200:
                    return (best_dist, best_lat, best_lon)

    return (best_dist, best_lat, best_lon)


def _determine_incident_status(announcement_type, end_time, now_utc):
    if end_time:
        try:
            if datetime.fromisoformat(end_time.replace("Z", "+00:00")) < now_utc:
                return ("situation_over", False)
        except (ValueError, TypeError):
            pass
    utype = (announcement_type or "").upper()
    return ("preliminary", True) if utype == "PRELIMINARY_ACCIDENT_REPORT" else ("confirmed", True) if utype else ("unknown", True)


def fetch_traffic_incidents(sampled_points, inactive_hours=6):
    if not sampled_points:
        return []

    url = (f"/api/traffic-message/v1/messages?situationType=TRAFFIC_ANNOUNCEMENT"
           f"&includeAreaGeometry=false&inactiveHours={inactive_hours}")
    try:
        conn = http.client.HTTPSConnection("tie.digitraffic.fi", timeout=15)
        conn.request("GET", url, headers={"Accept-Encoding": "gzip", "Digitraffic-User": "HazardAnalysis/risk-pipeline"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        if resp.status != 200:
            return []
        if resp.getheader("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        data = _json.loads(raw)
    except Exception:
        return []

    now_utc = datetime.now(timezone.utc)
    incidents = []
    for feat in data.get("features", []):
        geom = feat.get("geometry")
        if not geom:
            continue
        dist_m, closest_lat, closest_lon = _incident_corridor_match(geom, sampled_points)
        if dist_m > _INCIDENT_MAX_DISTANCE_M:
            continue
        props = feat.get("properties", {})
        ann = (props.get("announcements") or [{}])[0]
        td = ann.get("timeAndDuration", {}) or {}
        ann_type = props.get("trafficAnnouncementType", "")
        status, is_active = _determine_incident_status(ann_type, td.get("endTime"), now_utc)
        incidents.append(TrafficIncident(
            situation_id=props.get("situationId", ""),
            title=ann.get("title", ""),
            announcement_type=ann_type,
            start_time=td.get("startTime"),
            end_time=td.get("endTime"),
            status=status,
            is_active=is_active,
            features=[name for af in ann.get("features", []) or [] if (name := af.get("name", ""))],
            lat=closest_lat,
            lon=closest_lon,
            distance_from_route_m=round(dist_m, 0)))

    return sorted(incidents, key=lambda x: x.distance_from_route_m)


def _score_segment(segment_id, road_attrs, weather, darkness, sampled_points=None):
    score = 0.0
    reasons = []
    wx_usable = weather.get("weather_usable_for_scoring", False)

    if darkness.get("is_dark"):
        score += 0.15
        reasons.append("driving in darkness")
    elif darkness.get("is_twilight"):
        score += 0.08
        reasons.append("driving in twilight")

    if wx_usable:
        overall_cond = weather.get("overall_road_condition")
        surface = weather.get("surface_condition", "unknown")
        friction = weather.get("friction_condition")

        if overall_cond in ("EXTREMELY_POOR_CONDITION", "POOR_CONDITION"):
            extreme = overall_cond == "EXTREMELY_POOR_CONDITION"
            score += 0.30 if extreme else 0.20
            reasons.append("extremely poor road condition" if extreme else "poor road condition")
            if surface not in ("unknown", "dry"):
                reasons.append(f"surface condition: {surface}")
        else:
            surface_score = {"ice": 0.25, "partly_icy": 0.25, "frost": 0.25, "snow": 0.20, "slush": 0.20, "wet": 0.10, "moist": 0.10}.get(surface, 0.0)
            friction_score = {"VERY_SLIPPERY": 0.25, "SLIPPERY": 0.15}.get(friction, 0.0)
            winter_slip_score = 0.15 if weather.get("winter_slipperiness") else 0.0
            wx_detail_score = max(surface_score, friction_score, winter_slip_score)
            if wx_detail_score > 0:
                score += wx_detail_score
                if surface_score == wx_detail_score:
                    reasons.append(f"surface condition: {surface}")
                elif friction_score == wx_detail_score:
                    reasons.append(f"{'very slippery' if friction == 'VERY_SLIPPERY' else 'slippery'} friction condition")
                else:
                    reasons.append("winter slipperiness warning")

        grip = weather.get("grip")
        if grip is not None:
            if grip < 0.50:
                score += 0.20
                reasons.append(f"low grip ({grip:.2f})")
            elif grip < 0.70:
                score += 0.10
                reasons.append(f"reduced grip ({grip:.2f})")
    elif weather.get("weather_source", "unknown") not in ("stub", "unknown") and weather.get("weather_confidence", "none") != "none":
        reasons.append(f"weather data present but not scored (confidence={weather['weather_confidence']})")

    speed = road_attrs.get("speed_limit_kmh")
    width = road_attrs.get("road_width_m")
    road_lit = road_attrs.get("road_lit", False)
    if speed is not None and width is not None and speed >= 80 and width < 6.5:
        score += 0.10
        reasons.append(f"narrow road ({width}m) at {speed} km/h limit")

    if speed is not None and speed >= 100 and darkness.get("is_dark") and not road_lit:
        score += 0.05
        reasons.append(f"high speed ({speed} km/h) in darkness, unlit road")

    moose_risk = False
    if speed is not None and speed >= 80 and not road_lit and (darkness.get("is_twilight") or darkness.get("is_dark")):
        seg_ts = sampled_points[segment_id].estimated_timestamp if sampled_points and segment_id < len(sampled_points) else None
        season_factor = _MOOSE_SEASON_FACTOR.get(seg_ts.month if seg_ts else 6, 0.5)
        season_note = "" if season_factor >= 1.0 else " (reduced - low-season)"
        is_twi = darkness.get("is_twilight")
        moose_risk = True
        score += round((0.12 if is_twi else 0.08) * season_factor, 2)
        reasons.append(f"{'elevated moose/wildlife collision risk (twilight, rural unlit road)' if is_twi else 'moose/wildlife collision risk (darkness, rural unlit road)'}{season_note}")

    score = round(min(score, 1.0), 2)
    risk_level = "low" if score < 0.25 else "moderate" if score < 0.50 else "high" if score < 0.75 else "critical"

    if not reasons:
        reasons.append("no adverse factors detected")

    length_km = round(_haversine_km(
        sampled_points[segment_id].lat, sampled_points[segment_id].lon,
        sampled_points[segment_id + 1].lat, sampled_points[segment_id + 1].lon), 2) \
        if sampled_points and segment_id + 1 < len(sampled_points) else 0.0

    return SegmentRisk(**(weather | road_attrs | {
        "segment_id": segment_id,
        "from_point_index": segment_id,
        "to_point_index": segment_id + 1,
        "length_km": length_km,
        "is_dark": darkness.get("is_dark"),
        "is_twilight": darkness.get("is_twilight"),
        "solar_elevation_deg": darkness.get("solar_elevation_deg"),
        "moose_risk": moose_risk,
        "risk_score": score,
        "risk_level": risk_level,
        "reasons": reasons}))

def assess_journey(request):
    if request.departure_time.tzinfo is None:
        request = request.model_copy(update={
            "departure_time": request.departure_time.replace(tzinfo=_FINLAND_TZ)})

    route_summary, sampled_points = get_route(request)

    arrival = request.departure_time + timedelta(minutes=route_summary.estimated_duration_minutes)
    route_summary = route_summary.model_copy(update={"arrival_time": arrival})

    n_segments = len(sampled_points) - 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as _ex:
        _fut_attrs = _ex.submit(get_road_attributes, sampled_points)
        _fut_weather = _ex.submit(get_road_weather, sampled_points, request.departure_time)
        _fut_darkness = _ex.submit(_compute_darkness, sampled_points)
        _fut_incidents = _ex.submit(fetch_traffic_incidents, sampled_points)
        _fut_maintenance = _ex.submit(_fetch_maintenance, sampled_points, request.departure_time)
    road_attrs_list = _fut_attrs.result()
    weather_list = _fut_weather.result()
    darkness_list = _fut_darkness.result()
    traffic_incidents = _fut_incidents.result()
    maintenance_features = _fut_maintenance.result()

    segment_risks = [
        _attach_maintenance(
            _score_segment(i, road_attrs_list[i], weather_list[i], darkness_list[i], sampled_points),
            sampled_points, maintenance_features, request.departure_time)
        for i in range(n_segments)]

    scores = [s.risk_score for s in segment_risks]
    overall = round(sum(scores) / len(scores), 2) if scores else 0.0
    overall_level = "low" if overall < 0.25 else "moderate" if overall < 0.50 else "high" if overall < 0.75 else "critical"

    journey_risk = JourneyRiskSummary(
        overall_risk_score=overall,
        overall_risk_level=overall_level,
        highest_segment_score=max(scores) if scores else 0.0,
        dark_segment_count=sum(1 for s in segment_risks if s.is_dark),
        twilight_segment_count=sum(1 for s in segment_risks if s.is_twilight),
        poor_grip_segment_count=sum(
            1 for s in segment_risks if s.grip is not None and s.grip < 0.50
        ),
        poor_weather_segment_count=sum(
            1 for s in segment_risks
            if s.weather_usable_for_scoring
            and s.overall_road_condition in ("POOR_CONDITION", "EXTREMELY_POOR_CONDITION")
        ),
        slippery_segment_count=sum(
            1 for s in segment_risks
            if s.weather_usable_for_scoring
            and s.friction_condition in ("SLIPPERY", "VERY_SLIPPERY")
        ),
        weak_weather_match_count=sum(
            1 for s in segment_risks
            if s.weather_confidence == "low"
        ),
        usable_weather_segment_count=sum(
            1 for s in segment_risks if s.weather_usable_for_scoring
        ),
        lit_road_segment_count=sum(1 for s in segment_risks if s.road_lit),
        moose_risk_segment_count=sum(1 for s in segment_risks if s.moose_risk))

    seg_lengths = [s.length_km for s in segment_risks]
    seg_minutes = [
        (sampled_points[s.to_point_index].elapsed_minutes - sampled_points[s.from_point_index].elapsed_minutes)
        if s.to_point_index < len(sampled_points) else 0.0
        for s in segment_risks]
    is_dark_or_twi = [s.is_dark or s.is_twilight for s in segment_risks]
    dark_km = round(sum(l for l, d in zip(seg_lengths, is_dark_or_twi) if d), 1)
    daylight_km = round(sum(l for l, d in zip(seg_lengths, is_dark_or_twi) if not d), 1)
    dark_min = round(sum(m for m, d in zip(seg_minutes, is_dark_or_twi) if d), 1)
    daylight_min = round(sum(m for m, d in zip(seg_minutes, is_dark_or_twi) if not d), 1)
    journey_risk.darkness_total_km = dark_km
    journey_risk.darkness_total_minutes = dark_min
    journey_risk.daylight_total_km = daylight_km
    journey_risk.daylight_total_minutes = daylight_min

    darkness_transitions = []
    prev_state = "daylight"
    for s in segment_risks:
        cur = "darkness" if s.is_dark else "twilight" if s.is_twilight else "daylight"
        if cur != prev_state:
            pt = sampled_points[s.from_point_index]
            darkness_transitions.append(DarknessTransition(
                km=round(pt.cumulative_distance_km, 1),
                timestamp=pt.estimated_timestamp.isoformat() if pt.estimated_timestamp else "",
                event={"darkness": "enters_darkness", "twilight": "enters_twilight"}.get(cur, "exits_darkness"),
                lat=pt.lat, lon=pt.lon))
        prev_state = cur

    surface_changes = []
    prev_surface = segment_risks[0].surface_condition if segment_risks else "unknown"
    for s in segment_risks[1:]:
        cur_surface = s.surface_condition or "unknown"
        if cur_surface != prev_surface and cur_surface != "unknown" and prev_surface != "unknown":
            pt = sampled_points[s.from_point_index]
            surface_changes.append(SurfaceChange(
                km=round(pt.cumulative_distance_km, 1),
                timestamp=pt.estimated_timestamp.isoformat() if pt.estimated_timestamp else "",
                from_condition=prev_surface,
                to_condition=cur_surface,
                lat=pt.lat,
                lon=pt.lon))
        if cur_surface != "unknown":
            prev_surface = cur_surface

    speed_zone_changes = []
    prev_speed = segment_risks[0].speed_limit_kmh if segment_risks else None
    for s in segment_risks[1:]:
        cur_speed = s.speed_limit_kmh
        if cur_speed is not None and prev_speed is not None and cur_speed != prev_speed:
            pt = sampled_points[s.from_point_index]
            speed_zone_changes.append(SpeedZoneChange(
                km=round(pt.cumulative_distance_km, 1),
                timestamp=pt.estimated_timestamp.isoformat() if pt.estimated_timestamp else "",
                from_speed=prev_speed,
                to_speed=cur_speed,
                lat=pt.lat,
                lon=pt.lon))
        if cur_speed is not None:
            prev_speed = cur_speed

    sorted_segments = sorted(segment_risks, key=lambda s: s.risk_score, reverse=True)
    top_risky = [
        TopRiskyPart(
            segment_id=s.segment_id,
            risk_score=s.risk_score,
            risk_level=s.risk_level,
            reasons=s.reasons,
            cumulative_distance_km=round(sampled_points[s.from_point_index].cumulative_distance_km, 1)
                if s.from_point_index < len(sampled_points) else 0.0,
            estimated_time=sampled_points[s.from_point_index].estimated_timestamp.isoformat()
                if s.from_point_index < len(sampled_points) and sampled_points[s.from_point_index].estimated_timestamp
                else None)
        for s in sorted_segments[:3]]
    named_entries = (
        [(t, t.lat, t.lon) for t in darkness_transitions]
        + [(c, c.lat, c.lon) for c in surface_changes[:6]]
        + [(sz, sz.lat, sz.lon) for sz in speed_zone_changes[:6]]
        + [(tp, sampled_points[s.from_point_index].lat, sampled_points[s.from_point_index].lon)
           for tp, s in zip(top_risky, sorted_segments[:3]) if s.from_point_index < len(sampled_points)])
    if named_entries:
        names = _batch_reverse_geocode([(lat, lon) for _, lat, lon in named_entries])
        for entry, name in zip(named_entries, names):
            entry[0].road_name = name

    for t in darkness_transitions:
        if t.event in ("enters_darkness", "enters_twilight"):
            if not journey_risk.darkness_start_time:
                journey_risk.darkness_start_time = t.timestamp
                journey_risk.darkness_start_road = t.road_name
        elif t.event == "exits_darkness":
            journey_risk.darkness_end_time = t.timestamp
            journey_risk.darkness_end_road = t.road_name
            if not journey_risk.daylight_start_time:
                journey_risk.daylight_start_time = t.timestamp
                journey_risk.daylight_start_road = t.road_name

    if top_risky:
        journey_risk.highest_risk_road = top_risky[0].road_name

    dark_count = journey_risk.dark_segment_count
    twilight_count = journey_risk.twilight_segment_count
    poor_grip = journey_risk.poor_grip_segment_count
    poor_weather = journey_risk.poor_weather_segment_count
    slippery = journey_risk.slippery_segment_count
    weak_wx = journey_risk.weak_weather_match_count
    conditions_parts = [p for p in (
        f"{dark_count}/{n_segments} segments in darkness ({dark_km} km, {dark_min} min)" if dark_count else None,
        f"{twilight_count}/{n_segments} segments in twilight" if twilight_count else None,
        f"{daylight_km} km in daylight ({daylight_min} min)" if daylight_km > 0 else None,
        f"{poor_grip}/{n_segments} segments with poor grip" if poor_grip else None,
        f"{poor_weather}/{n_segments} segments with poor/extremely poor road condition (usable weather)" if poor_weather else None,
        f"{slippery}/{n_segments} segments with slippery conditions (usable weather)" if slippery else None,
        f"{weak_wx}/{n_segments} segments with weak weather match (not scored)" if weak_wx else None,
        f"{journey_risk.moose_risk_segment_count}/{n_segments} segments with elevated moose/wildlife risk" if journey_risk.moose_risk_segment_count else None,
        f"{journey_risk.lit_road_segment_count}/{n_segments} segments on lit roads" if journey_risk.lit_road_segment_count else None,
    ) if p] or ["no adverse conditions detected in any segment"]

    first_dark = next((s for s in segment_risks if s.is_dark), None)
    first_slippery = next((s for s in segment_risks
                           if s.weather_usable_for_scoring and s.friction_condition in ("SLIPPERY", "VERY_SLIPPERY")), None)
    first_dark_ts = (ts.isoformat() if first_dark and (ts := sampled_points[first_dark.from_point_index].estimated_timestamp) else None)
    first_slippery_ts = (ts.isoformat() if first_slippery and (ts := sampled_points[first_slippery.from_point_index].estimated_timestamp) else None)

    evidence = EvidenceForLlm(
        journey=f"{request.departure} -> {request.destination}",
        departure_time_local=request.departure_time.astimezone(_FINLAND_TZ).isoformat(),
        total_segments=n_segments,
        overall_risk_score=overall,
        overall_risk_level=overall_level,
        dark_segment_count=dark_count,
        twilight_segment_count=twilight_count,
        first_dark_timestamp=first_dark_ts,
        weak_weather_match_count=weak_wx,
        usable_weather_segment_count=journey_risk.usable_weather_segment_count,
        first_usable_slippery_weather_timestamp=first_slippery_ts,
        darkness_total_km=journey_risk.darkness_total_km,
        darkness_total_minutes=journey_risk.darkness_total_minutes,
        daylight_total_km=journey_risk.daylight_total_km,
        daylight_total_minutes=journey_risk.daylight_total_minutes,
        darkness_transitions=darkness_transitions,
        surface_changes=surface_changes,
        speed_zone_changes=speed_zone_changes,
        lit_road_segment_count=journey_risk.lit_road_segment_count,
        moose_risk_segment_count=journey_risk.moose_risk_segment_count,
        top_risky_parts=top_risky,
        conditions_summary="; ".join(conditions_parts),
        traffic_incidents=traffic_incidents)

    journey_presentation = build_journey_presentation(
        route=route_summary,
        journey_risk=journey_risk,
        evidence=evidence,
        top_risky=top_risky,
        total_segments=n_segments,
        sampling_minutes=request.sampling_minutes)

    return JourneyAnalysisResponse(
        route_id=route_summary.route_id,
        overall_risk_score=overall,
        route_summary=route_summary,
        sampled_points=sampled_points,
        segment_risks=segment_risks,
        journey_risk_summary=journey_risk,
        evidence_for_llm=evidence,
        journey_presentation=journey_presentation,
        top_risky_parts=top_risky,
        traffic_incidents=traffic_incidents)
