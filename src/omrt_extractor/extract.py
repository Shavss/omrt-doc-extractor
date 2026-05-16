"""Multimodal LLM extraction: per-page PDF -> PartialFrameworkExtraction.

This module wraps a PydanticAI agent that consumes (image, text, metadata)
and returns a partial framework. Per-page partials merge into a project-
level framework downstream.

The system prompt is loaded from prompts/extraction.md. The dual-pass
critical-fields agent uses prompts/critical_fields.md.

Primary functions:
    extract_page(image_path, text, page_meta) -> PartialFrameworkExtraction
    extract_project(preprocessed) -> ExtractionResult
    extract_critical_fields_dual_pass(preprocessed) -> CriticalFieldsExtraction

Hard rules from CLAUDE.md:
- Every value carries Provenance and Confidence.
- Never invent. Prefer None over a guess.
- Quote source text verbatim in Provenance.quoted_text.
- The merge step keeps all entries when pages return different values
  for the same field, so validators.py can flag disagreements.

Stage 2 of the build plan.
"""

from __future__ import annotations

# TODO Stage 2: implement extract_page, extract_project, dual-pass agent
