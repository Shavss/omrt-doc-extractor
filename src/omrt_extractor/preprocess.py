"""PDF preprocessing: render every page to 200 DPI PNG and extract its text layer.

This module produces the per-page image-and-text pairs that the multimodal
extraction step consumes. Caching is aggressive because preprocessing is
deterministic and rerun-expensive (a 200-page toelichting takes minutes).

Primary function:
    preprocess_project(input_dir, cache_dir) -> ProjectPreprocessed

ProjectPreprocessed (defined in schemas.py) lists, per PDF in the input
directory, a list of (page_number, image_path, text) entries. Skip pages
where both the image and text are already cached.

Implementation notes:
- Use pymupdf (fitz) for both extraction paths. It handles rotated text,
  encrypted PDFs, and embedded fonts more reliably than alternatives.
- Render at exactly settings.render_dpi (default 200) so the image quality
  is consistent across runs. Higher DPI inflates LLM costs without quality
  gain at this scale.
- Save images under cache_dir/<pdf_basename>/page_<n>.png.
- Classify each PDF's document_type heuristically by filename hints
  (regels/toelichting/kaveltekening) when possible, fall back to 'other'.

Stage 1 of the build plan.
"""

from __future__ import annotations

# TODO Stage 1: implement preprocess_project
