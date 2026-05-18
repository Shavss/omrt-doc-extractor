"""Vector geometry parsing from kaveltekening (verbeelding) PDFs.

Generic Dutch bestemmingsplan drawing parser, no project-specific values.
Reads vector paths, discovers the scale factor dynamically, classifies
labels by IMRO convention pattern, associates labels with polygons by
spatial proximity.

Primary function:
    parse_kaveltekening(pdf_path) -> Geometry

The output is a transient :class:`Geometry` pydantic model carrying plot
polygon, list of bouwvlakken with classified labels and inferred heights,
and list of constraint zones with their labels. Downstream stages convert
its polygons into :class:`GeometricConstraint` records in the main
``ParametricFramework``; the parser-level Geometry stays here so the
central schema is not coupled to a single drawing's intermediate form.

Implementation notes:
- Scale factor discovery: try PDF Measure dictionary on the page's viewports
  first (present on AutoCAD-exported PDFs that used the scale tool). Fall
  back to parsing 'Schaal 1:NNNN' or 'Scale 1:NNNN' from the text layer,
  deriving via the 0.3528 mm/point constant. Last resort: scale is None and
  ``scale_status='unknown'``, prompting the viewer for manual input.
- Label classification is by *pattern* only, never by *value*:
    ALL-CAPS short tokens     -> bestemming codes
    (parentheses)             -> function aanduidingen
    [square brackets]         -> bouwaanduidingen
    Numbers in 3..200 range   -> likely heights in metres
    'WR-X' / 'WS-X' style     -> dubbelbestemmingen
- Height annotation diamonds (5-vertex shapes < 100 m^2) are identified by
  shape before label association so they cannot capture IMRO codes; their
  height values are spatially joined onto the bouwvlakken they annotate.
- 'm' (moveto) operations inside a path are handled explicitly so multi-
  ring drawings are not collapsed into degenerate triangles.
- Graceful fallback: if the PDF is raster-only, has no extractable vectors,
  or the scale cannot be derived, return Geometry with
  ``status='manual_input_required'`` and a populated ``reason`` so the
  viewer can prompt the PM. This is part of the generalisation strategy,
  not a bug to hide.

Stage 3 of the build plan.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point, Polygon

if TYPE_CHECKING:
    import pymupdf

# 1 PDF point = 1/72 inch = 25.4/72 mm.
MM_PER_POINT = 25.4 / 72.0  # ~0.35278 mm/pt

# Maximum distance (in real-world metres, after scale conversion) between
# consecutive ring vertices for them to be treated as coincident and
# collapsed into a single point. Operating in metres keeps the behaviour
# stable across drawing scales; doing the snap in raw PDF units made the
# effective tolerance swing with 1:N. Kept tight enough that two distinct
# corners on a real plot polygon are never merged.
AUTO_CLOSE_THRESHOLD_M = 0.5

ScaleStatus = Literal["measure_dict", "schaal_text", "unknown"]
GeometryStatus = Literal["ok", "manual_input_required"]


class LabeledPolygon(BaseModel):
    """A polygon with the labels associated to it by spatial proximity.

    Coordinates are a closed ring in world metres (drawing-local cartesian).
    The labels arrays carry only the *classified* tokens; raw token text is
    kept for traceability.
    """

    model_config = ConfigDict(extra="forbid")

    coordinates: list[list[float]] = Field(
        description="Closed ring of [x, y] in world metres (drawing-local)."
    )
    area_m2: float = Field(ge=0.0)
    bestemming_codes: list[str] = Field(default_factory=list)
    function_aanduidingen: list[str] = Field(default_factory=list)
    bouwaanduidingen: list[str] = Field(default_factory=list)
    dubbelbestemmingen: list[str] = Field(default_factory=list)
    height_m: float | None = Field(
        default=None,
        description="Numeric label in 3..200 range associated to this polygon, in metres.",
    )
    height_reconciled_from: Literal["regels", "verbeelding", "verbeelding_uncorrected"] | None = (
        Field(
            default=None,
            description=(
                "How this polygon's height_m was sourced after the reconciliation "
                "pass. 'regels' when set or overwritten by a regels clause, "
                "'verbeelding' when a regels clause confirmed the value from the "
                "drawing, 'verbeelding_uncorrected' when no regels constraint "
                "applied and the drawing value stands. None before reconcile runs."
            ),
        )
    )
    raw_labels: list[str] = Field(default_factory=list)
    original_unique_count: int | None = Field(
        default=None,
        description=(
            "Number of well-separated corners (clustered at "
            "AUTO_CLOSE_THRESHOLD_M) in the raw polygon BEFORE auto-close "
            "vertex collapse ran. Lets the degenerate-geometry test tell "
            "a legitimate source triangle (original < 4) from a rectangle "
            "that auto-close collapsed (original >= 4, final < 4)."
        ),
    )
    final_unique_count: int | None = Field(
        default=None,
        description=(
            "Well-separated corner count AFTER the auto-close vertex "
            "collapse, before any later Polygon/buffer(0) self-"
            "intersection repair. Compared to original_unique_count to "
            "detect the rectangle-collapsed-into-a-triangle bug. The "
            "polygon's actual stored coordinates may have fewer unique "
            "vertices than this if Shapely had to repair a self-"
            "intersecting ring — that is not an auto-close failure."
        ),
    )


class Geometry(BaseModel):
    """Parser output for a verbeelding / kaveltekening PDF.

    Either ``status='ok'`` with a populated geometry, or
    ``status='manual_input_required'`` with a ``reason`` explaining what
    failed. The viewer uses the latter to prompt the PM for hand entry.
    """

    model_config = ConfigDict(extra="forbid")

    status: GeometryStatus
    reason: str | None = None
    source_pdf: str
    source_page: int | None = None

    scale_status: ScaleStatus = "unknown"
    scale_denominator: float | None = Field(
        default=None,
        description="The N in 'Schaal 1:N'. None when derived from a Measure dict directly.",
    )
    meters_per_unit: float | None = Field(
        default=None,
        description="Conversion factor from PDF user-space units to world metres.",
    )

    plot_polygon: list[list[float]] | None = None
    bouwvlakken: list[LabeledPolygon] = Field(default_factory=list)
    constraint_zones: list[LabeledPolygon] = Field(default_factory=list)
    degenerate_polygons_excluded: int = Field(
        default=0,
        description=(
            "Count of reconstructed rings dropped because auto-close "
            "collapsed an originally-4+-unique-point polygon down to fewer "
            "than 4 unique points (the bug case: rectangles snapped into "
            "triangles). Raw coordinates are logged at WARNING level. "
            "Polygons that were already triangular in the source are NOT "
            "counted here; see legitimate_triangles_kept."
        ),
    )
    legitimate_triangles_kept: int = Field(
        default=0,
        description=(
            "Count of polygons kept in output that have fewer than 4 "
            "unique vertex positions but were already triangular in the "
            "source (i.e. auto-close did not collapse them). These pass "
            "the area filter and are legitimate small shapes in the "
            "drawing — distinct from the degenerate-rectangle bug above."
        ),
    )


# =====================================================================
# Scale discovery
# =====================================================================


def _meters_per_unit_from_measure(doc: pymupdf.Document, page_index: int) -> float | None:
    """Try to read a PDF Measure dictionary on the page.

    ISO 32000-1 §12.9.2: a viewport on a page may carry a Measure dict whose
    ``/X`` array of NumberFormat entries has a ``/C`` conversion coefficient
    from user-space units. ``/U`` declares the unit string; if it indicates
    millimetres we scale by 1e-3, otherwise we assume metres.
    """
    try:
        page_xref = doc[page_index].xref
    except Exception:
        return None

    vp = doc.xref_get_key(page_xref, "VP")
    if not vp or vp[0] not in ("array", "xref"):
        return None

    # Walk every xref looking for a Measure dict on a VP entry. Cheaper than
    # parsing the array reliably across the variants in the wild.
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref)
        except Exception:
            continue
        if "/Measure" not in obj or "/Subtype" not in obj:
            continue
        c_match = re.search(r"/C\s+([0-9.+\-eE]+)", obj)
        u_match = re.search(r"/U\s*\(([^)]+)\)", obj)
        if not c_match:
            continue
        try:
            c = float(c_match.group(1))
        except ValueError:
            continue
        unit = u_match.group(1).strip().lower() if u_match else ""
        # Reject placeholder Measure dicts: C=1 with no declared unit means the
        # exporter wrote the entry but never configured a real scale (seen on
        # AutoCAD output where the scale tool was opened but not applied).
        # Coordinates are still in raw PDF points; defer to text-based scale.
        if not unit or c == 1.0:
            logger.debug(
                "Skipping placeholder Measure dict at xref {}: C={} U={!r}",
                xref,
                c,
                unit,
            )
            continue
        if unit in {"mm", "millimeter", "millimetre"}:
            mpu = c * 1e-3
        elif unit in {"cm", "centimeter", "centimetre"}:
            mpu = c * 1e-2
        elif unit in {"km", "kilometer", "kilometre"}:
            mpu = c * 1e3
        else:
            mpu = c
        logger.debug("Measure dict found at xref {}: C={} U={!r}", xref, c, unit)
        return mpu
    return None


_SCALE_TEXT_RE = re.compile(r"\b(?:Schaal|Scale)\s*1\s*:\s*([0-9][0-9.\s']{0,9})", re.IGNORECASE)


def _scale_denominator_from_text(page: pymupdf.Page) -> float | None:
    """Find 'Schaal 1:N' / 'Scale 1:N' in the page text layer.

    Generic typography pattern, not a Dutch-planning-value extraction.
    """
    text = page.get_text("text") or ""
    match = _SCALE_TEXT_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace("'", "").replace(".", "")
    try:
        n = float(raw)
    except ValueError:
        return None
    if n <= 0:
        return None
    return n


# =====================================================================
# Vector extraction
# =====================================================================

# A moveto that lands more than this many PDF user-space units from the
# last point of the in-progress ring is treated as starting a new sub-path,
# not as a micro-gap inside the same ring. Below the threshold the moveto
# is silently treated as continuation.
_MOVETO_GAP_THRESHOLD = 2.0


def _polygons_from_drawings(
    page: pymupdf.Page, page_height: float
) -> list[list[tuple[float, float]]]:
    """Reconstruct closed rings from pymupdf get_drawings output.

    Each drawing has a list of path items: lines, curves, rectangles, and
    movetos. A drawing whose segments form a closed loop (or contains a
    rectangle) is treated as a polygon. Curves are sampled at their
    endpoints only. Y is flipped so positive Y points up.

    Moveto handling: a moveto far from the last point flushes the in-
    progress ring and starts a new one. Without this, multi-ring drawings
    were being collapsed into degenerate triangles by closing across the
    sub-path boundary.
    """
    rings: list[list[tuple[float, float]]] = []

    def _flip(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0], page_height - p[1])

    def _flush(current: list[tuple[float, float]]) -> None:
        if len(current) < 3:
            return
        first, last = current[0], current[-1]
        if first != last:
            current.append(first)
        rings.append(list(current))

    for d in page.get_drawings():
        items = d.get("items") or []
        if not items:
            continue

        current: list[tuple[float, float]] = []

        for item in items:
            op = item[0]

            if op == "m":  # moveto: (op, point)
                target = _flip((item[1].x, item[1].y))
                if current:
                    dist = math.hypot(
                        target[0] - current[-1][0], target[1] - current[-1][1]
                    )
                    if dist > _MOVETO_GAP_THRESHOLD:
                        _flush(current)
                        current = [target]
                    elif dist > 0.01:
                        current.append(target)
                else:
                    current = [target]

            elif op == "l":  # line: (op, p1, p2)
                p1, p2 = item[1], item[2]
                if not current:
                    current.append(_flip((p1.x, p1.y)))
                current.append(_flip((p2.x, p2.y)))

            elif op == "c":  # cubic bezier: (op, p1, p2, p3, p4)
                p1, p4 = item[1], item[4]
                if not current:
                    current.append(_flip((p1.x, p1.y)))
                current.append(_flip((p4.x, p4.y)))

            elif op == "qu":  # quad: (op, Quad)
                _flush(current)
                current = []
                quad = item[1]
                corners = [
                    _flip((quad.ul.x, quad.ul.y)),
                    _flip((quad.ur.x, quad.ur.y)),
                    _flip((quad.lr.x, quad.lr.y)),
                    _flip((quad.ll.x, quad.ll.y)),
                    _flip((quad.ul.x, quad.ul.y)),
                ]
                rings.append(corners)

            elif op == "re":  # rectangle: (op, rect)
                _flush(current)
                current = []
                rect = item[1]
                corners = [
                    _flip((rect.x0, rect.y0)),
                    _flip((rect.x1, rect.y0)),
                    _flip((rect.x1, rect.y1)),
                    _flip((rect.x0, rect.y1)),
                    _flip((rect.x0, rect.y0)),
                ]
                rings.append(corners)

        _flush(current)

    return rings


# =====================================================================
# Label extraction and classification
# =====================================================================


_BESTEMMING_RE = re.compile(r"^[A-Z][A-Z0-9]{0,4}$")
_DUBBEL_RE = re.compile(r"^W[A-Z]-[A-Z0-9]{1,3}$")
_PAREN_RE = re.compile(r"^\((.+)\)$")
_BRACKET_RE = re.compile(r"^\[(.+)\]$")
_NUM_RE = re.compile(r"^[0-9]+(?:[.,][0-9]+)?$")


def _classify_token(tok: str) -> tuple[str, str] | None:
    """Return (category, normalised_value) or None if the token is noise.

    Categories: bestemming, dubbelbestemming, function, bouw, height, plain.
    """
    tok = tok.strip().strip(",;")
    if not tok:
        return None
    m = _PAREN_RE.match(tok)
    if m:
        return ("function", m.group(1).strip())
    m = _BRACKET_RE.match(tok)
    if m:
        return ("bouw", m.group(1).strip())
    if _DUBBEL_RE.match(tok):
        return ("dubbelbestemming", tok)
    if _NUM_RE.match(tok):
        try:
            v = float(tok.replace(",", "."))
        except ValueError:
            return None
        if 3.0 <= v <= 200.0:
            return ("height", str(v))
        return None
    if _BESTEMMING_RE.match(tok):
        return ("bestemming", tok)
    return None


def _extract_labels(
    page: pymupdf.Page, page_height: float
) -> list[tuple[str, tuple[float, float]]]:
    """Pull every text span and its centroid (Y-flipped to cartesian)."""
    out: list[tuple[str, tuple[float, float]]] = []
    raw = page.get_text("dict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []) or []:
            for span in line.get("spans", []) or []:
                text = (span.get("text") or "").strip()
                if not text:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                cx = (x0 + x1) / 2.0
                cy = (y0 + y1) / 2.0
                out.append((text, (cx, page_height - cy)))
    return out


# =====================================================================
# Polygon scoring and label association
# =====================================================================


def _distinct_corners(seq, threshold: float) -> int:
    """Count corners no two of which are within ``threshold`` metres.

    Greedy single-link: walks the input and adds each point as a new
    corner only if it lies at least ``threshold`` away from every corner
    already kept. Used to count well-separated corners regardless of
    listing order; a pen-lift micro-wiggle inside one real corner
    contributes one corner, not two.
    """
    centers: list[tuple[float, float]] = []
    for p in seq:
        if any(
            math.hypot(p[0] - c[0], p[1] - c[1]) < threshold for c in centers
        ):
            continue
        centers.append(p)
    return len(centers)


def _scaled_polygon(
    ring: list[tuple[float, float]], meters_per_unit: float
) -> tuple[Polygon | None, int, int]:
    """Scale a ring to metres, collapse near-coincident vertices, build a Polygon.

    Returns ``(polygon_or_None, original_unique_count, final_unique_count)``
    so the caller can distinguish a legitimate source triangle (original
    < 4) from a polygon whose corners auto-close collapsed (original >= 4
    AND final < 4). Degeneracy logging stays in the caller so the raw
    PDF-unit coordinates can be preserved in the warning.
    """
    pts = [(x * meters_per_unit, y * meters_per_unit) for x, y in ring]
    if len(pts) < 4:
        return None, _distinct_corners(pts, AUTO_CLOSE_THRESHOLD_M), 0

    # Count well-separated corners, not raw vertex positions: a pen-lift
    # micro-wiggle (two raw points within the auto-close threshold) is one
    # corner, not two. Without this the guard would mistakenly flag rings
    # like (A, A', B, C, A) — drawing artifacts that auto-close cleans up
    # to a legitimate triangle.
    original_unique = _distinct_corners(pts, AUTO_CLOSE_THRESHOLD_M)

    deduped: list[tuple[float, float]] = []
    for p in pts:
        if deduped and math.hypot(p[0] - deduped[-1][0], p[1] - deduped[-1][1]) < AUTO_CLOSE_THRESHOLD_M:
            continue
        deduped.append(p)
    # Restore explicit closure if the collapse swallowed the closing vertex.
    if len(deduped) >= 1 and deduped[0] != deduped[-1]:
        deduped.append(deduped[0])

    # final_unique reflects ONLY the effect of the auto-close vertex
    # collapse, not any later Polygon/buffer(0) self-intersection repair.
    # That distinction matters: the degenerate guard is about auto-close
    # losing corners, not Shapely fixing zig-zag rings. Use the same
    # corner-clustering metric as original_unique so they are comparable.
    final_unique = _distinct_corners(deduped, AUTO_CLOSE_THRESHOLD_M)

    if len(deduped) < 4:
        return None, original_unique, final_unique

    try:
        poly = Polygon(deduped)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            return None, original_unique, final_unique
        # buffer(0) on a self-intersecting ring may yield a MultiPolygon;
        # take the largest part so downstream stays single-polygon.
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        if poly.geom_type != "Polygon":
            return None, original_unique, final_unique
        return poly, original_unique, final_unique
    except Exception:
        return None, original_unique, final_unique




# Annotation diamonds: 4-corner shape (5 vertices incl. closure) under
# 100 m^2. Identified by shape alone so the label-association step can
# avoid handing IMRO codes to them.
_DIAMOND_VERTEX_COUNT = 5
_DIAMOND_MAX_AREA_M2 = 100.0


def _is_diamond_shape(poly: Polygon) -> bool:
    if len(poly.exterior.coords) != _DIAMOND_VERTEX_COUNT:
        return False
    return poly.area <= _DIAMOND_MAX_AREA_M2


def _associate_labels(
    polys_m: list[Polygon],
    labels_m: list[tuple[str, tuple[float, float]]],
) -> list[list[str]]:
    """For each polygon, return raw label tokens assigned by spatial proximity.

    Assignment strategy:
    - Numeric height tokens go to the smallest containing polygon (the
      annotation diamond itself is fine — its value is spatially joined
      onto the parent bouwvlak in step 4).
    - IMRO tokens (bestemming, function, bouw, dubbel) go to the smallest
      containing *non-diamond* polygon. Diamonds are excluded from the
      candidate pool so they cannot steal zone codes from the real zones
      they sit inside.
    - Labels with no containing polygon go to the nearest non-diamond
      polygon by distance.

    Output token lists are deduplicated (order-preserving).
    """
    assigned: list[list[str]] = [[] for _ in polys_m]
    if not polys_m:
        return assigned

    diamond_flags = [_is_diamond_shape(p) for p in polys_m]
    real_indices = [i for i, d in enumerate(diamond_flags) if not d]

    for text, (lx, ly) in labels_m:
        pt = Point(lx, ly)
        containing = [i for i, p in enumerate(polys_m) if p.contains(pt)]

        cls = _classify_token(text.strip().strip(",;"))
        is_height = cls is not None and cls[0] == "height"

        if containing:
            if is_height:
                pool = containing
            else:
                real = [i for i in containing if not diamond_flags[i]]
                pool = real if real else containing
            idx = min(pool, key=lambda i: polys_m[i].area)
        else:
            pool = real_indices if real_indices else list(range(len(polys_m)))
            idx = min(pool, key=lambda i: polys_m[i].distance(pt))

        for tok in text.split():
            assigned[idx].append(tok)

    deduped: list[list[str]] = []
    for toks in assigned:
        seen: set[str] = set()
        deduped.append([t for t in toks if not (t in seen or seen.add(t))])  # type: ignore[func-returns-value]
    return deduped


def _build_labeled(
    poly_m: Polygon,
    tokens: list[str],
    original_unique_count: int | None = None,
    final_unique_count: int | None = None,
) -> LabeledPolygon:
    bestemming, function, bouw, dubbel = [], [], [], []
    height: float | None = None
    for tok in tokens:
        cls = _classify_token(tok)
        if cls is None:
            continue
        cat, val = cls
        if cat == "bestemming":
            bestemming.append(val)
        elif cat == "dubbelbestemming":
            dubbel.append(val)
        elif cat == "function":
            function.append(val)
        elif cat == "bouw":
            bouw.append(val)
        elif cat == "height":
            v = float(val)
            if height is None or v > height:
                height = v
    coords = [list(c) for c in poly_m.exterior.coords]
    return LabeledPolygon(
        coordinates=coords,
        area_m2=float(poly_m.area),
        bestemming_codes=sorted(set(bestemming)),
        function_aanduidingen=sorted(set(function)),
        bouwaanduidingen=sorted(set(bouw)),
        dubbelbestemmingen=sorted(set(dubbel)),
        height_m=height,
        raw_labels=tokens,
        original_unique_count=original_unique_count,
        final_unique_count=final_unique_count,
    )


# =====================================================================
# Height annotation diamond detection and spatial join
# =====================================================================


def _is_height_marker(poly: Polygon, tokens: list[str]) -> bool:
    """Return True if this polygon is a height annotation diamond to strip.

    Shape must match a diamond (5 vertices, < 100 m^2). Either it carries
    no classifiable tokens at all (decoration), or every classifiable
    token is a height value (no IMRO code present).
    """
    if not _is_diamond_shape(poly):
        return False
    classified = [c for c in (_classify_token(t) for t in tokens) if c is not None]
    if not classified:
        return True
    return all(cat == "height" for cat, _ in classified)


def _assign_heights_to_bouwvlakken(
    height_markers: list[tuple[Polygon, float]],
    bouwvlakken: list[LabeledPolygon],
) -> None:
    """Spatially join height values from diamonds onto bouwvlakken, in-place.

    For each marker centroid: pick the smallest containing bouwvlak; if
    none contains it, pick the nearest by distance. Heights only fill an
    empty ``height_m`` — directly labelled polygons are never overwritten.
    """
    if not bouwvlakken or not height_markers:
        return

    bv_polys: list[Polygon | None] = []
    for lp in bouwvlakken:
        try:
            bv_polys.append(Polygon(lp.coordinates))
        except Exception:
            bv_polys.append(None)

    for marker_poly, h in height_markers:
        centroid = marker_poly.centroid
        containing = [
            i for i, p in enumerate(bv_polys) if p is not None and p.contains(centroid)
        ]
        if containing:
            idx = min(containing, key=lambda i: bv_polys[i].area)  # type: ignore[union-attr]
        else:
            distances = [
                p.distance(centroid) if p is not None else float("inf")
                for p in bv_polys
            ]
            if not distances:
                continue
            idx = min(range(len(distances)), key=lambda i: distances[i])

        if bouwvlakken[idx].height_m is None:
            bouwvlakken[idx].height_m = h


# =====================================================================
# Page selection
# =====================================================================


def _pick_drawing_page(doc: pymupdf.Document) -> int:
    """Pick the page with the most vector drawings.

    Multi-page verbeelding PDFs often have a title sheet plus the actual
    drawing; the drawing sheet wins on this metric.
    """
    best_idx = 0
    best_count = -1
    for i in range(len(doc)):
        try:
            n = len(doc[i].get_drawings())
        except Exception:
            n = 0
        if n > best_count:
            best_count = n
            best_idx = i
    return best_idx


# =====================================================================
# DVG overlay classification
# =====================================================================


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


# =====================================================================
# Public entry point
# =====================================================================


def parse_kaveltekening(pdf_path: Path | str) -> Geometry:
    """Parse a verbeelding / kaveltekening PDF into a :class:`Geometry`.

    Generic: nothing about a specific municipality, neighbourhood or
    drawing is hardcoded. Discovers the scale, extracts vector polygons,
    classifies text labels by IMRO pattern, and associates by proximity.
    Falls back to ``manual_input_required`` when the drawing cannot be
    decoded.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        return Geometry(
            status="manual_input_required",
            source_pdf=str(pdf_path),
            reason=f"PDF not found at {pdf_path}",
        )

    import pymupdf  # lazy: native init segfaults under pytest if imported at module load

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to open verbeelding PDF {}: {}", pdf_path, exc)
        return Geometry(
            status="manual_input_required",
            source_pdf=str(pdf_path),
            reason=f"Unable to open PDF: {exc}",
        )

    try:
        page_index = _pick_drawing_page(doc)
        page = doc[page_index]
        page_height = page.rect.height

        # Step 1: scale discovery.
        scale_status: ScaleStatus = "unknown"
        scale_denominator: float | None = None
        meters_per_unit: float | None = _meters_per_unit_from_measure(doc, page_index)
        if meters_per_unit is not None and meters_per_unit > 0:
            scale_status = "measure_dict"
        else:
            scale_denominator = _scale_denominator_from_text(page)
            if scale_denominator is not None:
                # 1 PDF unit = 1 point on paper = MM_PER_POINT mm on paper.
                # 1 mm on paper = N mm in world; so 1 unit = MM_PER_POINT * N mm = ...m
                meters_per_unit = (MM_PER_POINT * 1e-3) * scale_denominator
                scale_status = "schaal_text"

        if meters_per_unit is None:
            return Geometry(
                status="manual_input_required",
                source_pdf=str(pdf_path),
                source_page=page_index + 1,
                scale_status="unknown",
                reason=(
                    "Could not derive scale: no Measure dictionary on the page "
                    "and no 'Schaal 1:N' text found. Manual scale entry required."
                ),
            )

        # Step 2: vector polygons.
        rings = _polygons_from_drawings(page, page_height)
        polys_m: list[Polygon] = []
        degenerate_excluded = 0
        legitimate_triangles_kept = 0
        # Per-polygon corner counts, aligned with polys_m, so the downstream
        # LabeledPolygon can carry the values for honest reporting.
        polys_original_unique: list[int] = []
        polys_final_unique: list[int] = []
        for r in rings:
            poly, original_unique, final_unique = _scaled_polygon(r, meters_per_unit)
            if poly is None:
                # Polygon couldn't even be constructed. Only flag the bug
                # case (originally >=4 unique, but collapsed); silent drop
                # for source triangles/lines that never had enough corners.
                if original_unique >= 4 and final_unique < 4:
                    logger.warning(
                        "Excluding degenerate polygon (collapsed from {} to "
                        "{} unique pts by auto-close; polygon could not be "
                        "rebuilt); raw ring coords (PDF units, Y-flipped) = {}",
                        original_unique,
                        final_unique,
                        r,
                    )
                    degenerate_excluded += 1
                continue
            # Reject specks: anything under 1 m^2 is decoration. The area
            # filter is the right place to drop hatch/marker triangles —
            # the unique-point guard only handles the auto-close bug case.
            if poly.area < 1.0:
                continue
            if original_unique >= 4 and final_unique < 4:
                logger.warning(
                    "Excluding degenerate polygon (auto-close collapsed {} "
                    "unique pts to {}, area={:.1f} m2); raw ring coords "
                    "(PDF units, Y-flipped) = {}",
                    original_unique,
                    final_unique,
                    poly.area,
                    r,
                )
                degenerate_excluded += 1
                continue
            if final_unique < 4:
                # Legitimate source triangle that survived the area filter.
                legitimate_triangles_kept += 1
            polys_m.append(poly)
            polys_original_unique.append(original_unique)
            polys_final_unique.append(final_unique)

        if not polys_m:
            return Geometry(
                status="manual_input_required",
                source_pdf=str(pdf_path),
                source_page=page_index + 1,
                scale_status=scale_status,
                scale_denominator=scale_denominator,
                meters_per_unit=meters_per_unit,
                reason=(
                    "No vector polygons could be extracted. The PDF may be "
                    "raster-only or use a path encoding that this parser does "
                    "not yet support."
                ),
            )

        # Step 3: labels.
        raw_labels = _extract_labels(page, page_height)
        labels_m = [(t, (x * meters_per_unit, y * meters_per_unit)) for t, (x, y) in raw_labels]
        assigned = _associate_labels(polys_m, labels_m)

        if not any(toks for toks in assigned):
            return Geometry(
                status="manual_input_required",
                source_pdf=str(pdf_path),
                source_page=page_index + 1,
                scale_status=scale_status,
                scale_denominator=scale_denominator,
                meters_per_unit=meters_per_unit,
                reason=(
                    "Vector polygons found but no recognisable IMRO labels "
                    "could be associated. Manual classification required."
                ),
            )

        # Step 4: build LabeledPolygons, strip annotation diamonds (joining
        # their height values onto the parent bouwvlak), then categorise
        # the remaining real polygons into plot / bouwvlakken / zones.
        labeled = [
            _build_labeled(p, toks, ou, fu)
            for p, toks, ou, fu in zip(
                polys_m,
                assigned,
                polys_original_unique,
                polys_final_unique,
                strict=True,
            )
        ]

        height_markers: list[tuple[Polygon, float]] = []
        real_entries: list[tuple[Polygon, LabeledPolygon]] = []
        for poly, lp in zip(polys_m, labeled, strict=True):
            if _is_height_marker(poly, lp.raw_labels):
                if lp.height_m is not None:
                    height_markers.append((poly, lp.height_m))
            else:
                real_entries.append((poly, lp))

        logger.debug(
            "Stripped {} annotation diamonds; {} real polygons remain.",
            len(labeled) - len(real_entries),
            len(real_entries),
        )

        # Plot boundary: the single largest real polygon. Always picked,
        # even if it carries no IMRO label — the page outline often does
        # not. Smaller polygons inside it become the labelled zones.
        plot_idx: int | None = None
        if real_entries:
            plot_idx = max(
                range(len(real_entries)),
                key=lambda i: real_entries[i][1].area_m2,
            )
        plot_polygon = (
            real_entries[plot_idx][1].coordinates if plot_idx is not None else None
        )

        bouwvlakken: list[LabeledPolygon] = []
        constraint_zones: list[LabeledPolygon] = []
        for i, (_poly, lp) in enumerate(real_entries):
            if i == plot_idx:
                continue
            if not lp.raw_labels:
                continue
            if _is_dvg_only(lp):
                # Dove gevel acoustic overlay -- a constraint zone, never a building volume.
                # The height number next to it on the kaveltekening is the tower height
                # for the underlying bouwvlak, not a separate building height.
                constraint_zones.append(lp)
            elif lp.bouwaanduidingen:
                bouwvlakken.append(lp)
            elif lp.dubbelbestemmingen or lp.bestemming_codes or lp.function_aanduidingen:
                constraint_zones.append(lp)

        _assign_heights_to_bouwvlakken(height_markers, bouwvlakken)

        logger.info(
            "Parsed {} polygons from {}: plot={}, bouwvlakken={}, zones={}, "
            "degenerate_polygons_excluded={}, legitimate_triangles_kept={}",
            len(polys_m),
            pdf_path.name,
            plot_polygon is not None,
            len(bouwvlakken),
            len(constraint_zones),
            degenerate_excluded,
            legitimate_triangles_kept,
        )

        return Geometry(
            status="ok",
            source_pdf=str(pdf_path),
            source_page=page_index + 1,
            scale_status=scale_status,
            scale_denominator=scale_denominator,
            meters_per_unit=meters_per_unit,
            plot_polygon=plot_polygon,
            bouwvlakken=bouwvlakken,
            constraint_zones=constraint_zones,
            degenerate_polygons_excluded=degenerate_excluded,
            legitimate_triangles_kept=legitimate_triangles_kept,
        )
    finally:
        doc.close()


# =====================================================================
# Merge Stage 3 output into a ParametricFramework
# Converts the raw Geometry (plot_polygon, bouwvlakken, constraint_zones)
# into GeometricConstraint records and attaches them to a framework,
# wiring associated_rules from the existing numerical constraints by
# matching slug-normalised aanduiding codes against their applies_to.
# =====================================================================


def _slugify_code(code: str) -> str:
    """Normalise an aanduiding code so 'sba-1' matches an applies_to of 'sba_1'."""
    return code.lower().replace("-", "_").replace(" ", "_")


def _build_associated_rules(
    codes: list[str], framework_numerical: list  # list[NumericalConstraint]
) -> list[str]:
    """Find NumericalConstraint IDs whose applies_to references any of these codes."""
    slugs = {_slugify_code(c) for c in codes}
    return [
        c.id
        for c in framework_numerical
        if any(_slugify_code(a) in slugs for a in c.applies_to)
    ]


def merge_geometry_into_framework(
    framework,  # ParametricFramework
    geometry: "Geometry | dict",
):
    """Return a new ParametricFramework with bouwvlakken/zones added as GeometricConstraints.

    Inputs:
      framework: an existing ParametricFramework (typically from the extraction stage).
      geometry:  a parsed Geometry object or the raw dict loaded from
                 ``data/outputs/<project>_geometry.json``.

    Behaviour:
      - Plot polygon becomes one GeometricConstraint with feature_type='plot_boundary'.
      - Each bouwvlak becomes one GeometricConstraint with feature_type='bouwvlak'.
      - Each constraint zone becomes one with feature_type='no_build_zone' or
        'other' depending on whether dubbelbestemmingen are present.
      - associated_rules are wired from existing numerical constraints whose
        applies_to references any of the polygon's aanduiding codes
        (slug-normalised, so 'sba-1' matches an applies_to of 'sba_1').
      - Coordinates stay in their native CRS. The geometry parser produces
        drawing-local cartesian metres, so crs=CRS.DRAWING_LOCAL. A later
        georeferencing step can rewrite these to RD New.
      - Existing geometric constraints on the framework are preserved; new
        ones are appended.

    Returns a NEW framework (via model_validate(model_dump())). Does not mutate input.
    """
    # Local imports to avoid a top-level circular dependency between
    # geometry.py and schemas.py.
    from omrt_extractor.schemas import (
        CRS,
        Confidence,
        Constraints,
        GeometricConstraint,
        ParametricFramework,
        Provenance,
        SourceType,
    )

    if isinstance(geometry, dict):
        geo = Geometry.model_validate(geometry)
    else:
        geo = geometry

    if geo.status != "ok":
        logger.warning(
            "Geometry status is '{}'; nothing to merge. reason={}",
            geo.status,
            geo.reason,
        )
        return framework

    source_doc = Path(geo.source_pdf).name
    page = geo.source_page or 1
    base_prov = Provenance(
        source_type=SourceType.DOCUMENT,
        document=source_doc,
        page=page,
        quoted_text=f"Vector geometry parsed from {source_doc} page {page}.",
    )
    # Confidence: parsed structure is mechanically extracted, but the
    # scale derivation can be soft. Lower confidence when scale_status
    # is 'unknown' or 'measure_missing'.
    base_score = 0.9 if geo.scale_status in ("measure_dict", "schaal_text") else 0.6
    base_conf = Confidence(
        score=base_score,
        reasons=[f"Stage 3 vector parser; scale_status={geo.scale_status}"],
    )

    def _close_ring(coords: list[list[float]]) -> list[list[float]]:
        if len(coords) >= 1 and coords[0] != coords[-1]:
            return coords + [coords[0]]
        return coords

    def _next_id(used: set[str], stem: str) -> str:
        i = 1
        while f"{stem}_{i:02d}" in used:
            i += 1
            if i > 999:
                raise RuntimeError(f"Could not find a free ID for stem '{stem}'")
        return f"{stem}_{i:02d}"

    new_geoms: list[GeometricConstraint] = []
    used_ids = {
        c.id
        for collection in (
            framework.constraints.numerical,
            framework.constraints.geometric,
            framework.constraints.narrative,
            framework.variables.items,
            framework.kpis.items,
            framework.massings,
        )
        for c in collection
    }

    if geo.plot_polygon:
        pid = _next_id(used_ids, "plot_boundary")
        used_ids.add(pid)
        new_geoms.append(
            GeometricConstraint(
                id=pid,
                name="Plot boundary",
                feature_type="plot_boundary",
                coordinates=_close_ring(geo.plot_polygon),
                crs=CRS.DRAWING_LOCAL,
                associated_rules=[],
                provenance=base_prov,
                confidence=base_conf,
            )
        )

    for lp in geo.bouwvlakken:
        bid = _next_id(used_ids, "bouwvlak")
        used_ids.add(bid)
        codes = (
            lp.bouwaanduidingen
            + lp.function_aanduidingen
            + lp.bestemming_codes
        )
        rules = _build_associated_rules(codes, framework.constraints.numerical)
        label = ", ".join(codes) if codes else "(no label)"
        new_geoms.append(
            GeometricConstraint(
                id=bid,
                name=f"Bouwvlak {label}",
                feature_type="bouwvlak",
                coordinates=_close_ring(lp.coordinates),
                crs=CRS.DRAWING_LOCAL,
                associated_rules=rules,
                extrusion_height_m=lp.height_m,
                height_reconciled_from=lp.height_reconciled_from,
                provenance=base_prov,
                confidence=base_conf,
                notes=(
                    f"raw_labels={lp.raw_labels}; height_m={lp.height_m}; "
                    f"area_m2={lp.area_m2:.0f}"
                ),
            )
        )

    for lp in geo.constraint_zones:
        if _is_dvg_only(lp):
            ft = "dvg_overlay"
        elif lp.dubbelbestemmingen:
            ft = "no_build_zone"
        else:
            ft = "other"
        zid = _next_id(used_ids, ft)
        used_ids.add(zid)
        codes = (
            lp.dubbelbestemmingen
            + lp.function_aanduidingen
            + lp.bestemming_codes
        )
        rules = _build_associated_rules(codes, framework.constraints.numerical)
        label = ", ".join(codes) if codes else "(no label)"
        new_geoms.append(
            GeometricConstraint(
                id=zid,
                name=f"Zone {label}",
                feature_type=ft,
                coordinates=_close_ring(lp.coordinates),
                crs=CRS.DRAWING_LOCAL,
                associated_rules=rules,
                provenance=base_prov,
                confidence=base_conf,
                notes=f"raw_labels={lp.raw_labels}; area_m2={lp.area_m2:.0f}",
            )
        )

    logger.info(
        "Merging {} geometric features into framework "
        "({} bouwvlakken, {} zones, plot={})",
        len(new_geoms),
        len(geo.bouwvlakken),
        len(geo.constraint_zones),
        geo.plot_polygon is not None,
    )

    # Build a new framework via dump/validate so the model_validators re-fire
    # (in particular the ID uniqueness check).
    payload = framework.model_dump(mode="json")
    payload["constraints"]["geometric"].extend(
        [g.model_dump(mode="json") for g in new_geoms]
    )
    return ParametricFramework.model_validate(payload)
