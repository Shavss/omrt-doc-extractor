"""Example massing generation: two illustrative variants per project.

Purpose: demonstrate that the framework's numerical and geometric inputs
translate to geometry. NOT optimised design; that is the OMRT Run system's
job and lives downstream of this prototype.

Primary function:
    generate_example_massings(framework) -> list[Massing]

Two variants always produced:
    Variant A "Maximum envelope"
        Extrude every bouwvlak to its max allowed height with no setbacks.
    Variant B "Compliant with setbacks"
        Apply setback rules above the threshold height (read from the
        framework's constraints, never hardcoded).

Each Massing object includes:
    rationale: 1-2 sentences citing the rule that drove each form decision
    provenance: which inputs drove which moves
    moves: list of MassingMove with driven_by constraint IDs (validated)
    geometry_file: path to the COMPAS Mesh JSON
    mesh_polygons: inline triangulated mesh for viewer convenience

Shapely for 2D polygon operations, COMPAS Mesh for 3D output. Render in
viewer/streamlit_app.py with plotly Mesh3d.

If any input the massing depends on has confidence below threshold,
``uses_unverified_inputs`` is set on the Massing and the viewer banners
"preview based on unverified inputs" over the visualisation.

Stage 6b of the build plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from compas import json_dumps
from compas.datastructures import Mesh
from loguru import logger
from shapely.geometry import Polygon as ShapelyPolygon

from omrt_extractor.config import settings
from omrt_extractor.constraint_filters import is_base_height_constraint
from omrt_extractor.schemas import (
    GeometricConstraint,
    Massing,
    MassingMove,
    NumericalConstraint,
    ParametricFramework,
    Provenance,
    SourceType,
)

# ---------------------------------------------------------------------
# Constraint discovery
# Read structural inputs from the framework. Never hardcode numbers.
# ---------------------------------------------------------------------


def _scalar(value: float | tuple[float, float]) -> float | None:
    """Single float from a NumericalConstraint.value (scalar or (min, max))."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        # For a range upper bound is the most useful for envelopes.
        return float(value[1])
    return None


def _bouwvlakken(framework: ParametricFramework) -> list[GeometricConstraint]:
    """Bouwvlakken if available, otherwise the plot boundary as a fallback."""
    bvs = [g for g in framework.constraints.geometric if g.feature_type == "bouwvlak"]
    if bvs:
        return bvs
    return [g for g in framework.constraints.geometric if g.feature_type == "plot_boundary"]


# Universal physical-sense floor for what counts as a building-mass
# threshold or a building max-height. Below this, values almost always
# refer to door clearances, plinth dimensions, fences, or other
# non-mass-defining items. Not municipality-specific: 5 m is the
# globally-defensible lower bound on a top-of-mass.
_MIN_BUILDING_MASS_M = 5.0

# Conservative urban-residential mid-rise reference used only when both a
# label-matched regels height and a verbeelding height are absent. Generic;
# not municipality-specific.
DEFAULT_BASE_HEIGHT_M = 12.0


HeightSource = Literal["regels", "verbeelding", "default_fallback", "unresolved"]


def _label_tokens(bouwvlak: GeometricConstraint) -> set[str]:
    """Normalised labels a polygon carries (bouw/function aanduidingen, codes).

    The geometry-merge step pushes these into the bouwvlak's ``name`` as
    ``Bouwvlak <code>, <code>, ...`` and into ``notes`` as the raw_labels.
    Use ``name`` as the canonical source since it is structured.
    """
    prefix = "bouwvlak"
    raw = bouwvlak.name.lower()
    if raw.startswith(prefix):
        raw = raw[len(prefix) :].strip()
    tokens: set[str] = set()
    for piece in raw.split(","):
        t = piece.strip().strip("[]()").replace("-", "_").replace(" ", "_")
        if t and t != "(no_label)":
            tokens.add(t)
    return tokens


def _normalise(s: str) -> str:
    return s.strip().lower().strip("[]()").replace("-", "_").replace(" ", "_")


def _resolve_height(
    framework: ParametricFramework, bouwvlak: GeometricConstraint
) -> tuple[float | None, NumericalConstraint | None, HeightSource]:
    """Pick the height to extrude this bouwvlak to.

    Tier priority:
      1. Label-matched regels constraint. A base-height NumericalConstraint
         whose ``applies_to`` overlaps the polygon's labels OR is listed in
         ``associated_rules``. Highest-confidence value wins.
      2. Verbeelding height (``extrusion_height_m`` from the geometry parser).
      3. ``DEFAULT_BASE_HEIGHT_M`` fallback with a warning.

    Returns (height, rule_or_None, source). Source is one of:
      'regels' | 'verbeelding' | 'default_fallback' | 'unresolved'.

    Constraints with empty ``applies_to`` are never used here: they are not
    polygon-specific defaults, even if their value happens to be plausible.
    """
    labels = _label_tokens(bouwvlak)
    rule_ids = set(bouwvlak.associated_rules)

    candidates: list[NumericalConstraint] = []
    for c in framework.constraints.numerical:
        if not is_base_height_constraint(c):
            continue
        v = _scalar(c.value)
        if v is None or v < _MIN_BUILDING_MASS_M:
            continue
        applies_norm = {_normalise(a) for a in c.applies_to}
        if c.id in rule_ids or (applies_norm and applies_norm & labels):
            candidates.append(c)

    if candidates:
        winner = max(
            candidates,
            key=lambda c: (c.confidence.score, c.condition is None, -float(_scalar(c.value) or 0)),
        )
        return float(_scalar(winner.value) or 0), winner, "regels"

    if (
        bouwvlak.extrusion_height_m is not None
        and bouwvlak.extrusion_height_m >= _MIN_BUILDING_MASS_M
    ):
        return float(bouwvlak.extrusion_height_m), None, "verbeelding"

    logger.warning(
        "Bouwvlak {} ({}): no regels match and no verbeelding height; "
        "falling back to DEFAULT_BASE_HEIGHT_M={}",
        bouwvlak.id,
        bouwvlak.name,
        DEFAULT_BASE_HEIGHT_M,
    )
    return DEFAULT_BASE_HEIGHT_M, None, "default_fallback"


def _threshold_height(
    framework: ParametricFramework,
) -> tuple[float | None, NumericalConstraint | None]:
    """A base height above which a setback applies.

    Read structurally from the constraints: any height constraint marked
    as a lower bound (is_maximum=False) is treated as the threshold.
    Smallest such value wins (most binding).
    """
    candidates: list[tuple[float, NumericalConstraint]] = []
    for c in framework.constraints.numerical:
        if c.category != "height" or c.is_maximum is not False:
            continue
        v = _scalar(c.value)
        if v is None or v < _MIN_BUILDING_MASS_M:
            continue
        candidates.append((v, c))
    if not candidates:
        return None, None
    # Smallest plausible base height is the most binding step-back threshold:
    # in Dutch zoning this typically corresponds to the plinth or base
    # volume above which the building must step back. Picking the smallest
    # value is also failure-honest: it produces a visible step-back rather
    # than silently collapsing variant B onto variant A.
    v, c = min(candidates, key=lambda t: t[0])
    return v, c


def _setback_distance(
    framework: ParametricFramework,
) -> tuple[float | None, NumericalConstraint | None]:
    """Minimum setback distance from a setback NumericalConstraint."""
    candidates: list[tuple[float, NumericalConstraint]] = []
    for c in framework.constraints.numerical:
        if c.category != "setback" or c.is_maximum is not False:
            continue
        v = _scalar(c.value)
        if v is None or v <= 0:
            continue
        candidates.append((v, c))
    if not candidates:
        return None, None
    v, c = min(candidates, key=lambda t: t[0])
    return v, c


# ---------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------


def _coords_2d(geom: GeometricConstraint) -> list[tuple[float, float]]:
    """Return the planar ring as 2D tuples, dropping the closing point."""
    ring = [(p[0], p[1]) for p in geom.coordinates]
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def _extrude_to_mesh(
    ring: list[tuple[float, float]], z0: float, z1: float
) -> tuple[list[list[float]], list[list[int]]]:
    """Triangulate an extruded prism from a closed planar polygon.

    Returns (vertices, faces). Faces are triangles for plotly Mesh3d.
    Bottom and top use fan triangulation from vertex 0; sides emit two
    triangles per edge. Assumes the ring is simple and approximately
    convex, which holds for bouwvlakken in the prototype's scope.
    """
    n = len(ring)
    vertices: list[list[float]] = []
    for x, y in ring:
        vertices.append([x, y, z0])
    for x, y in ring:
        vertices.append([x, y, z1])

    faces: list[list[int]] = []
    # Bottom (reversed for outward normals downward)
    for i in range(1, n - 1):
        faces.append([0, i + 1, i])
    # Top
    for i in range(1, n - 1):
        faces.append([n, n + i, n + i + 1])
    # Sides
    for i in range(n):
        j = (i + 1) % n
        a, b, c, d = i, j, n + j, n + i
        faces.append([a, b, c])
        faces.append([a, c, d])
    return vertices, faces


def _faces_to_triangles(
    vertices: list[list[float]], faces: list[list[int]]
) -> list[list[list[float]]]:
    """Inline triangle representation for the viewer (no index buffer)."""
    return [[vertices[i] for i in f] for f in faces]


def _faces_to_mesh(vertices: list[list[float]], faces: list[list[int]]) -> Mesh:
    """Build a COMPAS Mesh from vertex/face arrays."""
    mesh = Mesh()
    keys = [mesh.add_vertex(x=v[0], y=v[1], z=v[2]) for v in vertices]
    for f in faces:
        mesh.add_face([keys[i] for i in f])
    return mesh


def _merge_geometry(
    parts: list[tuple[list[list[float]], list[list[int]]]],
) -> tuple[list[list[float]], list[list[int]]]:
    """Concatenate independent triangulated parts into one vertex/face arena."""
    all_v: list[list[float]] = []
    all_f: list[list[int]] = []
    for verts, faces in parts:
        offset = len(all_v)
        all_v.extend(verts)
        all_f.extend([[i + offset for i in f] for f in faces])
    return all_v, all_f


def _write_obj(path: Path, vertices: list[list[float]], faces: list[list[int]]) -> None:
    """Write a minimal OBJ file. 1-indexed vertices, triangle faces only."""
    lines = [f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in vertices]
    lines.extend(f"f {f[0] + 1} {f[1] + 1} {f[2] + 1}" for f in faces)
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------


def generate_example_massings(
    framework: ParametricFramework,
    output_dir: Path | None = None,
) -> list[Massing]:
    """Build two example Massing objects from the validated framework.

    Variant A "Maximum envelope": extrude each bouwvlak to its max
    allowed height, no setbacks. Illustrates the legal envelope.

    Variant B "Compliant with setbacks": same extrusion, but where the
    max height exceeds a structural threshold height (read from the
    constraints), apply the required setback distance above that
    threshold to produce a stepped upper volume.

    Inputs (bouwvlak polygons, max heights, threshold, setback distance)
    are pulled from the framework. Nothing about Draka or any specific
    municipality is hardcoded.

    If output_dir is provided, COMPAS JSON and OBJ exports are written
    under ``<output_dir>/massings/`` for the GH engineer; otherwise the
    paths on the returned Massing objects are relative placeholders and
    nothing is written to disk (useful in tests).
    """
    bouwvlakken = _bouwvlakken(framework)
    if not bouwvlakken:
        logger.warning("No bouwvlak or plot_boundary geometry; massings will be empty.")
        # Still return two placeholder massings so the schema-level contract
        # ("two variants always produced") holds. The viewer will banner the
        # absence as unverified.
        return [
            Massing(
                id="variant_a_maximum_envelope",
                name="Maximum envelope",
                rationale=(
                    "No bouwvlak geometry was extracted, so the maximum envelope "
                    "could not be derived. Run the geometry stage first."
                ),
                moves=[],
                geometry_file="massings/variant_a_maximum_envelope.compas.json",
                uses_unverified_inputs=True,
                mesh_polygons=[],
                provenance=Provenance(source_type=SourceType.INFERRED, inferred_from=[]),
            ),
            Massing(
                id="variant_b_compliant_with_setbacks",
                name="Compliant with setbacks",
                rationale=(
                    "No bouwvlak geometry was extracted, so the compliant variant "
                    "could not be derived. Run the geometry stage first."
                ),
                moves=[],
                geometry_file="massings/variant_b_compliant_with_setbacks.compas.json",
                uses_unverified_inputs=True,
                mesh_polygons=[],
                provenance=Provenance(source_type=SourceType.INFERRED, inferred_from=[]),
            ),
        ]

    threshold_h, threshold_rule = _threshold_height(framework)
    setback_d, setback_rule = _setback_distance(framework)
    base_z = 0.0
    threshold_below = settings.confidence_threshold

    # ----- Variant A: maximum envelope -----
    a_parts: list[tuple[list[list[float]], list[list[int]]]] = []
    a_moves: list[MassingMove] = []
    a_inferred_from: list[str] = []
    a_unverified = False

    excluded_unresolved: list[str] = []
    height_resolutions: list[
        tuple[GeometricConstraint, float, NumericalConstraint | None, HeightSource]
    ] = []

    for bv in bouwvlakken:
        max_h, max_rule, source = _resolve_height(framework, bv)
        if source == "unresolved" or max_h is None or max_h <= 0:
            excluded_unresolved.append(bv.id)
            logger.warning("Bouwvlak {} excluded from massing: unresolvable height.", bv.id)
            continue
        ring = _coords_2d(bv)
        if len(ring) < 3:
            continue
        height_resolutions.append((bv, max_h, max_rule, source))
        a_parts.append(_extrude_to_mesh(ring, base_z, base_z + max_h))
        via = f"regels ({max_rule.id})" if source == "regels" and max_rule else source
        logger.info(
            "Variant A: bouwvlak '{}' ({}) → {:.1f} m via {}",
            bv.id,
            bv.name,
            max_h,
            via,
        )
        a_moves.append(
            MassingMove(
                description=(
                    f"Extruded bouwvlak '{bv.name}' to {max_h:.1f} m, no setback. "
                    f"Height source: {via}."
                ),
                driven_by=[max_rule.id] if max_rule else [],
            )
        )
        if max_rule:
            a_inferred_from.append(max_rule.id)
            if max_rule.confidence.score < threshold_below:
                a_unverified = True
        if source in ("verbeelding", "default_fallback"):
            a_unverified = True
        if bv.confidence.score < threshold_below:
            a_unverified = True

    if excluded_unresolved:
        logger.warning(
            "{} bouwvlakken excluded from massing visualisation due to unresolvable height: {}",
            len(excluded_unresolved),
            excluded_unresolved,
        )

    a_vertices, a_faces = _merge_geometry(a_parts)
    a_triangles = _faces_to_triangles(a_vertices, a_faces)

    variant_a = Massing(
        id="variant_a_maximum_envelope",
        name="Maximum envelope",
        rationale=(
            "Each bouwvlak is extruded to its maximum allowed height as stated "
            "in the height constraints. No setback is applied. This illustrates "
            "the theoretical legal envelope before any stepping rule kicks in."
        ),
        moves=a_moves,
        geometry_file="massings/variant_a_maximum_envelope.compas.json",
        obj_file="massings/variant_a_maximum_envelope.obj",
        uses_unverified_inputs=a_unverified,
        mesh_polygons=a_triangles,
        provenance=Provenance(
            source_type=SourceType.INFERRED, inferred_from=sorted(set(a_inferred_from))
        ),
    )

    # ----- Variant B: compliant with setbacks -----
    b_parts: list[tuple[list[list[float]], list[list[int]]]] = []
    b_moves: list[MassingMove] = []
    b_inferred_from: list[str] = []
    b_unverified = False

    for bv in bouwvlakken:
        max_h, max_rule, source = _resolve_height(framework, bv)
        if source == "unresolved" or max_h is None or max_h <= 0:
            continue
        ring = _coords_2d(bv)
        if len(ring) < 3:
            continue

        applies_setback = threshold_h is not None and setback_d is not None and max_h > threshold_h

        if not applies_setback:
            b_parts.append(_extrude_to_mesh(ring, base_z, base_z + max_h))
            b_moves.append(
                MassingMove(
                    description=(
                        f"Extruded bouwvlak '{bv.name}' to {max_h:.1f} m; "
                        "no setback applied because the max height does not exceed "
                        "the threshold (or no setback rule was extracted)."
                    ),
                    driven_by=[max_rule.id] if max_rule else [],
                )
            )
            if max_rule:
                b_inferred_from.append(max_rule.id)
                if max_rule.confidence.score < threshold_below:
                    b_unverified = True
            continue

        # Lower volume: full footprint up to threshold height
        assert threshold_h is not None and setback_d is not None  # narrowed by applies_setback
        b_parts.append(_extrude_to_mesh(ring, base_z, base_z + threshold_h))
        # Upper volume: inset footprint by setback distance, from threshold to max
        shrunk = ShapelyPolygon(ring).buffer(-setback_d)
        if shrunk.is_empty or shrunk.geom_type != "Polygon":
            logger.warning(
                "Setback inset collapsed bouwvlak {}; only base volume rendered.",
                bv.id,
            )
        else:
            upper_ring = list(shrunk.exterior.coords)
            if upper_ring and upper_ring[0] == upper_ring[-1]:
                upper_ring = upper_ring[:-1]
            if len(upper_ring) >= 3:
                b_parts.append(_extrude_to_mesh(upper_ring, base_z + threshold_h, base_z + max_h))

        driven_by: list[str] = []
        if max_rule:
            driven_by.append(max_rule.id)
            b_inferred_from.append(max_rule.id)
            if max_rule.confidence.score < threshold_below:
                b_unverified = True
        if threshold_rule:
            driven_by.append(threshold_rule.id)
            b_inferred_from.append(threshold_rule.id)
            if threshold_rule.confidence.score < threshold_below:
                b_unverified = True
        if setback_rule:
            driven_by.append(setback_rule.id)
            b_inferred_from.append(setback_rule.id)
            if setback_rule.confidence.score < threshold_below:
                b_unverified = True

        b_moves.append(
            MassingMove(
                description=(
                    f"Bouwvlak '{bv.name}': base to {threshold_h:.1f} m, "
                    f"upper volume inset by {setback_d:.1f} m and extruded to "
                    f"{max_h:.1f} m to satisfy the setback above the threshold."
                ),
                driven_by=driven_by,
            )
        )
        if bv.confidence.score < threshold_below:
            b_unverified = True

    b_vertices, b_faces = _merge_geometry(b_parts)
    b_triangles = _faces_to_triangles(b_vertices, b_faces)

    rationale_b_bits = []
    if threshold_rule and setback_rule:
        rationale_b_bits.append(
            f"Above the threshold height of {threshold_h:.1f} m (rule "
            f"'{threshold_rule.id}'), a setback of {setback_d:.1f} m is applied "
            f"(rule '{setback_rule.id}')."
        )
    else:
        rationale_b_bits.append(
            "No threshold or setback rule was extracted with enough structure "
            "to apply a step-back; this variant matches variant A."
        )
    variant_b = Massing(
        id="variant_b_compliant_with_setbacks",
        name="Compliant with setbacks",
        rationale=(
            "Same envelope as variant A, with stepped upper volumes where "
            "setback rules above a threshold height apply. " + rationale_b_bits[0]
        ),
        moves=b_moves,
        geometry_file="massings/variant_b_compliant_with_setbacks.compas.json",
        obj_file="massings/variant_b_compliant_with_setbacks.obj",
        uses_unverified_inputs=b_unverified,
        mesh_polygons=b_triangles,
        provenance=Provenance(
            source_type=SourceType.INFERRED, inferred_from=sorted(set(b_inferred_from))
        ),
    )

    # ----- Export to disk if requested -----
    if output_dir is not None:
        massings_dir = output_dir / "massings"
        massings_dir.mkdir(parents=True, exist_ok=True)
        for massing, verts, faces in (
            (variant_a, a_vertices, a_faces),
            (variant_b, b_vertices, b_faces),
        ):
            mesh = _faces_to_mesh(verts, faces)
            (output_dir / massing.geometry_file).write_text(json_dumps(mesh, pretty=True))
            if massing.obj_file:
                _write_obj(output_dir / massing.obj_file, verts, faces)
        logger.info("Wrote example massings to {}", massings_dir)

    return [variant_a, variant_b]
