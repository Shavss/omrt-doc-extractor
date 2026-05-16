"""Multimodal LLM extraction: per-page PDF -> PartialFrameworkExtraction.

Wraps a pydantic-ai agent that consumes (image, text, metadata) and
returns a partial framework. Per-page partials merge into a project-
level ``ExtractionResult`` downstream. A separate critical-fields agent
runs the Layer-3 dual-pass over the whole document set using an
independent prompt formulation.

System prompts are loaded from ``prompts/extraction.md`` and
``prompts/critical_fields.md``. The glossary, when present at
``data/archive/glossary.json``, is injected into the system prompt so
the LLM grounds vocabulary against the Stelselcatalogus.

Public surface:
    extract_page(...)                 -> PartialFrameworkExtraction
    extract_project(...)              -> ExtractionResult
    extract_critical_fields_dual_pass(...) -> CriticalFieldsExtraction
    merge_partials(...)               -> ExtractionResult

Hard rules from CLAUDE.md:
- Every value carries Provenance and Confidence (LLM enforces via schema).
- Never invent. Prefer None over a guess.
- Quote source text verbatim in Provenance.quoted_text.
- Merge keeps all entries when multiple pages return values for the
  same conceptual field, so validators.py can flag disagreements.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from .config import settings
from .schemas import (
    Confidence,
    PartialFrameworkExtraction,
    PreprocessedDocument,
    PreprocessedPage,
    ProjectPreprocessed,
    Provenance,
)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_GLOSSARY_PATH = settings.archive_dir / "glossary.json"
_CHECKPOINT_DIR = Path("data/outputs/checkpoints")

# =====================================================================
# Aggregated extraction result + dual-pass output schemas
# Kept local to this module because they are internal pipeline
# artifacts, not part of the ParametricFramework contract.
# =====================================================================


class PageExtraction(BaseModel):
    """One page's partial result, tagged with its source location."""

    model_config = ConfigDict(extra="forbid")

    document_filename: str
    page_number: int
    partial: PartialFrameworkExtraction


class ExtractionResult(BaseModel):
    """Aggregated per-page partials for an entire project.

    Merge strategy: every value returned by any page is retained. No
    silent overwrite. Downstream validators.py flags duplicates and
    conflicts. The fields below are flat lists across pages; the
    ``per_page`` collection preserves the original page-scoped view.
    """

    model_config = ConfigDict(extra="forbid")

    per_page: list[PageExtraction] = Field(default_factory=list)
    numerical_constraints: list = Field(default_factory=list)
    geometric_constraints: list = Field(default_factory=list)
    narrative_constraints: list = Field(default_factory=list)
    programme_hints: list[str] = Field(default_factory=list)
    urban_intent_passages: list[str] = Field(default_factory=list)
    plan_ids_found: list[str] = Field(default_factory=list)
    municipalities_found: list[str] = Field(default_factory=list)
    neighbourhoods_found: list[str] = Field(default_factory=list)
    pages_with_extraction_errors: list[tuple[str, int, str]] = Field(default_factory=list)


CriticalFieldQuestion = Literal[
    "max_building_height",
    "default_height_regime",
    "goothoogte_nokhoogte",
    "setback_rules",
    "restricted_zones",
    "residential_parking_norm",
    "non_residential_parking_norm",
    "parking_exemptions",
]


class CriticalFieldFinding(BaseModel):
    """A single answer to one open question in the dual-pass.

    Independent of the schema-bound first pass: the dual-pass returns
    raw findings with verbatim quotes and the orchestrator compares
    them to the first pass numerically.
    """

    model_config = ConfigDict(extra="forbid")

    value: float | tuple[float, float] | None = Field(
        default=None,
        description=(
            "Numerical value or range. None when the finding is purely "
            "qualitative (e.g. a restricted-zone description)."
        ),
    )
    unit: str | None = None
    applies_to: str = Field(
        description=(
            "Location qualifier: zone code, facade, tenure, or 'general'. "
            "Always populated; the qualifier is what makes findings "
            "comparable across passes."
        )
    )
    provenance: Provenance
    confidence: Confidence
    binding: bool = Field(
        default=True,
        description="False when found only in toelichting tables or worked examples.",
    )
    notes: str | None = None


class CriticalFieldsAnswer(BaseModel):
    """All findings for one of the open questions."""

    model_config = ConfigDict(extra="forbid")

    question: CriticalFieldQuestion
    findings: list[CriticalFieldFinding] = Field(default_factory=list)
    not_found: bool = Field(default=False)
    internal_conflict: bool = Field(default=False)
    reasoning_trace: str = Field(
        description="One paragraph explaining how the findings were derived and any conflicts surfaced.",
    )


class CriticalFieldsExtraction(BaseModel):
    """Output of the Layer-3 dual-pass.

    Independent of PartialFrameworkExtraction. The orchestrator compares
    these answers to the corresponding NumericalConstraints from the
    first pass; disagreements are flagged on the constraint's Confidence
    with 'dual_pass_disagreement'.
    """

    model_config = ConfigDict(extra="forbid")

    answers: list[CriticalFieldsAnswer]


# =====================================================================
# Prompt + glossary loading
# =====================================================================


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _load_glossary_block() -> str:
    """Return a glossary block to append to the system prompt, or empty string."""
    if not _GLOSSARY_PATH.is_file():
        return ""
    try:
        raw = json.loads(_GLOSSARY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning(f"Glossary at {_GLOSSARY_PATH} is not valid JSON; skipping injection")
        return ""

    entries = raw if isinstance(raw, list) else raw.get("terms", [])
    if not entries:
        return ""

    lines = ["", "## Glossary (authoritative term definitions)", ""]
    for entry in entries:
        term = entry.get("term")
        definition = entry.get("definition")
        if not term or not definition:
            continue
        lines.append(f"- **{term}**: {definition}")
    lines.append("")
    return "\n".join(lines)


# =====================================================================
# Agent factories
# =====================================================================


def _anthropic_model(model_name: str | None) -> AnthropicModel:
    """Build an AnthropicModel with the API key from pydantic-settings.

    pydantic-ai otherwise reads ``os.environ['ANTHROPIC_API_KEY']``,
    which is empty here because the key is loaded via pydantic-settings
    from ``.env`` into ``settings.anthropic_api_key``.
    """
    provider = AnthropicProvider(api_key=settings.anthropic_api_key)
    return AnthropicModel(model_name or settings.extraction_model, provider=provider)


def build_extraction_agent(model_name: str | None = None) -> Agent:
    """Construct the per-page extraction agent."""
    model = _anthropic_model(model_name)
    instructions = _load_prompt("extraction.md") + _load_glossary_block()
    return Agent(
        model=model,
        output_type=PartialFrameworkExtraction,
        instructions=instructions,
        output_retries=2,
    )


def build_critical_fields_agent(model_name: str | None = None) -> Agent:
    """Construct the dual-pass critical-fields agent.

    The instruction text is the critical_fields.md prompt verbatim;
    crucially it does not reveal what the first pass returned.
    """
    model = _anthropic_model(model_name)
    instructions = _load_prompt("critical_fields.md") + _load_glossary_block()
    return Agent(
        model=model,
        output_type=CriticalFieldsExtraction,
        instructions=instructions,
        output_retries=2,
    )


# =====================================================================
# Per-page extraction
# =====================================================================


def _read_image_bytes(image_path: Path) -> bytes:
    return Path(image_path).read_bytes()


def _checkpoint_path(document_filename: str, page_number: int) -> Path:
    """Return the checkpoint file path for a given page."""
    safe_name = document_filename.replace("/", "_").replace(" ", "_")
    return _CHECKPOINT_DIR / f"{safe_name}_p{page_number}.json"


def _load_checkpoint(document_filename: str, page_number: int) -> PageExtraction | None:
    """Return a cached PageExtraction if one exists on disk, else None."""
    path = _checkpoint_path(document_filename, page_number)
    if path.exists():
        try:
            return PageExtraction.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Corrupt checkpoint for {document_filename} p{page_number}, ignoring: {exc}")
            path.unlink(missing_ok=True)
    return None


def _save_checkpoint(entry: PageExtraction) -> None:
    """Persist a PageExtraction to disk so re-runs can skip it."""
    _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path(entry.document_filename, entry.page_number)
    path.write_text(entry.model_dump_json(), encoding="utf-8")


async def extract_page(
    image_path: Path,
    text: str,
    page_meta: dict,
    agent: Agent | None = None,
) -> PartialFrameworkExtraction:
    """Run the extraction agent over a single (image, text, meta) page.

    ``page_meta`` must include 'document_filename', 'page_number', and
    'document_type' so the LLM can populate Provenance correctly.
    """
    agent = agent or build_extraction_agent()
    image_bytes = _read_image_bytes(image_path)
    user_message = [
        (
            f"Document: {page_meta['document_filename']}\n"
            f"Page: {page_meta['page_number']}\n"
            f"Document type: {page_meta.get('document_type', 'other')}\n"
            "\n"
            "Page image:"
        ),
        BinaryContent(data=image_bytes, media_type="image/png"),
        f"Text layer extracted from this page:\n\n{text or '(empty text layer)'}",
    ]
    result = await agent.run(user_message)
    return result.output


async def _extract_one_page_safe(
    doc: PreprocessedDocument,
    page: PreprocessedPage,
    agent: Agent,
) -> PageExtraction | tuple[str, int, str]:
    """Run extraction and surface failures rather than raising.

    Checks the on-disk checkpoint cache first so re-runs skip pages
    that already completed. Retries up to 5 times with exponential
    backoff on 429 rate-limit errors.
    """
    # --- Checkpoint cache hit ---
    cached = _load_checkpoint(doc.filename, page.page_number)
    if cached is not None:
        logger.info(f"Checkpoint hit: {doc.filename} p{page.page_number}, skipping API call")
        return cached

    # --- API call with retry ---
    max_retries = 5
    for attempt in range(max_retries):
        try:
            partial = await extract_page(
                page.image_path,
                page.text,
                {
                    "document_filename": doc.filename,
                    "page_number": page.page_number,
                    "document_type": doc.document_type,
                },
                agent=agent,
            )
            entry = PageExtraction(
                document_filename=doc.filename,
                page_number=page.page_number,
                partial=partial,
            )
            _save_checkpoint(entry)
            return entry

        except Exception as exc:
            is_rate_limit = "429" in str(exc) or "rate_limit" in str(exc).lower()
            if is_rate_limit and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)  # 60s, 120s, 180s, 240s, 300s
                logger.warning(
                    f"Rate limit on {doc.filename} p{page.page_number}, "
                    f"retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
            else:
                logger.warning(f"Extraction failed for {doc.filename} p{page.page_number}: {exc}")
                return (doc.filename, page.page_number, str(exc))


def merge_partials(per_page: list[PageExtraction]) -> ExtractionResult:
    """Concatenate per-page partials into an aggregated ExtractionResult.

    Concatenation, not deduplication: validators.py is the layer that
    flags disagreements between values reporting on the same conceptual
    field. Silent overwrite here would destroy that signal.
    """
    result = ExtractionResult(per_page=list(per_page))
    seen_plan_ids: set[str] = set()
    seen_municipalities: set[str] = set()
    seen_neighbourhoods: set[str] = set()

    for entry in per_page:
        p = entry.partial
        result.numerical_constraints.extend(p.numerical_constraints)
        result.geometric_constraints.extend(p.geometric_constraints)
        result.narrative_constraints.extend(p.narrative_constraints)
        result.programme_hints.extend(p.programme_hints)
        result.urban_intent_passages.extend(p.urban_intent_passages)

        if p.plan_id_found and p.plan_id_found not in seen_plan_ids:
            seen_plan_ids.add(p.plan_id_found)
            result.plan_ids_found.append(p.plan_id_found)
        if p.municipality_found and p.municipality_found not in seen_municipalities:
            seen_municipalities.add(p.municipality_found)
            result.municipalities_found.append(p.municipality_found)
        if p.neighbourhood_found and p.neighbourhood_found not in seen_neighbourhoods:
            seen_neighbourhoods.add(p.neighbourhood_found)
            result.neighbourhoods_found.append(p.neighbourhood_found)

    return result


# =====================================================================
# Project-level extraction
# =====================================================================


async def extract_project(
    preprocessed: ProjectPreprocessed,
    agent: Agent | None = None,
    max_concurrency: int = 1,
    skip_document_types: tuple[str, ...] = ("kaveltekening",),
) -> ExtractionResult:
    """Run extract_page over every page of every document.

    Kaveltekening pages are skipped by default because the dedicated
    geometry stage parses their vector content; the multimodal pass
    would mostly duplicate that work and burn budget.

    max_concurrency defaults to 1 to stay within Anthropic's 30,000
    input tokens per minute rate limit. Increase only if you have a
    higher tier or are processing very short pages.
    """
    agent = agent or build_extraction_agent()
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _runner(doc: PreprocessedDocument, page: PreprocessedPage):
        async with semaphore:
            return await _extract_one_page_safe(doc, page, agent)

    coros = []
    for doc in preprocessed.documents:
        if doc.document_type in skip_document_types:
            logger.info(f"Skipping {doc.filename} ({doc.document_type}) in multimodal extraction")
            continue
        for page in doc.pages:
            coros.append(_runner(doc, page))

    logger.info(f"Extracting {len(coros)} page(s) across the project")
    raw = await asyncio.gather(*coros)

    successes: list[PageExtraction] = []
    failures: list[tuple[str, int, str]] = []
    for item in raw:
        if isinstance(item, PageExtraction):
            successes.append(item)
        else:
            failures.append(item)

    merged = merge_partials(successes)
    merged.pages_with_extraction_errors = failures
    return merged


# =====================================================================
# Retry of pages that errored on a prior extraction run
# =====================================================================


async def retry_failed_pages(
    framework_path: Path,
    preprocessed: ProjectPreprocessed,
    agent: Agent | None = None,
    delay_seconds: float = 5.0,
) -> ExtractionResult:
    """Retry only the pages listed in ``pages_with_extraction_errors``.

    Loads the saved ExtractionResult at ``framework_path``, re-runs the
    extraction agent on each errored (document, page) pair with a small
    fixed delay between requests to avoid re-hitting an overloaded API,
    merges any new successes into the existing per-page list, and writes
    the updated framework back to the same path. Pages that fail again
    are kept in ``pages_with_extraction_errors``; they are not retried
    further. The checkpoint cache is bypassed (failed pages have no
    checkpoint by design).
    """
    existing = ExtractionResult.model_validate_json(
        framework_path.read_text(encoding="utf-8")
    )
    errors = list(existing.pages_with_extraction_errors)
    if not errors:
        logger.info(f"No pages_with_extraction_errors in {framework_path}, nothing to retry")
        return existing

    error_keys = {(filename, page_number) for filename, page_number, _ in errors}
    page_index: dict[tuple[str, int], tuple[PreprocessedDocument, PreprocessedPage]] = {}
    for doc in preprocessed.documents:
        for page in doc.pages:
            page_index[(doc.filename, page.page_number)] = (doc, page)

    missing = error_keys - page_index.keys()
    if missing:
        logger.warning(
            f"{len(missing)} errored page(s) not found in preprocessed input, skipping: {sorted(missing)}"
        )

    agent = agent or build_extraction_agent()

    new_successes: list[PageExtraction] = []
    still_failed: list[tuple[str, int, str]] = []
    total = len(error_keys & page_index.keys())
    logger.info(f"Retrying {total} previously errored page(s)")

    for i, (filename, page_number, _prev_err) in enumerate(errors, start=1):
        key = (filename, page_number)
        if key not in page_index:
            still_failed.append((filename, page_number, "page missing from preprocessed input"))
            continue
        doc, page = page_index[key]

        if i > 1:
            await asyncio.sleep(delay_seconds)

        logger.info(f"[{i}/{total}] Retrying {filename} p{page_number}")
        result = await _extract_one_page_safe(doc, page, agent)
        if isinstance(result, PageExtraction):
            new_successes.append(result)
            logger.info(f"[{i}/{total}] Success: {filename} p{page_number}")
        else:
            still_failed.append(result)
            logger.warning(f"[{i}/{total}] Still failing: {filename} p{page_number}: {result[2]}")

    all_pages = list(existing.per_page) + new_successes
    merged = merge_partials(all_pages)
    merged.pages_with_extraction_errors = still_failed

    framework_path.write_text(merged.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        f"Retry complete: {len(new_successes)} recovered, {len(still_failed)} still failing. "
        f"Wrote {framework_path}"
    )
    return merged


# =====================================================================
# Dual-pass critical fields (Layer 3)
# =====================================================================


async def extract_critical_fields_dual_pass(
    preprocessed: ProjectPreprocessed,
    agent: Agent | None = None,
    document_types: tuple[str, ...] = ("regels", "toelichting"),
    max_pages_per_doc: int | None = None,
) -> CriticalFieldsExtraction:
    """Independent second pass over the document set.

    The agent receives all page images and texts from the regels and
    toelichting at once and answers the open questions in
    ``prompts/critical_fields.md``. It does not see the first pass.
    The orchestrator compares these answers to the first pass numerically.
    """
    agent = agent or build_critical_fields_agent()

    user_parts: list = [
        "Project document set follows. Answer every open question in your instructions "
        "using only this source material. Quote verbatim. Surface conflicts, do not resolve them."
    ]

    page_count = 0
    for doc in preprocessed.documents:
        if doc.document_type not in document_types:
            continue
        pages = doc.pages if max_pages_per_doc is None else doc.pages[:max_pages_per_doc]
        for page in pages:
            user_parts.append(
                f"\n=== {doc.filename} (type: {doc.document_type}), page {page.page_number} ==="
            )
            user_parts.append(
                BinaryContent(data=_read_image_bytes(page.image_path), media_type="image/png")
            )
            user_parts.append(page.text or "(empty text layer)")
            page_count += 1

    logger.info(f"Dual-pass critical fields over {page_count} page(s)")
    result = await agent.run(user_parts)
    return result.output
