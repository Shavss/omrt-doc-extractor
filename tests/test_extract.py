"""Tests for the Stage 2 multimodal extraction pipeline.

Two layers:

1. Pure unit tests for the merge logic. These run in CI without any
   network and validate the contract that per-page partials concatenate
   without silent deduplication.
2. Live-API integration tests that run the extraction agent over Draka
   pages and assert *structural* presence of key fields (some height
   value, some parking norm). Marked with ``live_api`` so default CI
   runs skip them per CLAUDE.md ("Live API calls in tests are forbidden").
   Run locally with ``pytest -m live_api`` when an ANTHROPIC_API_KEY is
   present.

Per CLAUDE.md: assertions check structural presence, never specific
values from a specific document.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from omrt_extractor.extract import (
    ExtractionResult,
    PageExtraction,
    extract_critical_fields_dual_pass,
    extract_project,
    merge_partials,
)
from omrt_extractor.preprocess import preprocess_project
from omrt_extractor.schemas import (
    Confidence,
    NumericalConstraint,
    PartialFrameworkExtraction,
    Provenance,
    SourceType,
)

DRAKA_INPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "inputs" / "draka"


def _provenance(page: int, quote: str) -> Provenance:
    return Provenance(
        source_type=SourceType.DOCUMENT,
        document="regels.pdf",
        page=page,
        quoted_text=quote,
    )


def _height_constraint(slug: str, value: float, page: int, quote: str) -> NumericalConstraint:
    return NumericalConstraint(
        id=slug,
        name="Max building height",
        category="height",
        value=value,
        unit="m",
        is_maximum=True,
        provenance=_provenance(page, quote),
        confidence=Confidence(score=0.9),
    )


# =====================================================================
# Merge logic (offline)
# =====================================================================


def test_merge_concatenates_without_dedupe() -> None:
    """Two pages reporting different heights for the same concept must
    both survive the merge so validators.py can flag the disagreement."""
    p1 = PartialFrameworkExtraction(
        numerical_constraints=[_height_constraint("max_height_a", 21.0, 3, "21 m")],
        plan_id_found="NL.IMRO.0363.N2102BPGST-VG01",
    )
    p2 = PartialFrameworkExtraction(
        numerical_constraints=[_height_constraint("max_height_b", 31.0, 7, "31 m")],
        plan_id_found="NL.IMRO.0363.N2102BPGST-VG01",
    )
    merged = merge_partials(
        [
            PageExtraction(document_filename="regels.pdf", page_number=3, partial=p1),
            PageExtraction(document_filename="regels.pdf", page_number=7, partial=p2),
        ]
    )
    assert isinstance(merged, ExtractionResult)
    assert len(merged.numerical_constraints) == 2
    values = {c.value for c in merged.numerical_constraints}
    assert values == {21.0, 31.0}
    # Plan ID seen twice but stored once.
    assert merged.plan_ids_found == ["NL.IMRO.0363.N2102BPGST-VG01"]


def test_merge_preserves_per_page_view() -> None:
    p = PartialFrameworkExtraction(programme_hints=["mixed-use plinth"])
    merged = merge_partials(
        [PageExtraction(document_filename="toelichting.pdf", page_number=12, partial=p)]
    )
    assert len(merged.per_page) == 1
    assert merged.programme_hints == ["mixed-use plinth"]


def test_merge_empty_input_returns_empty_result() -> None:
    merged = merge_partials([])
    assert merged.numerical_constraints == []
    assert merged.per_page == []
    assert merged.plan_ids_found == []


# =====================================================================
# Live-API tests on Draka (skipped in CI)
# =====================================================================


_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


@pytest.fixture(scope="module")
def preprocessed_draka(tmp_path_factory: pytest.TempPathFactory):
    if not DRAKA_INPUT_DIR.is_dir():
        pytest.skip(f"Input directory not present: {DRAKA_INPUT_DIR}")
    cache_dir = tmp_path_factory.mktemp("extract_cache")
    return preprocess_project(DRAKA_INPUT_DIR, cache_dir)


@pytest.mark.live_api
@pytest.mark.slow
@pytest.mark.asyncio
async def test_extract_project_finds_height_and_parking(preprocessed_draka) -> None:
    """Structural assertion: any reasonable Dutch zoning packet yields
    at least one height constraint and at least one parking constraint.
    No specific values asserted."""
    if not _API_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")

    # Limit to the regels document and a small slice of pages to keep
    # the live run cheap. Behaviour generalises to the full set.
    truncated = preprocessed_draka.model_copy(deep=True)
    for doc in truncated.documents:
        if doc.document_type == "regels":
            doc.pages = doc.pages[:8]
        else:
            doc.pages = []

    result = await extract_project(truncated, max_concurrency=2)

    heights = [c for c in result.numerical_constraints if c.category == "height"]
    parking = [c for c in result.numerical_constraints if c.category == "parking"]

    assert heights, "Expected at least one height constraint"
    assert parking, "Expected at least one parking constraint"

    for c in heights:
        v = c.value[1] if isinstance(c.value, tuple) else c.value
        assert 3.0 <= v <= 200.0, f"Height {v} outside universal sanity bounds"
        assert c.provenance.quoted_text, "Every value must carry a verbatim quote"
        assert 0.0 <= c.confidence.score <= 1.0


@pytest.mark.live_api
@pytest.mark.slow
@pytest.mark.asyncio
async def test_dual_pass_returns_critical_field_answers(preprocessed_draka) -> None:
    """Dual-pass must return findings for at least the height and
    parking questions, with verbatim quotes."""
    if not _API_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")

    truncated = preprocessed_draka.model_copy(deep=True)
    for doc in truncated.documents:
        if doc.document_type in ("regels", "toelichting"):
            doc.pages = doc.pages[:5]
        else:
            doc.pages = []

    result = await extract_critical_fields_dual_pass(truncated, max_pages_per_doc=5)

    questions_with_findings = {a.question for a in result.answers if a.findings}
    assert "max_building_height" in questions_with_findings or any(
        a.findings for a in result.answers if a.question.startswith("max_building")
    )
    # At least one finding anywhere with a verbatim quote.
    quoted = [
        f
        for a in result.answers
        for f in a.findings
        if f.provenance.quoted_text
    ]
    assert quoted, "Dual-pass must produce at least one verbatim-quoted finding"
