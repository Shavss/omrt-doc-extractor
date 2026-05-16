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

# 4. Run the pipeline on Draka
omrt run data/inputs/draka/

# 5. Review in the Streamlit viewer
streamlit run viewer/streamlit_app.py
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

## Licence

Proprietary. Internal use only.
