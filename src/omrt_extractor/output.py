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


def serialise_framework(framework: ParametricFramework) -> dict[str, Any]:
    """Produce the JSON-ready dict for framework.json."""
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

    return {
        "header": _build_header(framework),
        "geometries": geometries_out,
        "framework": body,
    }


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
        return f"{value[0]}–{value[1]} {unit}"
    if isinstance(value, float) and not math.isnan(value):
        return f"{value:g} {unit}"
    return f"{value} {unit}"


def render_summary(framework: ParametricFramework) -> str:
    fw = framework
    lines: list[str] = []
    lines.append(f"# {fw.metadata.project_name}")
    lines.append("")
    lines.append(f"> **{_banner_for(fw.metadata.verification_status)}**")
    lines.append("")
    lines.append(f"- Verification status: `{fw.metadata.verification_status.value}`")
    lines.append(f"- Tool version: `{fw.metadata.tool_version}`")
    lines.append(f"- Plan ID: `{fw.metadata.location.plan_id or 'none'}`")
    lines.append(
        f"- Municipality: {fw.metadata.location.municipality}, "
        f"neighbourhood: {fw.metadata.location.neighbourhood or 'unspecified'}"
    )
    lines.append("")

    disagreements = [
        c
        for c in fw.constraints.numerical
        if c.cross_validation and c.cross_validation.agreement == "disagreement"
    ]
    if disagreements:
        lines.append("## IMRO API disagreements (review first)")
        lines.append("")
        for c in disagreements:
            auth = c.cross_validation.authoritative_value if c.cross_validation else None
            lines.append(
                f"- **{c.name}** (`{c.id}`): extracted "
                f"{_format_value(c.value, c.unit)}, authoritative {auth}"
            )
            if c.provenance.quoted_text:
                lines.append(f"  > \"{c.provenance.quoted_text}\" — "
                             f"{c.provenance.document} p.{c.provenance.page}")
        lines.append("")

    lines.append("## Objective")
    lines.append("")
    lines.append(fw.objective.statement)
    lines.append("")

    lines.append("## Numerical constraints")
    lines.append("")
    for c in fw.constraints.numerical:
        flag = "❗" if c.confidence.score < CONFIDENCE_REVIEW_THRESHOLD else ""
        lines.append(
            f"- {flag} **{c.name}** (`{c.id}`): {_format_value(c.value, c.unit)} "
            f"— confidence {c.confidence.score:.2f}"
        )
        if c.provenance.document:
            lines.append(
                f"  - source: {c.provenance.document} p.{c.provenance.page}"
            )
        if c.condition:
            lines.append(f"  - condition: {c.condition}")
    lines.append("")

    lines.append("## Geometric constraints")
    lines.append("")
    for g in fw.constraints.geometric:
        lines.append(
            f"- **{g.name}** (`{g.id}`, {g.feature_type}, LOD {g.lod}, CRS {g.crs.value})"
        )
    lines.append("")

    lines.append("## Programme proposal")
    lines.append("")
    p = fw.programme
    lines.append(f"- Target GFA: {p.target_total_gfa_m2:g} m²")
    if p.target_dwelling_count is not None:
        lines.append(f"- Target dwellings: {p.target_dwelling_count}")
    if p.parking_demand is not None:
        lines.append(f"- Parking demand: {p.parking_demand:g}")
    lines.append("")
    lines.append("### Reasoning trace")
    lines.append("")
    for step in p.reasoning_trace:
        if isinstance(step, str):
            lines.append(f"- {step}")
        else:
            evidence = f" — evidence: {step.evidence}" if step.evidence else ""
            lines.append(f"- Step {step.step}: {step.decision}{evidence}")
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

    payload = serialise_framework(framework)

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

    summary_path = output_dir / "summary.md"
    summary_path.write_text(render_summary(framework))
    logger.info("Wrote {}", summary_path)

    return framework_path
