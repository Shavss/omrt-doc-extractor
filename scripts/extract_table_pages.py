"""Re-extract specific pages with a table-aware instruction, merging into the framework.

Some pages in the toelichting carry programme tables whose row-level detail
(BVO target, outdoor area, kavel locations, function description) gets
summarised away by the default extraction prompt. This script re-runs the
extraction agent on a hand-picked list of (document, page) tuples with an
extra instruction that forces row-by-row transcription, then merges any new
programme_hints, narrative_constraints, and numerical_constraints into the
existing ExtractionResult on disk.

Idempotent enough for repeated runs: this script appends, it does not
deduplicate. Re-running grows the lists.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from omrt_extractor.config import settings  # noqa: E402
from omrt_extractor.extract import (  # noqa: E402
    ExtractionResult,
    PageExtraction,
    _save_checkpoint,
    build_extraction_agent,
    extract_page,
)
from omrt_extractor.preprocess import preprocess_project  # noqa: E402
from omrt_extractor.schemas import ProjectPreprocessed  # noqa: E402

FRAMEWORK_PATH = ROOT / "data" / "outputs" / "draka_framework_single_pass.json"
DRAKA_INPUT_DIR = ROOT / "data" / "inputs" / "draka"

TABLE_INSTRUCTION = (
    "CRITICAL FOR THIS PAGE: This page contains a programme table. "
    "Read the table content from the image directly. Capture EVERY row with "
    "its BVO target, outdoor area, kavel locations, and brief function "
    "description. Do not summarise; transcribe. Add ONE programme_hint per "
    "row, or pack rows into structured programme_hints if that fits the "
    "agent's output better."
)


def _find_page(preprocessed: ProjectPreprocessed, filename: str, page_number: int):
    for doc in preprocessed.documents:
        if doc.filename != filename:
            continue
        for page in doc.pages:
            if page.page_number == page_number:
                return doc, page
    return None, None


async def extract_table_pages(
    targets: list[tuple[str, int]],
    framework_path: Path = FRAMEWORK_PATH,
    input_dir: Path = DRAKA_INPUT_DIR,
) -> dict:
    """Run table-aware re-extraction over each target, merge into the framework."""
    framework = ExtractionResult.model_validate_json(framework_path.read_text(encoding="utf-8"))
    preprocessed = preprocess_project(input_dir, settings.cache_dir)
    agent = build_extraction_agent()

    added_hints: list[str] = []
    added_narrative: list = []
    added_numerical: list = []
    new_errors: list[tuple[str, int, str]] = []
    per_page_new: dict[tuple[str, int], list[str]] = {}

    for filename, page_number in targets:
        doc, page = _find_page(preprocessed, filename, page_number)
        if page is None:
            msg = "page missing from preprocessed input"
            logger.warning(f"{filename} p{page_number}: {msg}")
            new_errors.append((filename, page_number, msg))
            continue

        augmented_text = (page.text or "(empty text layer)") + "\n\n" + TABLE_INSTRUCTION
        try:
            partial = await extract_page(
                page.image_path,
                augmented_text,
                {
                    "document_filename": doc.filename,
                    "page_number": page.page_number,
                    "document_type": doc.document_type,
                },
                agent=agent,
            )
        except Exception as exc:
            logger.warning(f"Re-extraction failed for {filename} p{page_number}: {exc}")
            new_errors.append((filename, page_number, str(exc)))
            continue

        added_hints.extend(partial.programme_hints)
        added_narrative.extend(partial.narrative_constraints)
        added_numerical.extend(partial.numerical_constraints)
        per_page_new[(filename, page_number)] = list(partial.programme_hints)

        framework.programme_hints.extend(partial.programme_hints)
        framework.narrative_constraints.extend(partial.narrative_constraints)
        framework.numerical_constraints.extend(partial.numerical_constraints)

        # Reflect the new content in the per_page record so the framework's
        # flat lists stay reconcilable with their page-scoped source. Replace
        # an existing entry for this page; append a fresh one otherwise.
        new_entry = PageExtraction(
            document_filename=filename,
            page_number=page_number,
            partial=partial,
        )
        replaced = False
        for i, pe in enumerate(framework.per_page):
            if pe.document_filename == filename and pe.page_number == page_number:
                framework.per_page[i] = new_entry
                replaced = True
                break
        if not replaced:
            framework.per_page.append(new_entry)

        # Persist the checkpoint so subsequent runs (e.g. extract_project)
        # see this richer extraction instead of re-issuing the API call and
        # losing the table-aware content.
        _save_checkpoint(new_entry)

    if new_errors:
        existing_keys = {(f, p) for f, p, _ in framework.pages_with_extraction_errors}
        for err in new_errors:
            if (err[0], err[1]) not in existing_keys:
                framework.pages_with_extraction_errors.append(err)

    framework_path.write_text(framework.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        f"Merged: +{len(added_hints)} programme_hints, "
        f"+{len(added_narrative)} narrative_constraints, "
        f"+{len(added_numerical)} numerical_constraints. "
        f"Wrote {framework_path}"
    )

    return {
        "added_programme_hints": len(added_hints),
        "added_narrative_constraints": len(added_narrative),
        "added_numerical_constraints": len(added_numerical),
        "new_errors": new_errors,
        "per_page_new_hints": per_page_new,
    }


def main() -> None:
    targets: list[tuple[str, int]] = [
        ("Draka Terrein Hamerkwartier_Toelichting.pdf", 43),
    ]
    report = asyncio.run(extract_table_pages(targets))

    print()
    print("=" * 72)
    print("Table-page re-extraction report")
    print("=" * 72)
    print(f"Added programme_hints     : {report['added_programme_hints']}")
    print(f"Added narrative_constraints: {report['added_narrative_constraints']}")
    print(f"Added numerical_constraints: {report['added_numerical_constraints']}")
    if report["new_errors"]:
        print(f"New extraction errors      : {len(report['new_errors'])}")
        for f, p, e in report["new_errors"]:
            print(f"  - {f} p{p}: {e}")
    print()
    for (filename, page_number), hints in report["per_page_new_hints"].items():
        print(f"New programme_hints from {filename} p{page_number}:")
        if not hints:
            print("  (none)")
        for i, hint in enumerate(hints, start=1):
            print(f"  [{i}] {hint}")
        print()


if __name__ == "__main__":
    main()
