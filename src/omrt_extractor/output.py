"""Grasshopper handoff serialisation.

Writes the validated ParametricFramework to JSON for the Grasshopper
engineer plus a human-readable summary. Three artifacts per project under
``output_dir``:

    framework.json       The full ParametricFramework with handoff header
    massing_inputs.json  Slim envelope-driver subset for Grasshopper
    geometry/*.compas    COMPAS Polygon JSON per GeometricConstraint
    summary.md           Markdown summary of bindings and reasoning

The framework.json wraps the schema's serialised form with a top-level
header block carrying the prominent prototype banner, the generation
timestamp, the verification status, and a flat ``source_documents`` list.

Each GeometricConstraint is enriched with two parallel representations:

    geometry.geojson    GeoJSON-compatible Polygon (always WGS84 lng/lat)
    geometry.compas     COMPAS-JSON Polygon block (in native CRS)

Both are embedded inline so the Grasshopper engineer can pick whichever
loader is convenient. The COMPAS block is additionally written out to a
sidecar file under ``geometry/<id>.compas`` so loaders that prefer file
paths work too.

Stage 6 of the build plan.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from omrt_extractor.schemas import (
    CRS,
    GeometricConstraint,
    ParametricFramework,
    VerificationStatus,
    validate_cross_references,
)

PROTOTYPE_BANNER = "PROTOTYPE OUTPUT, NOT VERIFIED"
REVIEWED_BANNER = "Human-reviewed output. Verified by reviewer."
CONFIDENCE_REVIEW_THRESHOLD = 0.85

# Numerical-constraint categories that drive Grasshopper massing envelope.
# Other categories (noise, parking, sustainability, ...) stay in framework.json
# for audit but are excluded from the slim massing_inputs.json sidecar.
MASSING_CATEGORIES: frozenset[str] = frozenset(
    {"height", "setback", "footprint", "fsi_far", "bvo_limit", "use_mix"}
)


# ---------------------------------------------------------------------------
# CRS conversion (RD New EPSG:28992 to WGS84). Self-contained closed-form
# approximation good to a few centimetres inside the Netherlands. Avoids a
# hard dependency on pyproj in the handoff path.
# ---------------------------------------------------------------------------


def _rd_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Return (lng, lat) in WGS84 for an RD New (x, y) pair."""
    x0, y0 = 155000.0, 463000.0
    lat0, lng0 = 52.15517440, 5.38720621
    dx = (x - x0) * 1e-5
    dy = (y - y0) * 1e-5
    kp = [
        (0, 1, 3235.65389),
        (2, 0, -32.58297),
        (0, 2, -0.24750),
        (2, 1, -0.84978),
        (0, 3, -0.06550),
        (2, 2, -0.01709),
        (1, 0, -0.00738),
        (4, 0, 0.00530),
        (2, 3, -0.00039),
        (4, 1, 0.00033),
        (1, 1, -0.00012),
    ]
    lp = [
        (1, 0, 5260.52916),
        (1, 1, 105.94684),
        (1, 2, 2.45656),
        (3, 0, -0.81885),
        (1, 3, 0.05594),
        (3, 1, -0.05607),
        (0, 1, 0.01199),
        (3, 2, -0.00256),
        (1, 4, 0.00128),
        (0, 2, 0.00022),
        (2, 0, -0.00022),
        (5, 0, 0.00026),
    ]
    lat = lat0 + sum(c * dx**p * dy**q for p, q, c in kp) / 3600.0
    lng = lng0 + sum(c * dx**p * dy**q for p, q, c in lp) / 3600.0
    return lng, lat


def _to_geojson_ring(coords: list[list[float]], crs: CRS) -> list[list[float]]:
    """Project a polygon ring into WGS84 lng/lat order suitable for GeoJSON."""
    if crs == CRS.WGS84:
        return [[pt[1], pt[0]] for pt in coords]
    if crs == CRS.RD_NEW:
        out: list[list[float]] = []
        for pt in coords:
            lng, lat = _rd_to_wgs84(pt[0], pt[1])
            out.append([lng, lat])
        return out
    return [list(pt) for pt in coords]


def _compas_polygon(geom: GeometricConstraint) -> dict[str, Any]:
    """Build a COMPAS-JSON Polygon block in the geometry's native CRS."""
    points: list[list[float]] = []
    for pt in geom.coordinates:
        x, y = pt[0], pt[1]
        z = pt[2] if len(pt) == 3 else (geom.elevation_m or 0.0)
        points.append([x, y, z])
    return {
        "dtype": "compas.geometry/Polygon",
        "value": {"points": points[:-1] if points[0] == points[-1] else points},
        "crs": geom.crs.value,
    }


def _geojson_feature(geom: GeometricConstraint) -> dict[str, Any]:
    ring = _to_geojson_ring(geom.coordinates, geom.crs)
    return {
        "type": "Feature",
        "id": geom.id,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "name": geom.name,
            "feature_type": geom.feature_type,
            "lod": geom.lod,
            "elevation_m": geom.elevation_m,
            "extrusion_height_m": geom.extrusion_height_m,
            "associated_rules": geom.associated_rules,
            "confidence_score": geom.confidence.score,
        },
    }


# ---------------------------------------------------------------------------
# Header + serialisation
# ---------------------------------------------------------------------------


def _banner_for(status: VerificationStatus) -> str:
    return REVIEWED_BANNER if status == VerificationStatus.REVIEWED else PROTOTYPE_BANNER


def _build_header(framework: ParametricFramework) -> dict[str, Any]:
    status = framework.metadata.verification_status
    return {
        "banner": _banner_for(status),
        "verification_status": status.value,
        "generated_at": datetime.now(UTC).isoformat(),
        "tool_version": framework.metadata.tool_version,
        "project_name": framework.metadata.project_name,
        "plan_id": framework.metadata.location.plan_id,
        "source_documents": [
            {
                "filename": d.filename,
                "document_type": d.document_type,
                "page_count": d.page_count,
                "sha256": d.sha256,
            }
            for d in framework.metadata.source_documents
        ],
        "review_threshold": CONFIDENCE_REVIEW_THRESHOLD,
    }


def serialise_framework(
    framework: ParametricFramework,
    *,
    zone_programme_summary: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Produce the JSON-ready dict for framework.json.

    If ``zone_programme_summary`` is provided (the per-bouwvlak rules list
    written by ``enrich_zones.write_zone_summary``), it is embedded as a
    top-level key so the Grasshopper engineer can read every zone-to-rule
    mapping from framework.json alone.
    """
    body = framework.model_dump(mode="json")

    geometries_out: list[dict[str, Any]] = []
    for geom in framework.constraints.geometric:
        entry = body_geom_lookup(body, geom.id)
        compas_block = _compas_polygon(geom)
        feature = _geojson_feature(geom)
        if entry is not None:
            entry["geometry_geojson"] = feature
            entry["geometry_compas"] = compas_block
        geometries_out.append(
            {"id": geom.id, "geojson": feature, "compas": compas_block}
        )

    payload: dict[str, Any] = {
        "header": _build_header(framework),
        "geometries": geometries_out,
        "framework": body,
    }
    if zone_programme_summary is not None:
        payload["zone_programme_summary"] = zone_programme_summary
    return payload


def body_geom_lookup(body: dict[str, Any], geom_id: str) -> dict[str, Any] | None:
    for entry in body.get("constraints", {}).get("geometric", []):
        if entry.get("id") == geom_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Massing-inputs sidecar
# ---------------------------------------------------------------------------


def build_massing_inputs(framework: ParametricFramework) -> dict[str, Any]:
    """Slim envelope-driver payload for Grasshopper massing.

    Keeps only numerical constraints in MASSING_CATEGORIES plus geometric
    constraints (kavel, bouwvlak, maatvoeringaanduiding polygons). Drops
    narrative, noise, parking, sustainability, and other audit-only data.
    """
    numerical = [
        c.model_dump(mode="json")
        for c in framework.constraints.numerical
        if c.category in MASSING_CATEGORIES
    ]
    geometries = [
        {
            "id": g.id,
            "name": g.name,
            "feature_type": g.feature_type,
            "lod": g.lod,
            "elevation_m": g.elevation_m,
            "extrusion_height_m": g.extrusion_height_m,
            "associated_rules": g.associated_rules,
            "geojson": _geojson_feature(g),
            "compas": _compas_polygon(g),
        }
        for g in framework.constraints.geometric
    ]
    return {
        "header": _build_header(framework),
        "note": (
            "Slim envelope-driver subset of framework.json. "
            "Numerical constraints filtered to categories: "
            f"{sorted(MASSING_CATEGORIES)}. "
            "Full audit trail (narrative, noise, parking, sustainability) "
            "remains in framework.json."
        ),
        "numerical_constraints": numerical,
        "geometric_constraints": geometries,
        "programme": framework.programme.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# Summary markdown
# ---------------------------------------------------------------------------


def _format_value(value: Any, unit: str) -> str:
    if isinstance(value, list | tuple) and len(value) == 2:
        return f"{value[0]:g}–{value[1]:g} {unit}".replace(" ", " ", 1)
    if isinstance(value, float) and not math.isnan(value):
        return f"{value:g} {unit}"
    return f"{value} {unit}"


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load {}: {}", path, exc)
        return None


def _constraint_line(c: Any, indent: str = "- ") -> list[str]:
    flag = " ❗" if c.confidence.score < CONFIDENCE_REVIEW_THRESHOLD else ""
    line = (
        f"{indent}**{c.name}** (`{c.id}`): {_format_value(c.value, c.unit)}"
        f" — confidence {c.confidence.score:.2f}{flag}"
    )
    out = [line]
    if c.applies_to:
        out.append(f"  - applies to: {', '.join(c.applies_to)}")
    if c.condition:
        out.append(f"  - condition: {c.condition}")
    if c.provenance.document:
        out.append(
            f"  - source: {c.provenance.document} p.{c.provenance.page}"
        )
    return out


def _bbox_dims(coords: list[list[float]]) -> tuple[float, float] | None:
    if not coords:
        return None
    xs = [pt[0] for pt in coords]
    ys = [pt[1] for pt in coords]
    return max(xs) - min(xs), max(ys) - min(ys)


def render_summary(
    framework: ParametricFramework,
    *,
    extraction_raw: dict[str, Any] | None = None,
    reconciliation_report: list[dict[str, Any]] | None = None,
    parsed_geometry: dict[str, Any] | None = None,
    sanity_report: list[dict[str, Any]] | None = None,
    zone_programme_summary: list[dict[str, Any]] | None = None,
) -> str:
    """Render the Grasshopper-engineer handoff document.

    Pulls from framework plus optional sidecar artifacts so the summary can
    cite raw extraction counts, reconciliation actions, and the source
    kaveltekening's scale and plot dimensions. All sidecars are optional;
    missing data degrades the relevant sections, not the whole document.
    """
    fw = framework
    lines: list[str] = []

    # --------------------------------------------------------------
    # Header
    # --------------------------------------------------------------
    lines.append(f"# Project: {fw.metadata.project_name}")
    lines.append("")
    lines.append(f"**Status:** {_banner_for(fw.metadata.verification_status)}")

    plan_id = fw.metadata.location.plan_id
    if plan_id:
        cv_states = {
            (c.cross_validation.agreement if c.cross_validation else None)
            for c in fw.constraints.numerical
        }
        if "agreement" in cv_states or "disagreement" in cv_states:
            cv_note = "cross-validated against IMRO API"
        elif "unverifiable" in cv_states or "not_attempted" in cv_states:
            cv_note = "IMRO API cross-validation unavailable — see Data sources"
        else:
            cv_note = "no cross-validation attempted"
        lines.append(f"**Plan ID:** {plan_id} ({cv_note})")
    lines.append(
        f"**Generated:** {datetime.now(UTC).isoformat(timespec='seconds')}"
    )
    municipality = fw.metadata.location.municipality
    neighbourhood = fw.metadata.location.neighbourhood
    loc = municipality + (f", {neighbourhood}" if neighbourhood else "")
    lines.append(f"**Location:** {loc}")
    lines.append("")

    # --------------------------------------------------------------
    # How to consume
    # --------------------------------------------------------------
    geom_count = len(fw.constraints.geometric)
    massing_count = len(fw.massings)
    lines.append("## How to consume this output")
    lines.append("")
    lines.append(
        "1. `framework.json` — the structured design inputs. Top-level fields:\n"
        "   `metadata`, `objective`, `constraints` (numerical, geometric, narrative),\n"
        "   `variables`, `kpis`, `programme`, `geo_context`, `massings`.\n"
        "   The JSON wraps the validated `ParametricFramework` with a small\n"
        "   `header` block carrying the prototype banner, generation timestamp,\n"
        "   tool version, and source-document checksums."
    )
    lines.append(
        f"2. `geometry/*.compas` — {geom_count} polygons (plot, bouwvlakken,\n"
        "   constraint zones) as COMPAS-JSON Polygon blocks in the native\n"
        "   CRS (EPSG:28992 RD New). Load in Grasshopper via the\n"
        "   compas_ghpython component or via `compas_rhino.draw_mesh` /\n"
        "   `MeshArtist`. See https://compas.dev for documentation."
    )
    lines.append(
        f"3. `massings/*.compas.json` — {massing_count} example massings\n"
        "   (max envelope, compliant with setbacks). Illustrative only;\n"
        "   not design recommendations. `.obj` sidecars are exported for\n"
        "   quick preview."
    )
    lines.append(
        "4. `massing_inputs.json` — slim envelope-driver subset of\n"
        "   `framework.json` (heights, setbacks, footprints, BVO limits,\n"
        "   use-mix only) plus the geometric polygons. Use this when you\n"
        "   only need the envelope-binding rules and want to skip the audit\n"
        "   tail (noise, sustainability, etc.)."
    )
    lines.append(
        "5. `summary.md` (this file) — start here. Then read `framework.json`."
    )
    lines.append("")
    lines.append(
        "Every value in `framework.json` carries `provenance` (document, page,\n"
        "verbatim Dutch `quoted_text`) and `confidence` (score 0.0–1.0, with\n"
        f"{CONFIDENCE_REVIEW_THRESHOLD:.2f} as the review threshold). Click\n"
        "through to provenance for any ambiguous value."
    )
    lines.append("")

    # --------------------------------------------------------------
    # Programme intent (qualitative)
    # --------------------------------------------------------------
    lines.append("## Programme intent (from toelichting)")
    lines.append("")
    passages: list[str] = []
    if extraction_raw:
        raw_passages = extraction_raw.get("urban_intent_passages") or []
        passages = [p.strip() for p in raw_passages if p and p.strip()]
    if not passages and fw.objective.urban_intent:
        passages = [fw.objective.urban_intent]
    for passage in passages[:3]:
        lines.append(f"> {passage}")
        lines.append("")
    statement = (fw.objective.statement or "").strip()
    if statement and not statement.lower().startswith("inferred design goal"):
        lines.append(f"**Distilled objective:** {statement}")
        lines.append("")

    # --------------------------------------------------------------
    # Programme proposal (inferred)
    # --------------------------------------------------------------
    p = fw.programme
    lines.append("## Programme proposal (from inference, see programme.json)")
    lines.append("")
    gfa_range = (
        f" ({p.target_total_gfa_m2_range[0]:,.0f}–"
        f"{p.target_total_gfa_m2_range[1]:,.0f} m²)"
        if p.target_total_gfa_m2_range
        else ""
    )
    lines.append(
        f"- **Target total GFA:** {p.target_total_gfa_m2:,.0f} m²{gfa_range}"
    )

    use_split_fields = [
        ("residential", p.use_split.residential_m2),
        ("productive", p.use_split.productive_m2),
        ("office", p.use_split.office_m2),
        ("retail/horeca", p.use_split.retail_horeca_m2),
        ("cultural", p.use_split.cultural_m2),
        ("social", p.use_split.social_m2),
        ("other", p.use_split.other_m2),
    ]
    split_total = sum(v for _, v in use_split_fields) or 1.0
    nonzero = [(label, v) for label, v in use_split_fields if v > 0]
    parts = " | ".join(
        f"{label} {v:,.0f} m² ({v / split_total * 100:.0f}%)"
        for label, v in nonzero
    )
    lines.append(f"- **Use split:** {parts}")

    if p.target_dwelling_count is not None:
        dw_range = (
            f" ({p.total_dwelling_count_range[0]}–"
            f"{p.total_dwelling_count_range[1]})"
            if p.total_dwelling_count_range
            else ""
        )
        lines.append(
            f"- **Dwelling count target:** {p.target_dwelling_count}{dw_range}"
        )
    if p.parking_demand is not None:
        lines.append(f"- **Parking demand:** {p.parking_demand:g} spaces")

    if p.unit_mix:
        from collections import defaultdict

        by_tenure: dict[str, float] = defaultdict(float)
        for slice_ in p.unit_mix:
            by_tenure[slice_.tenure] += slice_.fraction_of_total_dwellings
        tenure_parts = " | ".join(
            f"{t} {f * 100:.0f}%" for t, f in sorted(by_tenure.items())
        )
        lines.append(f"- **Tenure split:** {tenure_parts}")
        lines.append("- **Unit mix:**")
        for slice_ in p.unit_mix:
            cnt = (
                f" ({slice_.target_count_range[0]}–"
                f"{slice_.target_count_range[1]} dwellings)"
                if slice_.target_count_range
                else ""
            )
            sz = (
                f", {slice_.target_size_m2_range[0]:g}–"
                f"{slice_.target_size_m2_range[1]:g} m²"
                if slice_.target_size_m2_range
                else ""
            )
            lines.append(
                f"  - {slice_.tenure} × {slice_.size_band}"
                f" ({slice_.typology or 'mixed typology'}): "
                f"{slice_.fraction_of_total_dwellings * 100:.0f}%"
                f"{cnt}{sz}"
            )

    lines.append("")
    lines.append(
        f"**Rationale:** {p.use_split.rationale[:600].rstrip()}"
        f"{'…' if len(p.use_split.rationale) > 600 else ''}"
    )
    lines.append("")
    lines.append(
        f"**Overall confidence:** {p.confidence.score:.2f} — "
        "see `programme.json` for the full reasoning trace."
    )
    lines.append("")

    # --------------------------------------------------------------
    # Numerical constraints (top binding values)
    # --------------------------------------------------------------
    lines.append("## Numerical constraints (top binding values)")
    lines.append("")
    by_cat: dict[str, list] = {}
    for c in fw.constraints.numerical:
        by_cat.setdefault(c.category, []).append(c)

    def _value_magnitude(c: Any) -> float:
        v = c.value
        if isinstance(v, list | tuple):
            return float(v[1])
        return float(v)

    # Display categories in a meaningful order, only what's present.
    display_order = [
        ("height", "Heights"),
        ("setback", "Setbacks"),
        ("footprint", "Footprint / coverage"),
        ("fsi_far", "FSI / FAR"),
        ("bvo_limit", "Programme BVO caps and floors"),
        ("parking", "Parking norms"),
        ("use_mix", "Use mix"),
        ("noise", "Noise"),
        ("sustainability", "Sustainability"),
        ("accessibility", "Accessibility"),
        ("other", "Other"),
    ]
    for cat_key, label in display_order:
        items = by_cat.get(cat_key)
        if not items:
            continue
        items.sort(
            key=lambda c: (-c.confidence.score, -_value_magnitude(c))
        )
        shown = items[:15]
        lines.append(f"### {label} ({len(items)} total, showing top {len(shown)})")
        lines.append("")
        for c in shown:
            lines.extend(_constraint_line(c))
        if len(items) > len(shown):
            lines.append(
                f"- … and {len(items) - len(shown)} more in `framework.json` →"
                f" `constraints.numerical` (category = `{cat_key}`)."
            )
        lines.append("")

    lines.append(
        f"See `framework.json` → `constraints.numerical` for all "
        f"{len(fw.constraints.numerical)} constraints with full provenance "
        "(document, page, verbatim Dutch text) and confidence scores."
    )
    lines.append("")

    # --------------------------------------------------------------
    # Geometric constraints
    # --------------------------------------------------------------
    lines.append("## Geometric constraints")
    lines.append("")
    by_feature: dict[str, int] = {}
    for g in fw.constraints.geometric:
        by_feature[g.feature_type] = by_feature.get(g.feature_type, 0) + 1
    lines.append("Polygon counts by feature type:")
    for feature_type, n in sorted(by_feature.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {feature_type}: {n}")
    lines.append("")

    if parsed_geometry:
        scale_d = parsed_geometry.get("scale_denominator")
        src_pdf = parsed_geometry.get("source_pdf")
        src_pdf_name = Path(src_pdf).name if src_pdf else None
        plot_poly = parsed_geometry.get("plot_polygon") or []
        plot_dims = (
            _bbox_dims(plot_poly) if isinstance(plot_poly, list) else None
        )
        lines.append("Source drawing:")
        if src_pdf_name:
            lines.append(f"- File: {src_pdf_name}")
        if scale_d:
            lines.append(f"- Scale: 1:{int(scale_d)}")
        if plot_dims:
            lines.append(
                f"- Plot bounding box: {plot_dims[0]:.0f} m × "
                f"{plot_dims[1]:.0f} m (RD New)"
            )
        lines.append("")
    lines.append(
        "Reconciled with regels for bouwvlak heights — see the "
        "Reconciliation summary below and `reconciliation_report.json`."
    )
    lines.append("")

    # --------------------------------------------------------------
    # Zone programme summary (per-bouwvlak rule mapping)
    # --------------------------------------------------------------
    if zone_programme_summary:
        lines.append("## Zone programme summary")
        lines.append("")
        lines.append(
            "| Zone | Height | Source | Codes | Matched rules | Key constraints |"
        )
        lines.append(
            "|------|--------|--------|-------|---------------|-----------------|"
        )
        for z in zone_programme_summary:
            h = z.get("height_m")
            h_txt = f"{h:g}m" if isinstance(h, int | float) else "—"
            source = z.get("height_source") or "—"
            codes = ", ".join(z.get("zone_codes") or []) or "—"
            rule_count = z.get("rule_count", 0)
            height_rules = (z.get("rules_by_category") or {}).get("height", [])
            keys = [
                f"{r.get('name', r.get('id', '?'))}="
                f"{r.get('value')}{r.get('unit') or ''}"
                for r in height_rules[:2]
            ]
            if len(height_rules) > 2:
                keys.append("…")
            key_txt = ", ".join(keys) or "—"
            zone_name = z.get("zone_name") or z.get("zone_id") or "?"
            lines.append(
                f"| {zone_name} | {h_txt} | {source} | {codes} | "
                f"{rule_count} | {key_txt} |"
            )
        lines.append("")
        lines.append(
            "Full zone-constraint mapping in `zone_programme_summary.json`. "
            "Zones with 0 matched rules may indicate that `applies_to` codes "
            "in the extracted constraints do not match the zone labels from "
            "the kaveltekening. Run `scripts/inspect_zones.py` to diagnose."
        )
        lines.append("")

    # --------------------------------------------------------------
    # Narrative constraints
    # --------------------------------------------------------------
    lines.append("## Narrative constraints (selected)")
    lines.append("")
    narratives = sorted(
        fw.constraints.narrative,
        key=lambda n: -n.confidence.score,
    )[:10]
    for n in narratives:
        lines.append(
            f"- **{n.statement}** (`{n.id}`, {n.category}) — "
            f"confidence {n.confidence.score:.2f}"
        )
        if n.provenance.quoted_text:
            quote = n.provenance.quoted_text.strip()
            lines.append(
                f'  > "{quote}" — {n.provenance.document or "unknown"}'
                f" p.{n.provenance.page or '?'}"
            )
    if len(fw.constraints.narrative) > 10:
        lines.append(
            f"- … and {len(fw.constraints.narrative) - 10} more in "
            "`framework.json` → `constraints.narrative`."
        )
    lines.append("")

    # --------------------------------------------------------------
    # Flagged ambiguities
    # --------------------------------------------------------------
    lines.append("## Flagged ambiguities")
    lines.append("")
    low_conf_num = [
        c
        for c in fw.constraints.numerical
        if c.confidence.score < 0.80
    ]
    low_conf_narr = [
        c
        for c in fw.constraints.narrative
        if c.confidence.score < 0.80
    ]
    disagreements = [
        c
        for c in fw.constraints.numerical
        if c.cross_validation and c.cross_validation.agreement == "disagreement"
    ]
    unverifiable = [
        c
        for c in fw.constraints.numerical
        if c.cross_validation and c.cross_validation.agreement == "unverifiable"
    ]
    extraction_errors: list[Any] = []
    if extraction_raw:
        extraction_errors = list(
            extraction_raw.get("pages_with_extraction_errors") or []
        )

    reconciliation_actions: dict[str, int] = {}
    if reconciliation_report:
        for entry in reconciliation_report:
            reconciliation_actions[entry["action"]] = (
                reconciliation_actions.get(entry["action"], 0) + 1
            )

    if disagreements:
        lines.append(
            f"- **IMRO API disagreements ({len(disagreements)}):** "
            "extracted values differ from the authoritative source. "
            "Listed under the relevant numerical-constraint entries."
        )
        for c in disagreements[:5]:
            auth = c.cross_validation.authoritative_value
            lines.append(
                f"  - `{c.id}`: extracted {_format_value(c.value, c.unit)}, "
                f"authoritative {auth}"
            )

    if reconciliation_actions.get("corrected"):
        lines.append(
            f"- **Reconciliation overrides "
            f"({reconciliation_actions['corrected']}):** regels clauses "
            "corrected the verbeelding's spatial-proximity reading. See "
            "`reconciliation_report.json`."
        )

    if low_conf_num:
        lines.append(
            f"- **{len(low_conf_num)} numerical constraints with "
            "confidence < 0.80:** review before relying on them. Listed "
            "with the ❗ marker under the relevant category above."
        )
    if low_conf_narr:
        lines.append(
            f"- **{len(low_conf_narr)} narrative constraints with "
            "confidence < 0.80.**"
        )
    if unverifiable:
        lines.append(
            f"- **{len(unverifiable)} constraints unverifiable against "
            "IMRO API:** API was contacted but field could not be matched."
        )
    if extraction_errors:
        lines.append(
            f"- **{len(extraction_errors)} pages had extraction errors** "
            "(see `extraction_raw.json` → `pages_with_extraction_errors`)."
        )
    if p.confidence.score < 0.75:
        lines.append(
            f"- **Programme inference confidence {p.confidence.score:.2f} "
            "below 0.75:** treat the programme proposal as a sketch."
        )

    if not any(
        [
            disagreements,
            reconciliation_actions.get("corrected"),
            low_conf_num,
            low_conf_narr,
            unverifiable,
            extraction_errors,
            p.confidence.score < 0.75,
        ]
    ):
        lines.append("- None flagged at the document level.")
    lines.append("")

    # --------------------------------------------------------------
    # Data sources used
    # --------------------------------------------------------------
    lines.append("## Data sources used")
    lines.append("")

    num_count = len(fw.constraints.numerical)
    narr_count = len(fw.constraints.narrative)
    doc_names = [d.filename for d in fw.metadata.source_documents]
    page_total = sum(d.page_count for d in fw.metadata.source_documents)
    lines.append(
        f"- ✓ Document extraction: {num_count} numerical, {narr_count} "
        f"narrative constraints across {len(doc_names)} PDFs "
        f"({page_total} pages total)."
    )

    if parsed_geometry and parsed_geometry.get("status") == "ok":
        n_bouw = len(parsed_geometry.get("bouwvlakken") or [])
        n_zones = len(parsed_geometry.get("constraint_zones") or [])
        scale_d = parsed_geometry.get("scale_denominator")
        scale_txt = f", scale 1:{int(scale_d)}" if scale_d else ""
        lines.append(
            f"- ✓ Vector geometry: {n_bouw + n_zones + 1} polygons from "
            f"kaveltekening{scale_txt} (1 plot, {n_bouw} bouwvlakken, "
            f"{n_zones} constraint zones)."
        )
    elif parsed_geometry:
        lines.append(
            f"- ✗ Vector geometry: parsing failed "
            f"({parsed_geometry.get('reason', 'unknown')})."
        )

    # Cross-validation summary
    cv_agree = sum(
        1
        for c in fw.constraints.numerical
        if c.cross_validation and c.cross_validation.agreement == "agreement"
    )
    cv_disagree = len(disagreements)
    cv_unverif = len(unverifiable)
    cv_not_attempted = sum(
        1
        for c in fw.constraints.numerical
        if c.cross_validation
        and c.cross_validation.agreement == "not_attempted"
    )
    cv_marker = "✓" if cv_agree or cv_disagree else "✗"
    cv_summary = (
        f"{cv_agree} agreed, {cv_disagree} disagreed, "
        f"{cv_unverif} unverifiable"
    )
    if cv_not_attempted:
        cv_summary += f", {cv_not_attempted} not attempted (API unavailable)"
    lines.append(f"- {cv_marker} IMRO API cross-validation: {cv_summary}.")

    geo = fw.geo_context
    if geo:
        if geo.nearby_buildings:
            nb = geo.nearby_buildings
            lines.append(
                f"- ✓ PDOK BAG: {nb.count} buildings within {nb.radius_m:g} m"
                + (
                    f" (year built {nb.typical_year_built[0]}–{nb.typical_year_built[1]})"
                    if nb.typical_year_built
                    else ""
                )
                + "."
            )
            if not nb.has_3d_bag_data:
                lines.append(
                    "- ✗ 3D BAG: not available — 2D context only for massing visualisation."
                )
        if geo.demographics:
            d = geo.demographics
            lines.append(
                f"- ✓ CBS demographics (buurt {d.buurt_code}): "
                f"pop {d.population}, "
                f"{d.household_count} households, "
                f"avg household size {d.average_household_size}, "
                f"median age {d.median_age}."
            )
        if geo.transit or geo.nearby_amenities:
            transit_bits = []
            if geo.transit:
                t = geo.transit
                if t.nearest_bus_m is not None:
                    transit_bits.append(f"bus {t.nearest_bus_m:.0f} m")
                if t.nearest_tram_m is not None:
                    transit_bits.append(f"tram {t.nearest_tram_m:.0f} m")
                if t.nearest_metro_m is not None:
                    transit_bits.append(f"metro {t.nearest_metro_m:.0f} m")
                if t.nearest_train_m is not None:
                    transit_bits.append(f"train {t.nearest_train_m:.0f} m")
            transit_txt = ", ".join(transit_bits) if transit_bits else ""
            amenities_txt = (
                f", {sum(geo.nearby_amenities.values())} amenities across "
                f"{len(geo.nearby_amenities)} categories"
                if geo.nearby_amenities
                else ""
            )
            lines.append(f"- ✓ OSM Overpass: {transit_txt}{amenities_txt}.")
        for failed in geo.data_sources_failed:
            if failed != "pdok_3d_bag":
                lines.append(f"- ✗ {failed}: failed (see geo_context.json).")
    lines.append("")

    # --------------------------------------------------------------
    # Reconciliation summary
    # --------------------------------------------------------------
    if reconciliation_report:
        lines.append("## Reconciliation summary")
        lines.append("")
        counts = reconciliation_actions
        action_descriptions = [
            (
                "matched",
                ("polygon height confirmed", "polygon heights confirmed"),
                "regels matched verbeelding",
            ),
            (
                "corrected",
                ("polygon height corrected by regels", "polygon heights corrected by regels"),
                "verbeelding's spatial-proximity reading overridden",
            ),
            (
                "inferred",
                ("polygon height inferred from regels", "polygon heights inferred from regels"),
                "verbeelding had no label",
            ),
            (
                "unmatched",
                ("regels clause with no matching polygon", "regels clauses with no matching polygon"),
                "non-bouwvlak labels or permit-gated deviations",
            ),
            (
                "skipped_non_base",
                ("non-base height constraint skipped", "non-base height constraints skipped"),
                "deviations, fences, lights",
            ),
        ]
        for key, (sing, plur), explainer in action_descriptions:
            n = counts.get(key, 0)
            if n:
                label = sing if n == 1 else plur
                lines.append(f"- {n} {label} ({explainer}).")
        lines.append("")
        lines.append("See `reconciliation_report.json` for per-polygon details.")
        lines.append("")

    # --------------------------------------------------------------
    # Sanity check (Scenario 1 Layer 5)
    # --------------------------------------------------------------
    lines.append("## Sanity check")
    lines.append("")
    if not sanity_report:
        lines.append(
            "No physical-sense violations detected. Every numerical constraint "
            "sits within universal bounds (heights 3–200 m, FSI 0–8, parking "
            "0–4/dwelling, GFA 100–1,000,000 m²) and the programme is internally "
            "consistent."
        )
        lines.append("")
    else:
        errors = [f for f in sanity_report if f.get("severity") == "error"]
        warnings = [f for f in sanity_report if f.get("severity") == "warning"]
        lines.append(
            f"**{len(sanity_report)} finding(s):** "
            f"{len(errors)} error(s), {len(warnings)} warning(s)."
        )
        lines.append("")
        for f in sanity_report:
            name = f.get("constraint_name") or f.get("category")
            value = f.get("value")
            unit = f.get("unit") or ""
            sev = f.get("severity")
            msg = f.get("message", "")
            lines.append(f"- **[{sev}]** `{name}` = {value} {unit} — {msg}")
        lines.append("")
        lines.append("See `sanity_report.json` for the full list.")
        lines.append("")

    # --------------------------------------------------------------
    # For the Grasshopper engineer
    # --------------------------------------------------------------
    lines.append("## For the Grasshopper engineer")
    lines.append("")
    lines.append(
        "Start with `framework.json` → `objective` and `programme` for "
        "context. Then `constraints.geometric` for the polygons (or load "
        "the `.compas` files directly). Then `constraints.numerical` for "
        "the binding rules. `massings/` contains two example variants "
        "illustrating how the inputs translate to geometry."
    )
    lines.append("")
    lines.append("**What to trust most:**")
    lines.append("")
    lines.append(
        "- `source_type: \"document\"` with `confidence ≥ 0.85` — verbatim "
        "from regels or toelichting and above the review threshold."
    )
    lines.append(
        "- `cross_validation.agreement == \"agreement\"` — additionally "
        "confirmed by the IMRO authoritative API."
    )
    lines.append(
        "- Bouwvlak heights with `height_reconciled_from == \"regels\"` — "
        "the regels clause is the canonical source; verbeelding-only values "
        "may reflect drawing-association errors."
    )
    lines.append("")
    lines.append("**What to treat with care:**")
    lines.append("")
    lines.append(
        "- `source_type: \"inferred\"` — derived by LLM reasoning. The "
        "entire `programme` block is inferred; treat numbers as the "
        "model's best estimate, not a brief."
    )
    lines.append(
        "- Any constraint flagged ❗ above (confidence below "
        f"{CONFIDENCE_REVIEW_THRESHOLD:.2f})."
    )
    lines.append(
        "- Bouwvlak heights with `height_reconciled_from == "
        "\"verbeelding_uncorrected\"` — drawing value with no regels "
        "clause to confirm."
    )
    lines.append("")
    lines.append(
        f"This output is **{PROTOTYPE_BANNER}**. A project manager will "
        "review before final use in the Run system."
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level handoff
# ---------------------------------------------------------------------------


def write_grasshopper_handoff(
    framework: ParametricFramework, output_dir: Path
) -> Path:
    """Write framework.json, geometry/*.compas, summary.md under output_dir.

    Returns the path to framework.json.
    """
    errors = validate_cross_references(framework)
    if errors:
        for err in errors:
            logger.warning("Cross-reference error: {}", err)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    geom_dir = output_dir / "geometry"
    geom_dir.mkdir(exist_ok=True)

    zone_programme_summary = _load_json(output_dir / "zone_programme_summary.json")
    zone_programme_summary = (
        zone_programme_summary if isinstance(zone_programme_summary, list) else None
    )

    payload = serialise_framework(
        framework, zone_programme_summary=zone_programme_summary
    )

    for entry in payload["geometries"]:
        path = geom_dir / f"{entry['id']}.compas"
        path.write_text(json.dumps(entry["compas"], indent=2))
        logger.debug("Wrote {}", path)

    framework_path = output_dir / "framework.json"
    framework_path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote {}", framework_path)

    massing_inputs = build_massing_inputs(framework)
    massing_path = output_dir / "massing_inputs.json"
    massing_path.write_text(json.dumps(massing_inputs, indent=2, default=str))
    logger.info(
        "Wrote {} ({} numerical, {} geometric)",
        massing_path,
        len(massing_inputs["numerical_constraints"]),
        len(massing_inputs["geometric_constraints"]),
    )

    extraction_raw = _load_json(output_dir / "extraction_raw.json")
    reconciliation_report = _load_json(output_dir / "reconciliation_report.json")
    parsed_geometry = _load_json(output_dir / "geometry.json")
    sanity_report = _load_json(output_dir / "sanity_report.json")

    summary_path = output_dir / "summary.md"
    summary_path.write_text(
        render_summary(
            framework,
            extraction_raw=extraction_raw if isinstance(extraction_raw, dict) else None,
            reconciliation_report=reconciliation_report
            if isinstance(reconciliation_report, list)
            else None,
            parsed_geometry=parsed_geometry if isinstance(parsed_geometry, dict) else None,
            sanity_report=sanity_report if isinstance(sanity_report, list) else None,
            zone_programme_summary=zone_programme_summary,
        )
    )
    logger.info("Wrote {}", summary_path)

    return framework_path
