"""Cross-project knowledge layer: archive, glossary, future few-shot retrieval.

Bridges single-project extraction to the growing archive. Only projects
with verification_status='reviewed' feed the layer; garbage in stays out.

Primary functions (wired in this prototype):
    load_glossary() -> dict[str, GlossaryTerm]
    relevant_glossary_terms(page_text) -> list[GlossaryTerm]
    archive_project(framework) -> Path

Primary functions (typed stubs, awaiting more archived projects):
    similar_past_extractions(location, zoning_type, k=3) -> list[ParametricFramework]
    historical_bounds(category, location) -> tuple[float, float] | None
    historical_programme_mix(location, radius_m) -> dict | None

The glossary is the part that earns its keep on day one. Seeded from the
Stelselcatalogus by scripts/seed_glossary.py, consulted by the extraction
prompt on every page where relevant terms appear. The other functions
become useful at 3-5 verified projects and replace universal sanity bounds
with municipality-calibrated distributions.

Persistence: plain JSON under data/archive/. glossary.json grows with use.
data/archive/projects/<project_id>/framework.json per verified project.

Stage 0 (glossary load), Stages 2+ (term lookup), Stage 6 (archive write).
"""

from __future__ import annotations

# TODO: implement glossary load, term lookup, archive write
# TODO future: similar_past_extractions, historical_bounds, programme_mix
