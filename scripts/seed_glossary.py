"""Seed data/archive/glossary.json from the Stelselcatalogus.

The Stelselcatalogus is the official Dutch national catalog of begrippen
(terms) for omgevingsdocumenten. Each begrip has a formele definitie
(formal definition), an uitleg in klare taal (plain-language explanation),
a bron (source), and gerelateerde begrippen (related concepts).

This script populates `data/archive/glossary.json` with the terms most
relevant to bestemmingsplan and omgevingsplan extraction. The LLM in
`extract.py` consults the glossary when interpreting Dutch planning
vocabulary on a page, especially for terms that vary across municipalities
(plint, peil, dove gevel, bouwlaag, and others).

Usage:
    python scripts/seed_glossary.py

If the environment variable STELSELCATALOGUS_API_KEY is set, the script
pulls live data from the API. If not, it writes a hand-curated fallback
glossary with the most common bestemmingsplan terminology so the pipeline
can still benefit from glossary grounding without API access.

Getting an API key:
- Register at https://aandeslagmetdeomgevingswet.nl/ontwikkelaarsportaal/
- The same key works for all DSO/Catalogus APIs.

API documentation:
- OpenAPI spec: https://stelselcatalogus.omgevingswet.overheid.nl/api/
- Endpoints: /begrippen, /activiteiten, /werkzaamheden, /begrippenkaders
- Auth: API-Key header on every request.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

# Make schemas importable regardless of how the script is invoked.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omrt_extractor.schemas import GlossaryTerm

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

STELSELCATALOGUS_BASE = "https://stelselcatalogus.omgevingswet.overheid.nl/api/v3"
PAGE_SIZE = 50
REQUEST_TIMEOUT = 30.0

# Terms we prioritise pulling from the catalog because they appear in
# bestemmingsplan regels and toelichtingen and tend to have municipality-
# specific resolutions. The full catalog is too large to mirror; this
# focused subset is what extraction actually needs.
PRIORITY_TERMS = [
    "bouwvlak",
    "bouwhoogte",
    "bouwaanduiding",
    "bouwlaag",
    "bestemming",
    "dubbelbestemming",
    "functieaanduiding",
    "peil",
    "plint",
    "dove gevel",
    "geluidzone",
    "vrijwaringszone",
    "maatschappelijke voorziening",
    "bedrijfswoning",
    "vloeroppervlakte",
    "bvo",
    "fsi",
    "bruto vloeroppervlakte",
    "kavelpaspoort",
    "voorgevelrooilijn",
    "achtergevelrooilijn",
    "kapconstructie",
    "nokhoogte",
    "goothoogte",
    "vlonder",
]

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "archive" / "glossary.json"

# ---------------------------------------------------------------------
# Fallback: hand-curated common terms
# Used when no API key is available. Definitions are paraphrased from
# common bestemmingsplan vocabulary; production should always use the
# authoritative source.
# ---------------------------------------------------------------------

FALLBACK_TERMS: list[dict[str, Any]] = [
    {
        "term": "bouwvlak",
        "definition": ("Een geometrisch bepaald vlak waarbinnen gebouwen mogen worden opgericht."),
        "definition_en": ("A geometrically defined area within which buildings may be erected."),
    },
    {
        "term": "bouwhoogte",
        "definition": (
            "De maximale hoogte van een bouwwerk, gemeten vanaf het peil tot het "
            "hoogste punt van het bouwwerk."
        ),
        "definition_en": (
            "Maximum height of a building, measured from grade level to the highest "
            "point of the structure."
        ),
    },
    {
        "term": "peil",
        "definition": (
            "Het niveau dat als referentiepunt geldt voor hoogtematen, doorgaans de "
            "hoogte van de aangrenzende openbare ruimte ter plaatse van de hoofdtoegang."
        ),
        "definition_en": (
            "Reference level for height measurements, typically the elevation of the "
            "adjacent public space at the main entrance."
        ),
    },
    {
        "term": "plint",
        "definition": (
            "De onderste bouwlaag van een gebouw, gelegen direct boven peil. "
            "In stedelijke contexten vaak bedoeld voor publieksgerichte functies."
        ),
        "definition_en": (
            "The ground floor of a building, directly above grade level. In urban "
            "contexts often intended for public-facing functions."
        ),
    },
    {
        "term": "dove gevel",
        "definition": (
            "Een gevel zonder te openen delen, waardoor geluidsbelasting op die "
            "gevel buiten beschouwing kan blijven bij de toetsing aan de Wet "
            "geluidhinder."
        ),
        "definition_en": (
            "A facade without operable openings, so that noise exposure on that "
            "facade can be disregarded when testing against the Noise Nuisance Act."
        ),
    },
    {
        "term": "bouwlaag",
        "definition": (
            "Een doorlopend gedeelte van een gebouw, begrensd door op gelijke of "
            "nagenoeg gelijke hoogte liggende vloeren."
        ),
        "definition_en": (
            "A continuous part of a building, bounded by floors at equal or nearly equal heights."
        ),
    },
    {
        "term": "bvo",
        "definition": (
            "Bruto vloeroppervlakte. De totale oppervlakte van alle bouwlagen, "
            "gemeten op vloerniveau langs de buitenomtrek van de gevels."
        ),
        "definition_en": (
            "Gross floor area. Total area of all floors, measured at floor level "
            "along the outer perimeter of the facades."
        ),
    },
    {
        "term": "fsi",
        "definition": (
            "Floor Space Index. Verhouding tussen de totale bruto vloeroppervlakte "
            "en het kaveloppervlak. Bepaalt de bebouwingsdichtheid van een kavel."
        ),
        "definition_en": ("Ratio of total gross floor area to plot area. Determines plot density."),
    },
    {
        "term": "dubbelbestemming",
        "definition": (
            "Een bestemming die over een andere (enkel)bestemming heen ligt en "
            "aanvullende beperkingen of voorschriften aan dat gebied toevoegt."
        ),
        "definition_en": (
            "A zoning that overlays another (single) zoning and adds further "
            "restrictions or requirements to that area."
        ),
    },
    {
        "term": "functieaanduiding",
        "definition": (
            "Een aanduiding op de verbeelding die binnen een bestemming nadere "
            "regels over toegestaan gebruik specificeert."
        ),
        "definition_en": (
            "A label on the verbeelding that, within a zoning category, specifies "
            "further rules about permitted use."
        ),
    },
    {
        "term": "bouwaanduiding",
        "definition": (
            "Een aanduiding op de verbeelding die nadere regels stelt aan de "
            "bouwwijze of de toelaatbare bouwwerken binnen een bestemming."
        ),
        "definition_en": (
            "A label on the verbeelding that imposes further rules on building "
            "method or permitted structures within a zoning category."
        ),
    },
    {
        "term": "geluidzone",
        "definition": (
            "Een gebied rondom een geluidsbron waarbinnen aanvullende regels "
            "gelden ten aanzien van geluidsbelasting en toegestane functies."
        ),
        "definition_en": (
            "Area surrounding a noise source within which additional rules apply "
            "regarding noise exposure and permitted functions."
        ),
    },
    {
        "term": "maatschappelijke voorziening",
        "definition": (
            "Een voorziening voor maatschappelijke functies zoals onderwijs, "
            "gezondheidszorg, religie, sport, cultuur of overheidsdienstverlening."
        ),
        "definition_en": (
            "Facility for public-good functions such as education, healthcare, "
            "religion, sports, culture, or government services."
        ),
    },
    {
        "term": "voorgevelrooilijn",
        "definition": (
            "De denkbeeldige lijn die langs de voorzijde van een bouwperceel loopt "
            "en waaraan de voorgevel van een gebouw moet worden gebouwd of niet "
            "voorbij mag worden gebouwd."
        ),
        "definition_en": (
            "Imaginary line along the front of a building plot, to which a "
            "building's front facade must be built or which it must not exceed."
        ),
    },
    {
        "term": "nokhoogte",
        "definition": (
            "De maximale hoogte van een schuin dak, gemeten vanaf peil tot het "
            "hoogste punt van het dak (de nok)."
        ),
        "definition_en": ("Maximum height of a pitched roof, measured from grade to the ridge."),
    },
    {
        "term": "goothoogte",
        "definition": (
            "De hoogte van een bouwwerk, gemeten vanaf peil tot bovenkant goot, "
            "boeibord of daarmee gelijk te stellen constructiedeel."
        ),
        "definition_en": (
            "Building height measured from grade to the top of the gutter, fascia, "
            "or equivalent structural element."
        ),
    },
]


# ---------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------


def fetch_term_from_api(client: httpx.Client, term: str) -> GlossaryTerm | None:
    """Look up a single term in the Stelselcatalogus.

    Returns None on any failure (404, 5xx, network error). Failures are
    logged but never raised; we want the script to complete even if some
    terms are missing from the catalog.
    """
    try:
        response = client.get(
            "/begrippen",
            params={"naam": term, "pageSize": 1},
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning(f"API lookup failed for '{term}': {e}")
        return None

    payload = response.json()
    items = payload.get("_embedded", {}).get("begrippen", [])
    if not items:
        logger.info(f"No catalog entry found for '{term}'")
        return None

    item = items[0]
    return GlossaryTerm(
        term=term,
        definition=item.get("definitie", "").strip() or "(no definition supplied)",
        source="stelselcatalogus",
        source_url=item.get("uri"),
        notes=item.get("uitleg"),
    )


def seed_from_api(api_key: str) -> list[GlossaryTerm]:
    """Pull priority terms from the Stelselcatalogus."""
    logger.info(f"Seeding glossary from Stelselcatalogus for {len(PRIORITY_TERMS)} terms")
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    terms: list[GlossaryTerm] = []
    with httpx.Client(
        base_url=STELSELCATALOGUS_BASE,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    ) as client:
        for term in PRIORITY_TERMS:
            result = fetch_term_from_api(client, term)
            if result is not None:
                terms.append(result)
    logger.info(f"Successfully fetched {len(terms)} of {len(PRIORITY_TERMS)} terms")
    return terms


def seed_from_fallback() -> list[GlossaryTerm]:
    """Use the hand-curated fallback when no API key is available."""
    logger.warning(
        "No STELSELCATALOGUS_API_KEY set; falling back to hand-curated terms. "
        "For authoritative definitions, register at "
        "https://aandeslagmetdeomgevingswet.nl/ontwikkelaarsportaal/ "
        "and set the env var."
    )
    return [
        GlossaryTerm(
            term=entry["term"],
            definition=entry["definition"],
            definition_en=entry.get("definition_en"),
            source="human_curated",
            notes=(
                "Fallback definition used because no API key was set. "
                "Replace with authoritative Stelselcatalogus content when available."
            ),
        )
        for entry in FALLBACK_TERMS
    ]


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def write_glossary(terms: list[GlossaryTerm]) -> None:
    """Write the glossary to disk, sorted by term for stable diffs."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sorted_terms = sorted(terms, key=lambda t: t.term)
    payload = {
        "version": 1,
        "source": "stelselcatalogus"
        if any(t.source == "stelselcatalogus" for t in terms)
        else "human_curated_fallback",
        "term_count": len(sorted_terms),
        "terms": [t.model_dump(mode="json") for t in sorted_terms],
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.success(f"Wrote {len(sorted_terms)} terms to {OUTPUT_PATH}")


def main() -> None:
    api_key = os.environ.get("STELSELCATALOGUS_API_KEY")
    if api_key:
        terms = seed_from_api(api_key)
        # Always backfill any missing priority terms from the fallback.
        seen = {t.term for t in terms}
        terms.extend(t for t in seed_from_fallback() if t.term not in seen)
    else:
        terms = seed_from_fallback()
    write_glossary(terms)


if __name__ == "__main__":
    main()
