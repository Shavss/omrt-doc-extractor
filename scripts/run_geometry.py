"""Parse a kaveltekening PDF and write geometry JSON.

Place this file at the repo root (same level as pyproject.toml / src/).

Usage
-----
    # If the package is pip-installed (editable or not):
    python scripts/run_geometry.py data/inputs/draka/kaveltekening.pdf

    # If NOT installed, run from repo root so the package is importable:
    PYTHONPATH=src python scripts/run_geometry.py data/inputs/draka/kaveltekening.pdf

    # Explicit output path:
    python scripts/run_geometry.py path/to/kaveltekening.pdf data/outputs/draka_geometry.json

Output defaults to  data/outputs/<pdf-stem>_geometry.json  relative to the
repo root (the directory containing this script). Pass a second argument to
override.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """Walk up from start until pyproject.toml or setup.py is found."""
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").is_file() or (parent / "setup.py").is_file():
            return parent
    return start  # fallback: treat script's directory as root


_SCRIPT_DIR = Path(__file__).parent.resolve()
_REPO_ROOT = _find_repo_root(_SCRIPT_DIR)

# Ensure the package source is importable when not pip-installed.
# Works for both src/ layout and flat layout (omrt_extractor/ at repo root).
for _candidate in (_REPO_ROOT / "src", _REPO_ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    pdf_path = Path(sys.argv[1]).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) >= 3:
        out_path = Path(sys.argv[2]).expanduser().resolve()
    else:
        out_dir = _REPO_ROOT / "data" / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{pdf_path.stem}_geometry.json"

    try:
        from omrt_extractor.geometry import parse_kaveltekening
    except ModuleNotFoundError as exc:
        print(
            f"ERROR: could not import omrt_extractor.geometry: {exc}\n\n"
            "Options:\n"
            "  1. pip install -e .            (from repo root)\n"
            "  2. PYTHONPATH=src python scripts/run_geometry.py <pdf>\n"
            "  3. PYTHONPATH=. python scripts/run_geometry.py <pdf>",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Parsing : {pdf_path}", file=sys.stderr)
    result = parse_kaveltekening(pdf_path)

    out_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False)
    )
    print(f"Written : {out_path}\n", file=sys.stderr)

    # Summary to stderr so you can sanity-check without opening the file.
    print(f"Status      : {result.status}", file=sys.stderr)
    if result.reason:
        print(f"Reason      : {result.reason}", file=sys.stderr)
    print(f"Scale       : 1:{result.scale_denominator}  ({result.scale_status})", file=sys.stderr)
    print(f"Plot polygon: {'yes' if result.plot_polygon else 'no'}", file=sys.stderr)
    print(f"Bouwvlakken : {len(result.bouwvlakken)}", file=sys.stderr)
    print(f"Zones       : {len(result.constraint_zones)}", file=sys.stderr)

    if result.bouwvlakken:
        print("\nBouwvlakken:", file=sys.stderr)
        for bv in result.bouwvlakken:
            codes = bv.bouwaanduidingen + bv.function_aanduidingen + bv.bestemming_codes
            height = f"{bv.height_m}m" if bv.height_m is not None else "None"
            print(
                f"  [{', '.join(codes) or 'unlabelled':35s}]"
                f"  {bv.area_m2:8.0f} m2"
                f"  height={height:>8s}",
                file=sys.stderr,
            )

    if result.constraint_zones:
        print("\nConstraint zones:", file=sys.stderr)
        for z in result.constraint_zones:
            codes = z.dubbelbestemmingen + z.function_aanduidingen + z.bestemming_codes
            print(
                f"  [{', '.join(codes) or 'unlabelled':35s}]"
                f"  {z.area_m2:8.0f} m2",
                file=sys.stderr,
            )

    sys.exit(0 if result.status == "ok" else 2)


if __name__ == "__main__":
    main()
