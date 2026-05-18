import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import os, httpx, json
from collections import deque

API_KEY = os.getenv("DSO_RP_API_KEY")
BASE = "https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4"
PLAN_ID = "NL.IMRO.0363.N2102BPGST-VG01"
headers = {"X-Api-Key": API_KEY, "Accept": "application/hal+json"}

def fetch(url):
    r = httpx.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def walk_teksten(start_url, max_nodes=60):
    """BFS walk of the teksten tree, collect all nodes with inhoud."""
    visited = set()
    queue = deque([start_url])
    results = []

    while queue and len(visited) < max_nodes:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        node = fetch(url)
        titel = node.get("titel", "")
        inhoud = node.get("inhoud")  # XHTML string when present

        if inhoud:
            results.append({
                "id": node.get("id"),
                "titel": titel,
                "inhoud": inhoud[:600]  # trim for readability
            })
        else:
            # No content yet -- print the node title so we can see the tree
            print(f"  [container] {node.get('id')} | {titel}")

        # Queue children
        children = node.get("_links", {}).get("children", [])
        for child in children:
            href = child.get("href")
            if href and href not in visited:
                queue.append(href)

    return results

REGELS_URL = f"{BASE}/plannen/{PLAN_ID}/teksten/NL.IMRO.PT.s206"
print("Walking regels tree...\n")
nodes_with_content = walk_teksten(REGELS_URL)

print(f"\n=== FOUND {len(nodes_with_content)} NODES WITH CONTENT ===")
for n in nodes_with_content:
    print(f"\n--- {n['id']} | {n['titel']} ---")
    print(n["inhoud"])
    print()

# Fetch artikel 3 Gemengd and walk its children
ARTIKEL_3_URL = "https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4/plannen/NL.IMRO.0363.N2102BPGST-VG01/teksten/NL.IMRO.PT.s337"

print("=== ARTIKEL 3 GEMENGD (full tree) ===\n")
nodes = walk_teksten(ARTIKEL_3_URL, max_nodes=80)

for n in nodes:
    print(f"\n--- {n['id']} | {n['titel']} ---")
    # Strip XHTML tags for readability
    import re
    clean = re.sub(r'<[^>]+>', '', n['inhoud'])
    print(clean[:800])

import re

nodes_to_fetch = [
    ("3.2.2 Gebouwen",          "NL.IMRO.PT.s711"),
    ("3.2.3 Bouwwerken",        "NL.IMRO.PT.s712"),
    ("3.3.9 Totale bvo",        "NL.IMRO.PT.s1102"),
    ("3.4.1 Voorwaardelijk",    "NL.IMRO.PT.s1252"),
    ("3.4.2 Woningen sgd-2",    "NL.IMRO.PT.s1253"),
    ("3.4.3 Woningen sgd-3",    "NL.IMRO.PT.s1254"),
    ("3.4.4 Woningen sgd-4",    "NL.IMRO.PT.s1255"),
    ("3.4.5 Woningen sgd-6",    "NL.IMRO.PT.s1256"),
]

BASE = "https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4"
PLAN_ID = "NL.IMRO.0363.N2102BPGST-VG01"

for label, tekst_id in nodes_to_fetch:
    url = f"{BASE}/plannen/{PLAN_ID}/teksten/{tekst_id}"
    r = httpx.get(url, headers=headers, timeout=15)
    data = r.json()
    inhoud = data.get("inhoud", "") or ""
    clean = re.sub(r'<[^>]+>', ' ', inhoud).strip()
    clean = re.sub(r'\s+', ' ', clean)
    print(f"\n=== {label} ({tekst_id}) ===")
    print(clean)