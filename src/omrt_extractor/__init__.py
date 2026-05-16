"""OMRT doc-extractor: Dutch project documents to Grasshopper-ready Parametric Framework.

This package implements the pipeline described in docs/architecture.md.
The single most important module is `schemas`, which defines the Pydantic
contract every other module produces or consumes.

Public entry points:
    omrt_extractor.cli:app       Typer CLI, `omrt run <input_dir>`
    omrt_extractor.schemas       The Pydantic schema
"""

from __future__ import annotations

__version__ = "0.1.0"
