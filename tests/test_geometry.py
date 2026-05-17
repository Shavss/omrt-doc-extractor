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


def test_no_output_polygon_was_degenerated_by_autoclose(geometry: Geometry) -> None:
    """The auto-close vertex collapse must not strip corners off a polygon.

    The bug being guarded against: a rectangle (4 well-separated corners)
    whose ring listing happens to put two corners within the auto-close
    threshold gets collapsed into a triangle. We assert no labelled output
    polygon shows that signature (original_unique_count >= 4 AND
    final_unique_count < 4). Source triangles (original < 4) are not the
    target of this check — see the next test.
    """
    if geometry.status == "manual_input_required":
        pytest.skip(f"Parser fell back to manual input: {geometry.reason}")

    for grp_name, group in (
        ("bouwvlakken", geometry.bouwvlakken),
        ("constraint_zones", geometry.constraint_zones),
    ):
        for i, lp in enumerate(group):
            orig = lp.original_unique_count
            final = lp.final_unique_count
            # Both fields must be set by the parser for this assertion to
            # be meaningful; skip-by-asserting-presence keeps this honest.
            assert orig is not None, f"{grp_name}[{i}] missing original_unique_count"
            assert final is not None, f"{grp_name}[{i}] missing final_unique_count"
            assert not (orig >= 4 and final < 4), (
                f"{grp_name}[{i}] was degenerated by auto-close: "
                f"original_unique_count={orig}, final_unique_count={final}"
            )


def test_polygons_below_4_unique_points_only_if_originally_triangular(
    geometry: Geometry,
) -> None:
    """If a polygon has fewer than 4 corners after auto-close, it had fewer to begin with.

    Complements the previous test: any labelled output polygon whose
    final_unique_count is below 4 must have already been triangular in
    the source drawing (original_unique_count also below 4). This rules
    out the case where auto-close silently reduced corner count without
    being caught.
    """
    if geometry.status == "manual_input_required":
        pytest.skip(f"Parser fell back to manual input: {geometry.reason}")

    for grp_name, group in (
        ("bouwvlakken", geometry.bouwvlakken),
        ("constraint_zones", geometry.constraint_zones),
    ):
        for i, lp in enumerate(group):
            final = lp.final_unique_count
            orig = lp.original_unique_count
            if final is None or final >= 4:
                continue
            assert orig is not None and orig < 4, (
                f"{grp_name}[{i}] has final_unique_count={final} but "
                f"original_unique_count={orig} — auto-close lost corners"
            )


def test_missing_pdf_returns_manual_input() -> None:
    g = parse_kaveltekening(Path("/nonexistent/does_not_exist.pdf"))
    assert g.status == "manual_input_required"
    assert g.reason
