"""Prompt files loaded by extract.py and infer.py.

Prompts live here rather than at repo root because they are runtime
resources for the package: they need to load via relative paths regardless
of where the CLI is invoked from, and they ship with the installed package.

Files:
    extraction.md       Per-page multimodal extraction (Stage 2)
    critical_fields.md  Dual-pass open-question verification (Stage 2)
    programme.md        Programme inference synthesis (Stage 5)
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt by filename (without extension).

    Example:
        load_prompt("extraction")  # reads extraction.md
    """
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")
