"""One-time migration of legacy output paths to data/outputs/<project>/ layout.

Idempotent: safe to run multiple times. Moves files only when source exists;
never silently clobbers a differing destination.

Legacy -> canonical mapping (project=draka):

  data/outputs/draka_framework_single_pass.json
    -> data/outputs/draka/extraction_raw.json
  data/outputs/draka_programme.json
    -> data/outputs/draka/programme.json
  data/outputs/draka_geometry.json
    -> data/outputs/draka/geometry.json
  data/test_output/geo_context.json
    -> data/outputs/draka/geo_context.json

In-subdir legacy duplicates (older copies left from a partial migration):
  data/outputs/draka/draka_framework_single_pass.json
    -> data/outputs/draka/extraction_raw.json
  data/outputs/draka/draka_geometry.json
    -> data/outputs/draka/geometry.json
  data/outputs/draka/draka_programme.json
    -> data/outputs/draka/programme.json

Conflict policy: if both src and dst exist and their sha256 differ, abort and
print the conflict. The user resolves by hand.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "data" / "outputs"
TEST_OUTPUT = ROOT / "data" / "test_output"

MIGRATIONS: list[tuple[Path, Path]] = [
    (
        OUTPUTS / "draka" / "draka_framework_single_pass.json",
        OUTPUTS / "draka" / "extraction_raw.json",
    ),
    (OUTPUTS / "draka" / "draka_geometry.json", OUTPUTS / "draka" / "geometry.json"),
    (OUTPUTS / "draka" / "draka_programme.json", OUTPUTS / "draka" / "programme.json"),
    (OUTPUTS / "draka_framework_single_pass.json", OUTPUTS / "draka" / "extraction_raw.json"),
    (OUTPUTS / "draka_geometry.json", OUTPUTS / "draka" / "geometry.json"),
    (OUTPUTS / "draka_programme.json", OUTPUTS / "draka" / "programme.json"),
    (TEST_OUTPUT / "geo_context.json", OUTPUTS / "draka" / "geo_context.json"),
]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def migrate(src: Path, dst: Path) -> str:
    if not src.exists():
        return f"skip  (no src):       {src.relative_to(ROOT)}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if src.resolve() == dst.resolve():
            return f"skip  (same path):    {src.relative_to(ROOT)}"
        if _sha256(src) == _sha256(dst):
            src.unlink()
            return f"dedup (identical):    removed {src.relative_to(ROOT)}"
        return (
            f"CONFLICT (differing): {src.relative_to(ROOT)} vs "
            f"{dst.relative_to(ROOT)} — resolve by hand"
        )
    shutil.move(str(src), str(dst))
    return f"moved:                {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}"


def main() -> int:
    conflicts = 0
    for src, dst in MIGRATIONS:
        msg = migrate(src, dst)
        print(msg)
        if msg.startswith("CONFLICT"):
            conflicts += 1
    if conflicts:
        print(f"\n{conflicts} conflict(s) — resolve manually and rerun.")
        return 1
    print("\nMigration complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
