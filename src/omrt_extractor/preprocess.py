"""PDF preprocessing: render every page to 200 DPI PNG and extract its text layer.

This module produces the per-page image-and-text pairs that the multimodal
extraction step consumes. Caching is aggressive because preprocessing is
deterministic and rerun-expensive (a 200-page toelichting takes minutes).

Primary function:
    preprocess_project(input_dir, cache_dir) -> ProjectPreprocessed

ProjectPreprocessed lists, per PDF in the input directory, a list of
(page_number, image_path, text) entries. Pages where both the image and
text are already cached are skipped.

Implementation notes:
- pymupdf (fitz) handles both rendering and text extraction. It is robust
  on rotated text, embedded fonts and encrypted PDFs.
- Render at exactly settings.render_dpi (default 200). Consistent across
  runs so the LLM input is reproducible.
- Images: cache_dir/<pdf_stem>/page_<n>.png. Text sidecar:
  cache_dir/<pdf_stem>/page_<n>.txt. The text sidecar lets us detect a
  "fully cached" page without re-opening the PDF.

Stage 1 of the build plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import pymupdf

from .config import settings
from .schemas import (
    PreprocessedDocument,
    PreprocessedPage,
    ProjectPreprocessed,
)


def _classify_document_type(filename: str) -> str:
    """Coarse routing hint from filename only.

    Filename heuristics are unreliable across municipalities, so this is
    a preprocessing convenience, not an authoritative classification.
    The LLM still decides SourceDocument.document_type from content.
    """
    name = filename.lower()
    if "regels" in name:
        return "regels"
    if "toelichting" in name:
        return "toelichting"
    if any(hint in name for hint in ("kaveltekening", "verbeelding", "plankaart")):
        return "kaveltekening"
    return "other"


def _page_artifact_paths(pdf_cache_dir: Path, page_number: int) -> tuple[Path, Path]:
    """Return (image_path, text_path) for a 1-indexed page."""
    image_path = pdf_cache_dir / f"page_{page_number}.png"
    text_path = pdf_cache_dir / f"page_{page_number}.txt"
    return image_path, text_path


def _render_and_extract(
    pdf: "pymupdf.Document",
    page_index: int,
    image_path: Path,
    text_path: Path,
    dpi: int,
) -> str:
    """Render the page to PNG, extract text, write both, return text."""
    page = pdf.load_page(page_index)
    pixmap = page.get_pixmap(dpi=dpi)
    pixmap.save(image_path)
    text = page.get_text("text")
    text_path.write_text(text, encoding="utf-8")
    return text


def preprocess_project(input_dir: Path, cache_dir: Path) -> ProjectPreprocessed:
    """Render and extract every page of every PDF in ``input_dir``.

    Outputs land under ``cache_dir/<pdf_stem>/`` and are reused on rerun.
    """
    import pymupdf

    input_dir = Path(input_dir)
    cache_dir = Path(cache_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    cache_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(p for p in input_dir.iterdir() if p.suffix.lower() == ".pdf")
    logger.info(f"Preprocessing {len(pdf_paths)} PDF(s) from {input_dir}")

    documents: list[PreprocessedDocument] = []
    for pdf_path in pdf_paths:
        pdf_cache_dir = cache_dir / pdf_path.stem
        pdf_cache_dir.mkdir(parents=True, exist_ok=True)
        pages: list[PreprocessedPage] = []

        with pymupdf.open(pdf_path) as pdf:
            page_count = pdf.page_count
            for page_index in range(page_count):
                page_number = page_index + 1
                image_path, text_path = _page_artifact_paths(pdf_cache_dir, page_number)

                if image_path.exists() and text_path.exists():
                    text = text_path.read_text(encoding="utf-8")
                else:
                    text = _render_and_extract(
                        pdf, page_index, image_path, text_path, settings.render_dpi
                    )

                pages.append(
                    PreprocessedPage(
                        page_number=page_number,
                        image_path=image_path.resolve(),
                        text=text,
                    )
                )

        logger.info(f"  {pdf_path.name}: {len(pages)} page(s) ready")
        documents.append(
            PreprocessedDocument(
                filename=pdf_path.name,
                pdf_path=pdf_path.resolve(),
                document_type=_classify_document_type(pdf_path.name),
                pages=pages,
            )
        )

    return ProjectPreprocessed(
        input_dir=input_dir.resolve(),
        cache_dir=cache_dir.resolve(),
        documents=documents,
    )
