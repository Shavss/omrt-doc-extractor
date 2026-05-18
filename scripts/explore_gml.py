"""
scripts/explore_gml.py

Quick exploration of the Draka bestemmingsplan GML file.
Extracts per-bouwvlak height limits (maatvoering) and prints them.

Usage:
    .venv/bin/python scripts/explore_gml.py
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import httpx
from lxml import etree

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.getenv("DSO_RP_API_KEY")
GML_URL = (
    "https://www.ruimtelijkeplannen.nl/historic/"
    "NL.IMRO.0363.N2102BPGST-VG01_2025.04.01_12.26.08/"
    "NL.IMRO.0363.N2102BPGST-VG01.gml"
)
GML_CACHE = Path("data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml")

# ---------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------

def fetch_gml() -> bytes:
    if GML_CACHE.exists():
        print(f"Using cached GML at {GML_CACHE}")
        return GML_CACHE.read_bytes()

    print(f"Fetching {GML_URL} ...")

    r = httpx.get(GML_URL, timeout=60, follow_redirects=True)
    if r.status_code == 200:
        print("Public access OK")
        GML_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GML_CACHE.write_bytes(r.content)
        return r.content

    print(f"Public access failed ({r.status_code}), trying with DSO API key...")
    r = httpx.get(
        GML_URL,
        headers={"X-Api-Key": API_KEY},
        timeout=60,
        follow_redirects=True,
    )
    if r.status_code == 200:
        print("Authenticated access OK")
        GML_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GML_CACHE.write_bytes(r.content)
        return r.content

    print(f"Both attempts failed. Last status: {r.status_code}")
    print(r.text[:300])
    sys.exit(1)

# ---------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------

def parse_gml(raw: bytes):
    root = etree.fromstring(raw)

    # ---- Detect namespaces ----
    print("\n=== NAMESPACES IN USE ===")
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.nsmap:
            for prefix, uri in el.nsmap.items():
                print(f"  {str(prefix):<15s} {uri}")
            break

    # ---- Top-level tag counts ----
    print("\n=== TOP-LEVEL ELEMENT TYPES (top 20) ===")
    tag_counts: dict[str, int] = {}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        local = etree.QName(el.tag).localname
        tag_counts[local] = tag_counts.get(local, 0) + 1
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {tag:<40s} {count}")

    # ---- Show first 3 featureMembers raw so we can see actual element names ----
    print("\n=== FIRST 3 FEATURE MEMBERS (raw) ===")
    count = 0
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if etree.QName(el.tag).localname == "featureMember":
            print(etree.tostring(el, pretty_print=True).decode()[:1200])
            print("---")
            count += 1
            if count >= 3:
                break

    # ---- Build namespace map dynamically from the document ----
    ns = {}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.nsmap:
            ns = dict(el.nsmap)
            break

    # Resolve None prefix (default namespace) to a usable key
    if None in ns:
        ns["imro"] = ns.pop(None)

    print(f"\nResolved namespace map: {ns}")

    # ---- All unique local names inside featureMembers ----
    print("\n=== UNIQUE ELEMENT NAMES INSIDE FEATURE MEMBERS ===")
    feature_tags: set[str] = set()
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if etree.QName(el.tag).localname == "featureMember":
            for child in el.iter():
                if not isinstance(child.tag, str):
                    continue
                feature_tags.add(etree.QName(child.tag).localname)
    for t in sorted(feature_tags):
        print(f"  {t}")

    # ---- Search for any element whose local name contains 'maatvoer' or 'bouwvlak' ----
    print("\n=== ELEMENTS MATCHING 'maatvoer' OR 'bouwvlak' (case-insensitive) ===")
    keywords = ["maatvoer", "bouwvlak", "hoogte", "maatvoering"]
    found_any = False
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        local = etree.QName(el.tag).localname.lower()
        if any(kw in local for kw in keywords):
            print(f"\n  TAG: {el.tag}")
            print(f"  ATTRIBS: {dict(el.attrib)}")
            print(f"  TEXT: {el.text!r}")
            print(etree.tostring(el, pretty_print=True).decode()[:600])
            found_any = True
    if not found_any:
        print("  None found -- height data may use different element names.")
        print("  Check the UNIQUE ELEMENT NAMES section above for clues.")

    # ---- Try to find omvang / waarde patterns regardless of namespace ----
    print("\n=== ALL 'waarde' ELEMENTS (likely contain numerical values) ===")
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if etree.QName(el.tag).localname == "waarde":
            parent_local = etree.QName(el.getparent().tag).localname if el.getparent() is not None else "?"
            grandparent = el.getparent().getparent() if el.getparent() is not None else None
            gp_local = etree.QName(grandparent.tag).localname if grandparent is not None else "?"
            print(f"  {gp_local} > {parent_local} > waarde = {el.text!r}")


if __name__ == "__main__":
    raw = fetch_gml()
    print(f"GML size: {len(raw):,} bytes")
    parse_gml(raw)