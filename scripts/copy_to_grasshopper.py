"""Copy Approach 1 (PDF pipeline) handoff artifacts for a project into
`grasshopper/examples/<project>/approach_1_pdf/` so the Grasshopper engineer
has a self-contained reference next to the README.

Usage:
    python scripts/copy_to_grasshopper.py <project_name>

The project must already have outputs at `data/outputs/<project_name>/`
(produced by `omrt run data/inputs/<project_name>/`).

Approach 2 (GML) is project-specific and not copied automatically; new test
projects use Approach 1 only.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from loguru import logger

APPROACH_1_FILES = ["framework.json", "massing_inputs.json", "geometry.json"]
APPROACH_1_DIRS = ["geometry", "massings"]


def copy_handoff(project: str) -> Path:
    src = Path("data/outputs") / project
    if not src.is_dir():
        raise SystemExit(f"No outputs found at {src}. Run the pipeline first.")

    dst = Path("grasshopper/examples") / project / "approach_1_pdf"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    for name in APPROACH_1_FILES:
        path = src / name
        if path.is_file():
            shutil.copy2(path, dst / name)
            logger.info(f"copied {name}")

    for name in APPROACH_1_DIRS:
        path = src / name
        if path.is_dir():
            shutil.copytree(path, dst / name)
            logger.info(f"copied {name}/")

    logger.success(f"Grasshopper handoff at {dst}")
    return dst


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/copy_to_grasshopper.py <project_name>")
    copy_handoff(sys.argv[1])
