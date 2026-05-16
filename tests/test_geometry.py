"""Tests for the Stage 3 verbeelding parser.

Assertions are structural-only: a scale was discovered, at least one
polygon was extracted with non-zero area, at least one bouwvlak was
labelled. No specific code values or heights are asserted; the parser
must work on any reasonable Dutch zoning packet, so these tests must
hold on any input that resembles a real kaveltekening.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omrt_extractor.geometry import (
    Geometry,
    LabeledPolygon,
    parse_kaveltekening,
)

DRAKA_INPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "inputs" / "draka"


def _find_kaveltekening() -> Path | None:
    if not DRAKA_INPUT_DIR.is_dir():
        return None
    for p in DRAKA_INPUT_DIR.iterdir():
        if p.suffix.lower() != ".pdf":
            continue
        if "kavel" in p.name.lower() or "verbeeld" in p.name.lower():
            return p
    return None


@pytest.fixture(scope="module")
def geometry() -> Geometry:
    pdf = _find_kaveltekening()
    if pdf is None:
        pytest.skip("No kaveltekening PDF available for geometry test")
    return parse_kaveltekening(pdf)


def test_returns_geometry_model(geometry: Geometry) -> None:
    assert isinstance(geometry, Geometry)
    assert geometry.source_pdf
    assert geometry.status in {"ok", "manual_input_required"}


def test_scale_was_discovered(geometry: Geometry) -> None:
    if geometry.status == "manual_input_required":
        pytest.skip(f"Parser fell back to manual input: {geometry.reason}")
    assert geometry.scale_status in {"measure_dict", "schaal_text"}
    assert geometry.meters_per_unit is not None
    assert geometry.meters_per_unit > 0


def test_at_least_one_polygon_with_area(geometry: Geometry) -> None:
    if geometry.status == "manual_input_required":
        pytest.skip(f"Parser fell back to manual input: {geometry.reason}")
    polys: list[LabeledPolygon] = list(geometry.bouwvlakken) + list(geometry.constraint_zones)
    if geometry.plot_polygon is not None:
        # The plot polygon is a raw ring; it should have at least 4 points.
        assert len(geometry.plot_polygon) >= 4
    assert any(lp.area_m2 > 0 for lp in polys) or geometry.plot_polygon is not None


def test_at_least_one_labeled_bouwvlak(geometry: Geometry) -> None:
    if geometry.status == "manual_input_required":
        pytest.skip(f"Parser fell back to manual input: {geometry.reason}")
    assert len(geometry.bouwvlakken) >= 1
    sample = geometry.bouwvlakken[0]
    assert sample.area_m2 > 0
    # Some classified token must exist on at least one bouwvlak.
    has_any_classified = any(
        bv.height_m is not None
        or bv.bestemming_codes
        or bv.bouwaanduidingen
        or bv.function_aanduidingen
        for bv in geometry.bouwvlakken
    )
    assert has_any_classified


def test_plot_polygon_has_plausible_dimensions(geometry: Geometry) -> None:
    """Universal sanity bound on the plot bounding box.

    A city plot is bigger than a house and smaller than a city. If the scale
    is wrong by an order of magnitude (placeholder Measure dict accepted, or
    the text scale denominator misparsed), the bbox will fall outside this
    range and the test catches it. Bounds are deliberately wide so they
    apply to any reasonable Dutch zoning packet.
    """
    if geometry.status == "manual_input_required":
        pytest.skip(f"Parser fell back to manual input: {geometry.reason}")
    assert geometry.plot_polygon is not None
    xs = [p[0] for p in geometry.plot_polygon]
    ys = [p[1] for p in geometry.plot_polygon]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert 50.0 <= width <= 2000.0, f"Plot width {width:.1f} m outside 50..2000 m"
    assert 50.0 <= height <= 2000.0, f"Plot height {height:.1f} m outside 50..2000 m"


def test_missing_pdf_returns_manual_input() -> None:
    g = parse_kaveltekening(Path("/nonexistent/does_not_exist.pdf"))
    assert g.status == "manual_input_required"
    assert g.reason
