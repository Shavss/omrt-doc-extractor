# Claude Code Prompt — Fix geometry.py + Add Post-Pipeline Zone Enrichment
# Paste this entire prompt into Claude Code in one go.

---

## PHILOSOPHY BEFORE CODING

This pipeline must work on ANY Dutch bestemmingsplan project, not just Draka.
That means:

- `geometry.py` must be PURELY STRUCTURAL. It reads shapes and labels from
  the PDF drawing. It does NOT know what any label means. It does not know
  that sba-dvg is an acoustic overlay. It does not know what sgd-2 allows.
  It can only classify label PATTERNS (brackets = bouwaanduiding, parens =
  functieaanduiding, etc.) and polygon GEOMETRY (area, shape).

- Programme rules live in the EXTRACTED CONSTRAINTS from the regels PDFs.
  The extraction pipeline already pulls these into NumericalConstraint and
  NarrativeConstraint records with `applies_to` fields referencing zone codes.

- Zone enrichment (attaching programme rules to polygons) must happen AFTER
  the pipeline runs, by matching extracted constraints to geometric zones.
  Not before. Not during PDF parsing.

The ONE structural exception: sba-dvg polygons can be identified by label
PATTERN alone (the code starts with "sba-dvg"), without knowing what dvg
means. This is like knowing "brackets = bouwaanduiding" -- it is a naming
convention in IMRO, not project-specific knowledge.

---

## WHAT WE ARE FIXING

**Problem 1 (geometry.py):** sba-dvg polygons are currently classified as
bouwvlakken. They should be constraint_zones. This can be fixed structurally
by pattern-matching the "sba-dvg" prefix -- no project-specific knowledge
required.

**Problem 2 (post-pipeline):** After the pipeline runs, each bouwvlak has
labels (sgd codes, sba codes) but no programme rules attached. The extracted
NumericalConstraints already have `applies_to` referencing these same codes.
We need a step that joins them.

---

## TASK 1: Fix geometry.py -- structural dvg detection only

### 1a. Add the helper function

In `src/omrt_extractor/geometry.py`, add this helper function BEFORE
`parse_kaveltekening`. It uses only the IMRO naming convention (the "dvg"
prefix is part of the standard IMRO bouwaanduiding naming scheme), not
any project-specific knowledge:

```python
def _is_dvg_only(lp: "LabeledPolygon") -> bool:
    """True when every bouwaanduiding on this polygon is a dove-gevel overlay.

    Identified purely by the IMRO naming convention: the standard Dutch
    planning code for specifieke bouwaanduiding dove gevel always has the
    form 'sba-dvgN' (N = 1..5). This is a structural pattern, not
    project-specific knowledge -- every bestemmingsplan that uses dove
    gevel aanduidingen uses this naming scheme per PRBP2012.

    A dvg-only polygon is an acoustic constraint annotation printed on the
    kaveltekening. It is NOT a building envelope and must not be extruded
    as a massing volume. It belongs in constraint_zones, not bouwvlakken.

    A polygon is dvg-only when:
      - it has at least one bouwaanduiding
      - ALL of its bouwaanduidingen start with 'sba-dvg'
      - it has NO bestemming_codes or function_aanduidingen
        (which would indicate it overlaps a real programme zone)
    """
    if not lp.bouwaanduidingen:
        return False
    if lp.bestemming_codes or lp.function_aanduidingen:
        return False
    return all(
        code.lower().startswith("sba-dvg")
        for code in lp.bouwaanduidingen
    )
```

### 1b. Update the categorisation block

Find the categorisation loop near the end of `parse_kaveltekening`
(where polygons are sorted into bouwvlakken vs constraint_zones) and
replace it with:

```python
for i, (_poly, lp) in enumerate(real_entries):
    if i == plot_idx:
        continue
    if not lp.raw_labels:
        continue
    if _is_dvg_only(lp):
        # Dove gevel acoustic overlay -- constraint annotation, not a
        # building volume. Structural pattern detection only; the actual
        # height thresholds come from the regels extraction pipeline.
        constraint_zones.append(lp)
    elif lp.bouwaanduidingen:
        bouwvlakken.append(lp)
    elif lp.dubbelbestemmingen or lp.bestemming_codes or lp.function_aanduidingen:
        constraint_zones.append(lp)
```

### 1c. Add 'dvg_overlay' to the feature_type Literal in schemas.py

In `src/omrt_extractor/schemas.py`, find the `feature_type` Literal on
`GeometricConstraint` and add `"dvg_overlay"`:

```python
feature_type: Literal[
    "plot_boundary",
    "bouwvlak",
    "no_build_zone",
    "setback_zone",
    "dove_gevel_zone",    # <- rename this to dvg_overlay or keep both
    "dvg_overlay",        # <- add this
    "archaeology_zone",
    "vaarweg_zone",
    "noise_contour",
    "context_building",
    "other",
]
```

### 1d. Update merge_geometry_into_framework to use dvg_overlay

In `merge_geometry_into_framework` in `geometry.py`, update the
constraint zones loop to detect dvg-only zones by the same structural
pattern and assign the correct feature_type:

```python
for lp in geo.constraint_zones:
    # Structural detection: dvg-only = dove gevel overlay annotation
    if _is_dvg_only(lp):
        ft = "dvg_overlay"
    elif lp.dubbelbestemmingen:
        ft = "no_build_zone"
    else:
        ft = "other"
```

---

## TASK 2: Add post-pipeline zone enrichment

Create a new file `src/omrt_extractor/enrich_zones.py`.

This module runs AFTER the full pipeline (extraction, reconciliation,
geometry merge) and enriches each bouwvlak GeometricConstraint with
the programme rules that the extraction pipeline already pulled from
the regels. It does this by matching the constraint's `applies_to` field
against the zone labels on each geometric polygon.

No project-specific knowledge is hardcoded here. The rules come entirely
from the extracted NumericalConstraints and NarrativeConstraints.

```python
"""
Post-pipeline zone enrichment: attach extracted programme rules to
geometric bouwvlak zones by matching applies_to codes to zone labels.

This runs AFTER extract.py, reconcile.py, and merge_geometry_into_framework.
It adds a structured programme_rules block to each bouwvlak's notes and
produces a zone summary table useful for the Grasshopper engineer and the
PM handoff.

Primary function:
    enrich_zones(framework) -> ParametricFramework

The enriched framework has the same structure as before; the enrichment
appears as structured data in each bouwvlak GeometricConstraint.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from omrt_extractor.schemas import (
    GeometricConstraint,
    NumericalConstraint,
    NarrativeConstraint,
    ParametricFramework,
)


def _normalise_code(code: str) -> str:
    """Normalise an aanduiding code for matching.

    Generic IMRO normalisation: strip brackets/parens, lowercase,
    hyphens to underscores. Matches how geometry.py and reconcile.py
    normalise codes.

    Examples:
        '[sba-2]'  -> 'sba_2'
        '(sgd-4)'  -> 'sgd_4'
        'sba-dvg1' -> 'sba_dvg1'
        'WR-A'     -> 'wr_a'
    """
    t = code.strip()
    if len(t) >= 2 and t[0] in "([" and t[-1] in ")]":
        t = t[1:-1].strip()
    return t.lower().replace("-", "_").replace(" ", "_")


def _zone_codes(geom: GeometricConstraint) -> set[str]:
    """Extract all aanduiding codes from a geometric constraint's name and notes.

    The geometry merge step encodes codes in the name ('Bouwvlak sba-2, sgd-4')
    and raw_labels in notes. Parse both to get a complete set of normalised codes.
    """
    codes: set[str] = set()

    # From name: 'Bouwvlak sba-2, sgd-4, ...'
    name = geom.name or ""
    if name.lower().startswith("bouwvlak"):
        remainder = name[len("bouwvlak"):].strip()
        for part in remainder.split(","):
            part = part.strip().strip("[]()").strip()
            if part:
                codes.add(_normalise_code(part))

    # From notes: look for raw_labels=[...] pattern
    notes = geom.notes or ""
    import re
    m = re.search(r"raw_labels=\[([^\]]*)\]", notes)
    if m:
        for tok in m.group(1).split(","):
            tok = tok.strip().strip("'\"")
            if tok:
                codes.add(_normalise_code(tok))

    return codes


def _constraints_for_zone(
    zone: GeometricConstraint,
    numerical: list[NumericalConstraint],
    narrative: list[NarrativeConstraint],
) -> tuple[list[NumericalConstraint], list[NarrativeConstraint]]:
    """Find all constraints whose applies_to overlaps this zone's codes.

    Matching is purely by normalised code string comparison.
    No knowledge of what any specific code means.
    """
    zone_codes = _zone_codes(zone)
    if not zone_codes:
        return [], []

    # Also check associated_rules (IDs of constraints linked during merge)
    linked_ids = set(zone.associated_rules)

    matched_numerical = [
        c for c in numerical
        if c.id in linked_ids
        or any(_normalise_code(a) in zone_codes for a in c.applies_to)
    ]
    matched_narrative = [
        c for c in narrative
        if c.id in linked_ids
        or any(_normalise_code(a) in zone_codes for a in c.applies_to)
    ]

    return matched_numerical, matched_narrative


def _build_zone_summary(
    zone: GeometricConstraint,
    numerical: list[NumericalConstraint],
    narrative: list[NarrativeConstraint],
) -> dict[str, Any]:
    """Build a human- and machine-readable summary of rules for one zone.

    Structure is generic -- works for any project. The categories and
    values come entirely from the extracted constraints, not hardcoded.
    """
    zone_codes = _zone_codes(zone)

    # Group matched constraints by category
    by_category: dict[str, list[dict]] = {}
    for c in numerical:
        cat = c.category
        if cat not in by_category:
            by_category[cat] = []
        v = c.value
        by_category[cat].append({
            "id": c.id,
            "name": c.name,
            "value": list(v) if isinstance(v, tuple) else v,
            "unit": c.unit,
            "is_maximum": c.is_maximum,
            "condition": c.condition,
            "confidence": c.confidence.score,
            "source": f"{c.provenance.document} p.{c.provenance.page}" if c.provenance.document else "inferred",
        })

    narrative_summaries = [
        {"id": c.id, "statement": c.statement, "category": c.category}
        for c in narrative
    ]

    return {
        "zone_id": zone.id,
        "zone_name": zone.name,
        "zone_codes": sorted(zone_codes),
        "height_m": zone.extrusion_height_m,
        "height_source": zone.height_reconciled_from,
        "rules_by_category": by_category,
        "narrative_rules": narrative_summaries,
        "rule_count": len(numerical) + len(narrative),
    }


def enrich_zones(framework: ParametricFramework) -> tuple[ParametricFramework, list[dict]]:
    """Enrich each bouwvlak GeometricConstraint with its matched programme rules.

    Matches extracted NumericalConstraints and NarrativeConstraints to
    geometric bouwvlak zones using their applies_to codes. Purely structural
    matching -- no project-specific knowledge.

    Returns:
        (enriched_framework, zone_summaries)
        zone_summaries is a list of dicts, one per bouwvlak, suitable for
        writing to data/outputs/<project>/zone_programme_summary.json
    """
    bouwvlakken = [
        g for g in framework.constraints.geometric
        if g.feature_type == "bouwvlak"
    ]

    if not bouwvlakken:
        logger.warning("No bouwvlak geometric constraints found; nothing to enrich.")
        return framework, []

    numerical = framework.constraints.numerical
    narrative = framework.constraints.narrative

    zone_summaries: list[dict] = []
    enriched_notes: dict[str, str] = {}

    for zone in bouwvlakken:
        matched_num, matched_narr = _constraints_for_zone(zone, numerical, narrative)
        summary = _build_zone_summary(zone, matched_num, matched_narr)
        zone_summaries.append(summary)

        if matched_num or matched_narr:
            # Append structured programme summary to notes
            cats = sorted(summary["rules_by_category"].keys())
            rule_count = summary["rule_count"]
            enriched_notes[zone.id] = (
                (zone.notes or "")
                + f" | programme_rules: {rule_count} constraints"
                  f" across categories {cats}"
            )
            logger.info(
                "Zone '{}': matched {} numerical + {} narrative constraints",
                zone.name,
                len(matched_num),
                len(matched_narr),
            )
        else:
            logger.warning(
                "Zone '{}' (codes={}): no matching constraints found. "
                "Check that applies_to in the extracted constraints uses "
                "the same code format as the kaveltekening labels.",
                zone.name,
                _zone_codes(zone),
            )

    # Rebuild framework with enriched notes (immutable update via model_dump)
    if enriched_notes:
        payload = framework.model_dump(mode="json")
        for geom in payload["constraints"]["geometric"]:
            if geom["id"] in enriched_notes:
                geom["notes"] = enriched_notes[geom["id"]]
        framework = ParametricFramework.model_validate(payload)

    return framework, zone_summaries


def write_zone_summary(
    zone_summaries: list[dict],
    output_path,
) -> None:
    """Write zone summaries to JSON for the Grasshopper engineer and PM."""
    from pathlib import Path
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(zone_summaries, indent=2, default=str))
    logger.info("Zone programme summary written to {}", p)


def print_zone_table(zone_summaries: list[dict]) -> None:
    """Print a human-readable zone summary table to stdout."""
    print(f"\n{'='*80}")
    print("ZONE PROGRAMME SUMMARY (from extracted constraints)")
    print(f"{'='*80}\n")
    print(f"  {'Zone':<35s}  {'Height':>7}  {'Rules':>5}  Categories")
    print(f"  {'-'*35}  {'-'*7}  {'-'*5}  {'-'*20}")

    for z in zone_summaries:
        h = f"{z['height_m']}m" if z['height_m'] else "?"
        cats = ", ".join(sorted(z['rules_by_category'].keys())) or "none"
        codes = " ".join(z['zone_codes'][:3])
        print(f"  {codes:<35s}  {h:>7}  {z['rule_count']:>5}  {cats}")

    print()
```

---

## TASK 3: Wire enrich_zones into the CLI pipeline

In `src/omrt_extractor/cli.py`, in the `run` command, add the zone
enrichment call in the cheap chain AFTER `merge_geometry_into_framework`
and BEFORE `generate_example_massings`:

```python
# After: framework = merge_geometry_into_framework(framework, geometry_obj)
# Add:
from omrt_extractor.enrich_zones import enrich_zones, write_zone_summary, print_zone_table

framework, zone_summaries = enrich_zones(framework)
zone_summary_path = out_dir / "zone_programme_summary.json"
write_zone_summary(zone_summaries, zone_summary_path)
print_zone_table(zone_summaries)
fresh.append("zone_enrichment")
```

---

## TASK 4: Add a standalone script for inspecting zone enrichment

Create `scripts/inspect_zones.py` for running zone enrichment in isolation
against an existing pipeline output, without re-running the full pipeline:

```python
"""
Inspect zone programme enrichment for a project that has already been run.

Usage:
    .venv/bin/python scripts/inspect_zones.py data/outputs/<project>/

Reads framework.json and zone_programme_summary.json if present,
prints the zone table, and shows which constraints matched each zone.
Useful for debugging applies_to mismatches.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from omrt_extractor.schemas import ParametricFramework
from omrt_extractor.enrich_zones import (
    enrich_zones, write_zone_summary, print_zone_table, _zone_codes
)

def main():
    if len(sys.argv) < 2:
        print("Usage: inspect_zones.py <output_dir>")
        sys.exit(1)

    output_dir = Path(sys.argv[1])
    framework_path = output_dir / "framework.json"
    if not framework_path.exists():
        print(f"framework.json not found at {framework_path}")
        sys.exit(1)

    raw = json.loads(framework_path.read_text())
    framework_data = raw.get("framework", raw)

    # Strip geometry_geojson and geometry_compas that were added by serialise_framework
    for entry in framework_data.get("constraints", {}).get("geometric", []) or []:
        entry.pop("geometry_geojson", None)
        entry.pop("geometry_compas", None)

    framework = ParametricFramework.model_validate(framework_data)

    print(f"\nProject: {framework.metadata.project_name}")
    print(f"Numerical constraints: {len(framework.constraints.numerical)}")
    print(f"Geometric constraints: {len(framework.constraints.geometric)}")
    print(f"Narrative constraints: {len(framework.constraints.narrative)}")

    bouwvlakken = [g for g in framework.constraints.geometric if g.feature_type == "bouwvlak"]
    print(f"Bouwvlakken: {len(bouwvlakken)}")

    # Show zone codes vs applies_to codes to diagnose mismatches
    print("\n=== ZONE CODES (from geometry) ===")
    for bv in bouwvlakken:
        codes = _zone_codes(bv)
        print(f"  {bv.name:<40s}  codes={sorted(codes)}")

    print("\n=== APPLIES_TO CODES (from extracted constraints) ===")
    for c in framework.constraints.numerical:
        if c.applies_to:
            print(f"  [{c.category}] {c.id:<40s}  applies_to={c.applies_to}")

    _, summaries = enrich_zones(framework)
    print_zone_table(summaries)

    out_path = output_dir / "zone_programme_summary.json"
    write_zone_summary(summaries, out_path)
    print(f"Written to {out_path}")

if __name__ == "__main__":
    main()
```

---

## TASK 5: Verify everything works

First re-run the geometry parser on Draka:

```bash
.venv/bin/python scripts/run_geometry.py \
  "data/inputs/draka/Drakaterrein-A2_2022-04-26 versie 2_kaveltekening.pdf" \
  data/outputs/draka/geometry.json
```

Then inspect zones against the existing Draka framework:

```bash
.venv/bin/python scripts/inspect_zones.py data/outputs/draka/
```

The output will show which zone codes the geometry parser found and
which applies_to codes the extraction pipeline produced. If they use
different normalisation (e.g. geometry has "sba_2" but applies_to has
"sba-2"), fix the normalisation in `_normalise_code` so they match.

Expected: each bouwvlak shows matched constraints from categories like
"height", "bvo_limit", "setback" with their source documents and values.

---

## WHAT NOT TO DO

- Do NOT hardcode any sgd or sba rules in geometry.py or enrich_zones.py
- Do NOT reference Draka, Amsterdam, or any specific plan in any module
- Do NOT add any logic that assumes a specific number of zones or a
  specific height value
- The `_is_dvg_only` function may ONLY use the structural pattern
  "sba-dvg" prefix -- this is a standard IMRO naming convention,
  not Draka-specific knowledge
- If applies_to matching fails for Draka, fix the normalisation, do not
  add special cases

---

## COMMIT WHEN DONE

```bash
git add src/omrt_extractor/geometry.py \
        src/omrt_extractor/schemas.py \
        src/omrt_extractor/enrich_zones.py \
        src/omrt_extractor/cli.py \
        scripts/inspect_zones.py

git commit -m "fix: structural dvg detection + post-pipeline zone enrichment

- geometry.py: _is_dvg_only() detects dove gevel overlays by IMRO
  naming pattern only (sba-dvgN prefix). No project-specific rules.
  dvg-only polygons now go to constraint_zones, not bouwvlakken.
- schemas.py: added 'dvg_overlay' feature_type
- enrich_zones.py: new post-pipeline step that matches extracted
  NumericalConstraints/NarrativeConstraints to geometric zones by
  applies_to code matching. Purely structural, no hardcoded rules.
- cli.py: enrich_zones wired into run command after geometry merge
- scripts/inspect_zones.py: diagnostic tool for applies_to matching"
```
