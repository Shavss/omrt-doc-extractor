"""Vector geometry parsing from kaveltekening (verbeelding) PDFs.

Generic Dutch bestemmingsplan drawing parser, no project-specific values.
Reads vector paths, discovers the scale factor dynamically, classifies
labels by IMRO convention pattern, associates labels with polygons by
spatial proximity.

Primary function:
    parse_kaveltekening(pdf_path) -> Geometry

Geometry is a Pydantic model (defined in schemas.py) carrying plot polygon,
list of bouwvlakken with classified labels and inferred heights, list of
constraint zones with their labels.

Implementation notes:
- Scale factor discovery: try PDF Measure dictionary at /VP[*]/Measure/X/C
  first (present on AutoCAD-exported PDFs). Fall back to parsing
  'Schaal 1:NNNN' from text layer, deriving via the 0.3528 mm/point
  constant. Last resort: set scale to None and mark scale_status='unknown',
  prompting the viewer for manual input.
- Label classification by pattern only, never by value:
    ALL-CAPS short tokens     -> bestemming codes (GD, V, G)
    (parentheses)             -> function aanduidingen
    [square brackets]         -> bouwaanduidingen
    Numbers in 3..200 range   -> likely heights in metres
    'WR-X' / 'WS-X' style     -> dubbelbestemmingen
- Graceful fallback: if PDF is raster-only, no extractable vectors, or
  scale unfindable, return Geometry(status='manual_input_required', reason=...).

Stage 3 of the build plan.
"""

from __future__ import annotations

# TODO Stage 3: implement parse_kaveltekening
