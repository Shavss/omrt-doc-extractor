# Schema reference

The Pydantic schema in `src/omrt_extractor/schemas.py` is the central contract of this prototype. Every other module produces or consumes instances of these models. This document is the field-by-field tour for anyone reading or building against the schema: the Grasshopper engineer who consumes the JSON output, the project manager who reviews a project in the Streamlit viewer, the reviewer assessing the prototype.

For the data flow that produces these models see `architecture.md`. 

## Reading conventions

Every model in the schema uses `model_config = ConfigDict(extra="forbid")`. Typos in field names are caught at validation time, not silently dropped. When you see a new field appear in the codebase, that field has been deliberately added; nothing is implicit.

Field types follow standard Python type hints. `float | None` means "a float or absent." `tuple[float, float]` means "a closed range." `list[...]` defaults to an empty list, not None.

IDs throughout the schema follow the pattern `^[a-z][a-z0-9_]*$`: lowercase slugs separated by underscores. The Grasshopper engineer can use these directly as parameter labels.

## The top-level model: ParametricFramework

`ParametricFramework` is the only object the pipeline ultimately produces. Every other model is reachable from this root.

Its top-level fields mirror the OMRT Run system so a populated framework can drop into the existing parametric pipeline without re-mapping:

- `metadata` (ProjectMetadata): project identification, source documents, verification status.
- `objective` (Objective): the urban intent that drives design decisions.
- `constraints` (Constraints): the hard rules. Three sub-collections: numerical, geometric, narrative.
- `variables` (Variables): the design variables the Grasshopper engineer will sweep.
- `kpis` (KPIs): the metrics the Run system optimises against.
- `programme` (ProgrammeProposal): the synthesised programme proposal.
- `geo_context` (GeoContext, optional): the surrounding geographic data.
- `massings` (list of Massing): zero or more example massings derived from the framework.

A cross-reference validator runs at construction time. Every `applies_to`, `driven_by`, or other reference between models must resolve to an ID that exists somewhere in the same framework, with the exception of the `programme.<tenure>` and `programme.<use_category>` string conventions used to link constraints to programme components.

## The three trust-signal primitives

These three small models appear on almost every other field in the schema. They are why a populated framework is auditable rather than merely structured.

### Provenance

Every extracted value has a `provenance: Provenance` field that answers "where did this come from?" The schema enforces consistency:

- `source_type: "document"` requires both a `document` filename and a `page` number. The `quoted_text` field carries the verbatim source text (capped at 500 characters).
- `source_type: "api"` requires an `api_name` from a standard vocabulary: `imro_plannen_v4`, `dso_omgevingsdocumenten`, `stelselcatalogus`, `pdok_bag`, `pdok_3d_bag`, `cbs_demographics`, `osm_overpass`, `amsterdam_datapunt`.
- `source_type: "manual"` requires an `entered_by` identifier (which human typed this value).
- `source_type: "inferred"` typically lists `inferred_from`: IDs of other constraints or context items the inference relied on.

The PM uses provenance to click any value in the viewer and see exactly the clause it came from. The Grasshopper engineer uses it to know whether a value is binding (regels) or informative (toelichting). The cross-validation layer uses it to find the authoritative equivalent.

### Confidence

Every extracted value has a `confidence: Confidence` field with a `score` between 0.0 and 1.0, a list of `reasons`, and a list of standard machine-readable `flags`.

The 0.85 threshold is the review gate. Values below 0.85 are highlighted in the viewer for explicit PM attention. Values at or above 0.85 still appear with their confidence visible but do not block sign-off.

Standard flags carry specific meaning:
- `cross_doc_conflict`: the regels and toelichting disagree on this value.
- `dual_pass_disagreement`: the two extraction passes returned different values.
- `outside_historical_bounds`: the value falls outside the historical distribution from the knowledge layer.
- `ambiguous_clause`: the source text contains hedging like "of meer" or "afhankelijk van".
- `unit_inferred`: the unit was inferred from context, not stated.
- `imro_api_agreement`: cross-validation against the IMRO API confirmed this value.
- `imro_api_disagreement`: the IMRO API holds a different value; the viewer surfaces both.
- `imro_api_unverifiable`: the API was contacted but the field could not be matched.

Flags are not Literal-typed; new flags can be added without a schema migration.

### CrossValidation

For values that have an authoritative external source, the `cross_validation: CrossValidation | None` field carries the result of the comparison. This is the strongest layer of the Scenario 1 defence.

For Dutch bestemmingsplannen with a published IMRO plan ID, the Ruimtelijke Plannen API is queried at Stage 4b of the build. Every NumericalConstraint is matched against an authoritative equivalent within a 5% relative tolerance.

The `agreement` field has four values:
- `agreement`: extracted and authoritative match within tolerance.
- `disagreement`: they differ. The viewer surfaces both side by side.
- `unverifiable`: the API was contacted but no authoritative equivalent could be matched.
- `not_attempted`: no cross-validation was run. The most common case for projects without a plan ID.

A `None` value on the field means the cross-validation pipeline never reached this constraint; an explicit `not_attempted` means it tried and recorded the absence.

## Project metadata

### ProjectMetadata

Identifies the project and tracks its verification lifecycle.

- `project_name`: human-readable label.
- `location` (ProjectLocation): centroid, municipality, plan ID.
- `source_documents` (list of SourceDocument): every PDF that fed the extraction, with sha256 for change detection.
- `tool_version`: the version of this prototype that produced the framework.
- `created_at`, `updated_at`: timestamps.
- `verification_status` (VerificationStatus enum): one of `extracted`, `inferred`, `reviewed`, `overridden`. Only `reviewed` projects feed the cross-project archive.

### ProjectLocation

- `centroid_rd`: project centroid in Dutch RD New coordinates (EPSG:28992). The single value that powers all coordinate-driven enrichment.
- `municipality`, `neighbourhood`: discovered from the source documents.
- `plan_id`: matches the IMRO pattern `^NL\.IMRO\.[a-zA-Z0-9.-]+$` when present. This is the single highest-value field on the document because it unlocks the IMRO API cross-validation downstream.

### SourceDocument

Records each input PDF with `filename`, `document_type` (one of `regels`, `toelichting`, `kaveltekening`, `other`), `page_count`, and `sha256`. The sha256 allows partial reruns when one document changes and others have not.

## The Objective

A single `Objective` per project. Captures the urban intent in qualitative form.

- `statement`: a one-sentence summary of what this project is.
- `urban_intent`: 1 to 3 sentences describing the qualitative goal (active plinth, public-space role, urban relationship).
- `programme_intent` (optional): a brief description of programme ambition before any numerical synthesis.
- `provenance`, `confidence` as for all extracted values.

The Objective is the main input to programme inference. The toelichting is its usual source; regels rarely state intent, only rules.

## Constraints

Three kinds of constraint, grouped under `Constraints`.

### NumericalConstraint

The most common kind. A binding numeric rule.

- `id`: lowercase slug, the stable handle for cross-references.
- `name`: human-readable label for the GH parameter and the viewer.
- `category`: one of `height`, `setback`, `parking`, `programme_min`, `programme_max`, `density`, `gfa`, `noise`. Open vocabulary; new categories can be added.
- `value`: a single number or a `(min, max)` tuple for ranges.
- `unit`: one of `m`, `m2`, `per_dwelling`, `per_100m2_bvo`, `ratio`, `percent`, `dB`. Open vocabulary.
- `is_maximum`: True for upper bounds, False for lower bounds, None for exact values.
- `condition`: free-text qualifier like "when building height exceeds 21 m" or "on Gedempt Hamerkanaal facade." Future versions may structure this; for now the GH engineer parses it.
- `applies_to`: list of IDs of GeometricConstraints, programme components, or other entities this rule binds on. Empty means project-wide.
- `provenance`, `confidence`, `cross_validation`.
- `notes`: any ambiguity or context the GH engineer should know.

### GeometricConstraint

A geometric feature that constrains design: plot boundary, bouwvlak, no-build zone, setback zone, dove gevel zone, archaeology zone, water, context building.

- `id`, `name`.
- `feature_type`: one of the values above.
- `coordinates`: closed polygon ring as `list[list[float]]`. Either 2D pairs `[x, y]` or 3D triples `[x, y, z]`. A validator checks that rings have at least four points and that all points have consistent dimensions.
- `crs` (CRS enum): defaults to `RD_NEW` (EPSG:28992). `WGS84` and `DRAWING_LOCAL` are supported; DRAWING_LOCAL should not appear in final outputs.
- `lod`: defaults to 0 (2.5D footprint). LoD 1+ applies to context buildings from the 3D BAG.
- `elevation_m`, `extrusion_height_m`: optional 2.5D extrusion parameters.
- `associated_rules`: list of NumericalConstraint IDs that bind on this feature.

### NarrativeConstraint

Qualitative requirements that cannot reduce to a number. "Active plinth along the Gedempt Hamerkanaal" is a narrative constraint. The Grasshopper engineer needs to know about it even though no formula encodes it.

- `id`, `name`, `description`.
- `applies_to`: optional list of geometric feature IDs.
- `provenance`, `confidence`.

## Variables and KPIs

### Variable, Variables

Each `Variable` represents a design parameter the Grasshopper engineer will sweep. Typology choice, plinth depth, tower position offsets are typical variables.

- `id`, `name`.
- `type`: `float`, `int`, `categorical`.
- `bounds`: `(min, max)` for numeric types; `allowed_values` (list of strings) for categorical.
- `default`: optional default value.
- `rationale`: why this is a variable rather than a constraint.
- `provenance`.

The `Variables` container holds a list under `items`.

### KPI, KPIs

Each `KPI` represents a metric the Run system optimises against: GFA achieved, daylight access, parking efficiency, view quality.

- `id`, `name`, `unit`, `direction` (`maximise` or `minimise`).
- `target`: optional target value.
- `weight`: relative importance, 0.0 to 1.0.
- `provenance`: typically `inferred` for KPIs derived from urban intent.

## Programme

### ProgrammeProposal

The synthesised proposal. Produced by Opus 4.7 at Stage 5 of the build.

- `target_total_gfa_m2`: a single number or a `(min, max)` range.
- `use_split` (UseSplit): GFA breakdown by use category.
- `unit_mix` (list of UnitTypeTarget): residential unit breakdown.
- `parking_demand_total`, `parking_breakdown`: parking spaces by category.
- `reasoning_trace`: ordered list of decision steps. Each step states what was decided and what evidence supported it.
- `requires_designer_input` (list of field names): fields that lack sufficient evidence and need a human.
- `provenance`, `confidence` on the proposal as a whole.

### UseSplit

Breakdown of total GFA across use categories. Standard categories: `residential_m2`, `productive_m2`, `office_m2`, `retail_horeca_m2`, `cultural_m2`, `social_m2`, `other_m2`. A `rationale` field explains the split. Provenance and confidence apply.

### UnitTypeTarget

A target for one residential unit type.

- `typology`: 1-bedroom, 2-bedroom, etc.
- `tenure`: `sociale_huur`, `middenhuur`, `vrije_sector`.
- `target_count`: integer or `(min, max)` range.
- `target_size_m2`: number or `(min, max)` range.
- `provenance`, `confidence`.

## Geographic context

### GeoContext

The composite output of Stage 4 enrichment. Populated when the project has a centroid; absent when geo enrichment was skipped.

- `nearby_buildings` (NearbyBuildingsSnapshot): aggregated BAG and 3D BAG data within 500 m.
- `demographics` (NeighbourhoodDemographics): CBS buurt-level data.
- `transit_access` (TransitAccess): OSM Overpass results for stops and lines.
- `data_sources_used`, `data_sources_failed`: lists of `api_name` strings recording which open APIs returned useful data on this run. Downstream code knows what is missing.

### NearbyBuildingsSnapshot

- `count`, `radius_m`.
- `dominant_uses`: list of (function, fraction) entries.
- `typical_heights_m`: `(min, max)` of nearby building heights.
- `typical_year_built`: `(min, max)`.
- `has_3d_bag_data`: True when the 3D BAG API returned LoD 1.2 geometry; powers the massing context visualisation.

### NeighbourhoodDemographics, TransitAccess

Self-explanatory wrappers around CBS and OSM data respectively. See the schema docstrings for the exact CBS fields captured.

## Massings

### Massing

A single example massing variant. Two are produced at Stage 6b: "Maximum envelope" and "Compliant with setbacks". Their purpose is to demonstrate that the framework's numerical and geometric inputs translate to geometry; they are not the OMRT Run's optimised outputs.

- `id`, `name`, `rationale`.
- `moves` (list of MassingMove): the structural decisions that produced this variant.
- `geometry_file`: relative path to the COMPAS Mesh JSON file under `data/outputs/<project>/massings/`.
- `provenance`: typically `inferred` with `inferred_from` listing the constraint IDs that drove the form.

### MassingMove

A single design move within a massing variant.

- `description`: free text, e.g. "Stepped back at 21 m to comply with setback rule".
- `driven_by`: list of NumericalConstraint or NarrativeConstraint IDs. The cross-reference validator checks these resolve.

## The glossary

### GlossaryTerm

Lives in `data/archive/glossary.json`, not in any ParametricFramework directly. Seeded from the Stelselcatalogus on first run by `scripts/seed_glossary.py` and grown over time.

- `term`: the Dutch term, lowercase. Examples: "plint", "bouwvlak", "peil", "dove gevel".
- `definition`: authoritative definition, in Dutch.
- `definition_en`: optional English summary for reviewer reference.
- `source`: one of `stelselcatalogus`, `imro_2012`, `human_curated`, `municipal`.
- `source_url`: optional URL to the authoritative entry.
- `seen_in_projects`: list of project IDs where this term has been observed. Grows as the archive grows.

At extraction time, the relevant glossary entries are injected into the prompt context so the LLM consults authoritative term definitions rather than relying purely on training data.

## The partial output model

### PartialFrameworkExtraction

The per-page output produced by the extraction agent. All fields are optional because most pages reveal only a few of them. Per-page partials merge into the project-level framework.

This is the only model the extraction LLM is asked to populate. The full ParametricFramework is assembled by the orchestrator, not by the LLM.

## JSON serialisation

Every model uses standard Pydantic JSON serialisation. `framework.model_dump_json()` produces a string; `ParametricFramework.model_validate_json(s)` round-trips it. Coordinates serialise as nested arrays of numbers. Datetimes serialise as ISO 8601 strings with timezone. Enums serialise as their string values.

The output handoff to Grasshopper at Stage 6 writes the JSON to `data/outputs/<project_name>/framework.json` along with the COMPAS geometry files referenced from the Massings.
