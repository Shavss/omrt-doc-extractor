"""Tests for src/omrt_extractor/reconcile.py.

Structural-only assertions per the project working agreement: never check
specific Draka values. The synthetic fixtures use plausible aanduiding
labels and round numbers to exercise the reconciliation logic.
"""

from __future__ import annotations

from omrt_extractor.geometry import Geometry, LabeledPolygon
from omrt_extractor.reconcile import (
    _is_permit_gated_deviation,
    _normalise_label,
    reconcile_heights,
)
from omrt_extractor.schemas import (
    Confidence,
    Constraints,
    KPIs,
    NumericalConstraint,
    Objective,
    ParametricFramework,
    ProgrammeProposal,
    ProjectLocation,
    ProjectMetadata,
    Provenance,
    SourceDocument,
    SourceType,
    UseSplit,
    Variables,
)


def _prov(quoted: str = "max bouwhoogte is X m") -> Provenance:
    return Provenance(
        source_type=SourceType.DOCUMENT,
        document="regels.pdf",
        page=3,
        quoted_text=quoted,
    )


def _conf(score: float = 0.95) -> Confidence:
    return Confidence(score=score)


def _square(x: float, y: float, size: float = 10.0) -> list[list[float]]:
    return [
        [x, y],
        [x + size, y],
        [x + size, y + size],
        [x, y + size],
        [x, y],
    ]


def _polygon(label: str, height_m: float | None = None) -> LabeledPolygon:
    return LabeledPolygon(
        coordinates=_square(0.0, 0.0),
        area_m2=100.0,
        bouwaanduidingen=[label],
        height_m=height_m,
        raw_labels=[f"[{label}]"],
    )


def _framework(constraints: list[NumericalConstraint]) -> ParametricFramework:
    prov = _prov()
    conf = _conf()
    return ParametricFramework(
        metadata=ProjectMetadata(
            project_name="Test",
            location=ProjectLocation(municipality="Testdam"),
            source_documents=[
                SourceDocument(
                    filename="regels.pdf",
                    document_type="regels",
                    page_count=10,
                    sha256="0" * 64,
                )
            ],
            tool_version="0.0.0",
        ),
        objective=Objective(
            statement="x", urban_intent="x", provenance=prov, confidence=conf
        ),
        constraints=Constraints(numerical=constraints),
        variables=Variables(),
        kpis=KPIs(),
        programme=ProgrammeProposal(
            target_total_gfa_m2=1.0,
            use_split=UseSplit(
                residential_m2=1.0,
                productive_m2=0,
                office_m2=0,
                retail_horeca_m2=0,
                cultural_m2=0,
                social_m2=0,
                other_m2=0,
                rationale="x",
                provenance=prov,
                confidence=conf,
            ),
            unit_mix=[],
            reasoning_trace=["x"],
            provenance=prov,
            confidence=conf,
        ),
    )


def _geometry(polys: list[LabeledPolygon]) -> Geometry:
    return Geometry(
        status="ok",
        source_pdf="kaveltekening.pdf",
        source_page=1,
        meters_per_unit=1.0,
        bouwvlakken=polys,
    )


def test_inferred_fills_missing_heights() -> None:
    constraint = NumericalConstraint(
        id="max_height_sba4",
        name="Max height sba-4",
        category="height",
        value=21.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_4"],
        provenance=_prov(),
        confidence=_conf(),
    )
    polys = [_polygon("sba-4", height_m=None) for _ in range(4)]
    fw = _framework([constraint])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)

    inferred = [f for f in findings if f.action == "inferred"]
    assert len(inferred) == 4
    assert all(p.height_m == 21.0 for p in new_geo.bouwvlakken)
    assert all(f.source_constraint_id == "max_height_sba4" for f in inferred)


def test_corrected_overwrites_with_regels_value() -> None:
    constraint = NumericalConstraint(
        id="max_height_sba1",
        name="Max height sba-1",
        category="height",
        value=45.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_1"],
        provenance=_prov(),
        confidence=_conf(),
    )
    polys = [_polygon("sba-1", height_m=60.0)]
    fw = _framework([constraint])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)

    corrected = [f for f in findings if f.action == "corrected"]
    assert len(corrected) == 1
    f = corrected[0]
    assert f.previous_height_m == 60.0
    assert f.new_height_m == 45.0
    assert new_geo.bouwvlakken[0].height_m == 45.0


def test_matched_when_within_tolerance() -> None:
    constraint = NumericalConstraint(
        id="max_height_sba2",
        name="Max height sba-2",
        category="height",
        value=30.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_2"],
        provenance=_prov(),
        confidence=_conf(),
    )
    polys = [_polygon("sba-2", height_m=30.3)]
    fw = _framework([constraint])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)

    assert len(findings) == 1
    assert findings[0].action == "matched"
    assert new_geo.bouwvlakken[0].height_m == 30.3  # untouched


def test_unmatched_when_no_polygon_carries_label() -> None:
    constraint = NumericalConstraint(
        id="max_height_sba99",
        name="Max height sba-99",
        category="height",
        value=15.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_99"],
        provenance=_prov(),
        confidence=_conf(),
    )
    polys = [_polygon("sba-1", height_m=20.0)]
    fw = _framework([constraint])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)

    unmatched = [f for f in findings if f.action == "unmatched"]
    assert len(unmatched) == 1
    assert unmatched[0].label == "sba_99"
    assert unmatched[0].polygon_index == -1
    assert new_geo.bouwvlakken[0].height_m == 20.0


def test_permit_gated_deviation_detection() -> None:
    assert _is_permit_gated_deviation(None) is False
    assert _is_permit_gated_deviation("") is False
    # Permit-gated deviations
    assert _is_permit_gated_deviation("Met omgevingsvergunning") is True
    assert (
        _is_permit_gated_deviation(
            "Met omgevingsvergunning; gemiddelde bouwhoogte op sba-1 maximaal 45 m"
        )
        is True
    )
    assert _is_permit_gated_deviation("Burgemeester kan afwijken") is True
    assert _is_permit_gated_deviation("Verhoogd met max 5 m") is True
    assert _is_permit_gated_deviation("With permit") is True
    # Pure stipulations
    assert (
        _is_permit_gated_deviation(
            "Geldt als gemiddelde over alle bouwhoogtes op gronden met sba-1"
        )
        is False
    )
    assert _is_permit_gated_deviation("Gemeten vanaf peil") is False
    # Unknown -> conservative skip
    assert _is_permit_gated_deviation("Some unknown phrase") is True


def test_average_stipulation_is_reconciled() -> None:
    stipulation = NumericalConstraint(
        id="avg_height_sba1",
        name="Average height sba-1",
        category="height",
        value=45.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_1"],
        condition="Geldt als gemiddelde over alle bouwhoogtes op gronden met sba-1",
        provenance=_prov(),
        confidence=_conf(),
    )
    polys = [_polygon("sba-1", height_m=None)]
    fw = _framework([stipulation])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)
    assert len(findings) == 1
    assert findings[0].action == "inferred"
    assert new_geo.bouwvlakken[0].height_m == 45.0


def test_permit_gated_deviation_is_skipped() -> None:
    deviation = NumericalConstraint(
        id="max_height_sba1_increased",
        name="Max height sba-1 with permit",
        category="height",
        value=50.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_1"],
        condition="Met omgevingsvergunning; gemiddelde bouwhoogte op sba-1 maximaal 45 m",
        provenance=_prov(),
        confidence=_conf(),
    )
    polys = [_polygon("sba-1", height_m=None)]
    fw = _framework([deviation])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)
    assert findings == []
    assert new_geo.bouwvlakken[0].height_m is None


def test_height_reconciled_from_tracking() -> None:
    constraint = NumericalConstraint(
        id="max_height_sba1",
        name="Max height sba-1",
        category="height",
        value=45.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_1"],
        provenance=_prov(),
        confidence=_conf(),
    )
    polys = [
        _polygon("sba-1", height_m=None),        # inferred -> regels
        _polygon("sba-1", height_m=45.2),        # matched  -> verbeelding
        _polygon("sba-1", height_m=60.0),        # corrected-> regels
        _polygon("sba-2", height_m=30.5),        # no matching constraint
    ]
    fw = _framework([constraint])
    geo = _geometry(polys)

    new_geo, _ = reconcile_heights(fw, geo)
    sources = [p.height_reconciled_from for p in new_geo.bouwvlakken]
    assert sources == [
        "regels",
        "verbeelding",
        "regels",
        "verbeelding_uncorrected",
    ]


def test_label_normalisation_matches_dash_and_underscore() -> None:
    assert _normalise_label("sba_1") == "sba_1"
    assert _normalise_label("sba-1") == "sba_1"
    assert _normalise_label("[sba-1]") == "sba_1"
    assert _normalise_label("(SBA-1)") == "sba_1"
    assert _normalise_label("SBA-1") == "sba_1"

    constraint = NumericalConstraint(
        id="max_height_sba1",
        name="Max height sba-1",
        category="height",
        value=40.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_1"],
        provenance=_prov(),
        confidence=_conf(),
    )
    # Polygon uses the dashed form; should still match.
    polys = [_polygon("sba-1", height_m=None)]
    fw = _framework([constraint])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)
    assert len(findings) == 1
    assert findings[0].action == "inferred"
    assert new_geo.bouwvlakken[0].height_m == 40.0


def test_base_rule_wins_over_stipulation_on_tie() -> None:
    base = NumericalConstraint(
        id="max_height_sba1_base",
        name="Base max sba-1",
        category="height",
        value=45.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_1"],
        provenance=_prov(),
        confidence=_conf(0.9),
    )
    stipulation = NumericalConstraint(
        id="max_height_sba1_avg",
        name="Avg max sba-1",
        category="height",
        value=50.0,
        unit="m",
        is_maximum=True,
        applies_to=["sba_1"],
        condition="Geldt als gemiddelde",
        provenance=_prov(),
        confidence=_conf(0.9),
    )
    polys = [_polygon("sba-1", height_m=None)]
    fw = _framework([base, stipulation])
    geo = _geometry(polys)

    new_geo, findings = reconcile_heights(fw, geo)
    inferred = [f for f in findings if f.action == "inferred"]
    assert len(inferred) == 1
    assert inferred[0].source_constraint_id == "max_height_sba1_base"
    assert new_geo.bouwvlakken[0].height_m == 45.0
