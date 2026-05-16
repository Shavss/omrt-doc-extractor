"""Programme inference: synthesise a ProgrammeProposal from Extraction + GeoContext.

Uses claude-opus-4-7 because this is the judgment-heavy step. Prompt at
prompts/programme.md. Produces target unit mix, GFA split, parking demand,
and a reasoning trace where every programme decision cites its evidence
(constraint ID, BAG/CBS/OSM data point, or explicit designer judgment).

Primary function:
    infer_programme(extraction, geo_context, cross_validation_flags) -> ProgrammeProposal

Hard rules from prompts/programme.md:
- Never invent unsupported numbers. Mark fields requires_designer_input=true
  when evidence is missing.
- Prefer ranges over false precision.
- Mark assumptions vs extracted facts in the reasoning trace.
- Respect cross-validation flags. Programme numbers depending on
  imro_api_disagreement values must flag the dependency.
- Confidence cannot exceed 0.7 if most decisions rest on designer judgment.

Stage 5 of the build plan.
"""

from __future__ import annotations

# TODO Stage 5: implement infer_programme
