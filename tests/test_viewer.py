"""Smoke tests for viewer panel functions.

Streamlit rendering itself is not exercised — only that the panel
helpers import and run without raising on representative input dicts.
Streamlit's runtime is monkeypatched with a no-op stub so the calls
do not require an active streamlit script context.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_streamlit(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace streamlit with a permissive mock for the duration of the test."""
    stub = MagicMock(name="streamlit")
    # st.columns(n) -> list of context-manager-capable mocks
    def _columns(n: int | list[int]) -> list[MagicMock]:
        count = n if isinstance(n, int) else len(n)
        return [MagicMock(name=f"col{i}") for i in range(count)]

    stub.columns.side_effect = _columns
    stub.expander.return_value.__enter__ = lambda self: self
    stub.expander.return_value.__exit__ = lambda self, *a: False
    monkeypatch.setitem(sys.modules, "streamlit", stub)
    # Force re-import so the viewer binds to the stub
    sys.modules.pop("viewer.streamlit_app", None)
    return stub


def _sample_programme() -> dict[str, Any]:
    return {
        "target_total_gfa_m2": 151400.0,
        "target_total_gfa_m2_range": [145000.0, 151400.0],
        "use_split": {
            "residential_m2": 120000.0,
            "productive_m2": 12000.0,
            "office_m2": 9000.0,
            "retail_horeca_m2": 3000.0,
            "cultural_m2": 3500.0,
            "social_m2": 3900.0,
            "other_m2": 0.0,
            "normalised_from_pct": False,
            "rationale": "Use split anchored in the explicit caps." * 10,
        },
        "unit_mix": [
            {
                "tenure": "sociale_huur",
                "size_band": "30_60m2",
                "fraction_of_total_dwellings": 0.18,
                "target_count_range": [280, 310],
            },
            {
                "tenure": "middenhuur",
                "size_band": "60_90m2",
                "fraction_of_total_dwellings": 0.20,
                "target_count_range": [310, 340],
            },
            {
                "tenure": "vrije_sector_huur",
                "size_band": "over_90m2",
                "fraction_of_total_dwellings": 0.12,
                "target_count_range": [180, 210],
            },
        ],
        "target_dwelling_count": 1630,
        "total_dwelling_count_range": [1540, 1720],
        "parking_demand": 595.0,
        "reasoning_trace": [
            {
                "step": 1,
                "decision": "Set total GFA at 151,400 m².",
                "evidence": "[max_bvo_total_draka] caps total; [cbs_demographics: households 2135] confirms scale.",
                "confidence_in_step": 0.9,
            },
            "Plain-string step is also legal in the schema.",
        ],
        "provenance": {
            "source_type": "inferred",
            "inferred_from": ["max_bvo_total_draka", "cbs_demographics"],
        },
        "confidence": {"score": 0.85, "reasons": [], "flags": []},
    }


def _sample_geo() -> dict[str, Any]:
    return {
        "data_sources_used": ["pdok_bag", "cbs_demographics", "osm_overpass"],
        "data_sources_failed": ["pdok_3d_bag"],
        "nearby_buildings": {
            "radius_m": 1000.0,
            "count": 1000,
            "dominant_uses": [],
            "typical_heights_m": None,
            "typical_year_built": [1888, 2022],
            "has_3d_bag_data": False,
        },
        "demographics": {
            "buurt_code": "BU0363NL03",
            "population": 4075,
            "household_count": 2135,
            "average_household_size": 1.9,
            "median_age": 39.4,
        },
        "transit": {
            "nearest_tram_m": None,
            "nearest_metro_m": 377.4,
            "nearest_train_m": 377.4,
            "nearest_bus_m": 75.8,
        },
        "nearby_amenities": {
            "school": 6,
            "shop_supermarket": 6,
            "playground": 35,
            "park": 10,
            "cafe": 1,
        },
    }


def test_render_programme_panel_smoke(stub_streamlit: MagicMock) -> None:
    from viewer.streamlit_app import render_programme_panel

    render_programme_panel(_sample_programme())
    assert stub_streamlit.markdown.called


def test_render_neighbourhood_panel_smoke(stub_streamlit: MagicMock) -> None:
    from viewer.streamlit_app import render_neighbourhood_panel

    render_neighbourhood_panel(_sample_geo())
    assert stub_streamlit.markdown.called


def test_render_programme_panel_handles_missing_optional_fields(
    stub_streamlit: MagicMock,
) -> None:
    from viewer.streamlit_app import render_programme_panel

    minimal = {
        "target_total_gfa_m2": 10000.0,
        "use_split": {
            "residential_m2": 10000.0,
            "productive_m2": 0.0,
            "office_m2": 0.0,
            "retail_horeca_m2": 0.0,
            "cultural_m2": 0.0,
            "social_m2": 0.0,
            "other_m2": 0.0,
            "normalised_from_pct": False,
            "rationale": "short.",
        },
        "unit_mix": [],
        "reasoning_trace": [],
    }
    render_programme_panel(minimal)


def test_render_neighbourhood_panel_handles_empty(stub_streamlit: MagicMock) -> None:
    from viewer.streamlit_app import render_neighbourhood_panel

    render_neighbourhood_panel({"data_sources_used": [], "data_sources_failed": []})
