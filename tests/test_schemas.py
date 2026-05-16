"""Tests for the Pydantic schemas.

The schema is the contract every other module depends on, so this test suite
is the canary. Run it first in CI and on every schema change.

Coverage targets:
- Each primitive (Provenance, Confidence, CrossValidation, GlossaryTerm) is
  constructible in all its valid forms and rejects its invalid forms.
- Cross-field validators (Provenance source_type consistency, GeometricConstraint
  polygon ring) fire correctly.
- ParametricFramework ID uniqueness is enforced.
- validate_cross_references catches broken references but tolerates the
  'programme.*' naming convention.
- JSON round-trip is lossless for every model.
- Backward compatibility: a NumericalConstraint without cross_validation is
  still valid (cross_validation defaults to None).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from omrt_extractor.schemas import (
    CRS,
    Confidence,
    Constraints,
    CrossValidation,
    GeometricConstraint,
    GlossaryTerm,
    KPIs,
    Massing,
    MassingMove,
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
    Variable,
    Variables,
    VerificationStatus,
    validate_cross_references,
)

# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def doc_provenance() -> Provenance:
    """A typical document-sourced provenance record."""
    return Provenance(
        source_type=SourceType.DOCUMENT,
        document="regels.pdf",
        page=17,
        quoted_text="de bouwhoogte van gebouwen bedraagt ten hoogste 45 meter",
    )


@pytest.fixture
def high_confidence() -> Confidence:
    """Default high-confidence value used in many fixtures."""
    return Confidence(score=0.95, reasons=["clear regels clause"])


@pytest.fixture
def minimal_framework(doc_provenance, high_confidence) -> ParametricFramework:
    """A minimal valid ParametricFramework, useful as a baseline for many tests."""
    return ParametricFramework(
        metadata=ProjectMetadata(
            project_name="Test project",
            location=ProjectLocation(
                municipality="Amsterdam",
                centroid_rd=(121000.0, 489000.0),
                plan_id="NL.IMRO.0363.N2102BPGST-VG01",
            ),
            source_documents=[
                SourceDocument(
                    filename="regels.pdf",
                    document_type="regels",
                    page_count=37,
                    sha256="a" * 64,
                ),
            ],
            tool_version="0.1.0",
        ),
        objective=Objective(
            statement="Mixed-use development with active plinth",
            urban_intent="Active plinth, residential above, public space integration",
            provenance=doc_provenance,
            confidence=high_confidence,
        ),
        constraints=Constraints(),
        variables=Variables(),
        kpis=KPIs(),
        programme=ProgrammeProposal(
            target_total_gfa_m2=10000,
            use_split=UseSplit(
                residential_m2=8000,
                productive_m2=1000,
                office_m2=0,
                retail_horeca_m2=500,
                cultural_m2=0,
                social_m2=500,
                other_m2=0,
                rationale="Inferred from toelichting urban vision section",
                provenance=doc_provenance,
                confidence=high_confidence,
            ),
            unit_mix=[],
            reasoning_trace=["Step 1: extracted urban intent from toelichting"],
            provenance=doc_provenance,
            confidence=high_confidence,
        ),
    )


# ---------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------


class TestProvenance:
    def test_document_provenance_requires_document_and_page(self):
        with pytest.raises(ValidationError, match="Document provenance requires"):
            Provenance(source_type=SourceType.DOCUMENT)
        with pytest.raises(ValidationError, match="Document provenance requires"):
            Provenance(source_type=SourceType.DOCUMENT, document="x.pdf")

    def test_api_provenance_requires_api_name(self):
        with pytest.raises(ValidationError, match="API provenance requires 'api_name'"):
            Provenance(source_type=SourceType.API)

    def test_manual_provenance_requires_entered_by(self):
        with pytest.raises(ValidationError, match="Manual provenance requires 'entered_by'"):
            Provenance(source_type=SourceType.MANUAL)

    def test_inferred_provenance_needs_no_specific_fields(self):
        """Inferred provenance only requires source_type. inferred_from is optional."""
        p = Provenance(source_type=SourceType.INFERRED)
        assert p.source_type == SourceType.INFERRED
        assert p.inferred_from == []

    def test_page_must_be_positive(self):
        with pytest.raises(ValidationError):
            Provenance(source_type=SourceType.DOCUMENT, document="r.pdf", page=0)

    def test_api_provenance_with_name_validates(self):
        p = Provenance(source_type=SourceType.API, api_name="imro_plannen_v4")
        assert p.api_name == "imro_plannen_v4"

    def test_quoted_text_length_capped(self):
        with pytest.raises(ValidationError):
            Provenance(
                source_type=SourceType.DOCUMENT,
                document="r.pdf",
                page=1,
                quoted_text="x" * 501,
            )


# ---------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------


class TestConfidence:
    def test_score_range_enforced(self):
        Confidence(score=0.0)
        Confidence(score=1.0)
        with pytest.raises(ValidationError):
            Confidence(score=-0.1)
        with pytest.raises(ValidationError):
            Confidence(score=1.5)

    def test_flags_default_empty(self):
        c = Confidence(score=0.9)
        assert c.flags == []
        assert c.reasons == []

    def test_flags_accept_arbitrary_strings(self):
        """Flags are documented vocabulary but the field doesn't enforce a Literal.
        New flags can be added without a schema migration."""
        c = Confidence(score=0.5, flags=["imro_api_disagreement", "custom_team_flag"])
        assert "custom_team_flag" in c.flags


# ---------------------------------------------------------------------
# CrossValidation
# ---------------------------------------------------------------------


class TestCrossValidation:
    def test_agreement_with_authoritative_value(self):
        cv = CrossValidation(
            source="imro_plannen_v4",
            authoritative_value=45.0,
            authoritative_unit="m",
            agreement="agreement",
            tolerance_used=0.05,
        )
        assert cv.agreement == "agreement"
        assert cv.authoritative_value == 45.0

    def test_disagreement_carries_both_values_via_parent_constraint(
        self,
        doc_provenance,
    ):
        """The disagreement case: extraction got 32, authority says 23."""
        cv = CrossValidation(
            source="imro_plannen_v4",
            authoritative_value=23.0,
            authoritative_unit="m",
            agreement="disagreement",
            tolerance_used=0.05,
            notes="Extracted 32 m differs from authoritative 23 m",
        )
        constraint = NumericalConstraint(
            id="max_h",
            name="Max height",
            category="height",
            value=32.0,
            unit="m",
            is_maximum=True,
            provenance=doc_provenance,
            confidence=Confidence(score=0.55, flags=["imro_api_disagreement"]),
            cross_validation=cv,
        )
        assert constraint.value == 32.0
        assert constraint.cross_validation.authoritative_value == 23.0
        assert "imro_api_disagreement" in constraint.confidence.flags

    def test_not_attempted_when_no_plan_id(self):
        """When the project has no plan ID, cross-validation records this explicitly."""
        cv = CrossValidation(
            source="imro_plannen_v4",
            agreement="not_attempted",
            notes="Project has no IMRO plan ID",
        )
        assert cv.agreement == "not_attempted"
        assert cv.authoritative_value is None

    def test_unverifiable_when_field_cannot_be_matched(self):
        cv = CrossValidation(
            source="imro_plannen_v4",
            agreement="unverifiable",
            notes="No equivalent field found in authoritative API for 'sustainability_target_kwh'",
        )
        assert cv.agreement == "unverifiable"

    def test_range_value_supported_for_authoritative(self):
        """Some constraints are ranges; the authoritative version may also be a range."""
        cv = CrossValidation(
            source="imro_plannen_v4",
            authoritative_value=(0.4, 0.6),
            authoritative_unit="per_dwelling",
            agreement="agreement",
        )
        assert cv.authoritative_value == (0.4, 0.6)

    def test_extra_fields_forbidden(self):
        """extra='forbid' means typos in field names are caught."""
        with pytest.raises(ValidationError):
            CrossValidation(
                source="imro_plannen_v4",
                agreement="agreement",
                authorative_value=45.0,  # typo: should be authoritative_value
            )


# ---------------------------------------------------------------------
# GlossaryTerm
# ---------------------------------------------------------------------


class TestGlossaryTerm:
    def test_minimal_term(self):
        term = GlossaryTerm(
            term="plint",
            definition="De onderste bouwlaag van een gebouw, gelegen direct boven peil.",
            source="stelselcatalogus",
        )
        assert term.term == "plint"
        assert term.seen_in_projects == []

    def test_term_with_english_and_projects(self):
        term = GlossaryTerm(
            term="dove gevel",
            definition="Gevel zonder te openen delen waardoor geluidsbelasting irrelevant is.",
            definition_en="Deaf facade: a facade without operable openings, so noise exposure is irrelevant.",
            source="stelselcatalogus",
            source_url="https://stelselcatalogus.omgevingswet.overheid.nl/begrippen/dove_gevel",
            seen_in_projects=["draka_hamerkwartier"],
        )
        assert term.definition_en is not None
        assert len(term.seen_in_projects) == 1


# ---------------------------------------------------------------------
# NumericalConstraint
# ---------------------------------------------------------------------


class TestNumericalConstraint:
    def test_id_pattern_enforced(self, doc_provenance, high_confidence):
        """IDs must be lowercase slugs."""
        NumericalConstraint(
            id="max_height_sba2",
            name="ok",
            category="height",
            value=10.0,
            unit="m",
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        with pytest.raises(ValidationError):
            NumericalConstraint(
                id="MaxHeight",  # not lowercase
                name="bad",
                category="height",
                value=10.0,
                unit="m",
                provenance=doc_provenance,
                confidence=high_confidence,
            )

    def test_range_value(self, doc_provenance, high_confidence):
        c = NumericalConstraint(
            id="parking_band",
            name="Parking norm band",
            category="parking",
            value=(0.4, 0.6),
            unit="per_dwelling",
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        assert c.value == (0.4, 0.6)

    def test_no_cross_validation_is_backward_compatible(
        self,
        doc_provenance,
        high_confidence,
    ):
        """Constraints constructed before Stage 4b runs have no cross_validation."""
        c = NumericalConstraint(
            id="some_rule",
            name="Some rule",
            category="height",
            value=10.0,
            unit="m",
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        assert c.cross_validation is None


# ---------------------------------------------------------------------
# GeometricConstraint
# ---------------------------------------------------------------------


class TestGeometricConstraint:
    def test_valid_polygon(self, doc_provenance, high_confidence):
        gc = GeometricConstraint(
            id="plot",
            name="Plot",
            feature_type="plot_boundary",
            coordinates=[[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        assert gc.lod == 0
        assert gc.crs == CRS.RD_NEW

    def test_polygon_ring_too_few_points(self, doc_provenance, high_confidence):
        with pytest.raises(ValidationError, match="at least 4 points"):
            GeometricConstraint(
                id="bad",
                name="Bad",
                feature_type="plot_boundary",
                coordinates=[[0, 0], [100, 0], [0, 0]],
                provenance=doc_provenance,
                confidence=high_confidence,
            )

    def test_polygon_point_wrong_dimensions(self, doc_provenance, high_confidence):
        with pytest.raises(ValidationError, match=r"\[x, y\] or \[x, y, z\]"):
            GeometricConstraint(
                id="bad",
                name="Bad",
                feature_type="plot_boundary",
                coordinates=[[0], [100], [50], [0]],
                provenance=doc_provenance,
                confidence=high_confidence,
            )

    def test_lod1_with_3d_coordinates(self, doc_provenance, high_confidence):
        """Context buildings from 3D BAG land in here at LoD 1."""
        gc = GeometricConstraint(
            id="ctx_bldg",
            name="Context building",
            feature_type="context_building",
            lod=1,
            coordinates=[[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 0]],
            elevation_m=0.0,
            extrusion_height_m=15.0,
            provenance=Provenance(source_type=SourceType.API, api_name="pdok_3d_bag"),
            confidence=Confidence(score=0.9),
        )
        assert gc.lod == 1


# ---------------------------------------------------------------------
# ParametricFramework: uniqueness validator
# ---------------------------------------------------------------------


class TestFrameworkUniqueness:
    def test_minimal_framework_valid(self, minimal_framework):
        assert minimal_framework.metadata.verification_status == VerificationStatus.EXTRACTED

    def test_duplicate_constraint_ids_caught(
        self,
        minimal_framework,
        doc_provenance,
        high_confidence,
    ):
        rule_a = NumericalConstraint(
            id="dup",
            name="A",
            category="height",
            value=10.0,
            unit="m",
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        rule_b = NumericalConstraint(
            id="dup",
            name="B",
            category="height",
            value=20.0,
            unit="m",
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        data = minimal_framework.model_dump()
        data["constraints"] = Constraints(numerical=[rule_a, rule_b]).model_dump()
        with pytest.raises(ValidationError, match="Duplicate IDs"):
            ParametricFramework.model_validate(data)

    def test_duplicate_across_model_types_caught(
        self,
        minimal_framework,
        doc_provenance,
        high_confidence,
    ):
        """The validator catches collisions even across different model types."""
        constraint = NumericalConstraint(
            id="shared_id",
            name="Constraint",
            category="height",
            value=10.0,
            unit="m",
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        variable = Variable(
            id="shared_id",
            name="Variable",
            type="float",
            bounds=(0.0, 10.0),
            rationale="test",
            provenance=doc_provenance,
        )
        data = minimal_framework.model_dump()
        data["constraints"] = Constraints(numerical=[constraint]).model_dump()
        data["variables"] = Variables(items=[variable]).model_dump()
        with pytest.raises(ValidationError, match="Duplicate IDs"):
            ParametricFramework.model_validate(data)


# ---------------------------------------------------------------------
# Cross-reference validation
# ---------------------------------------------------------------------


class TestCrossReferences:
    def test_clean_framework_has_no_errors(self, minimal_framework):
        assert validate_cross_references(minimal_framework) == []

    def test_broken_reference_detected(
        self,
        minimal_framework,
        doc_provenance,
        high_confidence,
    ):
        bad_rule = NumericalConstraint(
            id="bad",
            name="bad",
            category="height",
            value=10.0,
            unit="m",
            applies_to=["nonexistent_id"],
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        framework = minimal_framework.model_copy(
            update={"constraints": Constraints(numerical=[bad_rule])},
        )
        errors = validate_cross_references(framework)
        assert len(errors) == 1
        assert "nonexistent_id" in errors[0]

    def test_programme_prefix_tolerated(
        self,
        minimal_framework,
        doc_provenance,
        high_confidence,
    ):
        """The 'programme.*' convention is not validated as an ID."""
        rule = NumericalConstraint(
            id="parking_norm",
            name="Parking norm",
            category="parking",
            value=0.6,
            unit="per_dwelling",
            applies_to=["programme.sociale_huur"],
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        framework = minimal_framework.model_copy(
            update={"constraints": Constraints(numerical=[rule])},
        )
        assert validate_cross_references(framework) == []

    def test_resolvable_reference_passes(
        self,
        minimal_framework,
        doc_provenance,
        high_confidence,
    ):
        bouwvlak = GeometricConstraint(
            id="bouwvlak_x",
            name="Bouwvlak X",
            feature_type="bouwvlak",
            coordinates=[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        rule = NumericalConstraint(
            id="max_h",
            name="Max height",
            category="height",
            value=45.0,
            unit="m",
            applies_to=["bouwvlak_x"],
            provenance=doc_provenance,
            confidence=high_confidence,
        )
        framework = minimal_framework.model_copy(
            update={
                "constraints": Constraints(numerical=[rule], geometric=[bouwvlak]),
            },
        )
        assert validate_cross_references(framework) == []

    def test_massing_move_reference_validated(
        self,
        minimal_framework,
        doc_provenance,
        high_confidence,
    ):
        """Massing moves cite the rule that produced them; the rule must exist."""
        massing = Massing(
            id="variant_a",
            name="Maximum envelope",
            rationale="Extrude every bouwvlak to its max height",
            moves=[
                MassingMove(
                    description="Stepped back at 21 m",
                    driven_by=["setback_above_21m"],  # doesn't exist
                ),
            ],
            geometry_file="massings/variant_a.compas.json",
        )
        framework = minimal_framework.model_copy(update={"massings": [massing]})
        errors = validate_cross_references(framework)
        assert any("variant_a" in e and "setback_above_21m" in e for e in errors)


# ---------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------


class TestJsonRoundtrip:
    def test_framework_roundtrip(self, minimal_framework):
        json_str = minimal_framework.model_dump_json()
        restored = ParametricFramework.model_validate_json(json_str)
        assert restored.metadata.project_name == minimal_framework.metadata.project_name
        assert restored.metadata.location.plan_id == "NL.IMRO.0363.N2102BPGST-VG01"

    def test_constraint_with_cross_validation_roundtrip(
        self,
        doc_provenance,
    ):
        cv = CrossValidation(
            source="imro_plannen_v4",
            authoritative_value=21.0,
            authoritative_unit="m",
            agreement="disagreement",
            tolerance_used=0.05,
            notes="Extracted 31 m differs from authoritative 21 m",
        )
        c = NumericalConstraint(
            id="max_h",
            name="Max height",
            category="height",
            value=31.0,
            unit="m",
            is_maximum=True,
            provenance=doc_provenance,
            confidence=Confidence(score=0.55, flags=["imro_api_disagreement"]),
            cross_validation=cv,
        )
        restored = NumericalConstraint.model_validate_json(c.model_dump_json())
        assert restored.cross_validation.agreement == "disagreement"
        assert restored.cross_validation.authoritative_value == 21.0
        assert "imro_api_disagreement" in restored.confidence.flags

    def test_glossary_term_roundtrip(self):
        term = GlossaryTerm(
            term="bouwvlak",
            definition="Geometrisch bepaald vlak waarbinnen gebouwen mogen worden opgericht.",
            source="stelselcatalogus",
            seen_in_projects=["draka", "another_project"],
        )
        data = json.loads(term.model_dump_json())
        restored = GlossaryTerm.model_validate(data)
        assert restored.term == "bouwvlak"
        assert restored.seen_in_projects == ["draka", "another_project"]
