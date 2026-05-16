"""Tests for the Stage 4 geo enrichment pipeline.

All external APIs are mocked with respx; no live calls. Tests assert
graceful degradation and shape, never specific real-world values.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from omrt_extractor import enrich as enrich_mod
from omrt_extractor.enrich import (
    API_3D_BAG,
    API_CBS,
    API_OSM,
    API_PDOK_BAG,
    enrich_3d_bag,
    enrich_geo,
)
from omrt_extractor.schemas import CRS, GeoContext, NearbyBuildingsSnapshot, ProjectLocation

# Project centroid roughly inside Amsterdam, used as a generic NL point.
# (Structural tests only; the actual coordinate is irrelevant because all
# APIs are mocked.)
RD_CENTROID = (122000.0, 487000.0)
WGS_CENTROID = (52.37, 4.90)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the enrichment cache to a temp directory per test."""
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(enrich_mod.settings, "project_root", tmp_path, raising=False)
    return cache_root


def _bag_response() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "identificatie": "0363100012345678",
                    "oorspronkelijk_bouwjaar": 1965,
                    "status": "Pand in gebruik",
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "identificatie": "0363100012345679",
                    "oorspronkelijk_bouwjaar": 1998,
                    "status": "Pand in gebruik",
                },
            },
        ],
    }


def _buurt_response() -> dict:
    """Full 2025 buurten properties — demographics embedded directly in the feature."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "buurtcode": "BU03630000",
                    "buurtnaam": "Test Buurt",
                    "aantal_inwoners": 4321,
                    "aantal_huishoudens": 2100,
                    "gemiddelde_huishoudsgrootte": 2.05,
                    "percentage_personen_0_tot_15_jaar": 15.0,
                    "percentage_personen_15_tot_25_jaar": 12.0,
                    "percentage_personen_25_tot_45_jaar": 28.0,
                    "percentage_personen_45_tot_65_jaar": 25.0,
                    "percentage_personen_65_jaar_en_ouder": 20.0,
                },
            }
        ],
    }


def _mock_buurt_ok() -> None:
    respx.get(
        f"{enrich_mod.PDOK_WIJKENBUURTEN_BASE}/collections/buurten/items"
    ).mock(return_value=httpx.Response(200, json=_buurt_response()))


def _3d_bag_response() -> dict:
    # Heights are NAP absolute; subtract maaiveld for the building height.
    # Building heights here: 14.2-0.0=14.2, 32.5-0.5=32.0, 21.0-1.0=20.0
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "b3_function": "wonen",
                    "b3_h_dak_50p": 14.2,
                    "b3_h_maaiveld": 0.0,
                    "oorspronkelijk_bouwjaar": 1972,
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "b3_function": "wonen",
                    "b3_h_dak_50p": 32.5,
                    "b3_h_maaiveld": 0.5,
                    "oorspronkelijk_bouwjaar": 2005,
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "b3_function": "kantoor",
                    "b3_h_dak_50p": 21.0,
                    "b3_h_maaiveld": 1.0,
                    "oorspronkelijk_bouwjaar": 1990,
                },
            },
        ],
    }


def _mock_3d_bag_ok() -> None:
    respx.get(f"{enrich_mod.BAG_3D_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json=_3d_bag_response())
    )


def _mock_3d_bag_down() -> None:
    respx.get(f"{enrich_mod.BAG_3D_BASE}/collections/pand/items").mock(
        side_effect=httpx.ConnectError("boom")
    )


def _osm_response() -> dict:
    return {
        "elements": [
            {"type": "node", "lat": 52.371, "lon": 4.901, "tags": {"railway": "tram_stop"}},
            {"type": "node", "lat": 52.369, "lon": 4.899, "tags": {"highway": "bus_stop"}},
            {"type": "node", "lat": 52.372, "lon": 4.902, "tags": {"amenity": "school"}},
            {"type": "node", "lat": 52.370, "lon": 4.898, "tags": {"shop": "supermarket"}},
        ]
    }


@respx.mock
def test_enrich_geo_happy_path() -> None:
    bag = respx.get(f"{enrich_mod.PDOK_BAG_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json=_bag_response())
    )
    osm = respx.post(enrich_mod.OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_osm_response())
    )
    _mock_buurt_ok()
    _mock_3d_bag_ok()

    ctx = enrich_geo(RD_CENTROID, radius_m=500, crs=CRS.RD_NEW)

    assert bag.called
    assert osm.called

    assert isinstance(ctx, GeoContext)
    assert set(ctx.data_sources_used) >= {API_PDOK_BAG, API_CBS, API_OSM, API_3D_BAG}
    assert ctx.data_sources_failed == []

    # 3D BAG snapshot supersedes the 2D one when both succeed.
    assert ctx.nearby_buildings is not None
    assert ctx.nearby_buildings.has_3d_bag_data is True
    assert ctx.nearby_buildings.count == 3
    assert "wonen" in ctx.nearby_buildings.dominant_uses
    # Heights are roof - maaiveld: 14.2-0.0, 32.5-0.5, 21.0-1.0 -> (14.2, 32.0)
    assert ctx.nearby_buildings.typical_heights_m == (14.2, 32.0)

    # Demographics come directly from the buurten OGC feature.
    assert ctx.demographics is not None
    assert ctx.demographics.buurt_code == "BU03630000"
    assert ctx.demographics.population == 4321
    assert ctx.demographics.household_count == 2100
    assert ctx.demographics.average_household_size == 2.05
    assert ctx.demographics.median_age is not None  # weighted from age bands

    assert ctx.transit is not None
    assert ctx.transit.nearest_tram_m is not None
    assert ctx.transit.nearest_bus_m is not None
    assert ctx.nearby_amenities.get("school") == 1
    assert ctx.nearby_amenities.get("shop_supermarket") == 1


@respx.mock
def test_enrich_geo_bag_down_continues() -> None:
    respx.get(f"{enrich_mod.PDOK_BAG_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(503)
    )
    respx.post(enrich_mod.OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_osm_response())
    )
    # Buurten also down — CBS should fail gracefully.
    respx.get(
        f"{enrich_mod.PDOK_WIJKENBUURTEN_BASE}/collections/buurten/items"
    ).mock(return_value=httpx.Response(503))
    _mock_3d_bag_down()

    ctx = enrich_geo(RD_CENTROID, radius_m=500, crs=CRS.RD_NEW)

    assert API_PDOK_BAG in ctx.data_sources_failed
    # CBS fails because the buurten lookup returned 503.
    assert API_CBS in ctx.data_sources_failed
    assert API_3D_BAG in ctx.data_sources_failed
    assert API_OSM in ctx.data_sources_used
    assert ctx.nearby_buildings is None
    assert ctx.demographics is None
    assert ctx.transit is not None


@respx.mock
def test_enrich_geo_all_apis_down() -> None:
    respx.get(f"{enrich_mod.PDOK_BAG_BASE}/collections/pand/items").mock(
        side_effect=httpx.ConnectError("boom")
    )
    respx.post(enrich_mod.OVERPASS_URL).mock(side_effect=httpx.ConnectError("boom"))
    respx.get(
        f"{enrich_mod.PDOK_WIJKENBUURTEN_BASE}/collections/buurten/items"
    ).mock(side_effect=httpx.ConnectError("boom"))
    _mock_3d_bag_down()

    ctx = enrich_geo(WGS_CENTROID, radius_m=500, crs=CRS.WGS84)

    assert set(ctx.data_sources_failed) >= {API_PDOK_BAG, API_CBS, API_OSM, API_3D_BAG}
    assert ctx.data_sources_used == []
    assert ctx.nearby_buildings is None
    assert ctx.demographics is None
    assert ctx.transit is None


@respx.mock
def test_enrich_geo_accepts_project_location() -> None:
    respx.get(f"{enrich_mod.PDOK_BAG_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json=_bag_response())
    )
    respx.post(enrich_mod.OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_osm_response())
    )
    _mock_buurt_ok()
    _mock_3d_bag_ok()

    loc = ProjectLocation(municipality="TestStad", centroid_rd=RD_CENTROID)
    ctx = enrich_geo(loc, radius_m=300)

    assert API_PDOK_BAG in ctx.data_sources_used
    assert API_CBS in ctx.data_sources_used


def test_detect_crs() -> None:
    assert enrich_mod._detect_crs(RD_CENTROID) == CRS.RD_NEW
    assert enrich_mod._detect_crs(WGS_CENTROID) == CRS.WGS84


@respx.mock
def test_cache_hit_skips_network() -> None:
    route = respx.get(f"{enrich_mod.PDOK_BAG_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json=_bag_response())
    )
    respx.post(enrich_mod.OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_osm_response())
    )
    _mock_buurt_ok()
    _mock_3d_bag_ok()

    enrich_geo(RD_CENTROID, radius_m=500, crs=CRS.RD_NEW)
    first_call_count = route.call_count
    enrich_geo(RD_CENTROID, radius_m=500, crs=CRS.RD_NEW)
    assert route.call_count == first_call_count, "Second call should hit disk cache"


# ---------------------------------------------------------------------
# 3D BAG (Stage 4c)
# ---------------------------------------------------------------------


@respx.mock
def test_enrich_3d_bag_aggregates() -> None:
    route = respx.get(f"{enrich_mod.BAG_3D_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json=_3d_bag_response())
    )

    snap = enrich_3d_bag(
        ProjectLocation(municipality="TestStad", centroid_rd=RD_CENTROID),
        radius_m=500,
    )

    assert route.called
    assert isinstance(snap, NearbyBuildingsSnapshot)
    assert snap.has_3d_bag_data is True
    assert snap.count == 3
    # Heights are roof - maaiveld: (14.2-0.0, 32.5-0.5, 21.0-1.0)
    assert snap.typical_heights_m == (14.2, 32.0)
    assert snap.typical_year_built == (1972, 2005)
    assert "wonen" in snap.dominant_uses
    # 'wonen' appears twice, 'kantoor' once; 'wonen' should rank first
    assert snap.dominant_uses[0] == "wonen"


@respx.mock
def test_enrich_3d_bag_unreachable_returns_empty() -> None:
    respx.get(f"{enrich_mod.BAG_3D_BASE}/collections/pand/items").mock(
        side_effect=httpx.ConnectError("boom")
    )

    snap = enrich_3d_bag(RD_CENTROID, radius_m=500, crs=CRS.RD_NEW)

    assert snap.count == 0
    assert snap.has_3d_bag_data is False
    assert snap.dominant_uses == []


@respx.mock
def test_enrich_3d_bag_empty_response_marks_no_data() -> None:
    respx.get(f"{enrich_mod.BAG_3D_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    snap = enrich_3d_bag(RD_CENTROID, radius_m=500, crs=CRS.RD_NEW)

    assert snap.count == 0
    assert snap.has_3d_bag_data is False


@respx.mock
def test_enrich_3d_bag_writes_cityjson_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enrich_mod.settings, "project_root", tmp_path, raising=False)
    respx.get(f"{enrich_mod.BAG_3D_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json=_3d_bag_response())
    )

    enrich_3d_bag(RD_CENTROID, radius_m=500, lod="1.2", crs=CRS.RD_NEW)

    cache_dir = enrich_mod.settings.cache_dir / "3dbag"
    files = list(cache_dir.glob("*_500_lod1.2.cityjson"))
    assert len(files) == 1, f"Expected one cached CityJSON, got {files}"


@respx.mock
def test_enrich_3d_bag_handles_cityjson_shape() -> None:
    payload = {
        "CityObjects": {
            "NL.IMBAG.Pand.001": {
                "attributes": {
                    "b3_function": "wonen",
                    "b3_h_dak_50p": 9.5,
                    "oorspronkelijkbouwjaar": 1955,
                }
            },
            "NL.IMBAG.Pand.002": {
                "attributes": {
                    "b3_function": "industrie",
                    "b3_h_dak_50p": 18.0,
                    "oorspronkelijkbouwjaar": 1980,
                }
            },
        }
    }
    respx.get(f"{enrich_mod.BAG_3D_BASE}/collections/pand/items").mock(
        return_value=httpx.Response(200, json=payload)
    )

    snap = enrich_3d_bag(RD_CENTROID, radius_m=500, crs=CRS.RD_NEW)

    assert snap.count == 2
    assert snap.has_3d_bag_data is True
    assert snap.typical_heights_m == (9.5, 18.0)
