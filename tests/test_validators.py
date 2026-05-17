"""Tests for src/omrt_extractor/validators.py.

Universal physical-sense bounds (Layer 5 of the Scenario 1 defence).
Structural-only assertions: severity and category, never document-specific
values. Synthetic constraints exercise the bound logic.
"""

from __future__ import annotations

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
    UnitTypeTarget,
    UseSplit,
    Variables,
)
from omrt_extractor.validators import (
    CATEGORY_BOUNDS,
    HEIGHT_BOUNDS_M,
    check_programme_sanity,
    check_sanity_bounds,
    run_all_validations,
)


def _prov() -> Provenance:
    return Provenance(
        source_type=SourceType.DOCUMENT,
        document="regels.pdf",
        page=3,
        quoted_text="max bouwhoogte is X m",
    )


def _conf(score: float = 0.95) -> Confidence:
    return Confidence(score=score)


def _height(value: float | tuple[float, float], cid: str = "h") -> NumericalConstraint:
    return NumericalConstraint(
        id=cid,
        name=f"Height {cid}",
        category="height",
        value=value,
        unit="m",
        is_maximum=True,
        provenance=_prov(),
        confidence=_conf(),
    )


def _framework(
    constraints: list[NumericalConstraint],
    *,
    programme: ProgrammeProposal | None = None,
) -> ParametricFramework:
    prov = _prov()
    conf = _conf()
    if programme is None:
        programme = ProgrammeProposal(
            target_total_gfa_m2=1000.0,
            use_split=UseSplit(
                residential_m2=1000.0,
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
            unit_mix=[
                UnitTypeTarget(
                    tenure="sociale_huur",
                    size_band="mixed",
                    fraction_of_total_dwellings=1.0,
                    rationale="x",
                    provenance=prov,
                    confidence=conf,
                )
            ],
            reasoning_trace=["x"],
            provenance=prov,
            confidence=conf,
        )
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
        programme=programme,
    )


# ---------------------------------------------------------------------
# Sanity bounds
# ---------------------------------------------------------------------


def test_height_above_bound_is_error() -> None:
    fw = _framework([_height(300.0)])
    findings = check_sanity_bounds(fw)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].category == "height"
    assert findings[0].bound == HEIGHT_BOUNDS_M


def test_height_below_bound_is_error() -> None:
    fw = _framework([_height(0.1)])
    findings = check_sanity_bounds(fw)
    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_height_within_bounds_no_finding() -> None:
    fw = _framework([_height(45.0)])
    assert check_sanity_bounds(fw) == []


def test_fence_height_within_universal_bound() -> None:
    # 2m fence rule must NOT trip the universal building-height bound.
    fence = NumericalConstraint(
        id="fence",
        name="Erfafscheiding height",
        category="height",
        value=2.0,
        unit="m",
        provenance=_prov(),
        confidence=_conf(),
    )
    fw = _framework([fence])
    assert check_sanity_bounds(fw) == []


def test_range_value_checks_both_endpoints() -> None:
    fw = _framework([_height((15.0, 300.0))])
    findings = check_sanity_bounds(fw)
    severities = {f.severity for f in findings}
    assert "error" in severities


def test_parking_percent_unit_skipped() -> None:
    # EV charging percent must NOT trip the per-dwelling parking bound.
    ev = NumericalConstraint(
        id="ev",
        name="EV charging provision",
        category="parking",
        value=50.0,
        unit="percent",
        provenance=_prov(),
        confidence=_conf(),
    )
    fw = _framework([ev])
    assert check_sanity_bounds(fw) == []


def test_unmapped_category_skipped() -> None:
    sustainability = NumericalConstraint(
        id="sus",
        name="Energy target",
        category="sustainability",
        value=99999.0,
        unit="kWh",
        provenance=_prov(),
        confidence=_conf(),
    )
    fw = _framework([sustainability])
    assert check_sanity_bounds(fw) == []


def test_setback_within_bound_no_finding() -> None:
    setback = NumericalConstraint(
        id="sb",
        name="Setback",
        category="setback",
        value=200.0,
        unit="m",
        provenance=_prov(),
        confidence=_conf(),
    )
    fw = _framework([setback])
    assert check_sanity_bounds(fw) == []


# ---------------------------------------------------------------------
# Programme sanity
# ---------------------------------------------------------------------


def _programme(
    *,
    target_gfa: float,
    use_split: UseSplit,
    unit_fractions: list[float],
    dwelling_count: int | None = None,
) -> ProgrammeProposal:
    prov = _prov()
    conf = _conf()
    return ProgrammeProposal(
        target_total_gfa_m2=target_gfa,
        use_split=use_split,
        unit_mix=[
            UnitTypeTarget(
                tenure="sociale_huur",
                size_band="mixed",
                fraction_of_total_dwellings=frac,
                rationale="x",
                provenance=prov,
                confidence=conf,
            )
            for frac in unit_fractions
        ],
        target_dwelling_count=dwelling_count,
        reasoning_trace=["x"],
        provenance=prov,
        confidence=conf,
    )


def test_use_split_mismatch_is_error() -> None:
    prov = _prov()
    conf = _conf()
    # use_split sums to 800 but target_total_gfa_m2 is 1000 → 20% off
    split = UseSplit(
        residential_m2=800.0,
        productive_m2=0,
        office_m2=0,
        retail_horeca_m2=0,
        cultural_m2=0,
        social_m2=0,
        other_m2=0,
        rationale="x",
        provenance=prov,
        confidence=conf,
    )
    prog = _programme(target_gfa=1000.0, use_split=split, unit_fractions=[1.0])
    fw = _framework([], programme=prog)
    findings = check_programme_sanity(fw)
    assert any(f.severity == "error" and f.category == "use_split_gfa" for f in findings)


def test_unit_mix_fraction_near_one_warning() -> None:
    prov = _prov()
    conf = _conf()
    split = UseSplit(
        residential_m2=1000.0,
        productive_m2=0,
        office_m2=0,
        retail_horeca_m2=0,
        cultural_m2=0,
        social_m2=0,
        other_m2=0,
        rationale="x",
        provenance=prov,
        confidence=conf,
    )
    # Fractions sum to 1.07 — outside ±0.05, below ±0.15 → warning
    prog = _programme(
        target_gfa=1000.0, use_split=split, unit_fractions=[0.5, 0.57]
    )
    fw = _framework([], programme=prog)
    findings = check_programme_sanity(fw)
    unit_mix = [f for f in findings if f.category == "unit_mix_fraction"]
    assert len(unit_mix) == 1
    assert unit_mix[0].severity == "warning"


def test_programme_internally_consistent_no_findings() -> None:
    prov = _prov()
    conf = _conf()
    split = UseSplit(
        residential_m2=1000.0,
        productive_m2=0,
        office_m2=0,
        retail_horeca_m2=0,
        cultural_m2=0,
        social_m2=0,
        other_m2=0,
        rationale="x",
        provenance=prov,
        confidence=conf,
    )
    prog = _programme(
        target_gfa=1000.0,
        use_split=split,
        unit_fractions=[0.6, 0.4],
        dwelling_count=12,  # 12 × 80 ≈ 960, within ±50% of 1000
    )
    fw = _framework([], programme=prog)
    assert check_programme_sanity(fw) == []


# ---------------------------------------------------------------------
# run_all_validations
# ---------------------------------------------------------------------


def test_empty_framework_no_findings() -> None:
    fw = _framework([])
    assert run_all_validations(fw) == []


def test_run_all_returns_errors() -> None:
    fw = _framework([_height(300.0), _height(0.1, cid="h2")])
    findings = run_all_validations(fw)
    assert len(findings) == 2
    assert all(f.severity == "error" for f in findings)


def test_category_bounds_keys_subset_of_valid_categories() -> None:
    # Guardrail: nothing in CATEGORY_BOUNDS that the schema rejects.
    valid = {
        "height",
        "setback",
        "footprint",
        "fsi_far",
        "bvo_limit",
        "parking",
        "use_mix",
        "sustainability",
        "noise",
        "accessibility",
        "other",
    }
    assert set(CATEGORY_BOUNDS).issubset(valid)
