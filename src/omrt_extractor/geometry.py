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
    raw_labels: list[str] = Field(default_factory=list)


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


def _polygons_from_drawings(
    page: pymupdf.Page, page_height: float
) -> list[list[tuple[float, float]]]:
    """Reconstruct closed rings from pymupdf get_drawings output.

    Each drawing has a list of path items: lines, curves, and rectangles.
    A drawing whose segments form a closed loop (or contains a rectangle)
    is treated as a polygon. Curves are sampled at their endpoints only.
    Y is flipped so positive Y points up, matching cartesian convention.
    """
    rings: list[list[tuple[float, float]]] = []

    def _flip(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0], page_height - p[1])

    for d in page.get_drawings():
        items = d.get("items") or []
        if not items:
            continue

        current: list[tuple[float, float]] = []
        for item in items:
            op = item[0]
            if op == "l":  # line: (op, p1, p2)
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
                rect = item[1]
                # rect corners CCW after Y-flip
                corners = [
                    _flip((rect.x0, rect.y0)),
                    _flip((rect.x1, rect.y0)),
                    _flip((rect.x1, rect.y1)),
                    _flip((rect.x0, rect.y1)),
                    _flip((rect.x0, rect.y0)),
                ]
                rings.append(corners)
            else:
                # 'm' moves implicitly handled by segment endpoints
                continue

        if len(current) >= 3:
            # Auto-close if endpoints are near each other
            first, last = current[0], current[-1]
            if math.hypot(first[0] - last[0], first[1] - last[1]) < 1.0:
                if first != last:
                    current.append(first)
                rings.append(current)

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


def _scaled_polygon(ring: list[tuple[float, float]], meters_per_unit: float) -> Polygon | None:
    pts = [(x * meters_per_unit, y * meters_per_unit) for x, y in ring]
    if len(pts) < 4:
        return None
    try:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            return None
        return poly
    except Exception:
        return None


def _associate_labels(
    polys_m: list[Polygon],
    labels_m: list[tuple[str, tuple[float, float]]],
) -> list[list[str]]:
    """For each polygon, return raw label tokens whose centroid is closest.

    A label is assigned to the polygon it falls inside; if it falls in none,
    to the polygon with the smallest centroid-to-label distance.
    """
    assigned: list[list[str]] = [[] for _ in polys_m]
    for text, (lx, ly) in labels_m:
        pt = Point(lx, ly)
        containing = [i for i, p in enumerate(polys_m) if p.contains(pt)]
        if containing:
            # Smallest containing polygon wins (most specific).
            idx = min(containing, key=lambda i: polys_m[i].area)
        else:
            if not polys_m:
                continue
            idx = min(range(len(polys_m)), key=lambda i: polys_m[i].distance(pt))
        for tok in text.split():
            assigned[idx].append(tok)
    return assigned


def _build_labeled(poly_m: Polygon, tokens: list[str]) -> LabeledPolygon:
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
    )


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
        for r in rings:
            poly = _scaled_polygon(r, meters_per_unit)
            if poly is None:
                continue
            # Reject specks: anything under 1 m^2 is decoration.
            if poly.area < 1.0:
                continue
            polys_m.append(poly)

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

        # Step 4: categorise polygons. The single largest polygon with at
        # least one label is treated as the plot boundary; polygons with an
        # inferred height become bouwvlakken; the remainder, if labelled,
        # become constraint zones.
        labeled = [_build_labeled(p, toks) for p, toks in zip(polys_m, assigned, strict=True)]

        plot_idx: int | None = None
        for i in sorted(range(len(labeled)), key=lambda j: labeled[j].area_m2, reverse=True):
            if labeled[i].raw_labels:
                plot_idx = i
                break

        bouwvlakken: list[LabeledPolygon] = []
        constraint_zones: list[LabeledPolygon] = []
        for i, lp in enumerate(labeled):
            if i == plot_idx:
                continue
            if not lp.raw_labels:
                continue
            if lp.height_m is not None or lp.bouwaanduidingen:
                bouwvlakken.append(lp)
            elif lp.dubbelbestemmingen or lp.bestemming_codes or lp.function_aanduidingen:
                constraint_zones.append(lp)

        plot_polygon = labeled[plot_idx].coordinates if plot_idx is not None else None

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
        )
    finally:
        doc.close()
