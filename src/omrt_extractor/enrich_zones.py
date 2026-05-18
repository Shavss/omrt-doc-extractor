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
import re
from pathlib import Path
from typing import Any

from loguru import logger

from omrt_extractor.schemas import (
    GeometricConstraint,
    NarrativeConstraint,
    NumericalConstraint,
    ParametricFramework,
)


def _normalise_code(code: str) -> str:
    """Normalise an aanduiding code for matching.

    Generic IMRO normalisation: strip surrounding/stray brackets/parens
    and quotes, lowercase, hyphens to underscores. Tolerates malformed
    one-sided brackets (e.g. '[sba_4') that can leak from upstream
    serialisation.

    Examples:
        '[sba-2]'  -> 'sba_2'
        '(sgd-4)'  -> 'sgd_4'
        '[sba_4'   -> 'sba_4'
        "'[sba-1]'"-> 'sba_1'
        'sba-dvg1' -> 'sba_dvg1'
        'WR-A'     -> 'wr_a'
    """
    t = code.strip().strip("'\"").strip()
    t = t.lstrip("[(").rstrip("])").strip()
    return t.lower().replace("-", "_").replace(" ", "_")


def _zone_codes(geom: GeometricConstraint) -> set[str]:
    """Extract all aanduiding codes from a geometric constraint's name and notes.

    The geometry merge step encodes codes in the name ('Bouwvlak sba-2, sgd-4')
    and raw_labels in notes. Parse both to get a complete deduplicated set of
    normalised codes.
    """
    codes: set[str] = set()

    name = geom.name or ""
    if name.lower().startswith("bouwvlak"):
        remainder = name[len("bouwvlak"):].strip()
        for part in re.split(r"[,\s]+", remainder):
            normalised = _normalise_code(part)
            if normalised:
                codes.add(normalised)

    notes = geom.notes or ""
    # Lazy match with a lookahead so we span the entire bracketed raw_labels
    # list — the trailing `]` is followed by `;`, ` |`, or end-of-string. A
    # naive `\[[^\]]*\]` truncates at the first inner `]` (e.g. inside
    # `'[sba-4]'`) and drops every label after it.
    m = re.search(r"raw_labels=\[(.*?)\](?=;|\s*\||$)", notes)
    if m:
        for tok in m.group(1).split(","):
            normalised = _normalise_code(tok)
            if normalised:
                codes.add(normalised)

    return codes


def _acoustic_overlays(geom: GeometricConstraint) -> list[str]:
    """Return overlay aanduidingen for a zone (e.g. sba-dvg* acoustic overlays).

    These codes accompany a real programme zone but describe overlay
    annotations rather than the buildable zone itself. Surfaced so the
    Grasshopper engineer can see them without inferring from the name.
    """
    overlays: list[str] = []
    for code in sorted(_zone_codes(geom)):
        if code.startswith("sba_dvg"):
            overlays.append(code)
    return overlays


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

    overlays = _acoustic_overlays(zone)
    return {
        "zone_id": zone.id,
        "zone_name": zone.name,
        "zone_codes": sorted(zone_codes),
        "acoustic_overlays": overlays,
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
