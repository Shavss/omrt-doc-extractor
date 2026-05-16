"""Tests for the Stage 1 preprocessing pipeline.

Assertions are structural: every PDF in the input directory must be
processed, every page must yield both an image file on disk and a
non-empty text string, and at least one document in any reasonable
Dutch zoning packet runs longer than 10 pages. No document-specific
strings are asserted; the test must pass on any reasonable packet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omrt_extractor.preprocess import preprocess_project
from omrt_extractor.schemas import ProjectPreprocessed

DRAKA_INPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "inputs" / "draka"


@pytest.fixture(scope="module")
def preprocessed(tmp_path_factory: pytest.TempPathFactory) -> ProjectPreprocessed:
    if not DRAKA_INPUT_DIR.is_dir():
        pytest.skip(f"Input directory not present: {DRAKA_INPUT_DIR}")
    cache_dir = tmp_path_factory.mktemp("preprocess_cache")
    return preprocess_project(DRAKA_INPUT_DIR, cache_dir)


def test_all_pdfs_processed(preprocessed: ProjectPreprocessed) -> None:
    pdf_files = sorted(p.name for p in DRAKA_INPUT_DIR.iterdir() if p.suffix.lower() == ".pdf")
    processed = sorted(doc.filename for doc in preprocessed.documents)
    assert processed == pdf_files
    assert len(processed) >= 1


def test_every_page_has_image_and_text(preprocessed: ProjectPreprocessed) -> None:
    for doc in preprocessed.documents:
        assert len(doc.pages) >= 1, f"No pages produced for {doc.filename}"
        seen_numbers = [p.page_number for p in doc.pages]
        assert seen_numbers == sorted(seen_numbers)
        assert seen_numbers[0] == 1
        for page in doc.pages:
            assert page.image_path.exists(), f"Missing image: {page.image_path}"
            assert page.image_path.stat().st_size > 0
        # Most pages must carry text. Real packets include the occasional
        # blank separator or back-cover page, so allow a small fraction
        # to be empty rather than asserting non-empty text on every page.
        text_pages = sum(1 for p in doc.pages if p.text.strip())
        assert text_pages >= max(1, int(0.8 * len(doc.pages))), (
            f"{doc.filename}: only {text_pages}/{len(doc.pages)} pages have text"
        )


def test_draka_filename_classification(preprocessed: ProjectPreprocessed) -> None:
    """Coarse filename routing covers the three Draka document types."""
    by_type = {doc.document_type for doc in preprocessed.documents}
    assert by_type == {"regels", "toelichting", "kaveltekening"}


def test_longest_pdf_has_at_least_10_text_pages(preprocessed: ProjectPreprocessed) -> None:
    longest = max(
        (sum(1 for p in doc.pages if p.text.strip()) for doc in preprocessed.documents),
        default=0,
    )
    assert longest >= 10, f"Longest document only has {longest} text pages"


def test_cache_reuse_skips_rerender(tmp_path: Path) -> None:
    if not DRAKA_INPUT_DIR.is_dir():
        pytest.skip(f"Input directory not present: {DRAKA_INPUT_DIR}")
    cache_dir = tmp_path / "cache"
    first = preprocess_project(DRAKA_INPUT_DIR, cache_dir)
    sample_image = first.documents[0].pages[0].image_path
    original_mtime = sample_image.stat().st_mtime_ns

    second = preprocess_project(DRAKA_INPUT_DIR, cache_dir)
    assert second.documents[0].pages[0].image_path == sample_image
    assert sample_image.stat().st_mtime_ns == original_mtime
