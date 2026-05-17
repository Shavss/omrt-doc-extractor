# OMRT doc-extractor

A prototype that turns Dutch project document bundles (bestemmingsplan regels, toelichting, kaveltekening) into a validated, structured Parametric Framework for the OMRT Run system.

## Quick start

```bash
# 1. Install
uv sync --extra dev

# 2. Configure
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY (and optionally STELSELCATALOGUS_API_KEY)

# 3. Seed the glossary (one-off)
python scripts/seed_glossary.py

# 4. Run the pipeline on a project
omrt run data/inputs/draka/

# 5. Review in the Streamlit viewer
streamlit run viewer/streamlit_app.py
```

## Pipeline orchestration

`omrt run <input_dir>` is the canonical entry point. It derives the
project name from the input directory basename and writes every artifact
to `data/outputs/<project>/`. The four expensive stages — multimodal
extraction, geo enrichment, IMRO cross-validation, programme inference —
are skipped when their cached output already exists; the cheap chain
(geometry parse, reconciliation, framework assembly, massings, handoff)
always runs so any change to the assembly logic takes effect on the
next invocation.

Flags:

- `--force` re-runs every stage, ignoring caches.
- `--skip-extraction` / `--skip-programme` / `--skip-enrich` /
  `--skip-cross-validate` opt out of a single expensive stage. The
  cached output must already exist (or, for cross-validate, may be
  absent — the constraint set is then used as-is).

Output layout per project:

```
data/outputs/<project>/
  extraction_raw.json          # expensive (LLM)
  programme.json               # expensive (LLM)
  geo_context.json             # expensive (PDOK / CBS / OSM)
  imro_cross_validation.json   # expensive (IMRO API)
  geometry.json                # cheap (vector parser)
  reconciliation_report.json   # cheap
  framework.json               # final handoff
  summary.md                   # human-readable handoff
  massing_inputs.json          # slim envelope for Grasshopper
  geometry/*.compas            # per-polygon COMPAS Polygons
  massings/*.compas.json       # example massings
```

## Documentation

Start with one of these depending on what you want:

- **`docs/architecture.md`** if you want to understand what the system does and why.
- **`docs/schema_reference.md`** if you want to consume the JSON output or build against the Pydantic schema.
- **`PROJECT_PLAN.md`** if you want to see the working plan with stage-by-stage build prompts and time estimates.
- **`CLAUDE.md`** if you are working in the repo with Claude Code; this is the working agreement.

## Repository layout

```
.
├── PROJECT_PLAN.md          # Working plan with time estimates
├── CLAUDE.md                # Agreement for Claude Code sessions
├── pyproject.toml           # Dependencies and tool config
├── src/omrt_extractor/      # The package (see module docstrings)
├── scripts/                 # One-off scripts (glossary seeding)
├── tests/                   # Pytest test suite
├── data/                    # Inputs, outputs, archive, cache
├── docs/                    # Anchoring documents
├── viewer/                  # Streamlit review interface
└── grasshopper/             # JSON output format docs, sample GH file
```

## Status

This is a prototype, not a production tool. The output is never authoritative until a human marks a project as `reviewed`. See `docs/architecture.md` section "The Scenario 1 defence" for what this guarantees and what it does not.

## Known issues

**macOS + Python 3.12 + pymupdf segfault under pytest.** Pytest's
import-rewriting machinery triggers a SIGSEGV when pymupdf's SWIG
C extension is first loaded during test collection on this Python
version. Worked around by `scripts/test.sh`, which pre-imports
pymupdf before invoking pytest. Run tests via that script rather
than `pytest` directly:

    ./scripts/test.sh           # all tests
    ./scripts/test.sh -v        # verbose
    ./scripts/test.sh -k schema # filter by name

A production build would pin pymupdf to a version with stable
macOS wheels under Python 3.12, or evaluate `pypdfium2` as an
alternative rendering backend.

## Licence

Proprietary. Internal use only.

