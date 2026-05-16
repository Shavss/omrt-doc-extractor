# Architecture

This document describes the architecture of the OMRT document extraction prototype: a pipeline that turns Dutch project document bundles (bestemmingsplan regels, toelichting, kaveltekening) into a validated, structured Parametric Framework that a Grasshopper engineer can consume.

It is the entry point for understanding the system. For the field-by-field schema specification see `schema_reference.md`. For the working plan with time estimates and stage-by-stage prompts see `PROJECT_PLAN.md` at the repository root.

## What this prototype does and does not do

It does: parse a project document bundle, extract a structured framework with provenance and confidence on every value, cross-validate against the authoritative Dutch IMRO API where a plan ID exists, enrich with geo context from open Dutch APIs, infer a programme proposal with evidence-cited reasoning, and present everything for human review before Grasshopper handoff.

It does not: optimise designs, run parametric sweeps, score variants against KPIs, decide on its own to ship a framework, or replace the project manager's judgment. It is a structured-input pipeline, not a design system. The two example massings it produces are illustrative outputs to show that the inputs translate to geometry.

## Design principles

Two principles drive every architectural decision.

**Schema-as-product.** A single Pydantic schema (`schemas.py`) is the contract every other module depends on. The schema is the only thing that must be excellent on day one; everything else can be improved iteratively without breaking the contract. The schema's top-level shape mirrors the OMRT Run system (Objective, Constraints, Variables, KPIs) so the prototype's output drops into the existing parametric pipeline without re-mapping.

**Failure honesty.** A bad number in a parametric framework propagates through every downstream design decision. The architecture assumes errors will happen and is built so they surface visibly. Every extracted value carries provenance (which document, which page, what verbatim text) and confidence (a score and a list of reasons). The output is never authoritative until a human has marked it `reviewed`.

## Data flow

The pipeline is a directed acyclic flow with seven primary stages plus an archive feedback loop. The architecture diagram in `PROJECT_PLAN.md` shows this visually; the description below is the prose equivalent.

A project enters as a folder of PDFs in `data/inputs/<project_name>/`. Per-page preprocessing renders each page to a 200 DPI image and extracts its text layer, producing paired image-and-text per page. Multimodal extraction then runs the page pairs through a PydanticAI agent (Claude Sonnet 4.5) that returns a partial framework with provenance and confidence on every value. Per-page partials merge into a project-level framework. Critical fields (heights, setbacks, parking) get an independent second pass with an open-question prompt; disagreements between passes are flagged, not silently averaged.

In parallel, vector geometry parsing reads the kaveltekening PDF: discover the scale factor dynamically, extract every vector path, classify text labels by IMRO convention (caps for bestemmingen, parentheses for function aanduidingen, brackets for bouwaanduidingen), associate labels with polygons by proximity. Generic fallback to `manual_input_required` if the PDF is raster-only or the scale cannot be derived.

Geo enrichment queries the project centroid against PDOK BAG (2D buildings), the 3D BAG API (LoD 1.2 buildings within 500 m, for the massing context), CBS (buurt demographics), and OSM Overpass (transit, amenities). Each API contributes to the GeoContext; failures are recorded explicitly so downstream code knows what is missing.

The extraction, geometry, and geo data assemble into a populated `ParametricFramework` Pydantic object. The IMRO API cross-validation layer then runs: if the project's plan ID matches the IMRO pattern, every NumericalConstraint is compared against the authoritative value from the Ruimtelijke Plannen API within a 5% tolerance. Disagreement is recorded on the constraint's `cross_validation` field; the value's confidence is reduced and a flag is added. Projects without a plan ID record `agreement='not_attempted'` and continue unchanged.

Programme inference (Claude Opus 4.7) synthesises the framework, the urban intent, and the geo context into a `ProgrammeProposal` with target unit mix, GFA split, parking demand, and a reasoning trace. Each programme decision cites its evidence: a constraint ID, a BAG or CBS data point, or explicit designer judgment.

Output serialises to JSON for the Grasshopper engineer and to a Streamlit viewer for PM review. The viewer surfaces low-confidence fields in red, inferred fields in amber, IMRO disagreements side by side. The PM marks the project `reviewed` only when the framework is verified. Only reviewed projects feed the archive.

## The Scenario 1 defence

The reference failure case from the brief: extraction reports a maximum building height of 32 m, the real permit says 23 m, nobody notices, the client spots it in the results presentation. The architecture defends against this with seven layers of independent checks.

The first layer is provenance. Every value has a Provenance object naming the document, page, and verbatim quoted text. Click any value in the viewer, see the source. Without this, the PM has no way to verify anything.

The second layer is per-field confidence. The LLM reports confidence per extraction. Low confidence is highlighted in the viewer. Confidence is further reduced when the same value is mentioned multiple times with different numbers, when a value falls outside historical bounds, or when the source text uses hedging language like "of meer" or "in principe".

The third layer is dual-pass on critical fields. Heights, setbacks, and parking norms are extracted twice with independent prompts. The first pass uses the structured schema. The second pass asks open questions like "what is the maximum building height anywhere in this document, and where exactly is it stated?" Disagreement between passes is flagged.

The fourth layer is cross-document validation. The regels and toelichting often mention the same numbers in different contexts. If the regels says 70 m and the toelichting mentions buildings up to 80 m, that is a flag.

The fourth-b layer is the strongest. For Dutch projects with a published plan ID, the IMRO Ruimtelijke Plannen API holds the machine-readable canonical version of the plan. Every NumericalConstraint is compared against the authoritative value. Disagreement populates the `cross_validation.agreement='disagreement'` field, adds the `imro_api_disagreement` flag to the confidence, and the viewer surfaces both values side by side.

The fifth layer is universal sanity bounds. A 3000 m residential height is impossible. A 12 per-dwelling parking ratio is impossible. These bounds are universal physics, not municipality-specific assumptions.

The sixth layer is the human review surface. The Streamlit viewer surfaces every flag for PM attention before the framework can be marked reviewed.

The seventh layer is the "never authoritative" gate. Until a human marks a project as reviewed, the viewer banner and the JSON output header both say "PROTOTYPE OUTPUT, NOT VERIFIED."

How this catches the 32m/23m case: dual-pass often catches it because the corrupted number does not appear elsewhere; cross-document validation usually catches it because the toelichting references the same number; the IMRO API cross-validation almost always catches it because the API holds the canonical uncorrupted plan. The deliberately corrupted Draka demo in `docs/corruption_demo.md` (produced in Stage 7b of the build) demonstrates this end-to-end.

The system cannot guarantee zero errors. It can guarantee that errors are visible.

## Generality strategy

The prototype must work on any incoming project document bundle, not only Draka. The architecture achieves this without hardcoding municipality-specific values anywhere.

Discovery over hardcoding. The PDF scale factor is read from the PDF Measure dictionary or derived from "Schaal 1:NNNN" text, never hardcoded. IMRO codes are classified by pattern (caps, parentheses, brackets, dubbelbestemming prefixes), never by enumerated value. Glossary terms are seeded from the national Stelselcatalogus and consulted at extraction time, never baked into Python code.

Coordinate-driven enrichment. Geographic context is derived from the project centroid using national APIs (PDOK, 3D BAG, CBS, OSM) that cover all of the Netherlands uniformly. Switching from Amsterdam to Utrecht requires no code changes.

Graceful degradation. Every external dependency has a documented fallback. If the IMRO API is unreachable, `cross_validation.agreement='not_attempted'`. If the kaveltekening is raster-only, the geometry stage returns `manual_input_required`. If 3D BAG returns no buildings, the massing viewer falls back to no context. The pipeline produces useful output even when half the external services are down.

Universal sanity bounds. Heights between 3 and 200 m. Parking norms between 0 and 4 per dwelling. These bounds are not municipality-specific; they encode universal physical sense.

## The cross-project knowledge layer

A single project is one data point; an archive of verified projects is a dataset. The architecture treats project archiving as a first-class concern because the value compounds over time, even though most of the layer is stubbed in this prototype.

The one part that is fully wired on day one is the glossary. The Stelselcatalogus (the official Dutch national catalog of begrippen for omgevingsdocumenten) is mirrored into `data/archive/glossary.json` by a seeding script. The extraction prompt consults the glossary on every fresh run so vocabulary grounding is real from the first project.

The parts that are typed stubs awaiting more projects: few-shot retrieval (find the K most similar past projects and inject their verified extractions as examples in the prompt), historical sanity bounds (replace universal bounds with municipality and zone-specific distributions), and programme inference grounding (cite "what was built in similar contexts" rather than relying on the LLM's training data).

The critical design rule: only projects with `verification_status='reviewed'` feed the layer. Garbage in stays out.

## Models and external services

**LLMs.** Claude Sonnet 4.5 for multimodal extraction (Stage 2) and dual-pass critical-fields verification. Claude Opus 4.7 for programme inference (Stage 5). All access goes through the PydanticAI framework so swapping models requires changing one string. Ollama with Gemma 3 is used for local prompt iteration during development, never for final extraction.

**Dutch open APIs.** The Ruimtelijke Plannen API v4 (`imro_plannen_v4`) is the authoritative source for pre-2024 bestemmingsplannen and powers the cross-validation layer. The Stelselcatalogus (`stelselcatalogus`) seeds the glossary. PDOK BAG (`pdok_bag`), the 3D BAG API (`pdok_3d_bag`), CBS Open Data (`cbs_demographics`), and OSM Overpass (`osm_overpass`) provide geographic enrichment. All are free with fair-use policies. All responses are cached under `data/cache/` so reruns are cheap.

Notable exclusions and the reason for each: the Bbl (national building code) applies to detailed construction, not massing inputs, so it sits outside this prototype's scope. Amsterdam's municipal Datapunt API would couple the prototype to one gemeente, so we use the national PDOK and CBS equivalents instead. The DSO Omgevingsdocumenten APIs (the post-2024 successor to IMRO) are architecturally supported (the `cross_validation` schema is source-agnostic) but not yet wired; this is a one-day extension listed in the productisation plan.

## Module layout

```
src/omrt_extractor/
├── schemas.py           # Pydantic schema, the central contract
├── preprocess.py        # PDF rendering + text extraction
├── extract.py           # Multimodal LLM extraction (Sonnet 4.5)
├── geometry.py          # CAD vector parsing from kaveltekening
├── enrich.py            # Geo APIs: PDOK, 3D BAG, CBS, OSM
├── cross_validate.py    # IMRO API cross-validation, Scenario 1 Layer 4b
├── infer.py             # Programme inference (Opus 4.7)
├── validators.py        # Sanity bounds, cross-doc checks
├── output.py            # Grasshopper handoff serialisation
├── massing.py           # Example massing generation
├── knowledge.py         # Archive and glossary layer
├── prompts/             # Markdown prompts for each LLM role
└── cli.py               # `omrt run <input_dir>` entry point
```

The order in that list is also roughly the data flow order, with the exception that `cross_validate` runs after the framework is populated but before `infer`, and `knowledge` reads happen during extract while writes happen after a project is marked reviewed.

## What is deferred

Three additions that would be high value in a longer engagement:

The first is full activation of the few-shot retrieval and historical-bounds parts of the knowledge layer. Both are typed stubs today; activating them requires three to five verified projects in the archive and a vector index for similarity queries.

The second is DSO Omgevingsdocumenten cross-validation alongside the IMRO version, covering post-2024 omgevingsplannen. The cross-validation architecture already supports it (different `api_name` in Provenance, same `CrossValidation` structure).

The third is a real CAD parser for raster-only kaveltekeningen. The current behaviour for that case is to return `manual_input_required` and prompt the PM. A vision-model-driven parser is feasible but adds variance that the prototype is not ready to accept.
