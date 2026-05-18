"""
scripts/extract_gml_heights.py

Extract all bouwhoogte maatvoeringen from the Draka GML and write
data/outputs/draka_gml_heights.json

Usage:
    .venv/bin/python scripts/extract_gml_heights.py
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import httpx
from lxml import etree

load_dotenv(Path(__file__).parent.parent / ".env")

GML_URL = (
    "https://www.ruimtelijkeplannen.nl/historic/"
    "NL.IMRO.0363.N2102BPGST-VG01_2025.04.01_12.26.08/"
    "NL.IMRO.0363.N2102BPGST-VG01.gml"
)
GML_CACHE  = Path("data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml")
OUTPUT     = Path("data/outputs/draka_gml_heights.json")

def fetch_gml() -> bytes:
    if GML_CACHE.exists():
        return GML_CACHE.read_bytes()
    r = httpx.get(GML_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    GML_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GML_CACHE.write_bytes(r.content)
    return r.content

def extract_heights(raw: bytes) -> list[dict]:
    root = etree.fromstring(raw)

    # Detect namespace dynamically -- handles 1.0 and 1.1
    ns_uri = None
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.nsmap:
            ns_uri = el.nsmap.get(None) or next(iter(el.nsmap.values()))
            break

    IMRO = f"{{{ns_uri}}}"
    results = []

    for el in root.iter(f"{IMRO}Maatvoering"):
        gml_id  = el.get("{http://www.opengis.net/gml/3.2}id", "")
        naam_el = el.find(f"{IMRO}naam")
        naam    = naam_el.text.strip() if naam_el is not None else ""

        # Get position (centroid label point)
        pos_el  = el.find(f".//{{{' http://www.opengis.net/gml/3.2'}}}pos")
        coords  = pos_el.text.strip().split() if pos_el is not None else []

        for wet in el.findall(f".//{IMRO}WaardeEnType"):
            waarde_el    = wet.find(f"{IMRO}waarde")
            type_el      = wet.find(f"{IMRO}waardeType")

            if waarde_el is None:
                continue

            raw_val = waarde_el.text.strip().replace(",", ".")
            try:
                value = float(raw_val)
            except ValueError:
                value = None

            results.append({
                "id":         gml_id,
                "naam":       naam,
                "waarde_m":   value,
                "waarde_type": type_el.text.strip() if type_el is not None else "",
                "coords_rd":  [float(c) for c in coords] if len(coords) == 2 else [],
            })

    return results

def summarise(heights: list[dict]) -> dict:
    bouwhoogtes = [
        h["waarde_m"] for h in heights
        if h["waarde_m"] is not None
        and "bouwhoogte" in h["waarde_type"].lower()
    ]
    from collections import Counter
    distribution = dict(sorted(Counter(bouwhoogtes).items()))
    return {
        "plan_id":      "NL.IMRO.0363.N2102BPGST-VG01",
        "source":       "GML via ruimtelijkeplannen.nl",
        "total_maatvoeringen": len(heights),
        "bouwhoogte_distribution_m": distribution,
        "max_bouwhoogte_m": max(bouwhoogtes) if bouwhoogtes else None,
        "min_bouwhoogte_m": min(bouwhoogtes) if bouwhoogtes else None,
        "detail": heights,
    }

if __name__ == "__main__":
    raw     = fetch_gml()
    heights = extract_heights(raw)
    report  = summarise(heights)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2))

    print(f"Maatvoeringen found: {report['total_maatvoeringen']}")
    print(f"Height distribution: {report['bouwhoogte_distribution_m']}")
    print(f"Range: {report['min_bouwhoogte_m']}m to {report['max_bouwhoogte_m']}m")
    print(f"Written to {OUTPUT}")

    # Add this to explore_gml.py temporarily and run it
print("\n=== FIRST 2 BOUWVLAKKEN FULL CONTENT ===")
root = etree.fromstring(raw)

ns_uri = None
for el in root.iter():
    if not isinstance(el.tag, str):
        continue
    if el.nsmap:
        ns_uri = el.nsmap.get(None) or next(iter(el.nsmap.values()))
        break

IMRO = f"{{{ns_uri}}}"
count = 0
for el in root.iter(f"{IMRO}Bouwvlak"):
    print(etree.tostring(el, pretty_print=True).decode())
    print("---")
    count += 1
    if count >= 2:
        break