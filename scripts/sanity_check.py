"""Sanity-check the outputs of a single project run.

Verifies that the pipeline produced a well-formed, non-trivial result
for a new project bundle. Designed for the generality test: drop a new
project's PDFs into `data/inputs/<project>/`, run the pipeline, then
run this script against `data/outputs/<project>/` to confirm the four
load-bearing artifacts exist and carry the minimum structural content
a Grasshopper engineer needs.

The checks are universal and structural (presence, schema validity,
plausible ranges), never value-specific. They should pass on any
reasonable Dutch zoning packet.

Usage:
    python scripts/sanity_check.py data/outputs/<project_name>/

Exit codes:
    0  every check passed
    1  one or more checks failed (diagnostics printed to stderr)
    2  invalid invocation (bad path, missing argument)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from omrt_extractor.schemas import ParametricFramework

REQUIRED_SUMMARY_HEADERS = [
    "## How to consume this output",
    "## Numerical constraints",
    "## Geometric constraints",
    "## Programme proposal",
]


def _fail(check: str, detail: str) -> tuple[bool, str]:
    return False, f"FAIL [{check}] {detail}"


def _ok(check: str) -> tuple[bool, str]:
    return True, f"PASS [{check}]"


def check_framework(output_dir: Path) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    path = output_dir / "framework.json"

    if not path.exists():
        results.append(_fail("framework.exists", f"{path} not found"))
        return results
    results.append(_ok("framework.exists"))

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        results.append(_fail("framework.json_parse", str(exc)))
        return results

    payload = raw.get("framework", raw) if isinstance(raw, dict) else raw

    # The on-disk framework.json is augmented by output.serialise_framework:
    # each geometric constraint gets `geometry_geojson` and `geometry_compas`
    # baked in for downstream consumers. Those keys violate the schema's
    # extra="forbid", so strip them before validating the structural contract.
    if isinstance(payload, dict):
        for entry in payload.get("constraints", {}).get("geometric", []) or []:
            entry.pop("geometry_geojson", None)
            entry.pop("geometry_compas", None)

    try:
        framework = ParametricFramework.model_validate(payload)
    except ValidationError as exc:
        results.append(
            _fail(
                "framework.schema",
                f"ParametricFramework validation failed: {exc.error_count()} errors",
            )
        )
        return results
    results.append(_ok("framework.schema"))

    height_constraints = [c for c in framework.constraints.numerical if c.category == "height"]
    if not height_constraints:
        results.append(
            _fail("framework.height_constraint", "no numerical constraint with category='height'")
        )
    else:
        results.append(_ok("framework.height_constraint"))

    geometric_feature_types = {c.feature_type for c in framework.constraints.geometric}
    if not geometric_feature_types & {"plot_boundary", "bouwvlak"}:
        results.append(
            _fail(
                "framework.geometric_feature",
                f"no geometric_constraint with feature_type in {{'plot_boundary','bouwvlak'}}; saw {sorted(geometric_feature_types)}",
            )
        )
    else:
        results.append(_ok("framework.geometric_feature"))

    return results


def check_programme(output_dir: Path) -> list[tuple[bool, str]]:
    path = output_dir / "programme.json"
    if not path.exists():
        return [_fail("programme.exists", f"{path} not found")]
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [_fail("programme.json_parse", str(exc))]

    gfa = data.get("target_total_gfa_m2")
    if not isinstance(gfa, (int, float)) or gfa <= 0:
        return [_fail("programme.gfa", f"target_total_gfa_m2 must be > 0, got {gfa!r}")]
    return [_ok("programme.exists"), _ok("programme.gfa")]


def check_reconciliation(output_dir: Path) -> list[tuple[bool, str]]:
    path = output_dir / "reconciliation_report.json"
    if not path.exists():
        return [_fail("reconciliation.exists", f"{path} not found")]
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [_fail("reconciliation.json_parse", str(exc))]

    entries = data if isinstance(data, list) else data.get("entries", [])
    actions = {entry.get("action") for entry in entries if isinstance(entry, dict)}
    if not actions & {"matched", "corrected"}:
        return [
            _fail(
                "reconciliation.matched_or_corrected",
                f"no polygon with action in {{'matched','corrected'}}; saw {sorted(a for a in actions if a)}",
            )
        ]
    return [_ok("reconciliation.exists"), _ok("reconciliation.matched_or_corrected")]


def check_summary(output_dir: Path) -> list[tuple[bool, str]]:
    path = output_dir / "summary.md"
    if not path.exists():
        return [_fail("summary.exists", f"{path} not found")]
    text = path.read_text()
    if not text.strip():
        return [_fail("summary.non_empty", "summary.md is empty")]

    missing = [h for h in REQUIRED_SUMMARY_HEADERS if h not in text]
    if missing:
        return [_fail("summary.headers", f"missing section headers: {missing}")]
    return [_ok("summary.exists"), _ok("summary.headers")]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/sanity_check.py <output_dir>", file=sys.stderr)
        return 2

    output_dir = Path(argv[1])
    if not output_dir.is_dir():
        print(f"not a directory: {output_dir}", file=sys.stderr)
        return 2

    results: list[tuple[bool, str]] = []
    results.extend(check_framework(output_dir))
    results.extend(check_programme(output_dir))
    results.extend(check_reconciliation(output_dir))
    results.extend(check_summary(output_dir))

    for ok, msg in results:
        stream = sys.stdout if ok else sys.stderr
        print(msg, file=stream)

    failed = sum(1 for ok, _ in results if not ok)
    total = len(results)
    if failed:
        print(f"\n{failed}/{total} checks failed for {output_dir}", file=sys.stderr)
        return 1
    print(f"\nAll {total} checks passed for {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
