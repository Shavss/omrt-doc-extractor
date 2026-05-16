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
    Provenance,
    ProgrammeProposal,
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

    # Numerical constraints with cross-validation status
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
            value_str = (
                f"{c.value[0]}\u2013{c.value[1]}" if isinstance(c.value, tuple) else str(c.value)
            )
            condition_str = f" (condition: {c.condition})" if c.condition else ""
            applies_str = f" [applies_to: {', '.join(c.applies_to)}]" if c.applies_to else ""
            prov_str = ""
            if c.provenance.source_type == SourceType.DOCUMENT:
                prov_str = f" \u2014 {c.provenance.document} p.{c.provenance.page}"
                if c.provenance.quoted_text:
                    prov_str += f': "{c.provenance.quoted_text[:120]}"'
            lines.append(
                f"- [{c.id}] {c.name}: {value_str} {c.unit}{condition_str}"
                f"{applies_str} (conf={c.confidence.score:.2f}){cv_note}{prov_str}"
            )

    # Narrative constraints from toelichting
    toelichting_passages = [
        c for c in framework.constraints.narrative
        if c.provenance.source_type == SourceType.DOCUMENT
        and c.provenance.document
        and "toelichting" in c.provenance.document.lower()
    ]
    if toelichting_passages:
        lines.append("\n## Urban Design Intentions (toelichting)")
        for c in toelichting_passages[:8]:
            prov = f"{c.provenance.document} p.{c.provenance.page}"
            lines.append(f"- [{c.id}] {c.statement} (source: {prov})")

    all_narrative = [c for c in framework.constraints.narrative if c not in toelichting_passages]
    if all_narrative:
        lines.append("\n## Other Narrative Constraints")
        for c in all_narrative[:6]:
            lines.append(f"- [{c.id}] {c.statement}")

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
                f"- Typical heights: {nb.typical_heights_m[0]}\u2013{nb.typical_heights_m[1]} m"
            )
        if nb.typical_year_built:
            lines.append(
                f"- Typical year built: {nb.typical_year_built[0]}\u2013{nb.typical_year_built[1]}"
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
            "\n## Nearby Amenities (OSM): "
            + ", ".join(f"{k}: {v}" for k, v in top_amenities)
        )

    if geo.data_sources_failed:
        lines.append(f"\n## Failed data sources: {', '.join(geo.data_sources_failed)}")
        if "pdok_3d_bag" in geo.data_sources_failed:
            lines.append(
                "  Note: 3D BAG returned HTTP 400 \u2014 no 3D context buildings available. "
                "Urban height context is inferred from 2D BAG and document constraints only."
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

Now produce a ProgrammeProposal JSON object following the schema exactly.
Remember:
1. Every UnitTypeTarget, UseSplit, and the overall ProgrammeProposal must have
   provenance with source_type="inferred" and inferred_from listing the constraint IDs
   or geo data points that drove each decision.
2. The reasoning_trace list must contain 4\u20138 steps. Each step cites either:
   - A constraint ID in brackets, e.g. [max_height_sba2]
   - A geo data point, e.g. [pdok_bag: 145 residential buildings within 500m]
   - "designer judgment: <explicit rationale>"
3. At least one reasoning step must cite a toelichting passage by constraint ID.
4. At least one reasoning step must cite a BAG or CBS data point.
5. If 3D BAG data is unavailable (as noted above), acknowledge this explicitly
   in a reasoning step and rely on 2D BAG heights and document constraints instead.
6. Prefer value ranges over false precision. Use target_dwelling_count=null if
   evidence is insufficient to estimate.
7. Unit mix fractions must sum to 1.0.
8. Set confidence.score <= 0.7 if more than half the decisions rest on designer judgment.

Return ONLY valid JSON matching the ProgrammeProposal schema. No markdown, no commentary.
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
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = message.content[0].text.strip()

    # Strip markdown code fences if the model wrapped the JSON
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        raw_text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error(f"LLM returned non-JSON response: {raw_text[:500]}")
        raise ValueError(
            f"LLM did not return valid JSON for programme inference: {exc}"
        ) from exc


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
        c for c in framework.constraints.numerical
        if c.category in ("bvo_limit", "fsi_far")
    ]
    height_constraints = [
        c for c in framework.constraints.numerical
        if c.category == "height"
    ]

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
        gfa_rationale = "designer judgment: no BVO constraint found \u2014 value set to 0, requires designer input"

    inferred_from = [c.id for c in bvo_constraints[:2]] + [c.id for c in height_constraints[:2]]

    inferred_prov = Provenance(
        source_type=SourceType.INFERRED,
        inferred_from=inferred_from or ["objective"],
    )

    return ProgrammeProposal(
        target_total_gfa_m2=max(total_gfa, 1.0),
        use_split=UseSplit(
            residential_m2=max(total_gfa * 0.7, 1.0),
            productive_m2=total_gfa * 0.15,
            office_m2=0.0,
            retail_horeca_m2=total_gfa * 0.1,
            cultural_m2=0.0,
            social_m2=total_gfa * 0.05,
            other_m2=0.0,
            rationale="designer judgment: fallback 70/15/10/5 split \u2014 requires designer input",
            provenance=inferred_prov,
            confidence=Confidence(
                score=0.2,
                reasons=["Fallback due to LLM unavailability \u2014 all values need review"],
                flags=["requires_designer_input"],
            ),
        ),
        unit_mix=[
            UnitTypeTarget(
                tenure="sociale_huur",
                size_band="mixed",
                fraction_of_total_dwellings=0.4,
                rationale="designer judgment: Amsterdam 40/40/20 target \u2014 requires verification",
                provenance=inferred_prov,
                confidence=Confidence(
                    score=0.2,
                    reasons=["Fallback \u2014 unverified assumption"],
                    flags=["requires_designer_input"],
                ),
            ),
            UnitTypeTarget(
                tenure="middenhuur",
                size_band="mixed",
                fraction_of_total_dwellings=0.4,
                rationale="designer judgment: Amsterdam 40/40/20 target \u2014 requires verification",
                provenance=inferred_prov,
                confidence=Confidence(
                    score=0.2,
                    reasons=["Fallback \u2014 unverified assumption"],
                    flags=["requires_designer_input"],
                ),
            ),
            UnitTypeTarget(
                tenure="vrije_sector_huur",
                size_band="mixed",
                fraction_of_total_dwellings=0.2,
                rationale="designer judgment: Amsterdam 40/40/20 target \u2014 requires verification",
                provenance=inferred_prov,
                confidence=Confidence(
                    score=0.2,
                    reasons=["Fallback \u2014 unverified assumption"],
                    flags=["requires_designer_input"],
                ),
            ),
        ],
        target_dwelling_count=None,
        parking_demand=None,
        reasoning_trace=[
            f"FALLBACK MODE ({reason}): LLM inference was not available.",
            gfa_rationale,
            "designer judgment: use split set to indicative 70/15/10/5 \u2014 requires designer input",
            "designer judgment: unit mix set to indicative 40/40/20 \u2014 requires designer input",
            "All values below confidence 0.3 \u2014 must be reviewed before handoff to Grasshopper",
        ],
        provenance=inferred_prov,
        confidence=Confidence(
            score=0.15,
            reasons=[f"Fallback programme: {reason}"],
            flags=["requires_designer_input"],
        ),
    )


# ---------------------------------------------------------------------------
# JSON -> ProgrammeProposal with graceful validation
# ---------------------------------------------------------------------------


def _parse_programme_response(
    data: dict[str, Any],
    framework: ParametricFramework,
) -> ProgrammeProposal:
    """Parse the LLM JSON into a ProgrammeProposal, fixing common issues."""

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
        proposal = ProgrammeProposal.model_validate(data)
    except Exception as exc:
        logger.warning(f"ProgrammeProposal validation failed: {exc}. Falling back.")
        raise ValueError(str(exc)) from exc

    # Validate unit_mix fractions sum to ~1.0
    total_fraction = sum(u.fraction_of_total_dwellings for u in proposal.unit_mix)
    if abs(total_fraction - 1.0) > 0.05:
        logger.warning(
            f"Unit mix fractions sum to {total_fraction:.3f}, expected ~1.0. Normalising."
        )
        for u in proposal.unit_mix:
            u.fraction_of_total_dwellings = u.fraction_of_total_dwellings / total_fraction

    # Check toelichting citation in reasoning trace
    toelichting_ids = {
        c.id
        for c in framework.constraints.narrative
        if c.provenance.document and "toelichting" in c.provenance.document.lower()
    }
    if toelichting_ids and not any(
        any(tid in step for tid in toelichting_ids)
        for step in proposal.reasoning_trace
    ):
        logger.warning(
            "Programme reasoning trace does not cite any toelichting constraint. "
            "Consider re-running with more detailed prompt."
        )

    # Check BAG/CBS citation in reasoning trace
    geo_keywords = ["pdok_bag", "cbs", "bag", "demographics", "buurt", "nearby_buildings"]
    if not any(
        any(kw in step.lower() for kw in geo_keywords)
        for step in proposal.reasoning_trace
    ):
        logger.warning(
            "Programme reasoning trace does not cite any geo data. "
            "Consider re-running \u2014 the output may rely too heavily on designer judgment."
        )

    return proposal


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def infer_programme(
    framework: ParametricFramework,
    geo_context: GeoContext | None = None,
    *,
    dry_run: bool = False,
) -> ProgrammeProposal:
    """Infer a ProgrammeProposal from the extracted framework and geo context.

    Args:
        framework: The ParametricFramework with constraints, objective, and
            variables already populated (Stages 1\u20134b).
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
        logger.success(
            f"Programme inference complete. "
            f"GFA={proposal.target_total_gfa_m2:.0f}m\u00b2, "
            f"confidence={proposal.confidence.score:.2f}"
        )
        return proposal

    except (ImportError, ValueError, KeyError) as exc:
        logger.error(f"Programme inference failed: {exc}")
        return _fallback_programme(framework, geo_context, str(exc))

    except Exception as exc:  # noqa: BLE001
        logger.error(f"Unexpected error during programme inference: {exc}")
        return _fallback_programme(framework, geo_context, f"unexpected error: {exc}")
