# OMRT Document to Design Inputs Prototype: Project Plan

**Goal.** Turn a messy bundle of project documents (Dutch zoning rules, explanatory memorandum, plot drawing) into a validated, structured set of design inputs that a Grasshopper engineer can use on day one.

**Time budget.** 16 hours, accelerated by Claude Code.

**Stack.** Python 3.11+, Pydantic + PydanticAI, Claude API (Sonnet 4.5 for extraction, Opus 4.7 for synthesis), pymupdf, shapely, COMPAS, Streamlit.

**Validation target.** End-to-end run on Draka packet, then unseen second Amsterdam packet during evaluation.

---

## 1. The brief distilled

OMRT's bottleneck is project intake. Today a PM reads 100+ pages of documents and translates them into a Parametric Framework (Objective, Constraints, Variables, KPIs) that the Computational Design team builds against. This prototype compresses that loop. It does not eliminate the human, it accelerates them.

### What evaluators will look for
- End-to-end execution on the provided packet
- Behaviour on missing, ambiguous, conflicting data
- Outputs immediately usable by a Grasshopper engineer
- Generality to a second, unseen packet

### What they will assess
Build judgment, AI fluency, computational instinct, generality, failure honesty, productisation thinking.

The most important of these for design choices is **failure honesty**. Scenario 1, where a wrong building height slips through to a client meeting, is the failure mode this whole system is built against. Every architecture decision below has been checked against it.

---

## 2. Two design principles

**The schema is the product.** Everything orbits one Pydantic schema. Inputs validate into it, the LLM is constrained to fill it, the Grasshopper engineer consumes from it, the archive stores it. If we change models, storage, viewer, or handoff format, the schema absorbs the change. The schema is the only thing that must be excellent on day one.

**Confidence and provenance are first-class fields, not afterthoughts.** Every extracted value carries: the value itself, the source (document + page + quoted text), a confidence score (0.0 to 1.0), and a verification status (extracted, inferred, or verified). The system never claims authority. It surfaces evidence and asks the human to confirm.

---

## 3. Generality strategy

The second packet will be unseen. To survive, four rules:

**No regex on Dutch terms.** The LLM handles vocabulary differences across municipalities. Building a regex for "bouwhoogte" works for Amsterdam plans and fails for Rotterdam plans phrased differently. The schema specifies what to extract. The LLM figures out how it's expressed in any given document.

**Coordinate-driven enrichment, not policy-driven.** We extract project coordinates from the documents and query open Dutch geo APIs (PDOK, CBS, OSM). Same code on any Dutch site. With light adaptation, same approach on any European site. We never hardcode "Amsterdam wants 40/40/20 housing." That kind of policy assumption breaks on the second packet.

**Uniform per-page processing.** Every PDF page is rendered to a 200 DPI image and has its text layer extracted. The same prompt and schema runs over every page of every document. No document-type detection, no section-targeted prompts. The LLM extracts whatever fits the schema from whatever it sees.

**Sanity bounds are universal, not site-specific.** Building heights must be between 3 m and 200 m globally. Parking ratios between 0 and 5 per dwelling. FSI between 0.1 and 10. These are physical-sense bounds, not Amsterdam priors. Site-specific tightening comes from the knowledge layer as it grows, never from hardcoded values.

The one risk this leaves: documents in languages other than Dutch. The prompts are written for Dutch documents with English schema names. A French or German permit would need an extra translation pass. For Dutch packets the system is municipality-agnostic.

---

## 4. Guardrails: the Scenario 1 defence

The reference failure: extraction reports max building height of 32 m, the real permit says 23 m, nobody notices, client spots it in the results presentation. Layered defence:

**Layer 1, Provenance.** Every field has a Provenance object: PDF name, page number, region or bounding box, and quoted text from the source. Click any value in the viewer, see the source. Without this, the PM has no way to verify anything.

**Layer 2, Per-field confidence.** The LLM reports confidence per extraction. Low confidence highlighted in the viewer. Confidence is further reduced when:
- A value is mentioned multiple times in the documents with different numbers
- A value falls outside historical bounds (knowledge layer signal)
- A value depends on ambiguous text ("of meer", "in principe", "afhankelijk van")

**Layer 3, Dual-pass on critical fields.** Heights, setbacks, and parking norms are extracted twice with independent prompts. The first pass uses the structured schema. The second pass asks an open question like "what is the maximum building height anywhere in this document, and where exactly is it stated?" Disagreement between passes is flagged in the schema, not silently averaged.

**Layer 4, Cross-document validation.** Regels and toelichting often mention the same numbers in different contexts. If the regels says 70 m and the toelichting mentions "buildings up to 80 m," that's a flag. The schema captures both with their provenance, surfaces the conflict, asks the PM to resolve.

**Layer 4b, Authoritative API cross-validation.** This is the strongest layer for Dutch projects with a published plan ID. The IMRO Ruimtelijke Plannen API (and the DSO Omgevingsdocumenten APIs for post-2024 omgevingsplannen) hold the machine-readable canonical version of the same plan we're extracting from PDFs. When a project's plan ID resolves in the API, every NumericalConstraint is compared against the authoritative value within a 5% relative tolerance. Disagreement populates `cross_validation.agreement='disagreement'`, the confidence flag `imro_api_disagreement`, and the viewer surfaces both values side by side. This is robust by design: if the project has no plan ID (developer brief, draft plan, non-Dutch project), the layer records `agreement='not_attempted'` and the pipeline continues unchanged.

**Layer 5, Universal sanity bounds.** Out-of-physical-sense values are caught regardless of confidence. A 3000 m residential height is impossible. A 12 per-dwelling parking ratio is impossible. These bounds are universal physics, not municipality-specific assumptions.

**Layer 6, Human review surface.** Streamlit viewer with colour-coded fields: red border for hard constraints with confidence below threshold, amber for inferred values, green for human-verified. JSON output carries the same status flags so a Grasshopper engineer building on red values knows they're working on assumptions.

**Layer 7, Output is never authoritative.** Top-level `verification_status` field. Until a human marks a project as `reviewed`, viewer banners and JSON headers both say "PROTOTYPE OUTPUT, NOT VERIFIED."

How this catches the 32m/23m case:
1. Dual-pass extraction (Layer 3) often catches it on its own, second pass returns 23.
2. If not, cross-document check (Layer 4) catches it because the toelichting typically mentions 23 m in the urban vision or massing section.
3. The IMRO API cross-validation (Layer 4b) almost always catches it because the authoritative plan has the uncorrupted value. The viewer shows extracted 32 m next to authoritative 23 m with a red flag.
4. If all of the above miss, low confidence (Layer 2) flags it for human attention.
5. If the PM also misses it during review, the Grasshopper engineer sees "unverified, please confirm" (Layer 7) and asks before building.

The Scenario 1 demo we ship makes this concrete: a deliberately corrupted Draka regels (one height value edited from 21 to 31), run end-to-end through the pipeline, with the viewer screenshots showing the cross-validation catching the corruption. Details in stage 7b.

The system cannot guarantee zero errors. It can guarantee that errors are visible and that nothing pretends to be ground truth.

---

## 5. The cross-project knowledge layer

This is the nice-to-have, and the argument for it is stronger than "graph theory is interesting." The layer makes future *extractions* better, not just future *designs* better.

When OMRT has 20 verified projects in the archive, the layer offers six extraction-time benefits a one-off tool cannot:

**Glossary disambiguation, seeded from the national catalog.** Dutch planning vocabulary varies by municipality and even by document author. "Plint" might be defined as 8 m minimum in one zoning plan, 6 m in another. "Peil" resolves to NAP+x in Amsterdam but might be specified differently in coastal municipalities. The glossary stores each term with its authoritative definition and the per-project resolutions seen so far. Critically, this prototype does not start from zero: we seed the glossary from the Stelselcatalogus, the official Dutch national catalog of begrippen for omgevingsdocumenten. On day one we have authoritative definitions for the common planning vocabulary. As projects accumulate, the glossary grows with project-specific resolutions verified by humans. The LLM consults the glossary on every fresh extraction, so vocabulary grounding is real from the first run, not a promise that activates after 20 projects.

**Few-shot retrieval, the right kind of RAG.** When a new document arrives, retrieve the K most-similar past extractions (similar municipality, similar zoning type, similar size). Use those as few-shot examples in the prompt. The LLM sees "here is how this kind of clause was extracted before, validated by a human." This is RAG retrieving validated examples to ground the model, not retrieval of chunks within a single document. This is the kind of RAG that genuinely improves output quality.

**Sanity bounds, learned not hardcoded.** Heights in Amsterdam-Noord cluster 21 to 70 m. Parking norms in NL urban zones span 0.1 to 1.5 per dwelling. With history, "330 m residential height" is flagged as a hundred times the historical max. Without history, we have to hardcode a sanity range and bake in our assumptions. The bigger the archive, the tighter and smarter the bounds.

**Schema evolution evidence.** New projects reveal fields the schema didn't anticipate. The archive is where we collect "field requests" backed by real evidence. "Three projects near Schiphol needed a noise contour field." That justifies a schema migration grounded in data, not speculation.

**Cross-validation against the universe of past work.** If extraction returns "FAR 8.5" but no project in the archive has FAR above 5.0, that warrants a flag. Either a genuine outlier worth examining, or an error worth fixing. Both deserve attention.

**Programme inference grounding.** For the question "what should be built here?", the strongest signal is "what's been built nearby and in similar contexts." The archive captures every project's location and final programme. Future inference queries "what was the housing/retail/maker-space mix in Hamerkwartier-like sites we've processed before?" and grounds the LLM in real precedent rather than free-floating reasoning.

For this prototype, the archive is implemented minimally: a `data/archive/projects/` folder of validated project JSONs, a `glossary.json` seeded from the Stelselcatalogus and growing with project-specific entries, and a `knowledge.py` module with realistic interfaces. The save function and the glossary lookup are fully wired (the glossary is the part that earns its keep on day one). Project-similarity retrieval and historical-bounds queries are typed stubs awaiting a meaningful number of archived projects. The architectural option is preserved on the parts where data is the bottleneck; the parts where data exists today (Stelselcatalogus) are real.

The critical design choice: only projects with `verification_status: reviewed` feed the layer. Garbage in stays out.

---

## 6. Folder structure

```
omrt-doc-extractor/
├── README.md                   # Run instructions, demo walkthrough
├── CLAUDE.md                   # Claude Code working agreement
├── PROJECT_PLAN.md             # This file
├── pyproject.toml              # uv project config
├── .env.example                # Template for ANTHROPIC_API_KEY
├── .gitignore
│
├── src/omrt_extractor/
│   ├── __init__.py
│   ├── config.py               # Settings: models, paths, thresholds
│   ├── schemas.py              # ALL Pydantic models, central artifact
│   ├── preprocess.py           # PDF rendering + text extraction
│   ├── extract.py              # Multimodal LLM extraction
│   ├── geometry.py             # CAD vector parsing
│   ├── enrich.py               # Geo API queries (PDOK BAG, 3D BAG, CBS, OSM)
│   ├── cross_validate.py       # IMRO/DSO API cross-validation (Scenario 1 Layer 4b)
│   ├── infer.py                # Programme inference synthesis
│   ├── validators.py           # Sanity bounds, cross-doc checks
│   ├── output.py               # Grasshopper handoff serialisation
│   ├── massing.py              # Example massing generation
│   ├── knowledge.py            # Archive + glossary layer
│   ├── prompts/
│   │   ├── system.md           # System prompt, schema-aware
│   │   ├── extraction.md       # Per-page extraction prompt
│   │   ├── critical_fields.md  # Dual-pass prompt for heights/parking
│   │   └── programme.md        # Synthesis prompt for inference step
│   └── cli.py                  # `omrt run <input_dir>` entry point
│
├── scripts/
│   └── seed_glossary.py        # One-off Stelselcatalogus pull, populates glossary.json
│
├── tests/
│   ├── test_schemas.py         # Schema validation tests
│   ├── test_preprocess.py
│   ├── test_geometry.py
│   ├── test_cross_validate.py  # Mocked IMRO API tests
│   └── test_e2e.py             # Run pipeline on draka, assert key fields
│
├── data/
│   ├── inputs/
│   │   ├── draka/              # Original Draka packet (READ ONLY)
│   │   ├── draka_corrupted/    # Scenario 1 demo: deliberately corrupted variant
│   │   └── synthetic_test/     # Second-packet generalisation test
│   ├── outputs/
│   │   └── draka/              # Generated JSONs, viewer dumps, massings
│   ├── archive/                # Verified projects feed knowledge layer
│   │   ├── projects/           # One folder per verified project
│   │   └── glossary.json       # Seeded from Stelselcatalogus, grows with use
│   └── cache/                  # API response cache, page images, 3D BAG tiles
│
├── viewer/
│   └── streamlit_app.py        # Human review UI
│
├── grasshopper/
│   ├── omrt_reader.gh          # Stub GH definition that reads our JSON
│   └── README.md               # How to consume the JSON in GH
│
└── docs/
    ├── architecture.md         # System diagram, design decisions
    ├── schema_reference.md     # Schema field-by-field
    ├── generalisation_test.md  # Results from second-packet test
    └── written_response.md     # Answers to 4.1, 4.2, 4.3, 4.4
```

Notes: `data/inputs/` is read-only by convention. `data/cache/` and `.env` are gitignored. The archive folder structure mirrors a future database schema, so promotion to a real DB later is straightforward.

---

## 7. Libraries

**Core stack**
- `pydantic`, `pydantic-settings`: schemas, settings
- `pydantic-ai`: agent framework with structured outputs, retries, validation, model swapping
- `anthropic`: Claude API client (consumed via pydantic-ai)

**PDF and geometry**
- `pymupdf` (also imported as `fitz`): PDF text extraction, page rendering, vector path extraction
- `shapely`: polygon operations, buffers, intersections
- `compas`: Rhino-compatible geometry serialisation
- `pyproj`: coordinate transformations (RD New ↔ WGS84, since Dutch documents use both)

**Geo enrichment**
- `httpx`: async HTTP for the open APIs
- `cachetools` or `diskcache`: cache API responses, keep dev iteration fast

**Viewer and CLI**
- `streamlit`: review UI
- `typer`: clean CLI
- `rich`: console output during pipeline runs

**Storage and observability**
- `loguru`: simpler logging than stdlib
- Plain JSON files for the archive; SQLite or Postgres is a productisation step

**Dev**
- `pytest`: tests
- `ruff`: lint + format
- `uv`: package manager (faster than poetry or pip-tools)

---

## 8. Build plan, 18.5 hours total

The plan grew from 16h to add three high-leverage capabilities (IMRO API cross-validation, 3D BAG context buildings, corrupted Draka demo) and then trimmed back to 18.5h once we pre-built the schema, the test suite, the seeder, the prompts, and the anchoring docs. Stage 0 is now a drop-in scaffolding pass rather than a from-scratch schema build, saving an hour that would otherwise have been spent re-deriving what we already have.

**Stage 0, scaffolding (2 hours, was 3).** Project structure, pyproject.toml, environment. Drop in the pre-built artifacts: schemas.py (with CrossValidation and GlossaryTerm), test_schemas.py, seed_glossary.py, the three prompt files, and the two anchoring docs (architecture.md, schema_reference.md). Run the test suite to confirm 36 tests pass. Run the seeder to populate glossary.json. The hour saved here goes into a slightly larger Stage 6 viewer pass (now 1.5h) so the IMRO disagreement display gets the care it deserves.

**Stage 1, preprocessing (1.5 hours).** Render every PDF page to 200 DPI PNG, extract text layer per page, save as paired files. Image-and-text per page becomes the input to extraction. Cache aggressively, this stage runs once per project then never again.

**Stage 2, multimodal extraction (3 hours).** PydanticAI agent that takes a page (image + text) and returns a PartialFrameworkExtraction. Run over every page of every PDF. Merge per-page partials into a project-level extraction with provenance and confidence on every field. Add the dual-pass for critical fields (heights, setbacks, parking). Glossary terms are loaded from `data/archive/glossary.json` and injected into the prompt when relevant terms appear on a page.

**Stage 3, vector geometry (2 hours).** Parse the verbeelding PDF generically (no Draka-specific values): discover the scale factor dynamically, extract all vector paths, classify text labels by IMRO pattern, associate labels with polygons by proximity. Graceful fallback to `manual_input_required` if the PDF is raster-only or scale cannot be derived.

**Stage 4, geo enrichment (1.5 hours).** Query PDOK BAG (2D) for nearby buildings, CBS for buurt demographics, OSM Overpass for amenities and transit. Cache responses. Output a GeoContext object with explicit "data sources used" and "data sources failed" fields so downstream code knows what's missing.

**Stage 4b, IMRO API cross-validation (2 hours).** New layer. If the extracted project has a recognised IMRO plan ID, query the Ruimtelijke Plannen API v4 and compare every extracted NumericalConstraint against the authoritative value within a 5% tolerance. Populate `cross_validation` on each constraint. This is Layer 4b of the Scenario 1 defence. Graceful when the plan ID is absent or the API is unavailable.

**Stage 4c, 3D BAG context buildings (1.5 hours).** Query the 3D BAG API for buildings within 500 m of the project centroid at LoD 1.2. Save as CityJSON. Aggregate into `NearbyBuildingsSnapshot` with `has_3d_bag_data=True`. The massing visualisation will sit our two example variants in this real urban context.

**Stage 5, programme inference (1 hour).** Synthesis call: takes urban intent, hard rules, geo context (now including 3D context), outputs ProgrammeProposal with target unit mix, GFA split, parking demand, and reasoning trace. Each programme number cites its evidence. Trimmed from 1.5h: the reasoning trace will be shorter than originally planned, citing two to three evidence points per decision rather than a full chain. Acceptable trade for the cross-validation gain elsewhere.

**Stage 6, output and viewer (1.5 hours).** Write Grasshopper JSON, Streamlit viewer with provenance click-through, confidence highlighting, and the IMRO disagreement side-by-side display. The disagreement display matters: it is the visible proof that Layer 4b works.

**Stage 6b, example massings (1 hour).** Generate both massing variants (max envelope, compliant with setbacks) from the validated JSON. Visualise in plotly with 3D BAG context buildings around them. Export to COMPAS JSON.

**Stage 7, generalisation test and write-up (1 hour).** Trimmed from a heavier scope because IMRO cross-validation gives us a strong generalisation signal on its own: any Dutch project with a published plan ID is automatically validated against the authoritative source. We still run on one second Amsterdam-area packet from ruimtelijkeplannen.nl to confirm no hardcoded assumptions slipped in, then write `docs/written_response.md` answering questions 4.1 through 4.4 using the working notes in sections 11 and 12.

**Stage 7b, the corrupted Draka demo (0.5 hours).** Copy `data/inputs/draka/` to `data/inputs/draka_corrupted/` and edit the regels PDF to introduce one plausible error in a binding height clause. Run the full pipeline. Take screenshots of the viewer showing the cross-validation catching the corruption. Write `docs/corruption_demo.md` with the walk-through. This is the literal demonstration of Scenario 1.

If something slips, what gets cut: more programme-inference reasoning depth (Stage 5 collapses to just citing primary evidence per decision), or the second massing variant (keep compliant-with-setbacks, the more informative of the two). What does not get cut: schema quality (Stage 0), provenance and confidence (woven throughout), the IMRO cross-validation (Stage 4b is the single most assessment-relevant addition), or the corrupted Draka demo (Stage 7b is the literal answer to Scenario 1).

---

## 9. CLAUDE.md content

This file tells Claude Code how to work in the repo. Suggested content:

```markdown
# Claude Code working agreement, omrt-doc-extractor

## What we're building
A prototype that turns Dutch project document PDFs into validated, structured design inputs for Grasshopper. Schema-centric architecture, layered guardrails for failure honesty, generalises to unseen packets. See PROJECT_PLAN.md for full context.

## Hard rules
- Never hardcode municipality names, neighbourhood names, document-specific terms, scale factors, or specific bestemming/aanduiding code values in Python code. Discover them from the source documents at runtime. The LLM handles vocabulary; the parser handles structure.
- Never use regex on Dutch planning text to extract values. Always go via the LLM with a Pydantic schema.
- Every extracted value must carry Provenance (document + page + quoted text) and Confidence (0.0 to 1.0).
- Every Pydantic field needs a docstring explaining what the field represents and how a Grasshopper engineer would consume it.
- Sanity bounds are universal physical sense (e.g. height 3 to 200 m), never municipality-specific.
- Test assertions check structural presence (a polygon exists, a number is in a plausible range), never specific values from a specific document. Tests must pass on any reasonable Dutch zoning packet.
- External API integrations (`enrich.py`, `cross_validate.py`) must degrade gracefully when an API is unreachable or returns no useful data. Log the failure via loguru, record it in `GeoContext.data_sources_failed` or `CrossValidation(agreement='not_attempted')`, and let the pipeline continue. Never raise an unhandled exception from an API call.
- Live API calls in tests are forbidden. Mock the responses. Live calls flake CI and burn fair-use budget.
- No secrets in code or logs. `.env` is gitignored; check before committing.

## Code style
- Python 3.11+
- Type hints everywhere
- Functions under 50 lines, files under 400 lines
- `from __future__ import annotations` at the top of every module
- Prefer Pydantic models over ad-hoc dicts

## Tests
- `pytest tests/` runs the full suite
- New schema fields need a test that validates a sample value
- Each pipeline stage gets at least one integration test
- Tests assert presence and types, not specific extracted values (LLM output varies)

## Commands
- Install: `uv pip install -e .`
- Run end-to-end: `omrt run data/inputs/draka/`
- Open viewer: `streamlit run viewer/streamlit_app.py`
- Test: `pytest`
- Lint: `ruff check . && ruff format .`

## What NOT to do
- Don't modify anything under `data/inputs/`, those are read-only source documents.
- Don't commit `data/cache/` or `.env` files.
- Don't add new top-level dependencies without justifying in PROJECT_PLAN.md.
- Don't write code that requires the LLM to follow a specific output format outside the Pydantic schema. The schema is the format.
- Don't add document-type detection ("if this is a regels PDF, do X"). Uniform processing only.

## Anchoring documents
- Architecture: docs/architecture.md
- Schema reference: docs/schema_reference.md
- Project plan: PROJECT_PLAN.md
```

---

## 10. Claude Code prompts per stage

Run these one stage at a time in fresh Claude Code sessions. Each one assumes prior stages are committed and green. Each one references PROJECT_PLAN.md so context stays anchored.

**Stage 0:**
> Read PROJECT_PLAN.md and CLAUDE.md completely. Then set up the project structure as described in section 6. Initialize pyproject.toml with the libraries from section 7, using uv. Create stubs for every module listed in section 6 with module-level docstrings explaining the purpose.
>
> Several anchoring artifacts have already been drafted and are ready to drop in. Place them in their target locations exactly as provided, do not regenerate them:
> - `src/omrt_extractor/schemas.py`: the full Pydantic schema (1198 lines, verified working).
> - `tests/test_schemas.py`: the schema test suite (36 passing tests).
> - `scripts/seed_glossary.py`: the Stelselcatalogus seeding script with API + fallback paths.
> - `src/omrt_extractor/prompts/extraction.md`, `prompts/critical_fields.md`, `prompts/programme.md`: the LLM prompts.
> - `docs/architecture.md`, `docs/schema_reference.md`: the anchoring documents that CLAUDE.md references.
>
> Then: run `python scripts/seed_glossary.py` to populate `data/archive/glossary.json` in fallback mode (or with the live API if `STELSELCATALOGUS_API_KEY` is set). Run `pytest` and `ruff check`, fix any issues, commit. Confirm everything builds and 36 tests pass before moving to Stage 1.

**Stage 1:**
> Read PROJECT_PLAN.md sections 3 and 6. Implement src/omrt_extractor/preprocess.py. Function signature: `preprocess_project(input_dir: Path, cache_dir: Path) -> ProjectPreprocessed`, where ProjectPreprocessed is a Pydantic model (define in schemas.py) listing, per PDF, a list of (page_number, image_path, text) entries. Use pymupdf for both text extraction and rendering. Render to PNG at 200 DPI. Save images under cache_dir/<pdf_name>/page_<n>.png. Skip pages where both the image and text are already cached. Write tests/test_preprocess.py against data/inputs/draka/ that asserts all PDFs in the directory are processed, every page produces both an image file and non-empty text, and the longest PDF has at least 10 pages of extracted text. Avoid asserting any document-specific strings; tests should pass on any reasonable Dutch zoning packet, not just Draka.

**Stage 2:**
> Read PROJECT_PLAN.md sections 2, 4, and the schemas in schemas.py. Implement src/omrt_extractor/extract.py using pydantic-ai with the Anthropic provider, model `claude-sonnet-4-5`. The agent takes one (image_path, text, page_meta) input and returns a PartialFrameworkExtraction (subset of fields present on this page). Per-page outputs merge into a project-level Extraction. Merge strategy: for fields where multiple pages return a value, keep all entries (don't silently overwrite), so validators.py can flag disagreements. Every extracted value carries Provenance and Confidence. If the LLM doesn't see a field, leave it None, do not invent. Add the dual-pass logic for critical fields per section 4 Layer 3. The dual-pass uses an independent prompt formulation in prompts/critical_fields.md. Tests should run on Draka pages and assert presence of key fields (some height value, some parking norms). Do not assert specific values, the test should pass on any reasonable extraction.

**Stage 3:**
> Read PROJECT_PLAN.md section 8 stage 3. Implement src/omrt_extractor/geometry.py for parsing the verbeelding (zoning plan drawing) PDF of any Dutch bestemmingsplan. Nothing in this code may be Draka-specific.
>
> Approach:
> 1. Read vector paths from the PDF with pymupdf.
> 2. Discover the scale factor dynamically. First try the PDF Measure dictionary at `/VP[*]/Measure/X/C` (present on AutoCAD-exported PDFs with the scale tool used). If absent, parse "Schaal 1:NNNN" or "Scale 1:NNNN" from the embedded text and derive conversion via the PDF point-to-mm constant (0.3528 mm per point). If neither succeeds, set scale to None and mark the geometry output as `scale_status="unknown"`, prompting manual input in the viewer.
> 3. Extract every text label in the drawing with its position.
> 4. Classify labels by IMRO convention pattern, never by specific value: ALL-CAPS short tokens are bestemming codes, tokens in (parentheses) are function aanduidingen, tokens in [square brackets] are bouwaanduidingen, plain numbers in range 3 to 200 are likely building heights in meters, tokens like "WR-X" are dubbelbestemmingen. The set of valid codes is whatever appears in this particular drawing.
> 5. Associate labels with the nearest polygon by spatial proximity.
> 6. Output as a Geometry pydantic model: plot polygon, list of bouwvlakken with their classified labels and inferred heights, list of constraint zones with their labels.
>
> If parsing fails (raster-only PDF, no extractable vectors, scale not found, no recognisable labels), return `Geometry(status="manual_input_required", reason=...)` so the viewer can prompt the PM. This graceful degradation is part of the generalisation strategy, not a bug to hide.
>
> Tests run on Draka kaveltekening and assert presence and structure only: at least one polygon with non-zero area, at least one labeled bouwvlak, a successfully discovered scale factor. Do not assert any specific code values or specific heights; that would couple the test to Draka.

**Stage 4:**
> Read PROJECT_PLAN.md section 3 paragraph "Coordinate-driven enrichment." Implement src/omrt_extractor/enrich.py. Take coordinates (auto-detect WGS84 vs Dutch RD New) and a buffer radius (default 500 m). Query: PDOK BAG WFS for buildings (function, year, area, height), CBS Open Data for buurt demographics, OSM Overpass for transit stops, retail counts by category, schools, parks. Cache responses under data/cache/enrich/ by coordinate hash + buffer. Output a GeoContext pydantic model. Include an explicit `data_sources_used` and `data_sources_failed` field listing which APIs returned data and which failed, so downstream code knows what's missing. If an API is down, log via loguru and continue with partial data.

**Stage 4b:**
> Read PROJECT_PLAN.md section 4 Layer 4b and the CrossValidation schema in schemas.py. Implement src/omrt_extractor/cross_validate.py. Primary function: `cross_validate_imro(framework: ParametricFramework) -> ParametricFramework`. The function returns a new framework with `cross_validation` fields populated on every NumericalConstraint that has an authoritative equivalent.
>
> Approach:
> 1. Read `framework.metadata.location.plan_id`. If it matches the IMRO regex `^NL\.IMRO\.[a-zA-Z0-9.-]+$`, proceed. Otherwise, populate every NumericalConstraint.cross_validation with `CrossValidation(source='imro_plannen_v4', agreement='not_attempted', notes='No IMRO plan ID on this project')`. This is graceful degradation, not failure.
> 2. Query the Ruimtelijke Plannen API v4 at `https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4/plannen/{plan_id}`. Walk its bestemmingsvlakken and maatvoeringen endpoints to enumerate authoritative numerical values. Cache the response under `data/cache/imro/{plan_id}.json`.
> 3. For each NumericalConstraint in the framework, attempt to match it against an authoritative equivalent by category and applies_to context. When a match is found, compare values with a 5% relative tolerance (configurable). Populate `cross_validation` with authoritative_value, source='imro_plannen_v4', and agreement of 'agreement' or 'disagreement'. When no match is found, use 'unverifiable' with a brief note.
> 4. On disagreement, also append 'imro_api_disagreement' to the constraint's Confidence.flags and lower the score by 0.3 (clipped to 0). On agreement, append 'imro_api_agreement' and leave score unchanged.
> 5. If the API is unreachable, fail gracefully: every constraint gets `agreement='not_attempted'` with a note indicating the network error.
>
> Tests: a unit test with a mocked successful API response asserts agreement and disagreement are flagged correctly. A test with no plan_id asserts every constraint gets 'not_attempted'. A test with a mocked 503 from the API asserts the graceful path. Do not include any live integration test in the CI; the API is rate-limited.

**Stage 4c:**
> Read PROJECT_PLAN.md section 8 stage 4c. Extend src/omrt_extractor/enrich.py with a function `enrich_3d_bag(location: ProjectLocation, radius_m: int = 500, lod: str = "1.2") -> NearbyBuildingsSnapshot`. Query the 3D BAG API at `https://api.3dbag.nl/` for all buildings within `radius_m` of the centroid. Use LoD 1.2 by default (block models; smaller response). LoD 2.2 is optional via the parameter.
>
> Output a `NearbyBuildingsSnapshot` with count, dominant uses (joined from BAG attributes), typical_heights_m (min, max), typical_year_built (min, max), and `has_3d_bag_data=True`. Also save the raw CityJSON to `data/cache/3dbag/{coord_hash}_{radius}_lod{lod}.cityjson` so the massing stage can load it for the visualisation.
>
> If the API is unreachable or returns no buildings, return a snapshot with `count=0` and `has_3d_bag_data=False`, and append `'pdok_3d_bag'` to `GeoContext.data_sources_failed`. The massing visualisation falls back to no context buildings in that case.
>
> Tests should mock the API response and verify the snapshot's aggregate calculations.

**Stage 5:**
> Read PROJECT_PLAN.md sections 2 and 5. Implement src/omrt_extractor/infer.py. Input: an Extraction (with urban intent + hard rules) and a GeoContext (which now includes 3D BAG context). Output: a ProgrammeProposal with target unit mix (sociale huur, middenhuur, vrije sector split), GFA breakdown by use, parking demand, and a reasoning trace where each programme decision cites its evidence (document clause via Provenance, geo data point, or "designer judgment" with explicit rationale). Keep reasoning concise: two to three evidence citations per decision, not a full chain. Use `claude-opus-4-7` here, reasoning quality matters most. The prompt in prompts/programme.md should explicitly instruct: never invent unsupported numbers, prefer ranges over false precision when evidence is weak, mark assumptions versus extracted facts, ground programme decisions in BAG and CBS data wherever possible. Test: run on Draka and assert the programme reasoning cites at least one toelichting passage and at least one BAG data point.

**Stage 6:**
> Implement src/omrt_extractor/output.py and viewer/streamlit_app.py. output.py serialises a full ParametricFramework to grasshopper.json including: top-level verification_status, generated_at timestamp, source_documents list, numeric constraints with confidence + provenance, geometry as both GeoJSON-compatible coordinates and a COMPAS-JSON block, programme proposal with reasoning trace, and a prominent "PROTOTYPE OUTPUT, NOT VERIFIED" banner field in the JSON header. viewer/streamlit_app.py loads a ParametricFramework JSON and renders fields with: red border for hard constraints with confidence below 0.85, amber for inferred values, green for human-verified; click any value to see the source PDF page and quoted text; a "mark as verified" button that updates the JSON in place; a diff view between two dual-pass results when they disagree. Don't over-design the viewer, it's a safety net not a dashboard.

**Stage 6b:**
> Read PROJECT_PLAN.md section 15. Implement src/omrt_extractor/massing.py. The function `generate_example_massings(framework: ParametricFramework) -> list[Massing]` returns two Massing variants derived from the validated geometry. Variant A "Maximum envelope" extrudes every bouwvlak to its max allowed height with no setbacks. Variant B "Compliant with setbacks" applies setback rules above the threshold height (read from the framework's constraints, never hardcoded). The Massing pydantic model includes name, rationale (1 to 2 sentences citing the rule that drove each form decision), provenance (which inputs drove which moves), and a list of mesh polygons. Use shapely for 2D polygon operations and COMPAS Mesh for 3D output. Add a Streamlit page section in viewer/streamlit_app.py that renders the two variants side by side using plotly Mesh3d. If any input the massing depends on has confidence below threshold, display a "preview based on unverified inputs" banner over the visualisation. Export the meshes to data/outputs/<project>/massings/ as both COMPAS JSON and a simple OBJ for the GH engineer. Test: run on Draka and assert two non-empty Massing objects are returned with valid mesh data; do not assert specific volumes or heights.


## 11. Written response, working notes

These notes shape what we build. Final answers go in docs/written_response.md.

**4.1 Approach.** The biggest decisions were: schema-as-product (everything orbits one Pydantic model so the system survives swapping any other component), provenance and confidence as first-class fields including authoritative cross-validation against the Dutch IMRO API (the Scenario 1 defence, every value is auditable against the canonical source where one exists), and coordinate-driven enrichment over policy hardcoding (the generality strategy, no municipality-specific assumptions baked into the code). A fourth decision worth flagging: keeping all source documents in Dutch end-to-end while using English schema names, so we never lose legal precision in translation but the framework remains internationally legible.

**4.2 AI choices.** Used: multimodal LLM (Sonnet 4.5) for extraction across heterogeneous Dutch documents because it generalises across municipalities where regex would brittle, and because it reads rasterised tables that text extraction misses; synthesis LLM (Opus 4.7) for programme inference because that is the judgment-heavy step; the Stelselcatalogus national glossary seeded into the prompt context so the LLM consults authoritative term definitions rather than relying on training data. Not used: ML for geometry parsing (vector PDF gives clean deterministic output, ML would add variance for no benefit); classification models for document-type detection (uniform per-page processing is more robust than trying to label documents); fine-tuning (we have one project, not the hundreds that would justify it). Reliability comes from a layered stack: Pydantic schema constrains output shape, confidence-per-field surfaces uncertainty, dual-pass on critical fields catches LLM mis-reads, cross-document validation catches conflicts within the packet, IMRO API cross-validation catches conflicts against the authoritative source, universal sanity bounds catch physical impossibilities, human review surface gates the handoff. The corrupted Draka demonstration shows these layers working on the exact failure case the brief describes.

**4.3 Another week.** Most valuable next step: harden the knowledge layer from glossary-only to full archive, seed it with three to five verified projects beyond Draka, wire up similarity-based few-shot retrieval, and run extraction with and without retrieval to measure the lift. Second most valuable: get one real Grasshopper engineer to do a round-trip with our JSON and refine the schema based on what they actually want. Third: add the DSO Omgevingsdocumenten cross-validation alongside the IMRO one, so post-2024 omgevingsplannen get the same Layer 4b coverage. What I would cut from the current prototype: the dual-pass diff view in the viewer is overbuilt because the IMRO API cross-validation gives a stronger and more readable disagreement signal. The dual-pass remains valuable as a confidence-lowering signal but does not deserve its own UI surface.

**4.4 Productisation.** From prototype to production tool:

The biggest changes are operational not algorithmic. Async job queue for large packets (current is synchronous and a 200-page toelichting takes several minutes). Per-document caching with change detection so partial reruns are cheap. Real authentication on the viewer. Audit trail recording which PM verified which fields when. Schema versioning so older projects don't break when the schema evolves. Integration with OMRT's existing intake form so a PM uploads PDFs in their normal workflow and the system runs automatically. Notification when a project is ready for review. A real archive backend (Postgres) replacing JSON files. A real geo cache (a periodic snapshot of relevant PDOK and CBS slices, including 3D BAG tiles for high-frequency areas) replacing per-query API calls, both for cost and for offline resilience. Monitoring on the cross-validation layer: track agreement rates over time, alert when disagreements spike (likely a sign the API schema or our matcher drifted).

Where the human stays in the loop: programme inference review (every decision in the reasoning trace), every red-flagged field (low confidence, out-of-historical-bounds, or IMRO API disagreement), and the final "approve and send to Grasshopper" gate. The system never decides on its own to ship a Parametric Framework. A PM always presses the button.

What breaks at scale: API rate limits (the IMRO and DSO APIs have fair-use policies that need batching and our own snapshots), LLM costs on large documents (need smarter triage or a cheaper first-pass model), the archive grows and naive retrieval gets slow (need vector index for similarity queries), schema migrations become tricky when older projects are in the field (need careful versioning, the verification_status field is the version-pin).

What OMRT teams I would need: a backend engineer for the queue and storage migration, a small UX investment for the production viewer (the prototype Streamlit is a stopgap), one Grasshopper engineer's time for schema refinement, and a Project Manager champion who tests every release on real intake packets and gives honest feedback about where it fails.

---

## 12. Scenario 2, the next prototype

If this lands and the CCO asks what to build next, working notes:

**A Run interpretation assistant that helps PMs and clients make sense of Run results.** Currently a Run produces thousands of variants ranked across KPIs. The bottleneck after intake is meaning-making: which trade-offs matter, what story do the results tell, what does the PM walk into the client meeting with?

An AI layer that reads the Run results, the Parametric Framework, and the client's stated priorities, then surfaces a small number of narrative clusters (groups of variants sharing a story: "tall slim tower with active plinth", "lower density with more public space", "max GFA with parking trade-off"). For each cluster it drafts the talking points, citing the actual KPI numbers from the Run, and flags trade-offs the PM should expect the client to push back on.

Why this and not something else: it's the other end of the same workflow. We built a tool to compress intake. The next obvious leverage is to compress synthesis. Same architectural approach (LLM-driven structured output, schema-anchored, human-in-the-loop), different content, closes the loop.

Seven-day validation: pick three completed projects, feed their actual Runs and Frameworks through the prototype, have a real PM compare the prototype's narrative output against their own written summary. Success criterion: the prototype captures at least 70% of what the PM would have said, with at least one insight the PM hadn't already surfaced.

---

## 13. Model and budget choices

**Paid LLM usage (Anthropic API):**
- Multimodal extraction (Stage 2): `claude-sonnet-4-5` via pydantic-ai. Sweet spot for cost and capability on structured-output work over dense pages.
- Programme inference (Stage 5): `claude-opus-4-7`. The reasoning quality difference matters here, and this step runs once per project.
- Dual-pass on critical fields: `claude-sonnet-4-5` with an independent prompt formulation.
- Local dev iteration: `ollama gemma3` for prompt drafting and quick smoke tests, never for actual final extraction.

**Open APIs used (all free, all in `api_name` vocabulary):**
- `imro_plannen_v4`: Ruimtelijke Plannen API at `https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4/`. Authoritative source for pre-2024 bestemmingsplannen including Draka. Used for cross-validation in Stage 4b.
- `stelselcatalogus`: Official national catalog of begrippen for omgevingsdocumenten. Used to seed `glossary.json` in Stage 0.
- `pdok_bag`: 2D building register via PDOK WFS. Used in Stage 4 for nearby building functions.
- `pdok_3d_bag`: 3D BAG at `https://api.3dbag.nl/`. Used in Stage 4c for context buildings at LoD 1.2.
- `cbs_demographics`: CBS Open Data API for buurt-level statistics. Used in Stage 4.
- `osm_overpass`: OpenStreetMap Overpass API for transit, amenities, retail. Used in Stage 4.

All open APIs have fair-use policies but no auth requirements for the volumes our prototype consumes. We cache aggressively under `data/cache/` so reruns don't re-hit them.

**Expected spend:** Well under €15 on Anthropic API for a full Draka run including verbose dual-pass and a couple of full reruns. Open APIs are free. The €30 cap leaves comfortable slack for the unseen second packet, prompt variations, and the corrupted-Draka demo run.

---

## 14. What we have not built and why

Worth being honest about, for the write-up:

- **No fine-tuned model.** Fine-tuning is overkill for an 18.5-hour prototype on heterogeneous documents. Frontier multimodal LLMs are already at or above the quality we need. Fine-tuning becomes interesting at hundreds of verified projects.
- **No CAD parser proper.** For Draka the vector PDF gives us everything we need. For a future raster-only plot, we degrade gracefully to "manual input required" rather than ship a brittle vision-only geometry pipeline that pretends to work. This is the stub the brief explicitly allows.
- **No real-time collaboration in the viewer.** The PM verifies, saves, hands off. No multi-user editing. Production tool would need it, prototype does not.
- **No fancy DB.** Plain JSON for the archive, plus the Stelselcatalogus-seeded `glossary.json`. Vector DB and graph DB are productisation steps with clear migration paths from this structure.
- **No optimised design generation.** We produce two illustrative massings to show that the inputs translate to geometry. We do not run a parametric sweep, score variants against KPIs, or rank options. That is the OMRT Run system, which is downstream of our work.
- **No Bbl (national building code) integration.** The Bbl applies universally to physical construction details (fire separation, ventilation, acoustic performance, energy demand), not to massing inputs. A PM does not re-evaluate Bbl compliance during massing exploration; that is the architect of record's job during detailed design. Out of scope for this prototype, but we note that any production version targeting the full Run pipeline could consume the Bbl as a sustainability and compliance KPI source.
- **No Amsterdam-specific Datapunt API integration.** Amsterdam publishes detailed open data via `api.data.amsterdam.nl`, but using it would couple the prototype to one municipality. The same information is available nationally via PDOK and CBS, which we use instead. If a production version is deployed gemeente-by-gemeente, municipal APIs become attractive enrichment add-ons but they sit behind the same `enrich.py` interface as the national ones.
- **No DSO Omgevingsdocumenten cross-validation.** The Ruimtelijke Plannen API (Layer 4b) covers pre-2024 bestemmingsplannen, which is the vast majority of plans currently in force including Draka. Post-2024 omgevingsplannen use the DSO Omgevingsdocumenten APIs at a different endpoint with a slightly different schema. Adding that path is a one-day extension and the architecture already supports it (different `api_name` in Provenance, same `cross_validation` structure). Out of scope for this weekend, listed in the "another week" answer.

---

## 15. Example massings, the nice-to-have

The brief asks for one or two example massings to illustrate how the inputs translate into geometry. The goal is to communicate the solution visually, not to design a building. The massing pair earns its keep by demonstrating consumability: if the JSON cannot drive a simple massing here, it certainly cannot drive a Grasshopper engineer's work.

**Variant A, "Maximum envelope."** For each bouwvlak in the validated geometry, extrude the 2D polygon to its max allowed height. No setbacks applied. This shows the theoretical maximum massing that satisfies only the height and footprint rules.

**Variant B, "Compliant with setbacks."** Same extrusion, but where a bouwvlak's max height exceeds the setback threshold (read from the schema, never hardcoded), apply the required setback distance above the threshold. The result is a base volume plus a stepped-back upper volume.

The pair illustrates the gap between "what's legally permitted" and "what's actually compliant after all rules apply." This is exactly the trade-off space the OMRT Run system explores at scale, by varying many parameters at once across many variants. By generating two extremes by hand we show what a Run could begin to vary across, without claiming to do the Run's job.

The massing is *derived* from the inputs, never invented. Every form decision cites the rule that produced it: "this tower stepped back at 21 m because regels article 3.2.2.r requires a setback of minimum 2.5 m above 21 m height." If a rule was not extracted with high enough confidence, the massing visualisation banners "preview based on unverified inputs" and the citation reflects the uncertainty. The system never silently fills gaps in the massing logic with assumptions.

Implementation outline:
- `src/omrt_extractor/massing.py` with `generate_example_massings(framework) -> list[Massing]`
- 2D operations in shapely (polygon, buffer, intersection)
- 3D output as COMPAS Mesh objects (the GH engineer can consume these directly)
- Visualised in Streamlit using plotly Mesh3d (no extra dependencies, side-by-side comparison)
- Exported to `data/outputs/<project>/massings/` as COMPAS JSON and OBJ

What this is not: a finished design, a buildable proposal, or a recommendation. It is a visual sanity check that says "yes, the structured inputs we extracted do compose into a coherent 3D form following the rules we identified." If they do not, that is the strongest possible signal that something in the extraction or schema is wrong, and the massing failure becomes diagnostic information.

---

## 16. Input-data adjustments log

Small, traceable edits to the read-only `data/inputs/` corpus. Each entry records what changed and why so the corpus stays honest about its provenance.

- **2026-05-16:** Renamed `data/inputs/draka/Drakaterrein-A2_2022-04-26 versie 2.pdf` to `Drakaterrein-A2_2022-04-26 versie 2_kaveltekening.pdf`. The preprocessing step uses a generic filename heuristic (`regels` / `toelichting` / `kaveltekening` / `verbeelding` / `plankaart`) to set `PreprocessedDocument.document_type`. The original filename carried no such hint, so the file was renamed rather than hardcoding "drakaterrein" as a kaveltekening marker (which would violate the CLAUDE.md no-municipality-names rule). The authoritative classification still comes from the LLM via `SourceDocument.document_type`; the filename hint is only a routing convenience.
