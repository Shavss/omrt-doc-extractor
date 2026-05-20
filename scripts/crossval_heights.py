"""
scripts/crossval_heights.py

Cross-validates bouwvlak heights extracted from the PDF (geometry.json)
against authoritative heights from the GML (ruimtelijkeplannen.nl).

Matching strategy (in priority order):
  1. By sgd code  -- unique per zone, reliable primary key
  2. By area      -- for zones with no sgd code, within 25% tolerance
  3. sba codes are NOT used as match keys -- they are overlay annotations
     that appear on multiple bouwvlakken and are not zone identifiers.
     sba-dvg zones are acoustic overlays, not building envelopes, and are
     classified as 'overlay_annotation' rather than 'unmatched'.

Usage:
    .venv/bin/python scripts/crossval_heights.py

Requires: lxml, shapely
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from shapely.geometry import Point, Polygon

GML_CACHE = Path("data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml")
OUTPUT = Path("data/outputs/crossval_heights_report.json")

AREA_TOLERANCE = 0.25
HEIGHT_TOLERANCE = 0.01

# sba-dvg codes are dove gevel acoustic overlays -- not building zones
DVG_PREFIXES = ("sba-dvg",)

# ------------------------------------------------------------------
# GML parsing helpers
# ------------------------------------------------------------------


def get_ns(root) -> tuple[str, str]:
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.nsmap:
            ns = el.nsmap.get(None) or next(iter(el.nsmap.values()))
            return f"{{{ns}}}", "{http://www.opengis.net/gml/3.2}"
    raise ValueError("No namespace found")


def parse_poslist(text: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in text.strip().split()]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]


def get_polygon(el, IMRO: str, GML: str) -> Polygon | None:
    pos_el = el.find(f".//{GML}posList")
    if pos_el is None or not pos_el.text:
        return None
    coords = parse_poslist(pos_el.text)
    return Polygon(coords) if len(coords) >= 3 else None


def get_text(el, IMRO: str, tag: str) -> str:
    child = el.find(f"{IMRO}{tag}")
    return child.text.strip() if child is not None and child.text else ""


# ------------------------------------------------------------------
# Build GML lookups
# ------------------------------------------------------------------


def build_gml_bouwvlakken(root, IMRO, GML) -> list[dict]:
    maatv = []
    for el in root.iter(f"{IMRO}Maatvoering"):
        pos_el = el.find(f".//{GML}pos")
        waarde_el = el.find(f".//{IMRO}waarde")
        type_el = el.find(f".//{IMRO}waardeType")
        if pos_el is None or waarde_el is None:
            continue
        if type_el is not None and "bouwhoogte" not in type_el.text.lower():
            continue
        xy = [float(v) for v in pos_el.text.strip().split()]
        if len(xy) != 2:
            continue
        try:
            h = float(waarde_el.text.strip().replace(",", "."))
        except ValueError:
            continue
        maatv.append((Point(xy[0], xy[1]), h))

    bouwvlakken = []
    for el in root.iter(f"{IMRO}Bouwvlak"):
        gml_id = el.get(f"{GML}id", "")
        poly = get_polygon(el, IMRO, GML)
        if poly is None:
            continue
        matched_h = [h for pt, h in maatv if poly.contains(pt)]
        bouwvlakken.append(
            {
                "id": gml_id,
                "polygon": poly,
                "area_m2": round(poly.area, 1),
                "height_m": max(matched_h) if matched_h else None,
                "sgd_codes": [],
            }
        )
    return bouwvlakken


def build_gml_functieaanduidingen(root, IMRO, GML) -> list[dict]:
    result = []
    for el in root.iter(f"{IMRO}Functieaanduiding"):
        poly = get_polygon(el, IMRO, GML)
        naam = get_text(el, IMRO, "naam")
        aanduiding = get_text(el, IMRO, "aanduiding")
        if poly is None:
            continue
        result.append({"naam": naam, "aanduiding": aanduiding, "polygon": poly})
    return result


def normalise_sgd(raw: str) -> str:
    return raw.replace("specifieke vorm van gemengd - ", "sgd-").strip()


def normalise_m_code(codes: list[str]) -> list[str]:
    """Normalise bare 'm' to 'maatschappelijk' so it matches GML functieaanduiding."""
    return ["maatschappelijk" if c == "m" else c for c in codes]


def attach_sgd_codes(bouwvlakken: list[dict], functieaanduidingen: list[dict]):
    for bv in bouwvlakken:
        for fa in functieaanduidingen:
            if bv["polygon"].intersects(fa["polygon"]):
                code = fa["aanduiding"] or fa["naam"]
                if code and code not in bv["sgd_codes"]:
                    bv["sgd_codes"].append(code)


# ------------------------------------------------------------------
# Classification helpers
# ------------------------------------------------------------------


def is_dvg_only(pdf_bv: dict) -> bool:
    """True if every bouwaanduiding on this zone is a dove gevel overlay."""
    sba = pdf_bv.get("bouwaanduidingen", [])
    sgd = pdf_bv.get("function_aanduidingen", [])
    best = pdf_bv.get("bestemming_codes", [])
    if not sba or sgd or best:
        return False
    return all(any(s.startswith(p) for p in DVG_PREFIXES) for s in sba)


def is_legend_swatch(pdf_bv: dict) -> bool:
    return pdf_bv.get("area_m2", 0) < 400


# ------------------------------------------------------------------
# Matching dataclass
# ------------------------------------------------------------------


@dataclass
class MatchResult:
    pdf_index: int
    pdf_labels: list
    pdf_height_m: float | None
    pdf_area_m2: float
    gml_id: str
    gml_height_m: float | None
    gml_area_m2: float
    match_method: str
    agreement: str  # agreement | disagreement | pdf_missing | unmatched | overlay_annotation | legend_swatch
    delta_m: float | None
    notes: str


def make_result(
    i, pdf_bv, labels, gml_bv, method, agreement_override=None, notes=""
) -> MatchResult:
    ph = pdf_bv.get("height_m")
    gh = gml_bv["height_m"] if gml_bv else None
    delta = abs(ph - gh) if ph is not None and gh is not None else None

    if agreement_override:
        agreement = agreement_override
    elif gml_bv is None:
        agreement = "unmatched"
    elif ph is None:
        agreement = "pdf_missing"
    elif delta is not None and delta <= HEIGHT_TOLERANCE:
        agreement = "agreement"
    else:
        agreement = "disagreement"

    return MatchResult(
        pdf_index=i,
        pdf_labels=labels,
        pdf_height_m=ph,
        pdf_area_m2=pdf_bv.get("area_m2", 0),
        gml_id=gml_bv["id"][-20:] if gml_bv else "",
        gml_height_m=gh,
        gml_area_m2=gml_bv["area_m2"] if gml_bv else 0,
        match_method=method,
        agreement=agreement,
        delta_m=round(delta, 2) if delta is not None else None,
        notes=notes,
    )


# ------------------------------------------------------------------
# Matching
# ------------------------------------------------------------------


def match_bouwvlakken(pdf_bouwvlakken, gml_bouwvlakken) -> list[MatchResult]:
    results: list[MatchResult] = []
    used_gml_ids: set[str] = set()
    matched_pdf: set[int] = set()

    # ------ Pre-pass: classify overlay annotations and legend swatches ------
    for i, pdf_bv in enumerate(pdf_bouwvlakken):
        if is_legend_swatch(pdf_bv):
            matched_pdf.add(i)
            # silently skip -- too small to be a real zone

        elif is_dvg_only(pdf_bv):
            matched_pdf.add(i)
            labels = pdf_bv.get("bouwaanduidingen", [])
            results.append(
                MatchResult(
                    pdf_index=i,
                    pdf_labels=labels,
                    pdf_height_m=pdf_bv.get("height_m"),
                    pdf_area_m2=pdf_bv.get("area_m2", 0),
                    gml_id="",
                    gml_height_m=None,
                    gml_area_m2=0,
                    match_method="classified",
                    agreement="overlay_annotation",
                    delta_m=None,
                    notes="Dove gevel acoustic overlay -- not a building envelope zone",
                )
            )

    # ------ Pass 1: match by sgd / functieaanduiding code ------
    for i, pdf_bv in enumerate(pdf_bouwvlakken):
        if i in matched_pdf:
            continue
        pdf_sgd = normalise_m_code(pdf_bv.get("function_aanduidingen", []))
        if not pdf_sgd:
            continue

        matched_gml = None
        for gml_bv in gml_bouwvlakken:
            if gml_bv["id"] in used_gml_ids:
                continue
            gml_codes = [normalise_sgd(c) for c in gml_bv["sgd_codes"]]
            if any(c in gml_codes for c in pdf_sgd):
                matched_gml = gml_bv
                break

        labels = pdf_sgd + pdf_bv.get("bouwaanduidingen", [])
        if matched_gml:
            used_gml_ids.add(matched_gml["id"])
            results.append(make_result(i, pdf_bv, labels, matched_gml, "sgd_code"))
        else:
            results.append(
                make_result(
                    i,
                    pdf_bv,
                    labels,
                    None,
                    "sgd_code",
                    notes=f"SGD codes {pdf_sgd} not found in GML",
                )
            )
        matched_pdf.add(i)

    # ------ Pass 2: area-based matching for remaining zones ------
    for i, pdf_bv in enumerate(pdf_bouwvlakken):
        if i in matched_pdf:
            continue

        pdf_area = pdf_bv.get("area_m2", 0)
        labels = (
            pdf_bv.get("bestemming_codes", [])
            + pdf_bv.get("bouwaanduidingen", [])
            + pdf_bv.get("function_aanduidingen", [])
        )

        best_gml, best_delta = None, float("inf")
        for gml_bv in gml_bouwvlakken:
            if gml_bv["id"] in used_gml_ids or gml_bv["area_m2"] == 0:
                continue
            diff = abs(pdf_area - gml_bv["area_m2"]) / gml_bv["area_m2"]
            if diff < AREA_TOLERANCE and diff < best_delta:
                best_delta, best_gml = diff, gml_bv

        if best_gml:
            used_gml_ids.add(best_gml["id"])
            results.append(
                make_result(i, pdf_bv, labels, best_gml, f"area ({best_delta * 100:.1f}% diff)")
            )
        else:
            results.append(
                make_result(
                    i,
                    pdf_bv,
                    labels,
                    None,
                    "area",
                    notes=f"No GML bouwvlak within {AREA_TOLERANCE * 100:.0f}% area tolerance",
                )
            )

        matched_pdf.add(i)

    results.sort(key=lambda r: r.pdf_index)
    return results


# ------------------------------------------------------------------
# Report
# ------------------------------------------------------------------


def print_report(results: list[MatchResult]):
    icon = {
        "agreement": "✓",
        "disagreement": "✗",
        "pdf_missing": "?",
        "unmatched": "-",
        "overlay_annotation": "○",
        "legend_swatch": "·",
    }

    print(f"\n{'=' * 84}")
    print("HEIGHT CROSS-VALIDATION: PDF extraction vs GML authoritative")
    print(f"{'=' * 84}\n")
    print(f"  {'#':>3}  {'labels':<32s}  {'pdf_h':>6}  {'gml_h':>6}  {'method':<22s}  status")
    print(f"  {'-' * 3}  {'-' * 32}  {'-' * 6}  {'-' * 6}  {'-' * 22}  {'-' * 14}")

    for r in results:
        labels = ", ".join(r.pdf_labels)[:30]
        ph = f"{r.pdf_height_m}m" if r.pdf_height_m is not None else "None"
        gh = f"{r.gml_height_m}m" if r.gml_height_m is not None else "n/a"
        ic = icon.get(r.agreement, " ")
        print(
            f"  {r.pdf_index:>3}  {labels:<32s}  {ph:>6}  {gh:>6}  "
            f"{r.match_method:<22s}  {ic} {r.agreement}"
        )
        if r.notes:
            print(f"       NOTE: {r.notes}")

    # Tally -- exclude overlays and swatches from the headline numbers
    real = [r for r in results if r.agreement not in ("overlay_annotation", "legend_swatch")]
    agreements = sum(1 for r in real if r.agreement == "agreement")
    disagreements = sum(1 for r in real if r.agreement == "disagreement")
    missing = sum(1 for r in real if r.agreement == "pdf_missing")
    unmatched = sum(1 for r in real if r.agreement == "unmatched")
    overlays = sum(1 for r in results if r.agreement == "overlay_annotation")

    print(f"\n  Agreements:          {agreements}")
    print(f"  Disagreements:       {disagreements}  <-- require PM review")
    print(f"  PDF missing height:  {missing}")
    print(f"  Unmatched:           {unmatched}")
    print(f"  Overlay annotations: {overlays}  (dove gevel zones, expected)")

    if disagreements:
        print("\nDISAGREEMENTS -- review before passing to Grasshopper:")
        for r in real:
            if r.agreement == "disagreement":
                print(
                    f"  [{r.pdf_index:02d}] labels={r.pdf_labels}  "
                    f"pdf={r.pdf_height_m}m  gml={r.gml_height_m}m  "
                    f"delta={r.delta_m}m"
                )


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main():
    candidates = [
        Path("data/outputs/draka_geometry.json"),
        Path("data/outputs/Drakaterrein-A2_2022-04-26_versie_2_kaveltekening_geometry.json"),
        Path("data/outputs/draka/geometry.json"),
    ]
    geo_path = next((p for p in candidates if p.exists()), None)
    if geo_path is None:
        print("geometry.json not found. Tried:")
        for c in candidates:
            print(f"  {c}")
        return

    print(f"Reading PDF extraction: {geo_path}")
    geo = json.loads(geo_path.read_text())
    pdf_bouwvlakken = geo.get("bouwvlakken", [])
    print(f"  {len(pdf_bouwvlakken)} bouwvlakken in PDF extraction")

    print(f"\nReading GML: {GML_CACHE}")
    raw = GML_CACHE.read_bytes()
    root = etree.fromstring(raw)
    IMRO, GML = get_ns(root)

    print("\nBuilding GML bouwvlak index...")
    gml_bv = build_gml_bouwvlakken(root, IMRO, GML)
    print(f"  {len(gml_bv)} bouwvlakken found")
    for bv in gml_bv:
        print(f"    {bv['id'][-24:]:<26s}  area={bv['area_m2']:8.0f}m2  h={bv['height_m']}")

    print("\nBuilding GML functieaanduiding index...")
    fa = build_gml_functieaanduidingen(root, IMRO, GML)
    print(f"  {len(fa)} functieaanduidingen found")
    attach_sgd_codes(gml_bv, fa)
    for bv in gml_bv:
        if bv["sgd_codes"]:
            print(f"    {bv['id'][-24:]:<26s}  sgd={bv['sgd_codes']}")

    print("\nMatching...")
    results = match_bouwvlakken(pdf_bouwvlakken, gml_bv)

    print_report(results)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            [
                {
                    "pdf_index": r.pdf_index,
                    "pdf_labels": r.pdf_labels,
                    "pdf_height_m": r.pdf_height_m,
                    "pdf_area_m2": r.pdf_area_m2,
                    "gml_id": r.gml_id,
                    "gml_height_m": r.gml_height_m,
                    "gml_area_m2": r.gml_area_m2,
                    "match_method": r.match_method,
                    "agreement": r.agreement,
                    "delta_m": r.delta_m,
                    "notes": r.notes,
                }
                for r in results
            ],
            indent=2,
        )
    )
    print(f"\nReport written to {OUTPUT}")


if __name__ == "__main__":
    main()
