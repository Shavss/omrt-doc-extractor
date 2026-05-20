"""Programme inference: synthesise a ProgrammeProposal from Extraction + GeoContext.

Uses claude-opus-4-7 because this is the judgment-heavy step. Prompt at
prompts/programme.md. Produces target unit mix, GFA split, parking demand,
and a reasoning trace where every programme decision cites its evidence
(constraint ID, BAG/CBS/OSM data point, or explicit designer judgment).

Primary function:
    infer_programme(extraction, geo_context, cross_validation_flags) -> ProgrammeProposal

Hard rules from prompts/programme.md:
- Never invent unsupported numbers. Mark fields requires_designer_input=true
  when evidence is missing.
- Prefer ranges over false precision.
- Mark assumptions vs extracted facts in the reasoning trace.
- Respect cross-validation flags. Programme numbers depending on
  imro_api_disagreement values must flag the dependency.
- Confidence cannot exceed 0.7 if most decisions rest on designer judgment.

Stage 5 of the build plan.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from omrt_extractor.schemas import (
    Confidence,
    GeoContext,
    ParametricFramework,
    ProgrammeProposal,
    Provenance,
    ReasoningStep,
    SourceType,
    UnitTypeTarget,
    UseSplit,
)

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers: summarise inputs for the LLM
# ---------------------------------------------------------------------------


def _summarise_constraints(framework: ParametricFramework) -> str:
    """Build a concise summary of constraints for the inference prompt."""
    lines: list[str] = []

    if framework.constraints.numerical:
        lines.append("## Numerical Constraints")
        for c in framework.constraints.numerical:
            cv_note = ""
            if c.cross_validation:
                if c.cross_validation.agreement == "disagreement":
                    cv_note = (
                        f" [IMRO DISAGREES: authoritative={c.cross_validation.authoritative_value}"
                        f" {c.cross_validation.authoritative_unit or c.unit}]"
                    )
                elif c.cross_validation.agreement == "agreement":
                    cv_note = " [IMRO confirmed]"
            value_str = f"{c.value[0]}–{c.value[1]}" if isinstance(c.value, tuple) else str(c.value)
            condition_str = f" (condition: {c.condition})" if c.condition else ""
            applies_str = f" [applies_to: {', '.join(c.applies_to)}]" if c.applies_to else ""
            prov_str = ""
            if c.provenance.source_type == SourceType.DOCUMENT:
                prov_str = f" — {c.provenance.document} p.{c.provenance.page}"
                if c.provenance.quoted_text:
                    prov_str += f': "{c.provenance.quoted_text[:120]}"'
            lines.append(
                f"- [{c.id}] {c.name}: {value_str} {c.unit}{condition_str}"
                f"{applies_str} (conf={c.confidence.score:.2f}){cv_note}{prov_str}"
            )

    toelichting_passages = [
        c
        for c in framework.constraints.narrative
        if c.provenance.source_type == SourceType.DOCUMENT
        and c.provenance.document
        and "toelichting" in c.provenance.document.lower()
    ]
    if toelichting_passages:
        lines.append("\n## Urban Design Intentions (toelichting)")
        for nc in toelichting_passages[:8]:
            prov = f"{nc.provenance.document} p.{nc.provenance.page}"
            lines.append(f"- [{nc.id}] {nc.statement} (source: {prov})")

    all_narrative = [nc for nc in framework.constraints.narrative if nc not in toelichting_passages]
    if all_narrative:
        lines.append("\n## Other Narrative Constraints")
        for nc in all_narrative[:6]:
            lines.append(f"- [{nc.id}] {nc.statement}")

    return "\n".join(lines)


def _summarise_geo_context(geo: GeoContext | None) -> str:
    """Build a concise geo-context summary for the inference prompt."""
    if geo is None:
        return "No geo context available."

    lines: list[str] = []

    if geo.nearby_buildings:
        nb = geo.nearby_buildings
        lines.append(f"## Nearby Buildings (PDOK BAG, {nb.radius_m}m radius)")
        lines.append(f"- Count: {nb.count}")
        if nb.dominant_uses:
            lines.append(f"- Dominant uses: {', '.join(nb.dominant_uses)}")
        if nb.typical_heights_m:
            lines.append(
                f"- Typical heights: {nb.typical_heights_m[0]}–{nb.typical_heights_m[1]} m"
            )
        if nb.typical_year_built:
            lines.append(
                f"- Typical year built: {nb.typical_year_built[0]}–{nb.typical_year_built[1]}"
            )
        lines.append(f"- 3D BAG data available: {nb.has_3d_bag_data}")

    if geo.demographics:
        d = geo.demographics
        lines.append(f"\n## Neighbourhood Demographics (CBS, buurt {d.buurt_code})")
        if d.population is not None:
            lines.append(f"- Population: {d.population}")
        if d.household_count is not None:
            lines.append(f"- Households: {d.household_count}")
        if d.average_household_size is not None:
            lines.append(f"- Avg household size: {d.average_household_size}")
        if d.median_age is not None:
            lines.append(f"- Median age: {d.median_age}")

    if geo.transit:
        t = geo.transit
        lines.append("\n## Transit Access (OSM)")
        if t.nearest_tram_m is not None:
            lines.append(f"- Nearest tram: {t.nearest_tram_m:.0f} m")
        if t.nearest_metro_m is not None:
            lines.append(f"- Nearest metro: {t.nearest_metro_m:.0f} m")
        if t.nearest_train_m is not None:
            lines.append(f"- Nearest train: {t.nearest_train_m:.0f} m")
        if t.nearest_bus_m is not None:
            lines.append(f"- Nearest bus: {t.nearest_bus_m:.0f} m")

    if geo.nearby_amenities:
        top_amenities = sorted(geo.nearby_amenities.items(), key=lambda x: -x[1])[:8]
        lines.append(
            "\n## Nearby Amenities (OSM): " + ", ".join(f"{k}: {v}" for k, v in top_amenities)
        )

    if geo.data_sources_failed:
        lines.append(f"\n## Failed data sources: {', '.join(geo.data_sources_failed)}")
        if "pdok_3d_bag" in geo.data_sources_failed:
            lines.append(
                "  **3D BAG returned HTTP 400 — no 3D height context available.** "
                "Urban height context must be inferred from 2D BAG and document constraints only. "
                "Do NOT invent building heights from 3D data."
            )

    if geo.data_sources_used:
        lines.append(f"\n## Successful data sources: {', '.join(geo.data_sources_used)}")

    return "\n".join(lines) if lines else "Geo context present but empty."


def _summarise_objective(framework: ParametricFramework) -> str:
    lines = [
        f"Objective: {framework.objective.statement}",
        f"Urban intent: {framework.objective.urban_intent}",
    ]
    if framework.objective.provenance.document:
        lines.append(
            f"Source: {framework.objective.provenance.document} "
            f"p.{framework.objective.provenance.page}"
        )
    return "\n".join(lines)


def _has_imro_disagreements(framework: ParametricFramework) -> list[str]:
    """Return IDs of constraints where IMRO API disagreed."""
    return [
        c.id
        for c in framework.constraints.numerical
        if c.cross_validation and c.cross_validation.agreement == "disagreement"
    ]


# ---------------------------------------------------------------------------
# LLM call via Anthropic SDK
# ---------------------------------------------------------------------------

_SCHEMA_SKELETON = """
EXACT JSON SCHEMA — return ONLY fields listed here, no extras:

{
  "target_total_gfa_m2": <float>,
  "target_total_gfa_m2_range": {"min": <float>, "max": <float>},
  "use_split": {
    "residential_m2": <float>,
    "productive_m2": <float>,
    "office_m2": <float>,
    "retail_horeca_m2": <float>,
    "cultural_m2": <float>,
    "social_m2": <float>,
    "other_m2": <float>,
    "rationale": "<string>",
    "provenance": {"source_type": "inferred", "inferred_from": ["<id>", ...], "timestamp": "<iso8601>"},
    "confidence": {"score": <0-1>, "reasons": ["<string>"], "flags": []}
  },
  "unit_mix": [
    {
      "tenure": "<sociale_huur|middenhuur|vrije_sector_huur|koop|other>",
      "typology": "<studio|1br|2br|3br|mixed>",
      "size_band": "<under_30m2|30_60m2|60_90m2|over_90m2|mixed>",
      "fraction_of_total_dwellings": <0-1>,
      "target_count_range": {"min": <int>, "max": <int>},
      "target_size_m2_range": {"min": <float>, "max": <float>},
      "rationale": "<string>",
      "provenance": {"source_type": "inferred", "inferred_from": ["<id>", ...], "timestamp": "<iso8601>"},
      "confidence": {"score": <0-1>, "reasons": ["<string>"], "flags": []}
    }
  ],
  "target_dwelling_count": <int or null>,
  "total_dwelling_count_range": {"min": <int>, "max": <int>},
  "parking_demand": <float or null>,
  "reasoning_trace": [
    {"step": <int>, "decision": "<string>", "evidence": "<string>", "confidence_in_step": <0-1>},
    ...
  ],
  "provenance": {"source_type": "inferred", "inferred_from": ["<id>", ...], "timestamp": "<iso8601>"},
  "confidence": {"score": <0-1>, "reasons": ["<string>"], "flags": []}
}

CRITICAL FIELD RULES:
- use_split fields are absolute m2 values (NOT percentages). Sum must equal target_total_gfa_m2.
- unit_mix tenure must be exactly one of: sociale_huur, middenhuur, vrije_sector_huur, koop, other
- unit_mix typology must be exactly one of: studio, 1br, 2br, 3br, mixed
- unit_mix size_band must be exactly one of: under_30m2, 30_60m2, 60_90m2, over_90m2, mixed
- Each unit_mix entry is ONE tenure × ONE typology combination. Split across multiple entries.
  Example: sociale_huur studio + sociale_huur 1br + middenhuur 1br + middenhuur 2br + vrije_sector_huur 2br
- fraction_of_total_dwellings is a decimal 0-1, ALL unit_mix entries must sum to 1.0
- target_count_range gives estimated min/max dwelling count for that specific tenure×typology slice
- target_size_m2_range gives typical unit floor area range in m² for that slice
- parking_demand is a single float (estimated total spaces)
- reasoning_trace is a list of objects with step, decision, evidence, confidence_in_step
- Do NOT add any field not shown above
"""


def _build_inference_prompt(
    framework: ParametricFramework,
    geo_context: GeoContext | None,
) -> str:
    """Assemble the full prompt for the programme inference call."""
    system_prompt = _load_prompt("programme.md")

    constraints_summary = _summarise_constraints(framework)
    geo_summary = _summarise_geo_context(geo_context)
    objective_summary = _summarise_objective(framework)
    imro_disagreements = _has_imro_disagreements(framework)

    project_name = framework.metadata.project_name
    municipality = framework.metadata.location.municipality

    disagreement_note = ""
    if imro_disagreements:
        disagreement_note = (
            f"\n\n**WARNING**: The following constraint IDs have IMRO API disagreements "
            f"and must not be used as reliable inputs for programme numbers without flagging: "
            f"{', '.join(imro_disagreements)}"
        )

    user_message = f"""You are inferring the developer programme for: **{project_name}** in {municipality}.

{objective_summary}

{constraints_summary}

{geo_summary}{disagreement_note}

{_SCHEMA_SKELETON}

Now produce a ProgrammeProposal JSON object following the schema above EXACTLY.
Remember:
1. Every UnitTypeTarget, UseSplit, and the overall ProgrammeProposal must have
   provenance with source_type="inferred" and inferred_from listing the constraint IDs
   or geo data points that drove each decision.
2. The reasoning_trace list must contain 4–8 PLAIN STRINGS. Each string cites either:
   - A constraint ID in brackets, e.g. [max_height_sba2]
   - A geo data point, e.g. [pdok_bag: 145 residential buildings within 500m]
   - "designer judgment: <explicit rationale>"
3. At least one reasoning step must cite a toelichting passage by constraint ID.
4. At least one reasoning step must cite a BAG or CBS data point.
5. If 3D BAG data is unavailable (as noted above), acknowledge this explicitly
   in a reasoning step and rely on 2D BAG heights and document constraints instead.
6. Prefer value ranges for dwelling count. Use target_dwelling_count=null if
   evidence is insufficient to estimate.
7. Unit mix fractions must sum to 1.0.
8. Set confidence.score <= 0.7 if more than half the decisions rest on designer judgment.

Return ONLY valid JSON matching the schema above. No markdown fences, no commentary.
"""
    return system_prompt + "\n\n---\n\n" + user_message


def _call_llm_for_programme(prompt: str) -> dict[str, Any]:
    """Call claude-opus-4-7 via the Anthropic SDK and return the parsed JSON."""
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "anthropic package is required for programme inference. "
            "Install with: uv pip install anthropic"
        ) from exc

    from omrt_extractor.config import settings

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    logger.info("Calling claude-opus-4-7 for programme inference...")
    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    first_block = message.content[0]
    raw_text = first_block.text.strip() if hasattr(first_block, "text") else ""

    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        raw_text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()

    try:
        return dict(json.loads(raw_text))
    except json.JSONDecodeError as exc:
        logger.error(f"LLM returned non-JSON response: {raw_text[:500]}")
        raise ValueError(f"LLM did not return valid JSON for programme inference: {exc}") from exc


# ---------------------------------------------------------------------------
# Fallback: construct a minimal ProgrammeProposal when LLM is unavailable
# ---------------------------------------------------------------------------


def _fallback_programme(
    framework: ParametricFramework,
    geo_context: GeoContext | None,
    reason: str,
) -> ProgrammeProposal:
    """Return a minimal ProgrammeProposal populated from hard constraints only.

    Used when the Anthropic API is unavailable or returns an unusable response.
    All values are marked as designer judgment with low confidence so the viewer
    surfaces them as needing human input.
    """
    logger.warning(f"Using fallback programme inference: {reason}")

    bvo_constraints = [
        c for c in framework.constraints.numerical if c.category in ("bvo_limit", "fsi_far")
    ]

    # Prefer site-total constraints over sub-category caps
    total_bvo = [
        c
        for c in bvo_constraints
        if any(k in c.id.lower() for k in ("total", "draka", "plangebied", "totaal"))
    ]
    if total_bvo:
        bvo_constraints = total_bvo
    elif bvo_constraints:
        # Fall back to the largest value to avoid picking up tiny subcategory caps
        bvo_constraints = [
            max(
                bvo_constraints,
                key=lambda c: c.value[1] if isinstance(c.value, tuple) else c.value,
            )
        ]

    height_constraints = [c for c in framework.constraints.numerical if c.category == "height"]

    if bvo_constraints:
        first_bvo = bvo_constraints[0]
        total_gfa = (
            float(first_bvo.value[1])
            if isinstance(first_bvo.value, tuple)
            else float(first_bvo.value)
        )
        gfa_rationale = f"[{first_bvo.id}] BVO limit used as GFA proxy"
    else:
        total_gfa = 0.0
        gfa_rationale = (
            "designer judgment: no BVO constraint found — value set to 0, requires designer input"
        )

    inferred_from = (
        [c.id for c in bvo_constraints[:2]] + [c.id for c in height_constraints[:2]]
    ) or ["objective"]

    inferred_prov = Provenance(
        source_type=SourceType.INFERRED,
        inferred_from=inferred_from,
    )

    low_conf = Confidence(
        score=0.2,
        reasons=["Fallback — unverified assumption"],
        flags=["requires_designer_input"],
    )

    return ProgrammeProposal(
        target_total_gfa_m2=max(total_gfa, 1.0),
        target_total_gfa_m2_range=None,
        use_split=UseSplit(
            residential_m2=max(total_gfa * 0.7, 1.0),
            productive_m2=total_gfa * 0.15,
            office_m2=0.0,
            retail_horeca_m2=total_gfa * 0.1,
            cultural_m2=0.0,
            social_m2=total_gfa * 0.05,
            other_m2=0.0,
            normalised_from_pct=False,
            rationale=("designer judgment: fallback 70/15/10/5 split — requires designer input"),
            provenance=inferred_prov,
            confidence=Confidence(
                score=0.2,
                reasons=["Fallback due to LLM unavailability — all values need review"],
                flags=["requires_designer_input"],
            ),
        ),
        unit_mix=[
            UnitTypeTarget(
                tenure="sociale_huur",
                typology="1br",
                size_band="30_60m2",
                fraction_of_total_dwellings=0.3,
                target_count_range=None,
                target_size_m2_range=None,
                rationale=(
                    "designer judgment: Amsterdam 30/40/30 transformation target "
                    "— requires verification"
                ),
                provenance=inferred_prov,
                confidence=low_conf,
            ),
            UnitTypeTarget(
                tenure="middenhuur",
                typology="1br",
                size_band="30_60m2",
                fraction_of_total_dwellings=0.2,
                target_count_range=None,
                target_size_m2_range=None,
                rationale=(
                    "designer judgment: Amsterdam 30/40/30 transformation target "
                    "— requires verification"
                ),
                provenance=inferred_prov,
                confidence=low_conf,
            ),
            UnitTypeTarget(
                tenure="middenhuur",
                typology="2br",
                size_band="60_90m2",
                fraction_of_total_dwellings=0.2,
                target_count_range=None,
                target_size_m2_range=None,
                rationale=(
                    "designer judgment: Amsterdam 30/40/30 transformation target "
                    "— requires verification"
                ),
                provenance=inferred_prov,
                confidence=low_conf,
            ),
            UnitTypeTarget(
                tenure="vrije_sector_huur",
                typology="2br",
                size_band="60_90m2",
                fraction_of_total_dwellings=0.2,
                target_count_range=None,
                target_size_m2_range=None,
                rationale=(
                    "designer judgment: Amsterdam 30/40/30 transformation target "
                    "— requires verification"
                ),
                provenance=inferred_prov,
                confidence=low_conf,
            ),
            UnitTypeTarget(
                tenure="vrije_sector_huur",
                typology="3br",
                size_band="over_90m2",
                fraction_of_total_dwellings=0.1,
                target_count_range=None,
                target_size_m2_range=None,
                rationale=(
                    "designer judgment: Amsterdam 30/40/30 transformation target "
                    "— requires verification"
                ),
                provenance=inferred_prov,
                confidence=low_conf,
            ),
        ],
        target_dwelling_count=None,
        total_dwelling_count_range=None,
        parking_demand=None,
        reasoning_trace=[
            ReasoningStep(
                step=1,
                decision=f"FALLBACK MODE ({reason}): LLM inference was not available.",
                evidence=None,
                confidence_in_step=1.0,
            ),
            ReasoningStep(
                step=2,
                decision=gfa_rationale,
                evidence=inferred_from[0] if inferred_from else None,
                confidence_in_step=0.5,
            ),
            ReasoningStep(
                step=3,
                decision=(
                    "designer judgment: use split set to indicative 70/15/10/5 "
                    "— requires designer input"
                ),
                evidence=None,
                confidence_in_step=0.2,
            ),
            ReasoningStep(
                step=4,
                decision=(
                    "designer judgment: unit mix set to indicative 30/40/30 "
                    "across tenure bands — requires designer input"
                ),
                evidence=None,
                confidence_in_step=0.2,
            ),
            ReasoningStep(
                step=5,
                decision=(
                    "All values below confidence 0.3 — must be reviewed "
                    "before handoff to Grasshopper"
                ),
                evidence=None,
                confidence_in_step=1.0,
            ),
        ],
        provenance=inferred_prov,
        confidence=Confidence(
            score=0.15,
            reasons=[f"Fallback programme: {reason}"],
            flags=["requires_designer_input"],
        ),
    )


# ---------------------------------------------------------------------------
# Pre-parse normaliser: remap LLM JSON to the exact Pydantic schema shape
# ---------------------------------------------------------------------------

_TENURE_ALIASES: dict[str, str] = {
    "middeldure_huur": "middenhuur",
    "vrije_sector": "vrije_sector_huur",
    "vrije_sector_koop": "koop",
    "sociale_huur": "sociale_huur",
    "middenhuur": "middenhuur",
    "vrije_sector_huur": "vrije_sector_huur",
    "koop": "koop",
    "other": "other",
}

_SIZE_BAND_ALIASES: dict[str, str] = {
    # typology → size_band fallback (used when size_band absent)
    "studio": "under_30m2",
    "1br": "30_60m2",
    "2br": "30_60m2",
    "3br": "60_90m2",
    # direct size_band values
    "small": "30_60m2",
    "medium": "60_90m2",
    "large": "over_90m2",
    "mixed": "mixed",
    "under_30m2": "under_30m2",
    "30_60m2": "30_60m2",
    "60_90m2": "60_90m2",
    "over_90m2": "over_90m2",
}


def _strip_extra_provenance_fields(prov: dict[str, Any]) -> dict[str, Any]:
    """Remove any field not in the Provenance schema."""
    allowed = {
        "source_type",
        "document",
        "page",
        "quoted_text",
        "api_name",
        "inferred_from",
        "entered_by",
        "timestamp",
    }
    return {k: v for k, v in prov.items() if k in allowed}


def _normalise_llm_json(data: dict[str, Any], total_gfa: float | None = None) -> dict[str, Any]:
    """Remap the LLM's richer JSON to exactly what ProgrammeProposal expects."""

    # ── top-level GFA ──────────────────────────────────────────────────────
    if "target_total_gfa_m2_range" in data:
        r = data["target_total_gfa_m2_range"]
        if isinstance(r, dict):
            data["target_total_gfa_m2_range"] = (r.get("min", 0), r.get("max", 0))
            if "target_total_gfa_m2" not in data:
                data["target_total_gfa_m2"] = (r["min"] + r["max"]) / 2.0
        elif isinstance(r, (list, tuple)) and len(r) == 2:
            data["target_total_gfa_m2_range"] = (float(r[0]), float(r[1]))
            if "target_total_gfa_m2" not in data:
                data["target_total_gfa_m2"] = (r[0] + r[1]) / 2.0

    # grab final GFA for use_split percentage conversion
    gfa = float(data.get("target_total_gfa_m2") or total_gfa or 1.0)

    # ── total_dwelling_count_range ─────────────────────────────────────────
    if "total_dwelling_count_range" in data:
        r = data["total_dwelling_count_range"]
        if isinstance(r, dict):
            data["total_dwelling_count_range"] = (
                int(r.get("min", 0)),
                int(r.get("max", 0)),
            )
            if "target_dwelling_count" not in data:
                data["target_dwelling_count"] = int((r["min"] + r["max"]) / 2)
        elif isinstance(r, (list, tuple)) and len(r) == 2:
            data["total_dwelling_count_range"] = (int(r[0]), int(r[1]))
            if "target_dwelling_count" not in data:
                data["target_dwelling_count"] = int((r[0] + r[1]) / 2)

    # ── parking_demand ─────────────────────────────────────────────────────
    pd = data.get("parking_demand")
    if isinstance(pd, dict):
        r = pd.get("total_spaces_range") or pd.get("total_spaces") or {}
        if isinstance(r, dict):
            data["parking_demand"] = (r.get("min", 0) + r.get("max", 0)) / 2.0
        elif isinstance(r, (int, float)):
            data["parking_demand"] = float(r)
        else:
            nums = [v for v in pd.values() if isinstance(v, (int, float))]
            data["parking_demand"] = float(nums[0]) if nums else None

    # ── use_split ──────────────────────────────────────────────────────────
    us = data.get("use_split")
    if isinstance(us, dict):
        pct_map = {
            "residential_pct": "residential_m2",
            "productive_pct": "productive_m2",
            "office_pct": "office_m2",
            "retail_horeca_pct": "retail_horeca_m2",
            "cultural_pct": "cultural_m2",
            "social_pct": "social_m2",
            "other_pct": "other_m2",
        }
        had_pct = False
        for pct_key, m2_key in pct_map.items():
            if pct_key in us and m2_key not in us:
                us[m2_key] = float(us.pop(pct_key)) * gfa
                had_pct = True
            else:
                us.pop(pct_key, None)

        if had_pct:
            us["normalised_from_pct"] = True

        for bad in ("notes", "typology", "total_m2"):
            us.pop(bad, None)

        if "provenance" in us and isinstance(us["provenance"], dict):
            us["provenance"] = _strip_extra_provenance_fields(us["provenance"])

        data["use_split"] = us

    # ── unit_mix ───────────────────────────────────────────────────────────
    unit_mix = data.get("unit_mix")
    if isinstance(unit_mix, list):
        cleaned: list[dict[str, Any]] = []
        for entry in unit_mix:
            if not isinstance(entry, dict):
                continue
            clean: dict[str, Any] = {}

            # tenure — normalise aliases
            tenure_raw = str(entry.get("tenure", "other"))
            clean["tenure"] = _TENURE_ALIASES.get(tenure_raw, "other")

            # typology — preserve as-is (studio, 1br, 2br, 3br, mixed)
            clean["typology"] = entry.get("typology") or None

            # size_band — try direct value first, fall back to typology mapping
            size_raw = str(entry.get("size_band", entry.get("typology", "mixed")))
            clean["size_band"] = _SIZE_BAND_ALIASES.get(size_raw, "mixed")

            # fraction — accept target_share as alias
            frac = entry.get("fraction_of_total_dwellings", entry.get("target_share"))
            clean["fraction_of_total_dwellings"] = float(frac) if frac is not None else 0.0

            # target_count_range
            count_range = entry.get("target_count_range")
            if isinstance(count_range, dict):
                clean["target_count_range"] = (
                    int(count_range.get("min", 0)),
                    int(count_range.get("max", 0)),
                )
            elif isinstance(count_range, (list, tuple)) and len(count_range) == 2:
                clean["target_count_range"] = (int(count_range[0]), int(count_range[1]))

            # target_size_m2_range
            size_range = entry.get("target_size_m2_range")
            if isinstance(size_range, dict):
                clean["target_size_m2_range"] = (
                    float(size_range.get("min", 0)),
                    float(size_range.get("max", 0)),
                )
            elif isinstance(size_range, (list, tuple)) and len(size_range) == 2:
                clean["target_size_m2_range"] = (float(size_range[0]), float(size_range[1]))

            clean["rationale"] = str(entry.get("rationale", "designer judgment"))

            prov = entry.get("provenance", {})
            if isinstance(prov, dict):
                prov = _strip_extra_provenance_fields(prov)
            clean["provenance"] = prov

            conf = entry.get("confidence", {})
            if isinstance(conf, dict):
                conf.pop("notes", None)
            clean["confidence"] = conf

            cleaned.append(clean)
        data["unit_mix"] = cleaned

    # ── reasoning_trace ────────────────────────────────────────────────────
    rt = data.get("reasoning_trace")
    if isinstance(rt, list):
        normalised_steps: list[Any] = []
        for step in rt:
            if isinstance(step, str):
                normalised_steps.append(step)
            elif isinstance(step, dict):
                # Preserve as structured ReasoningStep — keep confidence_in_step
                clean_step: dict[str, Any] = {
                    "step": int(step.get("step", 0)),
                    "decision": str(step.get("decision", "")),
                }
                evidence = step.get("evidence") or step.get("citations") or None
                if evidence:
                    clean_step["evidence"] = str(evidence)
                conf_in_step = step.get("confidence_in_step") or step.get("confidence_in_step")
                if conf_in_step is not None:
                    clean_step["confidence_in_step"] = float(conf_in_step)
                normalised_steps.append(clean_step)
            else:
                normalised_steps.append(str(step))
        data["reasoning_trace"] = normalised_steps

    # ── top-level provenance ───────────────────────────────────────────────
    if "provenance" in data and isinstance(data["provenance"], dict):
        data["provenance"] = _strip_extra_provenance_fields(data["provenance"])

    # ── top-level confidence ───────────────────────────────────────────────
    if "confidence" in data and isinstance(data["confidence"], dict):
        data["confidence"].pop("notes", None)

    return data


# ---------------------------------------------------------------------------
# JSON -> ProgrammeProposal with graceful validation
# ---------------------------------------------------------------------------


def _parse_programme_response(
    data: dict[str, Any],
    framework: ParametricFramework,
) -> ProgrammeProposal:
    """Normalise and parse the LLM JSON into a ProgrammeProposal."""

    def _walk_fix(obj: Any) -> Any:
        if isinstance(obj, dict):
            if "source_type" in obj and "timestamp" not in obj:
                obj["timestamp"] = datetime.now(UTC).isoformat()
            return {k: _walk_fix(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk_fix(i) for i in obj]
        return obj

    data = _walk_fix(data)

    try:
        data = _normalise_llm_json(data)
    except Exception as norm_exc:
        logger.warning(f"Normaliser raised unexpectedly: {norm_exc}. Proceeding anyway.")

    logger.debug(f"Normalised LLM JSON:\n{json.dumps(data, indent=2, default=str)}")

    try:
        proposal = ProgrammeProposal.model_validate(data)

    except Exception as exc:
        debug_path = Path("debug_raw_programme.json")
        debug_path.write_text(json.dumps(data, indent=2, default=str))
        logger.warning(
            f"ProgrammeProposal validation failed: {exc}\n"
            f"Normalised data saved to {debug_path.resolve()} for inspection."
        )
        logger.warning(
            "Returning model_construct bypass object — inspect debug_raw_programme.json "
            "then fix the normaliser or schema. Do not treat this output as production data."
        )
        return ProgrammeProposal.model_construct(**data)

    total_fraction = sum(u.fraction_of_total_dwellings for u in proposal.unit_mix)
    if proposal.unit_mix and abs(total_fraction - 1.0) > 0.05:
        logger.warning(
            f"Unit mix fractions sum to {total_fraction:.3f}, expected ~1.0. Normalising."
        )
        for u in proposal.unit_mix:
            u.fraction_of_total_dwellings = u.fraction_of_total_dwellings / total_fraction

    toelichting_ids = {
        c.id
        for c in framework.constraints.narrative
        if c.provenance.document and "toelichting" in c.provenance.document.lower()
    }
    if toelichting_ids and not any(
        any(tid in _reasoning_trace_text(step) for tid in toelichting_ids)
        for step in proposal.reasoning_trace
    ):
        logger.warning(
            "Programme reasoning trace does not cite any toelichting constraint. "
            "Consider re-running with more detailed prompt."
        )

    geo_keywords = ["pdok_bag", "cbs", "bag", "demographics", "buurt", "nearby_buildings"]
    if not any(
        any(kw in _reasoning_trace_text(step).lower() for kw in geo_keywords)
        for step in proposal.reasoning_trace
    ):
        logger.warning(
            "Programme reasoning trace does not cite any geo data. "
            "Consider re-running — the output may rely too heavily on designer judgment."
        )

    return proposal


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _reasoning_trace_text(step: ReasoningStep | str) -> str:
    """Extract searchable text from a reasoning step regardless of type."""
    if isinstance(step, str):
        return step
    parts = [step.decision]
    if step.evidence:
        parts.append(step.evidence)
    return " ".join(parts)


def infer_programme(
    framework: ParametricFramework,
    geo_context: GeoContext | None = None,
    *,
    dry_run: bool = False,
) -> ProgrammeProposal:
    """Infer a ProgrammeProposal from the extracted framework and geo context.

    Args:
        framework: The ParametricFramework with constraints, objective, and
            variables already populated (Stages 1–4b).
        geo_context: The GeoContext from enrich.py (Stage 4). May be None or
            partially populated when APIs failed (e.g. 3D BAG HTTP 400).
        dry_run: If True, skip the LLM call and return a low-confidence fallback.
            Useful for testing the plumbing without burning API budget.

    Returns:
        A ProgrammeProposal ready to be attached to the framework.
        All values carry provenance and confidence. Fields that could not
        be grounded are marked with requires_designer_input in flags.
    """
    logger.info(
        f"Starting programme inference for {framework.metadata.project_name!r}. "
        f"Geo context: {'present' if geo_context else 'absent'}. "
        "3D BAG: "
        + (
            str(geo_context.nearby_buildings.has_3d_bag_data)
            if geo_context and geo_context.nearby_buildings
            else "n/a"
        )
    )

    if geo_context and "pdok_3d_bag" in geo_context.data_sources_failed:
        logger.warning(
            "3D BAG was unavailable (HTTP 400 in enrichment stage). "
            "Programme inference will rely on 2D BAG and document constraints for "
            "height context. This is noted in the reasoning trace."
        )

    if dry_run:
        return _fallback_programme(framework, geo_context, "dry_run=True")

    try:
        prompt = _build_inference_prompt(framework, geo_context)
        raw_data = _call_llm_for_programme(prompt)
        proposal = _parse_programme_response(raw_data, framework)

    except (ImportError, ValueError, KeyError) as exc:
        logger.error(f"Programme inference failed: {exc}")
        return _fallback_programme(framework, geo_context, str(exc))

    except Exception as exc:
        logger.error(f"Unexpected error during programme inference: {exc}")
        return _fallback_programme(framework, geo_context, f"unexpected error: {exc}")

    # ── post-parse quality checks (warnings only, never raise) ────────────

    cites_toelichting = any(
        "toelichting" in _reasoning_trace_text(step).lower() for step in proposal.reasoning_trace
    )
    if not cites_toelichting:
        logger.warning(
            "Programme reasoning trace does not cite any toelichting constraint. "
            "Consider re-running with a more detailed prompt."
        )

    cites_geo = any(
        any(src in _reasoning_trace_text(step).lower() for src in ("bag", "cbs", "osm"))
        for step in proposal.reasoning_trace
    )
    if not cites_geo:
        logger.warning(
            "Programme reasoning trace does not cite any geo data (BAG/CBS/OSM). "
            "Geo context may not have been used."
        )

    unit_fractions = sum(u.fraction_of_total_dwellings for u in proposal.unit_mix)
    if proposal.unit_mix and not (0.99 <= unit_fractions <= 1.01):
        logger.warning(
            f"unit_mix fractions sum to {unit_fractions:.3f} — expected 1.0. "
            "The LLM may have returned an inconsistent split."
        )

    if proposal.confidence.score > 0.7 and any(
        "requires_designer_input" in u.confidence.flags for u in proposal.unit_mix
    ):
        logger.warning(
            "Overall confidence >0.7 but some unit_mix entries are flagged "
            "requires_designer_input — consider lowering overall confidence."
        )

    logger.success(
        f"Programme inference complete. "
        f"GFA={proposal.target_total_gfa_m2:.0f}m², "
        f"dwellings={proposal.target_dwelling_count}, "
        f"unit_mix={len(proposal.unit_mix)} entries, "
        f"confidence={proposal.confidence.score:.2f}, "
        f"flags={proposal.confidence.flags}"
    )
    return proposal
