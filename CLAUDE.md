# Claude Code working agreement, omrt-doc-extractor

Read this file first in every Claude Code session.

## What we're building

A prototype that turns Dutch project document PDFs into validated, structured design inputs for Grasshopper. Schema-centric architecture, layered guardrails for failure honesty, generalises to unseen packets. See `docs/architecture.md` for the design rationale and `PROJECT_PLAN.md` for the working plan.

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

- Python 3.11+. Use modern type hints (`X | None`, `list[X]`, not `Optional[X]` or `List[X]`).
- Pydantic v2 throughout. `model_config = ConfigDict(extra="forbid")` on every model.
- Loguru for logging, never `print` in production code.
- `pathlib.Path` for filesystem, never `os.path`.
- Async where the IO benefits (httpx calls, batched LLM requests). Sync where it doesn't.
- Module-level docstrings on every file; class and function docstrings where the purpose is not obvious from the signature.

## Tests

- Pytest. Run before every commit.
- Mock all external APIs with `respx` for httpx or `pytest-mock` for general mocking.
- A schema change must be accompanied by a test that locks in the new behaviour.
- 36 tests in `tests/test_schemas.py` are the schema contract. They should always pass.

## Commands

```bash
# Run all tests
pytest

# Run with markers to skip slow or live-API tests
pytest -m "not slow and not live_api"

# Lint and format
ruff check .
ruff format .

# Type check
mypy src/

# Seed the glossary
python scripts/seed_glossary.py

# Run the pipeline
omrt run data/inputs/draka/
```

## What NOT to do

- Do not invent fields in the schema without discussing first. The schema is the central contract; changes propagate everywhere.
- Do not call live external APIs in test code. Always mock.
- Do not commit `.env` or any file containing an API key.
- Do not paraphrase source text in the `quoted_text` field of Provenance. The whole audit chain depends on verbatim quotes.
- Do not use `model_copy(update=...)` when you need validators to re-fire. Use `model_validate(model_dump() | updates)` instead.

## Anchoring documents

- Architecture: `docs/architecture.md`
- Schema reference: `docs/schema_reference.md`
- Project plan: `PROJECT_PLAN.md`
