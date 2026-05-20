"""Geographic enrichment: PDOK BAG, CBS Wijken en Buurten, OSM Overpass.

Coordinate-driven. Takes the project centroid (auto-detect WGS84 vs RD
New) and a buffer radius, queries the three open Dutch APIs, returns a
GeoContext.

Hard rule from CLAUDE.md: every API call degrades gracefully. On any
network error or non-200 response, log via loguru, append the api_name
to GeoContext.data_sources_failed, and continue with whatever the other
APIs returned. Never raise from a network call.

Responses are cached under data/cache/enrich/<coord_hash>_<buffer>/
<api_name>.json so reruns and tests skip the network entirely.

Stage 4 of the build plan. Stage 4c (3D BAG) extends this module later.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from pyproj import Transformer

from .config import settings
from .schemas import (
    CRS,
    GeoContext,
    NearbyBuildingsSnapshot,
    NeighbourhoodDemographics,
    ProjectLocation,
    TransitAccess,
)

# API identifiers, matching the Provenance.api_name vocabulary in schemas.py.
API_PDOK_BAG = "pdok_bag"
API_CBS = "cbs_demographics"
API_OSM = "osm_overpass"
API_3D_BAG = "pdok_3d_bag"

# Endpoints. Configuration in one place so production swaps to a cached
# snapshot become a single-line change.
PDOK_BAG_BASE = "https://api.pdok.nl/kadaster/bag/ogc/v2"
PDOK_WIJKENBUURTEN_BASE = "https://api.pdok.nl/cbs/wijken-en-buurten-2025/ogc/v1"
PDOK_WIJKENBUURTEN_YEAR = 2025  # bump each January when PDOK publishes the new vintage
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_USER_AGENT = "omrt-doc-extractor/0.1 (prototype)"
BAG_3D_BASE = "https://api.3dbag.nl"

# OGC Features standard CRS URIs. The PDOK and 3D BAG OGC endpoints
# require the URI form here (not the bare "EPSG:28992").
CRS_URI_RD = "http://www.opengis.net/def/crs/EPSG/0/28992"
CRS_URI_NAP = "http://www.opengis.net/def/crs/EPSG/0/7415"

# RD New extents (EPSG:28992): X 7000..300000, Y 289000..630000.
_RD_X_RANGE = (0, 300000)
_RD_Y_RANGE = (289000, 650000)


def _detect_crs(coords: tuple[float, float]) -> CRS:
    """Heuristic: RD New if both components fall in NL projected ranges, else WGS84.

    Inputs are accepted as (x, y) in either CRS — for WGS84 we accept both
    (lat, lng) and (lng, lat) because Dutch latitudes (~50-54) never collide
    with the RD New projected ranges.
    """
    a, b = coords
    if _RD_X_RANGE[0] <= a <= _RD_X_RANGE[1] and _RD_Y_RANGE[0] <= b <= _RD_Y_RANGE[1]:
        return CRS.RD_NEW
    return CRS.WGS84


def _to_rd_and_wgs84(
    coords: tuple[float, float], crs: CRS
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return ((rd_x, rd_y), (lat, lng)) regardless of input CRS."""
    if crs == CRS.RD_NEW:
        rd = coords
        tf = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
        lng, lat = tf.transform(coords[0], coords[1])
        return rd, (lat, lng)
    # WGS84 input. Accept (lat, lng) by default; flip if it looks like (lng, lat).
    lat, lng = coords
    if abs(lat) > 90 or (3.0 <= lat <= 7.5 and 50.0 <= lng <= 54.0):
        lat, lng = lng, lat
    tf = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    rd_x, rd_y = tf.transform(lng, lat)
    return (rd_x, rd_y), (lat, lng)


def _coord_hash(rd: tuple[float, float], radius_m: int) -> str:
    """Stable hash keying the disk cache. Rounded so trivial coord noise hits cache."""
    key = f"{round(rd[0], 1)}_{round(rd[1], 1)}_{radius_m}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _cache_dir_for(rd: tuple[float, float], radius_m: int) -> Path:
    d = settings.cache_dir / "enrich" / f"{_coord_hash(rd, radius_m)}_{radius_m}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_cache(cache_dir: Path, api_name: str) -> Any | None:
    path = cache_dir / f"{api_name}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(cache_dir: Path, api_name: str, payload: Any) -> None:
    try:
        (cache_dir / f"{api_name}.json").write_text(json.dumps(payload))
    except (OSError, TypeError) as exc:
        logger.warning(f"Failed to write cache for {api_name}: {exc}")


# ---------------------------------------------------------------------
# PDOK BAG (2D buildings)
# ---------------------------------------------------------------------


def _fetch_pdok_bag(
    rd: tuple[float, float], radius_m: int, cache_dir: Path, client: httpx.Client
) -> dict[str, Any] | None:
    cached = _read_cache(cache_dir, API_PDOK_BAG)
    if cached is not None:
        return dict(cached)
    bbox = (rd[0] - radius_m, rd[1] - radius_m, rd[0] + radius_m, rd[1] + radius_m)
    url = f"{PDOK_BAG_BASE}/collections/pand/items"
    params: dict[str, str | int] = {
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "bbox-crs": CRS_URI_RD,
        "crs": CRS_URI_RD,
        "limit": 1000,
        "f": "json",
    }
    try:
        r = client.get(url, params=params, timeout=30.0)
    except httpx.HTTPError as exc:
        logger.warning(f"PDOK BAG network error: {exc}")
        return None
    if r.status_code != 200:
        logger.warning(f"PDOK BAG returned HTTP {r.status_code}")
        return None
    try:
        payload: dict[str, Any] = r.json()
    except ValueError:
        logger.warning("PDOK BAG returned non-JSON response")
        return None
    _write_cache(cache_dir, API_PDOK_BAG, payload)
    return payload


def _summarise_bag(payload: dict[str, Any], radius_m: int) -> NearbyBuildingsSnapshot:
    """Aggregate a PDOK BAG (OGC Features) response into a NearbyBuildingsSnapshot.

    The OGC pand collection carries the building identificatie, status,
    and oorspronkelijk_bouwjaar. It does NOT carry gebruiksdoel or
    height (those live on verblijfsobject and 3D BAG respectively).
    """
    raw_features = payload.get("features")
    features: list[Any] = list(raw_features) if isinstance(raw_features, list) else []

    years: list[int] = []
    for feat in features:
        props = feat.get("properties") if isinstance(feat, dict) else None
        if not isinstance(props, dict):
            continue
        for y_key in ("oorspronkelijk_bouwjaar", "bouwjaar", "oorspronkelijkBouwjaar"):
            v = props.get(y_key)
            if isinstance(v, int):
                years.append(int(v))
                break

    return NearbyBuildingsSnapshot(
        radius_m=float(radius_m),
        count=len(features),
        dominant_uses=[],
        typical_heights_m=None,
        typical_year_built=(min(years), max(years)) if years else None,
        has_3d_bag_data=False,
    )


# ---------------------------------------------------------------------
# CBS Wijken en Buurten (buurt lookup + demographics)
# Demographics are embedded directly in the OGC buurten features —
# no separate CBS OData call required.
# ---------------------------------------------------------------------


def _fetch_buurt_for_point(
    rd: tuple[float, float], cache_dir: Path, client: httpx.Client
) -> tuple[str | None, dict[str, Any] | None]:
    """Look up the CBS buurt containing the project centroid.

    Uses the PDOK wijken-en-buurten-2025 OGC collection with a 1 m
    point-bbox. Returns (buurtcode, properties_dict) so the caller can
    extract demographics directly from the same feature — no second
    CBS OData request needed.

    Returns (None, None) on any failure.
    """
    cached = _read_cache(cache_dir, "pdok_buurt")
    if cached is None:
        bbox = (rd[0] - 1, rd[1] - 1, rd[0] + 1, rd[1] + 1)
        url = f"{PDOK_WIJKENBUURTEN_BASE}/collections/buurten/items"
        params: dict[str, str | int] = {
            "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "bbox-crs": CRS_URI_RD,
            "crs": CRS_URI_RD,
            "limit": 5,
            "f": "json",
        }
        try:
            r = client.get(url, params=params, timeout=30.0)
        except httpx.HTTPError as exc:
            logger.warning(f"PDOK wijkenbuurten network error: {exc}")
            return None, None
        if r.status_code != 200:
            logger.warning(f"PDOK wijkenbuurten returned HTTP {r.status_code}")
            return None, None
        try:
            cached = r.json()
        except ValueError:
            logger.warning("PDOK wijkenbuurten returned non-JSON")
            return None, None
        _write_cache(cache_dir, "pdok_buurt", cached)

    features = cached.get("features") if isinstance(cached.get("features"), list) else []
    for feat in features:
        props = feat.get("properties") if isinstance(feat, dict) else None
        if not isinstance(props, dict):
            continue
        buurtcode = props.get("buurtcode")
        if isinstance(buurtcode, str) and buurtcode:
            return buurtcode, props
    return None, None


def _summarise_buurt(buurt_code: str, props: dict[str, Any]) -> NeighbourhoodDemographics | None:
    """Build NeighbourhoodDemographics from a 2025 buurten feature's properties.

    Available keys (confirmed from live API, May 2026):
      aantal_inwoners, aantal_huishoudens, gemiddelde_huishoudsgrootte,
      percentage_personen_0_tot_15_jaar, ..._15_tot_25_jaar,
      ..._25_tot_45_jaar, ..._45_tot_65_jaar, ..._65_jaar_en_ouder
      (no raw median_age field in the 2025 dataset).
    """

    def _num(*keys: str) -> float | None:
        for k in keys:
            v = props.get(k)
            if isinstance(v, int | float):
                return float(v)
        return None

    pop = _num("aantal_inwoners")
    hh = _num("aantal_huishoudens")
    avg = _num("gemiddelde_huishoudsgrootte")

    # Approximate median age from percentage age bands using band midpoints.
    # Bands: 0-15 (mid=7.5), 15-25 (mid=20), 25-45 (mid=35),
    #        45-65 (mid=55), 65+ (mid=75 assumed).
    band_midpoints = [
        ("percentage_personen_0_tot_15_jaar", 7.5),
        ("percentage_personen_15_tot_25_jaar", 20.0),
        ("percentage_personen_25_tot_45_jaar", 35.0),
        ("percentage_personen_45_tot_65_jaar", 55.0),
        ("percentage_personen_65_jaar_en_ouder", 75.0),
    ]
    weighted_sum = 0.0
    total_pct = 0.0
    for key, midpoint in band_midpoints:
        pct = _num(key)
        if pct is not None:
            weighted_sum += pct * midpoint
            total_pct += pct
    median_age = round(weighted_sum / total_pct, 1) if total_pct > 0 else None

    return NeighbourhoodDemographics(
        buurt_code=buurt_code,
        population=int(pop) if pop is not None else None,
        household_count=int(hh) if hh is not None else None,
        average_household_size=avg,
        median_age=median_age,
    )


# ---------------------------------------------------------------------
# OSM Overpass
# ---------------------------------------------------------------------


def _overpass_query(wgs: tuple[float, float], radius_m: int) -> str:
    """Tight-bbox Overpass query. Without a bbox the server times out."""
    lat, lng = wgs
    # ~1 deg lat = 111000 m; lng narrower at NL latitude, approximate
    dlat = radius_m / 111000.0
    dlng = radius_m / (111000.0 * 0.6)
    south, west, north, east = lat - dlat, lng - dlng, lat + dlat, lng + dlng
    bbox = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:25];
(
  node["public_transport"="stop_position"]({bbox});
  node["railway"="tram_stop"]({bbox});
  node["railway"="station"]({bbox});
  node["highway"="bus_stop"]({bbox});
  node["station"="subway"]({bbox});
  node["amenity"~"^(school|kindergarten|university)$"]({bbox});
  node["shop"]({bbox});
  node["leisure"~"^(park|playground)$"]({bbox});
  way["leisure"~"^(park|playground)$"]({bbox});
);
out tags center;
""".strip()


def _fetch_osm(
    wgs: tuple[float, float], radius_m: int, cache_dir: Path, client: httpx.Client
) -> dict[str, Any] | None:
    cached = _read_cache(cache_dir, API_OSM)
    if cached is not None:
        return dict(cached)
    query = _overpass_query(wgs, radius_m)
    try:
        r = client.post(
            OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": OVERPASS_USER_AGENT, "Accept": "application/json"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        logger.warning(f"Overpass network error: {exc}")
        return None
    if r.status_code != 200:
        logger.warning(f"Overpass returned HTTP {r.status_code}")
        return None
    try:
        payload: dict[str, Any] = r.json()
    except ValueError:
        logger.warning("Overpass returned non-JSON")
        return None
    _write_cache(cache_dir, API_OSM, payload)
    return payload


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat1, lng1 = radians(a[0]), radians(a[1])
    lat2, lng2 = radians(b[0]), radians(b[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def _summarise_osm(
    payload: dict[str, Any], wgs: tuple[float, float]
) -> tuple[TransitAccess, dict[str, int]]:
    elements = payload.get("elements", []) if isinstance(payload, dict) else []

    tram: list[float] = []
    metro: list[float] = []
    train: list[float] = []
    bus: list[float] = []
    amenities: Counter[str] = Counter()

    for el in elements:
        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        lat = el.get("lat")
        lng = el.get("lon")
        if lat is None or lng is None:
            center = el.get("center") or {}
            lat = center.get("lat")
            lng = center.get("lon")
        if not isinstance(lat, int | float) or not isinstance(lng, int | float):
            continue
        d = _haversine_m(wgs, (float(lat), float(lng)))

        if tags.get("railway") == "tram_stop":
            tram.append(d)
        if tags.get("railway") == "station":
            train.append(d)
        if tags.get("station") == "subway" or tags.get("subway") == "yes":
            metro.append(d)
        if tags.get("highway") == "bus_stop":
            bus.append(d)

        amenity = tags.get("amenity")
        if isinstance(amenity, str):
            amenities[amenity] += 1
        shop = tags.get("shop")
        if isinstance(shop, str):
            amenities[f"shop_{shop}"] += 1
        leisure = tags.get("leisure")
        if isinstance(leisure, str) and leisure in {"park", "playground"}:
            amenities[leisure] += 1

    transit = TransitAccess(
        nearest_tram_m=min(tram) if tram else None,
        nearest_metro_m=min(metro) if metro else None,
        nearest_train_m=min(train) if train else None,
        nearest_bus_m=min(bus) if bus else None,
    )
    return transit, dict(amenities)


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------


def enrich_geo(
    location: ProjectLocation | tuple[float, float],
    radius_m: int = settings.geo_buffer_radius_m,
    crs: CRS | None = None,
    client: httpx.Client | None = None,
) -> GeoContext:
    """Run the geo enrichment for one project centroid.

    Accepts either a ProjectLocation (preferred; carries both RD and WGS84
    if already populated) or a bare (x, y) tuple in either CRS. When the
    CRS isn't given for a bare tuple it's auto-detected from value ranges.

    Returns a GeoContext with whatever data the reachable APIs returned.
    Failed APIs are listed in data_sources_failed; the pipeline is
    expected to continue on partial data.
    """
    # Resolve coordinates in both projections.
    if isinstance(location, ProjectLocation):
        if location.centroid_rd is not None:
            rd, wgs = _to_rd_and_wgs84(location.centroid_rd, CRS.RD_NEW)
        elif location.centroid_wgs84 is not None:
            rd, wgs = _to_rd_and_wgs84(location.centroid_wgs84, CRS.WGS84)
        else:
            logger.error("ProjectLocation has neither centroid_rd nor centroid_wgs84")
            return GeoContext(data_sources_failed=[API_PDOK_BAG, API_CBS, API_OSM])
    else:
        resolved_crs = crs or _detect_crs(location)
        rd, wgs = _to_rd_and_wgs84(location, resolved_crs)

    cache_dir = _cache_dir_for(rd, radius_m)
    used: list[str] = []
    failed: list[str] = []

    owned_client = client is None
    http = client or httpx.Client()

    try:
        # PDOK BAG — 2D building footprints and build years.
        bag_payload = _fetch_pdok_bag(rd, radius_m, cache_dir, http)
        nearby_buildings: NearbyBuildingsSnapshot | None = None
        if bag_payload is not None:
            try:
                nearby_buildings = _summarise_bag(bag_payload, radius_m)
                used.append(API_PDOK_BAG)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(f"PDOK BAG parsing failed: {exc}")
                failed.append(API_PDOK_BAG)
        else:
            failed.append(API_PDOK_BAG)

        # CBS Wijken en Buurten — buurt lookup + demographics in one OGC call.
        # The 2025 buurten features carry stats directly; no CBS OData needed.
        demographics: NeighbourhoodDemographics | None = None
        buurt_code, buurt_props = _fetch_buurt_for_point(rd, cache_dir, http)
        if buurt_code and buurt_props:
            try:
                demographics = _summarise_buurt(buurt_code, buurt_props)
                if demographics is not None:
                    used.append(API_CBS)
                else:
                    failed.append(API_CBS)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(f"CBS buurt parsing failed: {exc}")
                failed.append(API_CBS)
        else:
            logger.info("Skipping CBS: no buurt found for centroid")
            failed.append(API_CBS)

        # OSM Overpass — transit stops and amenities. Independent of BAG/CBS.
        osm_payload = _fetch_osm(wgs, radius_m, cache_dir, http)
        transit: TransitAccess | None = None
        amenities: dict[str, int] = {}
        if osm_payload is not None:
            try:
                transit, amenities = _summarise_osm(osm_payload, wgs)
                used.append(API_OSM)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(f"Overpass parsing failed: {exc}")
                failed.append(API_OSM)
        else:
            failed.append(API_OSM)
    finally:
        if owned_client:
            http.close()

    # 3D BAG context buildings (Stage 4c). Independent of the 2D BAG above;
    # used by the massing visualisation to place variants in real urban
    # context. Failure here doesn't degrade anything else.
    owned_3d_client = client is None
    http_3d = client or httpx.Client()
    try:
        snapshot_3d = enrich_3d_bag(
            ProjectLocation(municipality="", centroid_rd=rd),
            radius_m=radius_m,
            client=http_3d,
        )
    finally:
        if owned_3d_client:
            http_3d.close()

    if snapshot_3d.has_3d_bag_data:
        used.append(API_3D_BAG)
        # Prefer the 3D snapshot over the 2D one when both succeed: it
        # carries the same aggregate fields plus the CityJSON cache that
        # the massing stage needs.
        nearby_buildings = snapshot_3d
    else:
        failed.append(API_3D_BAG)

    return GeoContext(
        nearby_buildings=nearby_buildings,
        demographics=demographics,
        transit=transit,
        nearby_amenities=amenities,
        data_sources_used=used,
        data_sources_failed=failed,
    )


# ---------------------------------------------------------------------
# 3D BAG (Stage 4c)
# ---------------------------------------------------------------------


def _3d_bag_cache_path(rd: tuple[float, float], radius_m: int, lod: str) -> Path:
    """Cache CityJSON under data/cache/3dbag/<hash>_<radius>_lod<lod>.cityjson."""
    cache_dir = settings.cache_dir / "3dbag"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{_coord_hash(rd, radius_m)}_{radius_m}_lod{lod}.cityjson"


def _iter_3d_bag_buildings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield per-building attribute dicts from a 3D BAG response.

    Tolerant of two shapes:
    - OGC API FeatureCollection: {"features": [{"properties": {...}}, ...]}
    - CityJSON / CityJSONSeq: {"CityObjects": {"<id>": {"attributes": {...}}}}
      or features wrapping a per-feature CityJSON under "feature".
    """
    out: list[dict[str, Any]] = []

    features = payload.get("features")
    if isinstance(features, list):
        for feat in features:
            if not isinstance(feat, dict):
                continue
            props = feat.get("properties")
            if isinstance(props, dict):
                out.append(props)
                continue
            inner = feat.get("feature")
            if isinstance(inner, dict):
                cobjs = inner.get("CityObjects")
                if isinstance(cobjs, dict):
                    for obj in cobjs.values():
                        attrs = obj.get("attributes") if isinstance(obj, dict) else None
                        if isinstance(attrs, dict):
                            out.append(attrs)

    cobjs = payload.get("CityObjects")
    if isinstance(cobjs, dict):
        for obj in cobjs.values():
            attrs = obj.get("attributes") if isinstance(obj, dict) else None
            if isinstance(attrs, dict):
                out.append(attrs)

    return out


def _summarise_3d_bag(payload: dict[str, Any], radius_m: int) -> NearbyBuildingsSnapshot:
    """Aggregate 3D BAG attributes into a NearbyBuildingsSnapshot."""
    buildings = _iter_3d_bag_buildings(payload)

    uses: Counter[str] = Counter()
    heights: list[float] = []
    years: list[int] = []
    for attrs in buildings:
        for u_key in ("b3_function", "gebruiksdoel", "gebruiksdoelen", "function"):
            v = attrs.get(u_key)
            if isinstance(v, list):
                uses.update(str(g) for g in v if g)
                break
            if isinstance(v, str) and v:
                uses[v] += 1
                break
        # 3D BAG roof height is absolute (NAP); subtract maaiveld to get
        # building height above ground. Fall back to absolute value if
        # maaiveld is missing.
        roof = None
        for h_key in ("b3_h_dak_50p", "b3_h_dak_max", "hoogte", "height"):
            v = attrs.get(h_key)
            if isinstance(v, int | float):
                roof = float(v)
                break
        if roof is not None:
            maaiveld = attrs.get("b3_h_maaiveld")
            if isinstance(maaiveld, int | float):
                heights.append(roof - float(maaiveld))
            else:
                heights.append(roof)
        for y_key in (
            "oorspronkelijk_bouwjaar",
            "oorspronkelijkbouwjaar",
            "bouwjaar",
            "year_built",
        ):
            v = attrs.get(y_key)
            if isinstance(v, int):
                years.append(int(v))
                break

    return NearbyBuildingsSnapshot(
        radius_m=float(radius_m),
        count=len(buildings),
        dominant_uses=[u for u, _ in uses.most_common(5)],
        typical_heights_m=(min(heights), max(heights)) if heights else None,
        typical_year_built=(min(years), max(years)) if years else None,
        has_3d_bag_data=len(buildings) > 0,
    )


def enrich_3d_bag(
    location: ProjectLocation | tuple[float, float],
    radius_m: int = 1000,
    lod: str = "1.2",
    crs: CRS | None = None,
    client: httpx.Client | None = None,
) -> NearbyBuildingsSnapshot:
    """Query the 3D BAG API for buildings within ``radius_m`` of the centroid.

    LoD 1.2 (block models) is the default because the response is smaller
    and the massing visualisation only needs context volumes. LoD 2.2
    (roof shapes) is available via the ``lod`` parameter.

    Saves the raw response to ``data/cache/3dbag/<hash>_<radius>_lod<lod>.cityjson``
    so the massing stage can load it directly.

    Degrades gracefully: on network error, non-200 response, or empty
    response, returns ``NearbyBuildingsSnapshot(count=0, has_3d_bag_data=False)``.
    The caller is expected to add ``API_3D_BAG`` to
    ``GeoContext.data_sources_failed`` in that case.
    """
    if isinstance(location, ProjectLocation):
        if location.centroid_rd is not None:
            rd, _ = _to_rd_and_wgs84(location.centroid_rd, CRS.RD_NEW)
        elif location.centroid_wgs84 is not None:
            rd, _ = _to_rd_and_wgs84(location.centroid_wgs84, CRS.WGS84)
        else:
            logger.error("ProjectLocation has neither centroid_rd nor centroid_wgs84")
            return NearbyBuildingsSnapshot(
                radius_m=float(radius_m), count=0, dominant_uses=[], has_3d_bag_data=False
            )
    else:
        resolved_crs = crs or _detect_crs(location)
        rd, _ = _to_rd_and_wgs84(location, resolved_crs)

    cache_path = _3d_bag_cache_path(rd, radius_m, lod)
    payload: dict[str, Any] | None = None
    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            payload = None

    owned_client = client is None
    http = client or httpx.Client()
    try:
        if payload is None:
            bbox = (rd[0] - radius_m, rd[1] - radius_m, rd[0] + radius_m, rd[1] + radius_m)
            url = f"{BAG_3D_BASE}/collections/pand/items"
            params: dict[str, str | int] = {
                "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                # 3DBAG API is not OGC-compliant — no bbox-crs or crs params accepted.
                # bbox must be in EPSG:28992 (RD New) X,Y. Only supported CRS is EPSG:7415.
                # Heights come from b3_h_dak_50p / b3_h_maaiveld attributes.
                "limit": 1000,
                "f": "json",
            }
            try:
                r = http.get(url, params=params, timeout=60.0)
            except httpx.HTTPError as exc:
                logger.warning(f"3D BAG network error: {exc}")
                return NearbyBuildingsSnapshot(
                    radius_m=float(radius_m), count=0, dominant_uses=[], has_3d_bag_data=False
                )
            if r.status_code != 200:
                logger.warning(f"3D BAG returned HTTP {r.status_code}")
                return NearbyBuildingsSnapshot(
                    radius_m=float(radius_m), count=0, dominant_uses=[], has_3d_bag_data=False
                )
            try:
                payload = r.json()
            except ValueError:
                logger.warning("3D BAG returned non-JSON")
                return NearbyBuildingsSnapshot(
                    radius_m=float(radius_m), count=0, dominant_uses=[], has_3d_bag_data=False
                )
            try:
                cache_path.write_text(json.dumps(payload))
            except (OSError, TypeError) as exc:
                logger.warning(f"Failed to write 3D BAG cache: {exc}")
    finally:
        if owned_client:
            http.close()

    try:
        return _summarise_3d_bag(payload, radius_m)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning(f"3D BAG parsing failed: {exc}")
        return NearbyBuildingsSnapshot(
            radius_m=float(radius_m), count=0, dominant_uses=[], has_3d_bag_data=False
        )
