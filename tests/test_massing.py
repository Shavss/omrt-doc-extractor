"""Tests for src/omrt_extractor/massing.py.

Asserts only structural properties of the returned Massing objects: that
two non-empty variants come back, that they reference real constraint
IDs, and that the mesh has plausibly-shaped data. Per the project
working agreement, never asserts specific volumes or heights extracted
from the Draka packet.
"""

from __future__ import annotations

from pathlib import Path

from omrt_extractor.massing import generate_example_massings
from omrt_extractor.schemas import (
    CRS,
    Confidence,
    Constraints,
    GeometricConstraint,
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
    validate_cross_references,
)


def _provenance() -> Provenance:
    return Provenance(
        source_type=SourceType.DOCUMENT,
        document="regels.pdf",
        page=1,
        quoted_text="example clause",
    )


def _confidence(score: float = 0.95) -> Confidence:
    return Confidence(score=score)


def _draka_like_framework() -> ParametricFramework:
    """Synthetic Draka-style framework with a bouwvlak and height/setback rules.

    The geometry stage of the pipeline may not have populated bouwvlakken
    on the live Draka extraction yet, so the test injects a small but
    realistically-shaped bouwvlak. The numerical constraints mirror the
    structure observed in Draka (a max height, a base/threshold height,
    a setback distance).
    """
    prov = _provenance()
    conf = _confidence()

    bouwvlak = GeometricConstraint(
        id="bouwvlak_a1",
        name="Bouwvlak A1",
        feature_type="bouwvlak",
        coordinates=[
            [121000.0, 489000.0],
            [121050.0, 489000.0],
            [121050.0, 489040.0],
            [121000.0, 489040.0],
            [121000.0, 489000.0],
        ],
        crs=CRS.RD_NEW,
        associated_rules=["max_height_a1", "base_height_threshold", "setback_above_threshold"],
        provenance=prov,
        confidence=conf,
    )

    max_height = NumericalConstraint(
        id="max_height_a1",
        name="Max height bouwvlak A1",
        category="height",
        value=45.0,
        unit="m",
        is_maximum=True,
        applies_to=["bouwvlak_a1"],
        provenance=prov,
        confidence=conf,
    )
    threshold = NumericalConstraint(
        id="base_height_threshold",
        name="Base height threshold",
        category="height",
        value=21.0,
        unit="m",
        is_maximum=False,
        provenance=prov,
        confidence=conf,
    )
    setback = NumericalConstraint(
        id="setback_above_threshold",
        name="Setback above threshold",
        category="setback",
        value=2.5,
        unit="m",
        is_maximum=False,
        condition="above the base height",
        provenance=prov,
        confidence=conf,
    )

    return ParametricFramework(
        metadata=ProjectMetadata(
            project_name="Synthetic Draka-like",
            location=ProjectLocation(
                municipality="Amsterdam",
                centroid_rd=(121025.0, 489020.0),
                plan_id="NL.IMRO.TEST.0001-VG01",
            ),
            source_documents=[
                SourceDocument(
                    filename="regels.pdf",
                    document_type="regels",
                    page_count=20,
                    sha256="b" * 64,
                ),
            ],
            tool_version="0.1.0",
        ),
        objective=Objective(
            statement="Test",
            urban_intent="Test",
            provenance=prov,
            confidence=conf,
        ),
        constraints=Constraints(
            numerical=[max_height, threshold, setback],
            geometric=[bouwvlak],
        ),
        variables=Variables(),
        kpis=KPIs(),
        programme=ProgrammeProposal(
            target_total_gfa_m2=1000,
            use_split=UseSplit(
                residential_m2=800,
                productive_m2=0,
                office_m2=0,
                retail_horeca_m2=200,
                cultural_m2=0,
                social_m2=0,
                other_m2=0,
                rationale="test",
                provenance=prov,
                confidence=conf,
            ),
            unit_mix=[],
            reasoning_trace=["test"],
            provenance=prov,
            confidence=conf,
        ),
    )


def test_generates_two_non_empty_massings() -> None:
    framework = _draka_like_framework()
    massings = generate_example_massings(framework)

    assert len(massings) == 2
    names = {m.name for m in massings}
    assert "Maximum envelope" in names
    assert "Compliant with setbacks" in names

    for m in massings:
        assert m.mesh_polygons is not None
        assert len(m.mesh_polygons) > 0, f"{m.name} has no mesh triangles"
        for tri in m.mesh_polygons:
            assert len(tri) == 3
            for pt in tri:
                assert len(pt) == 3
        assert m.rationale.strip()
        assert m.moves, f"{m.name} has no moves"
        for move in m.moves:
            assert move.description
        assert m.provenance is not None
        assert m.provenance.source_type == SourceType.INFERRED


def test_compliant_variant_steps_back_above_threshold() -> None:
    framework = _draka_like_framework()
    massings = generate_example_massings(framework)

    variant_b = next(m for m in massings if m.name == "Compliant with setbacks")
    # The compliant variant should reference both the threshold and the setback
    # rule somewhere in its moves; this is the structural fingerprint of the
    # step-back logic, not a check on any specific height value.
    referenced = {ref for move in variant_b.moves for ref in move.driven_by}
    assert "base_height_threshold" in referenced
    assert "setback_above_threshold" in referenced


def test_cross_references_resolve() -> None:
    framework = _draka_like_framework()
    massings = generate_example_massings(framework)
    fw = framework.model_copy(update={"massings": list(massings)})
    assert validate_cross_references(fw) == []


def test_disk_export_writes_compas_and_obj(tmp_path: Path) -> None:
    framework = _draka_like_framework()
    massings = generate_example_massings(framework, output_dir=tmp_path)
    for m in massings:
        assert (tmp_path / m.geometry_file).exists()
        assert m.geometry_file.endswith(".compas.json")
        assert (tmp_path / m.geometry_file).read_text().startswith("{")
        if m.obj_file:
            assert (tmp_path / m.obj_file).exists()
            obj_text = (tmp_path / m.obj_file).read_text()
            assert obj_text.startswith("v ")


def test_unverified_flag_when_inputs_low_confidence() -> None:
    framework = _draka_like_framework()
    # Drop confidence on the max height; the massings depending on it
    # should be flagged as using unverified inputs.
    framework.constraints.numerical[0] = framework.constraints.numerical[0].model_copy(
        update={"confidence": Confidence(score=0.4)}
    )
    massings = generate_example_massings(framework)
    assert any(m.uses_unverified_inputs for m in massings)


def test_no_bouwvlak_returns_placeholder_pair() -> None:
    framework = _draka_like_framework()
    framework = framework.model_copy(
        update={"constraints": Constraints(numerical=framework.constraints.numerical)}
    )
    massings = generate_example_massings(framework)
    assert len(massings) == 2
    for m in massings:
        assert m.uses_unverified_inputs is True
        assert m.mesh_polygons == []
