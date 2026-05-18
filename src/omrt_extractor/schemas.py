"""
Pydantic schemas for the OMRT document-to-design-inputs prototype.

Design principles:

1. The schema is the product. Everything orbits ParametricFramework:
   inputs validate into it, the LLM is constrained to fill it, the
   Grasshopper engineer consumes from it, the archive stores it.

2. The top level (Objective, Constraints, Variables, KPIs) mirrors the
   Run system's input contract per the brief. A Grasshopper engineer
   opening framework.json should immediately recognise the structure.

3. Internal normalisation: every entity has a stable string ID, cross-
   references use those IDs, and the cross-project knowledge layer
   queries atomic records rather than free text.

4. Every value carries Provenance and Confidence. The system never
   claims authority; the human verifies.

5. LOD framing (CityGML conventions):
     LOD 0: 2.5D footprints (plot boundary, bouwvlakken, no-build zones)
     LOD 1: Extruded volumes (example massings, 3D BAG context buildings)
     LOD 2+: Out of scope

Generality discipline: no Dutch term or municipality name is hardcoded
as a Literal value. Where we use Literal, the alternatives are universal
classification categories (e.g. "plot_boundary", "bouwvlak"), not
specific values from the Draka packet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# =====================================================================
# Primitives: provenance, confidence, status
# Every extracted value carries provenance and confidence. These are
# the load-bearing pieces of the Scenario 1 defence.
# =====================================================================


class SourceType(StrEnum):
    """Where a value came from."""

    DOCUMENT = "document"  # Extracted from a PDF page
    INFERRED = "inferred"  # Derived by LLM reasoning over other values
    API = "api"  # Pulled from an external API (PDOK, CBS, OSM)
    MANUAL = "manual"  # Entered or corrected by a human in review


class Provenance(BaseModel):
    """Where this value came from. Required on every extracted or inferred field.

    The viewer uses this to let a PM click any value and see its evidence.
    Without provenance, the PM has no way to verify; provenance is what
    makes the 32m-versus-23m failure case visible and correctable.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType = Field(
        description=(
            "Where this value came from. Determines which other "
            "fields are required by the validator."
        ),
    )
    document: str | None = Field(
        default=None,
        description="Source PDF filename. Required when source_type='document'.",
    )
    page: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed page number in the source PDF.",
    )
    quoted_text: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Verbatim text from the source supporting this value. Keep "
            "concise; this is what the PM sees when clicking through to "
            "the source."
        ),
    )
    api_name: str | None = Field(
        default=None,
        description=(
            "Identifier of the API providing this value when "
            "source_type='api'. Standard values: "
            "'imro_plannen_v4' (Ruimtelijke Plannen, authoritative cross-validation), "
            "'dso_omgevingsdocumenten' (post-2024 omgevingsplannen), "
            "'stelselcatalogus' (official term glossary), "
            "'pdok_bag' (2D building register), "
            "'pdok_3d_bag' (3D buildings LoD 1.2/1.3/2.2), "
            "'cbs_demographics' (CBS buurt-level statistics), "
            "'osm_overpass' (OpenStreetMap amenities and transit), "
            "'amsterdam_datapunt' (Amsterdam-specific, used sparingly to avoid coupling)."
        ),
    )
    inferred_from: list[str] = Field(
        default_factory=list,
        description=(
            "When source_type='inferred', IDs of constraints or context "
            "items this inference relied on. Enables tracing of reasoning."
        ),
    )
    entered_by: str | None = Field(
        default=None,
        description=(
            "Identifier of the human who entered or overrode this value, when source_type='manual'."
        ),
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this provenance record was created.",
    )

    @model_validator(mode="after")
    def check_consistency(self) -> Provenance:
        match self.source_type:
            case SourceType.DOCUMENT:
                if not self.document or self.page is None:
                    raise ValueError("Document provenance requires both 'document' and 'page'")
            case SourceType.API:
                if not self.api_name:
                    raise ValueError("API provenance requires 'api_name'")
            case SourceType.MANUAL:
                if not self.entered_by:
                    raise ValueError("Manual provenance requires 'entered_by'")
        return self


class Confidence(BaseModel):
    """Confidence in this value, plus reasoning.

    Score 1.0 means essentially certain (clearly stated in a regels clause).
    Score 0.85 is the review threshold; values below trigger highlighting.
    Score 0.0 means a guess.

    `flags` carries standard machine-readable signals so validators and
    the viewer can act consistently across runs.
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in this value, 0.0 to 1.0. 0.85 is the review threshold.",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Free-text notes explaining the score.",
    )
    flags: list[str] = Field(
        default_factory=list,
        description=(
            "Standard machine-readable flags. Recognised values include: "
            "'cross_doc_conflict' (regels and toelichting disagree), "
            "'dual_pass_disagreement' (two extraction passes returned "
            "different values), 'outside_historical_bounds' (value falls "
            "outside the historical distribution from the knowledge layer), "
            "'ambiguous_clause' (the source text contains hedging like "
            "'of meer' or 'afhankelijk van'), 'unit_inferred' (the unit "
            "was inferred not stated), 'imro_api_agreement' (cross-validation "
            "against IMRO API confirmed this value), 'imro_api_disagreement' "
            "(IMRO API holds a different value, viewer surfaces both), "
            "'imro_api_unverifiable' (API contacted but field could not be "
            "matched to an authoritative equivalent)."
        ),
    )


class VerificationStatus(StrEnum):
    """Lifecycle status. 'reviewed' is the gate to archive promotion."""

    EXTRACTED = "extracted"
    INFERRED = "inferred"
    REVIEWED = "reviewed"
    OVERRIDDEN = "overridden"


# =====================================================================
# Cross-validation against authoritative external sources
# Used when the project has a published IMRO plan ID (or equivalent
# stable identifier) that can be looked up in an open Dutch API.
# Graceful degradation: absence of cross-validation is not a failure,
# it is recorded as agreement='not_attempted'.
# =====================================================================


class CrossValidation(BaseModel):
    """Result of comparing this value against an authoritative external source.

    Only applies when an authoritative reference exists. For Dutch
    bestemmingsplannen with a valid IMRO plan ID, the Ruimtelijke Plannen
    API (v4) at ruimte.omgevingswet.overheid.nl is the canonical source.
    For omgevingsplannen post-2024, the DSO Omgevingsdocumenten APIs.

    A null `cross_validation` field on a NumericalConstraint means the
    check was not attempted (e.g. project has no plan ID). A populated
    field with agreement='not_attempted' means we tried but the API was
    unreachable or the field couldn't be matched. Both are legitimate
    outcomes; neither blocks the pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        description=(
            "Identifier of the authoritative source. Standard values match "
            "the Provenance.api_name vocabulary: 'imro_plannen_v4', "
            "'dso_omgevingsdocumenten', 'stelselcatalogus'."
        ),
    )
    authoritative_value: float | tuple[float, float] | None = Field(
        default=None,
        description=(
            "The value the authoritative source reports for this constraint. "
            "None when agreement='unverifiable' or 'not_attempted'."
        ),
    )
    authoritative_unit: str | None = Field(
        default=None,
        description="Unit reported by the authoritative source, in case it differs.",
    )
    agreement: Literal["agreement", "disagreement", "unverifiable", "not_attempted"] = Field(
        description=(
            "'agreement': values match within tolerance. "
            "'disagreement': values differ; the viewer surfaces both side by side. "
            "'unverifiable': source was contacted but couldn't resolve a matching field. "
            "'not_attempted': cross-validation wasn't run (e.g. no plan ID, API down)."
        ),
    )
    tolerance_used: float | None = Field(
        default=None,
        description=(
            "Relative tolerance used to determine agreement, e.g. 0.05 for 5%. "
            "None when not applicable (exact match required) or not attempted."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Human-readable explanation, especially for 'unverifiable' cases.",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# =====================================================================
# Glossary
# Authoritative term definitions, primarily seeded from the
# Stelselcatalogus (the official Dutch national glossary for
# omgevingsdocumenten). Used at extraction time to ground LLM
# interpretation of vocabulary that varies across municipalities.
# =====================================================================


class GlossaryTerm(BaseModel):
    """An authoritative definition of a planning term.

    Lives in data/archive/glossary.json, not in ParametricFramework
    directly. Seeded from the Stelselcatalogus on first run and grown
    over time as projects encounter new terms with human-curated
    definitions. Looked up at extraction time and injected into the
    relevant prompts; the LLM consults the glossary rather than relying
    purely on its training data.
    """

    model_config = ConfigDict(extra="forbid")

    term: str = Field(
        description="The Dutch term, lowercase. Examples: 'plint', 'bouwvlak', 'peil', 'dove gevel'.",
    )
    definition: str = Field(description="Authoritative definition, in Dutch.")
    definition_en: str | None = Field(
        default=None,
        description="English summary of the definition for reviewer reference.",
    )
    source: str = Field(
        description=(
            "Identifier of the authority. Standard values: 'stelselcatalogus' "
            "(default, national catalog), 'imro_2012' (older IMRO standard), "
            "'human_curated' (added by a reviewer after a project), "
            "'municipal' (sourced from a specific gemeente's documentation)."
        ),
    )
    source_url: str | None = None
    seen_in_projects: list[str] = Field(
        default_factory=list,
        description=(
            "IDs of projects where this term has been observed. Grows as the "
            "archive grows. Informs which terms are worth investing curation effort in."
        ),
    )
    notes: str | None = None


# =====================================================================
# Geometry primitives
# Polygons are list[list[float]] (closed ring of [x, y] pairs) for
# simple JSON round-trip. Richer geometry can be referenced via file
# paths.
# =====================================================================


class CRS(StrEnum):
    """Coordinate reference systems used in this prototype.

    RD_NEW is the Dutch standard (used in BAG, PDOK, most NL planning data).
    WGS84 is global lat/lng (used by OSM and web maps).
    DRAWING_LOCAL is pre-scaling kaveltekening coordinates; should not
    appear in final outputs.
    """

    RD_NEW = "EPSG:28992"
    WGS84 = "EPSG:4326"
    DRAWING_LOCAL = "drawing_local"


# =====================================================================
# Source documents and project metadata
# =====================================================================


class SourceDocument(BaseModel):
    """A document in the project packet."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(description="The PDF filename as received.")
    document_type: Literal[
        "regels",
        "toelichting",
        "verbeelding",
        "permit",
        "programme_brief",
        "other",
    ] = Field(
        description=(
            "Classification of the document. Inferred from content by the "
            "LLM, never inferred from filename patterns (which are not "
            "reliable across municipalities)."
        )
    )
    page_count: int = Field(ge=1)
    sha256: str = Field(
        description=(
            "SHA-256 of file contents for caching and reproducibility. "
            "Lets us detect when a document has been updated between runs."
        )
    )


class ProjectLocation(BaseModel):
    """Where the project is geographically.

    Coordinates drive the geo enrichment step. Both RD New and WGS84 are
    populated so different APIs can be queried in their native CRS without
    repeated conversions.
    """

    model_config = ConfigDict(extra="forbid")

    address: str | None = Field(default=None, description="Street address if available.")
    municipality: str = Field(description="Dutch gemeente name, e.g. 'Amsterdam', 'Rotterdam'.")
    district: str | None = Field(default=None, description="Stadsdeel or district if applicable.")
    neighbourhood: str | None = Field(default=None, description="Buurt name if mentioned.")

    centroid_rd: tuple[float, float] | None = Field(
        default=None,
        description="Project centroid in RD New (EPSG:28992). Drives PDOK and CBS queries.",
    )
    centroid_wgs84: tuple[float, float] | None = Field(
        default=None,
        description="Project centroid as (lat, lng) in WGS84. Drives OSM queries and map display.",
    )
    plan_id: str | None = Field(
        default=None,
        description=(
            "IMRO plan identifier when present in the documents, e.g. "
            "'NL.IMRO.0363.N2102BPGST-VG01'. Useful as a stable key for the archive."
        ),
    )


class ProjectMetadata(BaseModel):
    """Top-level metadata about this project and this extraction run."""

    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(description="Human-readable name, often the bestemmingsplan title.")
    location: ProjectLocation
    source_documents: list[SourceDocument]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_version: str = Field(description="omrt_extractor version that produced this output.")
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.EXTRACTED,
        description=(
            "Overall verification state of the framework. Only 'reviewed' "
            "frameworks are promoted to the cross-project archive."
        ),
    )


# =====================================================================
# Constraints: numerical, geometric, narrative
# The three families are dictated by the brief. Atomic records with
# stable IDs make the cross-project knowledge layer queryable.
# =====================================================================


ConstraintCategory = Literal[
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
]

class ReasoningStep(BaseModel):
    """A single step in the programme reasoning trace."""

    model_config = ConfigDict(extra="forbid")

    step: int
    decision: str = Field(description="What was decided in this step.")
    evidence: str | None = Field(
        default=None,
        description="Constraint IDs, geo data points, or 'designer judgment: ...' cited.",
    )
    confidence_in_step: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model's self-reported confidence in this specific reasoning step.",
    )


    
class NumericalConstraint(BaseModel):
    """A single numerical rule extracted from the documents.

    Examples:
      - Max building height for a specific bouwvlak
      - Max BVO for a specific use type
      - Parking norm per dwelling for a specific tenure
      - Min setback distance above a height threshold

    The combination of `category` and `applies_to` plus a `condition`
    lets the Grasshopper engineer (and the example-massing function)
    interpret the rule mechanically without re-parsing the source text.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        description=(
            "Unique slug-style ID, lowercase with underscores. Examples: "
            "'max_height_sba2', 'parking_norm_social_housing', "
            "'setback_above_21m'. Used as a stable handle for cross-references."
        ),
    )
    name: str = Field(description="Human-readable name for the viewer and the GH parameter label.")
    category: ConstraintCategory
    value: float | tuple[float, float] = Field(
        description=(
            "The numeric value in the declared unit. Use a (min, max) "
            "tuple for ranges. Single values are bounds (use is_maximum "
            "to distinguish min from max)."
        )
    )
    unit: str = Field(
        description=(
            "Unit of measure. Standard values: 'm', 'm2', 'per_dwelling', "
            "'per_100m2_bvo', 'ratio', 'percent', 'dB'. New units are "
            "acceptable when justified."
        )
    )
    is_maximum: bool | None = Field(
        default=None,
        description=(
            "True for upper bounds (max), False for lower bounds (min), "
            "None for exact values or when not applicable."
        ),
    )
    condition: str | None = Field(
        default=None,
        description=(
            "Optional free-text condition limiting when this rule applies, "
            "e.g. 'when building height exceeds 21 m', 'when located on "
            "Gedempt Hamerkanaal facade'. Resolved by the GH engineer or "
            "by future structured-condition extensions."
        ),
    )
    applies_to: list[str] = Field(
        default_factory=list,
        description=(
            "IDs of GeometricConstraints, programme components, or other "
            "entities this rule binds on. Empty list means project-wide. "
            "For programme references, use 'programme.<tenure>' or "
            "'programme.<use_category>' string conventions."
        ),
    )
    provenance: Provenance
    confidence: Confidence
    cross_validation: CrossValidation | None = Field(
        default=None,
        description=(
            "Result of comparing this value against an authoritative external "
            "source (e.g. the IMRO API for Dutch bestemmingsplannen). None "
            "when no cross-validation was attempted. Populated with "
            "agreement='disagreement' when the LLM extraction and the API "
            "value differ; the viewer surfaces both. This is the strongest "
            "layer of the Scenario 1 defence."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Any ambiguity, conflict, or context a Grasshopper engineer should know.",
    )


class GeometricConstraint(BaseModel):
    """A geometric feature that constrains design.

    Per the brief: 'plot boundary, buildable envelope, no-build zones,
    and anything else that is fundamentally geometric.' The feature's
    presence and position is itself the constraint; numerical rules
    that bind on it are linked through `associated_rules`.

    Default LOD is 0 (2.5D footprint). LOD 1+ would apply only to
    context buildings imported from 3D BAG.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(description="Human-readable label, e.g. 'Plot boundary', 'Bouwvlak SBA-2'.")
    feature_type: Literal[
        "plot_boundary",
        "bouwvlak",
        "no_build_zone",
        "setback_zone",
        "dove_gevel_zone",
        "dvg_overlay",
        "archaeology_zone",
        "vaarweg_zone",
        "noise_contour",
        "context_building",
        "other",
    ] = Field(description="Universal classification of the geometric feature.")
    lod: int = Field(
        default=0,
        ge=0,
        le=4,
        description=(
            "CityGML Level of Detail. 0 for footprints (default for "
            "constraints), 1 for extruded volumes (context buildings)."
        ),
    )
    coordinates: list[list[float]] = Field(
        description=(
            "Closed ring of [x, y] (or [x, y, z] for LOD 1+) in the "
            "declared CRS. First and last points should match."
        )
    )
    crs: CRS = Field(default=CRS.RD_NEW)
    elevation_m: float | None = Field(
        default=None,
        description="Base elevation for LOD 1+ extrusions. None for pure footprints.",
    )
    extrusion_height_m: float | None = Field(
        default=None,
        description="Extrusion height for LOD 1 features. None for footprints.",
    )
    geometry_file: str | None = Field(
        default=None,
        description=(
            "Optional relative path to a richer COMPAS JSON file with this "
            "feature's geometry. Used when the polygon is too complex to "
            "embed inline cleanly."
        ),
    )
    associated_rules: list[str] = Field(
        default_factory=list,
        description="IDs of NumericalConstraint and NarrativeConstraint records that bind on this feature.",
    )
    height_reconciled_from: Literal["regels", "verbeelding", "verbeelding_uncorrected"] | None = (
        Field(
            default=None,
            description=(
                "For bouwvlakken: how the polygon's height was sourced after the "
                "reconciliation pass. 'regels' = set or overwritten by a regels "
                "clause. 'verbeelding' = drawing value confirmed by regels. "
                "'verbeelding_uncorrected' = drawing value with no matching "
                "regels clause to confirm. None for non-height features or when "
                "reconciliation was skipped."
            ),
        )
    )
    provenance: Provenance
    confidence: Confidence
    notes: str | None = None

    @field_validator("coordinates")
    @classmethod
    def check_ring(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 4:
            raise ValueError(
                "A polygon ring needs at least 4 points (3 vertices plus closing point)."
            )
        for pt in v:
            if len(pt) not in (2, 3):
                raise ValueError("Each coordinate must be [x, y] or [x, y, z].")
        return v


class NarrativeConstraint(BaseModel):
    """A free-text rule that doesn't fit numerical or geometric form.

    Examples:
      - 'Plinth must be activated at street-facing facades'
      - 'Buildings over 30 m require a landscape integration study'
      - 'Designs must be approved by the Hamerkwartier supervision team'

    Surfaced to the GH engineer as context. Not mechanically enforced
    by the Run but a flag in the documentation around it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    statement: str = Field(description="The rule restated as a clear English sentence.")
    category: Literal[
        "urban_design",
        "sustainability",
        "process",
        "historical_cultural",
        "stakeholder",
        "ambiguity_flag",
        "other",
    ]
    applies_to: list[str] = Field(default_factory=list)
    provenance: Provenance
    confidence: Confidence


class Constraints(BaseModel):
    """All design constraints, partitioned per the brief's three families."""

    model_config = ConfigDict(extra="forbid")

    numerical: list[NumericalConstraint] = Field(default_factory=list)
    geometric: list[GeometricConstraint] = Field(default_factory=list)
    narrative: list[NarrativeConstraint] = Field(default_factory=list)


# =====================================================================
# Objective
# =====================================================================


class Objective(BaseModel):
    """The design goal, distilled from the toelichting plus programme intent.

    A short statement of what success looks like for this project. The
    Run engine uses this to weight KPIs and to surface narrative context
    to the client.
    """

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(
        description="One or two sentence statement of the design goal.",
    )
    urban_intent: str = Field(
        description="Longer description of urban character and ambitions from the toelichting.",
    )
    provenance: Provenance
    confidence: Confidence


# =====================================================================
# Variables: design parameters a Run can sweep over
# =====================================================================


VariableType = Literal["int", "float", "categorical"]


class Variable(BaseModel):
    """A design parameter a Run can vary.

    For every NumericalConstraint with an upper bound there is naturally
    a corresponding Variable with that bound. Some Variables represent
    design choices not bound by a rule (e.g. tower placement within a
    bouwvlak, programme mix proportions within a target range).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    type: VariableType
    bounds: tuple[float, float] | list[str] = Field(
        description=(
            "For int/float, a (min, max) tuple. For categorical, the list of allowed string values."
        )
    )
    unit: str | None = None
    default: float | str | None = Field(
        default=None,
        description="A sensible starting point within bounds. Useful for baseline Runs.",
    )
    applies_to: list[str] = Field(
        default_factory=list,
        description="IDs of geometric features or programme components this variable shapes.",
    )
    rationale: str = Field(
        description=(
            "Why this is a variable for this project. Helps the GH engineer "
            "decide whether to keep it, fix it, or extend its bounds."
        )
    )
    provenance: Provenance


class Variables(BaseModel):
    """Bundle of design variables for the Run."""

    model_config = ConfigDict(extra="forbid")

    items: list[Variable] = Field(default_factory=list)


# =====================================================================
# KPIs: what a Run measures and optimises
# =====================================================================


class KPI(BaseModel):
    """A key performance indicator the Run evaluates each variant against."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    direction: Literal["maximise", "minimise", "target"]
    target_value: float | None = Field(
        default=None,
        description="For direction='target', the value to aim for. None otherwise.",
    )
    unit: str
    rationale: str = Field(description="Why this KPI matters for this project specifically.")
    category: Literal["urban", "environmental", "financial", "programme", "compliance", "other"]
    provenance: Provenance


class KPIs(BaseModel):
    """Bundle of KPIs for the Run."""

    model_config = ConfigDict(extra="forbid")

    items: list[KPI] = Field(default_factory=list)


# =====================================================================
# Programme proposal
# Where we infer developer intent from toelichting + geo context.
# =====================================================================


class UnitTypeTarget(BaseModel):
    """One slice of the housing programme mix."""

    model_config = ConfigDict(extra="forbid")

    tenure: Literal[
        "sociale_huur",
        "middenhuur",
        "vrije_sector_huur",
        "koop",
        "other",
    ]
    size_band: Literal[
        "under_30m2",
        "30_60m2",
        "60_90m2",
        "over_90m2",
        "mixed",
    ] = Field(
        description=(
            "Floor area band. Matches the bands used in Dutch parking norms "
            "(which differ at 30 and 60 m2 thresholds)."
        )
    )
    fraction_of_total_dwellings: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of total dwellings as 0.0 to 1.0.",
    )
    typology: str | None = Field(
        default=None,
        description=(
            "Free-form typology label as returned by the LLM "
            "(e.g. 'studio_1br', '1br_2br', '2br_3br'). Informational only — "
            "not used in Run. Retained so reviewers can see the LLM's original intent."
        ),
    )
    target_count_range: tuple[int, int] | None = Field(
        default=None,
        description=(
            "LLM-suggested dwelling count range (min, max) for this tenure band. "
            "Not enforced by Run; surfaced in the viewer for human review."
        ),
    )
    target_size_m2_range: tuple[float, float] | None = Field(
        default=None,
        description=(
            "LLM-suggested floor area range in m² (min, max) for this band. "
            "Not enforced by Run; surfaced in the viewer for human review."
        ),
    )
    rationale: str
    provenance: Provenance
    confidence: Confidence


class UseSplit(BaseModel):
    """Split of total GFA between use categories."""

    model_config = ConfigDict(extra="forbid")

    residential_m2: float = Field(ge=0)
    productive_m2: float = Field(
        ge=0,
        description="Productive bedrijvigheid, maakindustrie, hybrid uses.",
    )
    office_m2: float = Field(ge=0)
    retail_horeca_m2: float = Field(ge=0)
    cultural_m2: float = Field(ge=0)
    social_m2: float = Field(
        ge=0,
        description="Maatschappelijke voorzieningen, schools, kinderdagverblijf.",
    )
    other_m2: float = Field(ge=0)
    normalised_from_pct: bool = Field(
        default=False,
        description=(
            "True when m2 values were derived by multiplying LLM-returned "
            "percentages (*_pct fields) by target_total_gfa_m2. "
            "Flag for reviewers — verify the GFA base value is correct."
        ),
    )
    rationale: str
    provenance: Provenance
    confidence: Confidence

class ProgrammeProposal(BaseModel):
    """The inferred developer programme.

    Per the brief, developer intent is not in the documents and must be
    inferred from toelichting + geo context + designer judgment. Every
    number cites its evidence, every assumption is in the reasoning trace.
    """

    model_config = ConfigDict(extra="forbid")

    target_total_gfa_m2: float = Field(
        gt=0, description="Total GFA the proposed programme delivers."
    )
    target_total_gfa_m2_range: tuple[float, float] | None = Field(
        default=None,
        description=(
            "LLM-suggested GFA range (min, max) in m². "
            "target_total_gfa_m2 is the midpoint when this is present."
        ),
    )
    use_split: UseSplit
    unit_mix: list[UnitTypeTarget] = Field(
        description=(
            "Breakdown of housing by tenure × typology. One entry per combination, "
            "e.g. sociale_huur×studio, sociale_huur×1br, middenhuur×1br, etc."
        )
    )
    target_dwelling_count: int | None = Field(
        default=None,
        description="Approximate dwelling count implied by the programme.",
    )
    total_dwelling_count_range: tuple[int, int] | None = Field(
        default=None,
        description=(
            "LLM-suggested dwelling count range (min, max). "
            "target_dwelling_count is the midpoint when this is present."
        ),
    )
    parking_demand: float | None = Field(
        default=None,
        description="Estimated total parking spaces required given the unit mix and norms.",
    )
    reasoning_trace: list[ReasoningStep | str] = Field(
        description=(
            "Stepwise reasoning. Each step cites either a constraint ID, a "
            "geo context data point, or explicitly states 'designer judgment' "
            "with rationale. Steps may be structured ReasoningStep objects "
            "(with per-step confidence) or plain strings (legacy)."
        )
    )
    provenance: Provenance
    confidence: Confidence


# =====================================================================
# Geo context (output of the enrichment stage)
# =====================================================================


class NearbyBuildingsSnapshot(BaseModel):
    """Aggregate of buildings from PDOK BAG within the enrichment buffer."""

    model_config = ConfigDict(extra="forbid")

    radius_m: float
    count: int = Field(ge=0)
    dominant_uses: list[str] = Field(
        description="Top function categories from BAG, e.g. 'wonen', 'kantoor', 'industrie'.",
    )
    typical_heights_m: tuple[float, float] | None = Field(
        default=None,
        description="(min, max) of building heights observed nearby. Useful as urban context and sanity check.",
    )
    typical_year_built: tuple[int, int] | None = None
    has_3d_bag_data: bool = Field(
        default=False,
        description="True if 3D BAG (CityGML LOD 1 or 2) data was retrieved alongside the 2D BAG.",
    )


class NeighbourhoodDemographics(BaseModel):
    """Aggregate from CBS at the buurt level."""

    model_config = ConfigDict(extra="forbid")

    buurt_code: str
    population: int | None = None
    household_count: int | None = None
    average_household_size: float | None = None
    median_age: float | None = None


class TransitAccess(BaseModel):
    """Aggregate from OSM."""

    model_config = ConfigDict(extra="forbid")

    nearest_tram_m: float | None = None
    nearest_metro_m: float | None = None
    nearest_train_m: float | None = None
    nearest_bus_m: float | None = None


class GeoContext(BaseModel):
    """Output of the enrichment stage.

    All fields are optional because any API can be unavailable. The
    data_sources_used and data_sources_failed fields tell downstream
    code what's missing, which feeds into confidence on derived values.
    """

    model_config = ConfigDict(extra="forbid")

    nearby_buildings: NearbyBuildingsSnapshot | None = None
    demographics: NeighbourhoodDemographics | None = None
    transit: TransitAccess | None = None
    nearby_amenities: dict[str, int] = Field(
        default_factory=dict,
        description="OSM amenity counts, e.g. {'school': 3, 'supermarket': 1, 'restaurant': 12}.",
    )
    data_sources_used: list[str] = Field(
        default_factory=list,
        description="API identifiers that returned data successfully.",
    )
    data_sources_failed: list[str] = Field(
        default_factory=list,
        description="API identifiers that were tried but failed.",
    )


# =====================================================================
# Massings (the nice-to-have visual)
# =====================================================================


class MassingMove(BaseModel):
    """A single form decision in a Massing, citing the rule that drove it."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        description="Short description, e.g. 'Stepped back at 21 m above east-facing facade'.",
    )
    driven_by: list[str] = Field(
        description="IDs of NumericalConstraint or NarrativeConstraint records that produced this move.",
    )


class Massing(BaseModel):
    """One example massing derived from the validated inputs.

    The prototype produces two: a maximum-envelope variant and a
    compliant-with-setbacks variant. Both are LOD 1. They are a visual
    proof that the inputs are usable to drive geometry, not a finished
    design.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(description="Short name, e.g. 'Maximum envelope', 'Compliant with setbacks'.")
    lod: int = Field(
        default=1,
        ge=0,
        le=2,
        description="LOD 1 by default for extruded volumes. LOD 2 would require roof modeling.",
    )
    rationale: str = Field(description="One or two sentences on what this variant illustrates.")
    moves: list[MassingMove] = Field(
        description="The form decisions that produced this massing, each citing the rule that drove it.",
    )
    geometry_file: str = Field(
        description="Relative path to the COMPAS Mesh JSON for this massing's geometry.",
    )
    obj_file: str | None = Field(
        default=None,
        description="Optional path to an OBJ export.",
    )
    mesh_polygons: list[list[list[float]]] | None = Field(
        default=None,
        description=(
            "Optional inline triangulated mesh as a list of triangles, each a "
            "list of three [x, y, z] points. Lets the viewer render with "
            "plotly Mesh3d without re-reading the COMPAS JSON. The COMPAS "
            "JSON at geometry_file remains the authoritative artifact."
        ),
    )
    provenance: Provenance | None = Field(
        default=None,
        description=(
            "Provenance of the massing as a whole. source_type='inferred' with "
            "inferred_from listing the constraint IDs whose values drove the moves. "
            "Optional for backward compatibility, but populated by "
            "generate_example_massings."
        ),
    )
    total_gfa_m2: float | None = Field(
        default=None,
        description=(
            "Computed total GFA from the massing volume. A useful sanity "
            "check against the programme target."
        ),
    )
    uses_unverified_inputs: bool = Field(
        default=False,
        description=(
            "True if any input that drove a move in this massing has "
            "confidence below threshold. Viewer banners this fact over "
            "the visualisation."
        ),
    )


# =====================================================================
# Top-level: ParametricFramework
# =====================================================================


class ParametricFramework(BaseModel):
    """The complete output. Mirrors the Run system's input contract at the
    top level (Objective, Constraints, Variables, KPIs) plus supporting
    blocks (metadata, programme, geo_context, massings).

    This is the JSON the Grasshopper engineer opens.
    """

    model_config = ConfigDict(extra="forbid")

    metadata: ProjectMetadata
    objective: Objective
    constraints: Constraints
    variables: Variables
    kpis: KPIs
    programme: ProgrammeProposal
    geo_context: GeoContext | None = Field(
        default=None,
        description="Geo enrichment data. None if enrichment was skipped or failed entirely.",
    )
    massings: list[Massing] = Field(
        default_factory=list,
        description="Example massings derived from the inputs. The nice-to-have visual proof.",
    )

    @model_validator(mode="after")
    def check_id_uniqueness(self) -> ParametricFramework:
        """Every ID must be unique within the framework regardless of model type.

        IDs are how cross-references work, so collisions silently break the
        system. We catch them at the schema boundary.
        """
        seen: set[str] = set()
        collisions: list[str] = []

        for c in self.constraints.numerical:
            if c.id in seen:
                collisions.append(c.id)
            seen.add(c.id)
        for c in self.constraints.geometric:
            if c.id in seen:
                collisions.append(c.id)
            seen.add(c.id)
        for c in self.constraints.narrative:
            if c.id in seen:
                collisions.append(c.id)
            seen.add(c.id)
        for v in self.variables.items:
            if v.id in seen:
                collisions.append(v.id)
            seen.add(v.id)
        for k in self.kpis.items:
            if k.id in seen:
                collisions.append(k.id)
            seen.add(k.id)
        for m in self.massings:
            if m.id in seen:
                collisions.append(m.id)
            seen.add(m.id)

        if collisions:
            raise ValueError(f"Duplicate IDs in framework: {collisions}")
        return self


def validate_cross_references(framework: ParametricFramework) -> list[str]:
    """Check that every cross-reference resolves to an existing ID.

    Run before serialising to JSON, not as a model_validator, because
    during incremental construction (per-page extraction merges) refs
    may legitimately point to entities that haven't been added yet.

    Returns a list of error messages. Empty list means the framework is
    internally consistent.

    Programme component refs (strings starting 'programme.') are tolerated
    without resolution; they're a stable convention rather than IDs.
    """
    valid_ids: set[str] = set()
    for c in framework.constraints.numerical:
        valid_ids.add(c.id)
    for c in framework.constraints.geometric:
        valid_ids.add(c.id)
    for c in framework.constraints.narrative:
        valid_ids.add(c.id)
    for v in framework.variables.items:
        valid_ids.add(v.id)
    for k in framework.kpis.items:
        valid_ids.add(k.id)
    for m in framework.massings:
        valid_ids.add(m.id)

    def is_programme_ref(ref: str) -> bool:
        return ref.startswith("programme.")

    errors: list[str] = []

    for c in framework.constraints.numerical:
        for ref in c.applies_to:
            if not is_programme_ref(ref) and ref not in valid_ids:
                errors.append(f"NumericalConstraint '{c.id}' references missing ID '{ref}'")

    for c in framework.constraints.geometric:
        for ref in c.associated_rules:
            if ref not in valid_ids:
                errors.append(f"GeometricConstraint '{c.id}' references missing rule '{ref}'")

    for c in framework.constraints.narrative:
        for ref in c.applies_to:
            if not is_programme_ref(ref) and ref not in valid_ids:
                errors.append(f"NarrativeConstraint '{c.id}' references missing ID '{ref}'")

    for v in framework.variables.items:
        for ref in v.applies_to:
            if not is_programme_ref(ref) and ref not in valid_ids:
                errors.append(f"Variable '{v.id}' references missing ID '{ref}'")

    for m in framework.massings:
        for move in m.moves:
            for ref in move.driven_by:
                if ref not in valid_ids:
                    errors.append(f"Massing '{m.id}' move references missing rule '{ref}'")

    return errors


# =====================================================================
# Partial extraction (LLM output for a single page)
# =====================================================================


class PartialFrameworkExtraction(BaseModel):
    """What the multimodal LLM returns for a single page.

    A partial may contribute any subset of the full framework's fields.
    The merge logic in extract.py combines per-page partials into the
    project-level Extraction, retaining all entries (no silent overwrite)
    when multiple pages report the same value. Disagreements are flagged
    in confidence with 'cross_doc_conflict'.

    This is the schema PydanticAI passes to the LLM, so the field
    descriptions matter more here than anywhere else; they are the
    effective per-field prompt.
    """

    model_config = ConfigDict(extra="forbid")

    numerical_constraints: list[NumericalConstraint] = Field(
        default_factory=list,
        description=(
            "Any numerical rules visible on this page (heights, setbacks, "
            "parking norms, GFA limits, FSI, sustainability targets). "
            "Always include provenance with the exact page number."
        ),
    )
    geometric_constraints: list[GeometricConstraint] = Field(
        default_factory=list,
        description=(
            "Geometric features visible on this page if it is a verbeelding "
            "or contains plan-like drawings. Coordinates can be left as a "
            "placeholder; the dedicated geometry stage fills these in from "
            "vector parsing. Use this field mostly for label-classification "
            "hints."
        ),
    )
    narrative_constraints: list[NarrativeConstraint] = Field(
        default_factory=list,
        description=(
            "Free-text rules and notes that don't fit a number or a polygon, "
            "e.g. process requirements, urban design intentions, ambiguities "
            "to flag."
        ),
    )
    programme_hints: list[str] = Field(
        default_factory=list,
        description=(
            "Notes about programme intent extracted from this page. Brief "
            "quotes or paraphrases. Fed into the inference stage."
        ),
    )
    urban_intent_passages: list[str] = Field(
        default_factory=list,
        description=(
            "Passages describing urban vision, character, or ambitions from "
            "this page. Especially valuable from the toelichting."
        ),
    )
    plan_id_found: str | None = Field(
        default=None,
        description="IMRO plan identifier if it appears on this page.",
    )
    municipality_found: str | None = Field(
        default=None,
        description="Dutch gemeente name if it appears on this page.",
    )
    neighbourhood_found: str | None = Field(
        default=None,
        description="Buurt name if it appears on this page.",
    )


# =====================================================================
# Preprocessing output (Stage 1)
# Per-page image and text pairs feeding the multimodal extractor.
# =====================================================================


class PreprocessedPage(BaseModel):
    """One page rendered to a PNG and its text-layer extraction.

    Both artifacts feed the multimodal LLM in Stage 2. The image carries
    visual structure (tables, drawings, layout) that text extraction
    drops; the text carries glyphs that the model would otherwise have
    to OCR from the image.
    """

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(
        ge=1,
        description="1-indexed page number as seen by a human reader.",
    )
    image_path: Path = Field(
        description=(
            "Absolute path to the rendered PNG. Lives under the project "
            "cache directory so reruns skip re-rendering."
        ),
    )
    text: str = Field(
        description=(
            "Text layer extracted by pymupdf. May be empty for scanned "
            "pages with no OCR; downstream code falls back to the image."
        ),
    )


class PreprocessedDocument(BaseModel):
    """All preprocessed pages for one PDF in the project packet."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(description="The PDF filename as received.")
    pdf_path: Path = Field(description="Absolute path to the source PDF.")
    document_type: Literal["regels", "toelichting", "kaveltekening", "other"] = Field(
        description=(
            "Coarse classification inferred from filename hints. Used only "
            "to route preprocessing artifacts and to give the multimodal "
            "extractor a soft prior. The authoritative document_type lives "
            "on SourceDocument and is set by the LLM from content; this "
            "field must not be trusted for legal or extraction decisions."
        ),
    )
    pages: list[PreprocessedPage] = Field(
        default_factory=list,
        description="Per-page preprocessed artifacts in page order.",
    )


class ProjectPreprocessed(BaseModel):
    """Stage 1 output: every PDF in the input directory, page by page."""

    model_config = ConfigDict(extra="forbid")

    input_dir: Path = Field(description="The packet directory that was processed.")
    cache_dir: Path = Field(description="Where rendered images are stored.")
    documents: list[PreprocessedDocument] = Field(
        default_factory=list,
        description="One entry per PDF discovered in the input directory.",
    )

