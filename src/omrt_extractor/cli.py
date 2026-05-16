"""Typer CLI: `omrt run <input_dir>` and friends.

The single entry point for invoking the pipeline from a shell.

Commands:
    omrt run <input_dir>      Run the full pipeline on a project folder
    omrt validate <path>      Re-run validators on an existing framework.json
    omrt archive <path>       Mark a framework as reviewed and archive it
    omrt seed-glossary        Run scripts/seed_glossary.py via the CLI

Usage examples:
    omrt run data/inputs/draka
    omrt run data/inputs/draka --skip-enrich --skip-cross-validate
    omrt archive data/outputs/draka/framework.json

Implementation: thin orchestration. Read inputs, call preprocess, extract,
geometry, enrich, cross_validate, infer, output, archive (gated by --archive
flag and verification status). Stream progress via rich.

Stage 6 of the build plan (the run command is the integration test for
everything before it).
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="omrt",
    help="OMRT doc-extractor: Dutch project documents to Grasshopper framework.",
    no_args_is_help=True,
)


@app.command()
def run(input_dir: str) -> None:
    """Run the pipeline on a project input directory."""
    typer.echo(f"TODO Stage 6: implement run on {input_dir}")


@app.command()
def validate(framework_path: str) -> None:
    """Re-run validators on an existing framework.json."""
    typer.echo(f"TODO: implement validate on {framework_path}")


@app.command()
def archive(framework_path: str) -> None:
    """Mark a framework as reviewed and archive it."""
    typer.echo(f"TODO: implement archive on {framework_path}")


if __name__ == "__main__":
    app()
