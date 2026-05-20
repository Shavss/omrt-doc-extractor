"""Streamlit viewer for human review of extracted ParametricFrameworks.

Loads a framework.json produced by ``omrt_extractor.output`` and renders
its constraints with traffic-light status coding so a PM can quickly
spot what needs verifying. Designed as a safety net, not a dashboard:
plain widgets, no plotting, no fancy layout.

Status rules per numerical constraint:

    red    confidence < 0.85, or cross_validation.agreement='disagreement',
           or any 'imro_api_disagreement' / 'cross_doc_conflict' flag
    amber  inferred values (Provenance.source_type='inferred'), or any
           'dual_pass_disagreement' / 'ambiguous_clause' flag
    green  verification_status='reviewed' OR Provenance.source_type='manual'

Each value is shown in a coloured box with an expander that reveals the
quoted source text, document filename, page number, and confidence
reasons. A "mark as verified" button promotes the framework to
verification_status='reviewed' and writes the JSON back in place.

Stage 6 of the build plan.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

REVIEW_THRESHOLD = 0.85
COLOURS = {
    "red": "#d9534f",
    "amber": "#f0ad4e",
    "green": "#5cb85c",
    "grey": "#777777",
}

USE_COLOURS = {
    "residential": "#4e79a7",
    "productive": "#f28e2b",
    "office": "#7f7f7f",
    "retail_horeca": "#e15759",
    "cultural": "#b07aa1",
    "social": "#59a14f",
    "other": "#bab0ab",
}

TENURE_COLOURS = {
    "sociale_huur": "#4e79a7",
    "middenhuur": "#f28e2b",
    "vrije_sector_huur": "#e15759",
}


def _fmt(n: float | int | None, suffix: str = "") -> str:
    if n is None:
        return "—"
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}{suffix}"
    return f"{int(n):,}{suffix}"


def _fmt_range(rng: list | tuple | None, suffix: str = "") -> str:
    if not rng or len(rng) != 2:
        return "—"
    return f"{_fmt(rng[0])} to {_fmt(rng[1])}{suffix}"


# ---------------------------------------------------------------------------
# Loading / saving
# ---------------------------------------------------------------------------


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def save_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str))


def framework_body(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept either a handoff payload {header, framework, ...} or a bare framework."""
    return payload.get("framework", payload)


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def constraint_status(constraint: dict[str, Any], framework_reviewed: bool) -> str:
    flags = set(constraint.get("confidence", {}).get("flags", []) or [])
    score = constraint.get("confidence", {}).get("score", 0.0)
    source_type = constraint.get("provenance", {}).get("source_type")
    cross = constraint.get("cross_validation") or {}

    if framework_reviewed or source_type == "manual":
        return "green"
    if (
        score < REVIEW_THRESHOLD
        or cross.get("agreement") == "disagreement"
        or "imro_api_disagreement" in flags
        or "cross_doc_conflict" in flags
    ):
        return "red"
    if (
        source_type == "inferred"
        or "dual_pass_disagreement" in flags
        or "ambiguous_clause" in flags
    ):
        return "amber"
    return "green"


def format_value(value: Any, unit: str) -> str:
    if isinstance(value, list) and len(value) == 2:
        return f"{value[0]}–{value[1]} {unit}"
    return f"{value} {unit}"


def render_constraint_card(c: dict[str, Any], framework_reviewed: bool) -> None:
    status = constraint_status(c, framework_reviewed)
    colour = COLOURS[status]
    score = c.get("confidence", {}).get("score", 0.0)
    cross = c.get("cross_validation") or {}

    st.markdown(
        f"""
        <div style="border-left:6px solid {colour};padding:6px 10px;margin:6px 0;
                    background:rgba(127,127,127,0.05);border-radius:4px;">
          <strong>{c["name"]}</strong>
          <code>{c["id"]}</code><br/>
          <span style="font-size:1.1em;">{format_value(c["value"], c["unit"])}</span>
          &nbsp; <span style="color:{colour};">●</span>
          confidence {score:.2f}
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("source / provenance", expanded=False):
        prov = c.get("provenance", {}) or {}
        st.write(f"**source_type**: `{prov.get('source_type')}`")
        if prov.get("document"):
            st.write(f"**document**: {prov['document']}  •  page {prov.get('page')}")
        if prov.get("quoted_text"):
            st.markdown(f"> {prov['quoted_text']}")
        if prov.get("inferred_from"):
            st.write(f"inferred from: {', '.join(prov['inferred_from'])}")
        reasons = c.get("confidence", {}).get("reasons", [])
        if reasons:
            st.write("**confidence reasons**")
            for r in reasons:
                st.write(f"- {r}")
        flags = c.get("confidence", {}).get("flags", [])
        if flags:
            st.write(f"**flags**: {', '.join(flags)}")
        if cross:
            st.write(
                f"**cross-validation**: {cross.get('agreement')} "
                f"vs {cross.get('source')} (authoritative: "
                f"{cross.get('authoritative_value')})"
            )
        if c.get("condition"):
            st.write(f"**condition**: {c['condition']}")
        if c.get("notes"):
            st.write(f"**notes**: {c['notes']}")


# ---------------------------------------------------------------------------
# Programme proposal panel
# ---------------------------------------------------------------------------


USE_FIELDS = [
    ("residential_m2", "residential"),
    ("productive_m2", "productive"),
    ("office_m2", "office"),
    ("retail_horeca_m2", "retail_horeca"),
    ("cultural_m2", "cultural"),
    ("social_m2", "social"),
    ("other_m2", "other"),
]

GEO_SOURCE_TOKENS = (
    "pdok_bag",
    "pdok_3d_bag",
    "cbs_demographics",
    "osm_overpass",
    "osm:",
    "cbs:",
    "bag:",
    "3d_bag",
)


def _emphasise_geo_citations(text: str) -> str:
    """Italicise tokens in evidence text that point at geo data sources."""
    if not text:
        return ""

    # Bracketed citations like [cbs_demographics: ...] or [pdok_bag: ...]
    def repl_bracket(m: re.Match[str]) -> str:
        inner = m.group(1)
        if any(tok in inner.lower() for tok in GEO_SOURCE_TOKENS):
            return f"_[{inner}]_"
        return f"`[{inner}]`"

    return re.sub(r"\[([^\[\]]+)\]", repl_bracket, text)


def _use_split_bar(use_split: dict[str, Any], total_gfa: float) -> go.Figure:
    fig = go.Figure()
    for field, label in USE_FIELDS:
        val = float(use_split.get(field) or 0.0)
        if val <= 0:
            continue
        pct = (val / total_gfa * 100.0) if total_gfa else 0.0
        fig.add_trace(
            go.Bar(
                y=["GFA"],
                x=[val],
                name=label,
                orientation="h",
                marker_color=USE_COLOURS.get(label, "#cccccc"),
                text=[f"{label}: {_fmt(val)} m² ({pct:.0f}%)"],
                textposition="inside",
                insidetextanchor="middle",
                hovertemplate=f"{label}: {_fmt(val)} m² ({pct:.1f}%)<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack",
        template="simple_white",
        height=160,
        margin=dict(l=20, r=20, t=20, b=20),
        showlegend=False,
        xaxis=dict(title="m² GFA", separatethousands=True),
        yaxis=dict(showticklabels=False),
    )
    return fig


def _unit_mix_heatmap(unit_mix: list[dict[str, Any]]) -> go.Figure:
    tenures = ["sociale_huur", "middenhuur", "vrije_sector_huur"]
    bands = ["30_60m2", "60_90m2", "over_90m2"]
    z = [[0.0] * len(tenures) for _ in bands]
    text = [[""] * len(tenures) for _ in bands]
    for item in unit_mix:
        tenure = item.get("tenure")
        band = item.get("size_band")
        if tenure not in tenures or band not in bands:
            continue
        i = bands.index(band)
        j = tenures.index(tenure)
        frac = float(item.get("fraction_of_total_dwellings") or 0.0)
        z[i][j] = frac
        rng = item.get("target_count_range") or [None, None]
        text[i][j] = f"{_fmt(rng[0])}–{_fmt(rng[1])}" if rng[0] is not None else ""
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=tenures,
            y=bands,
            text=text,
            texttemplate="%{text}",
            colorscale="Blues",
            colorbar=dict(title="share"),
            hovertemplate="%{y} × %{x}: %{z:.0%}<extra></extra>",
        )
    )
    fig.update_layout(
        template="simple_white",
        height=260,
        margin=dict(l=20, r=20, t=40, b=20),
        title="Unit mix (count range by tenure × size)",
    )
    return fig


def _tenure_donut(unit_mix: list[dict[str, Any]]) -> go.Figure:
    tally: dict[str, float] = {}
    for item in unit_mix:
        t = item.get("tenure")
        if not t:
            continue
        tally[t] = tally.get(t, 0.0) + float(item.get("fraction_of_total_dwellings") or 0.0)
    labels = list(tally.keys())
    values = [tally[k] for k in labels]
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.55,
                marker=dict(colors=[TENURE_COLOURS.get(k, "#ccc") for k in labels]),
                textinfo="percent",
            )
        ]
    )
    fig.update_layout(
        template="simple_white",
        height=240,
        margin=dict(l=20, r=20, t=30, b=20),
        title="Tenure split",
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
    )
    return fig


def render_programme_panel(programme: dict[str, Any]) -> None:
    """Render the programme-proposal panel. Pure rendering, no IO."""
    st.markdown("## Programme proposal")
    total = float(programme.get("target_total_gfa_m2") or 0.0)
    gfa_range = programme.get("target_total_gfa_m2_range")
    dwellings = programme.get("target_dwelling_count")
    dwelling_range = programme.get("total_dwelling_count_range")
    parking = programme.get("parking_demand")
    use_split = programme.get("use_split") or {}
    unit_mix = programme.get("unit_mix") or []
    conf = (programme.get("confidence") or {}).get("score")
    prov = programme.get("provenance") or {}
    inferred_from = prov.get("inferred_from") or []
    constraint_citations = [
        c for c in inferred_from if not any(tok in c.lower() for tok in GEO_SOURCE_TOKENS)
    ]
    st.caption(
        f"Confidence: {conf:.2f}, anchored in {len(constraint_citations)} "
        f"explicit constraint citations."
        if conf is not None
        else ""
    )

    left, right = st.columns(2)

    with left:
        st.metric(
            label="Target total GFA",
            value=f"{_fmt(total)} m²",
            delta=f"range {_fmt_range(gfa_range, ' m²')}",
            delta_color="off",
        )
        if total > 0:
            st.plotly_chart(
                _use_split_bar(use_split, total),
                use_container_width=True,
            )
        rationale = (use_split.get("rationale") or "").strip()
        if rationale:
            head = rationale[:300] + ("…" if len(rationale) > 300 else "")
            st.markdown(f"_{head}_")
            if len(rationale) > 300:
                with st.expander("read full rationale"):
                    st.write(rationale)

    with right:
        st.metric(
            label="Target dwellings",
            value=_fmt(dwellings),
            delta=f"range {_fmt_range(dwelling_range)}",
            delta_color="off",
        )
        if unit_mix:
            st.plotly_chart(_unit_mix_heatmap(unit_mix), use_container_width=True)
            st.plotly_chart(_tenure_donut(unit_mix), use_container_width=True)
        if parking is not None:
            st.metric(
                label="Parking demand",
                value=f"{_fmt(parking)} spaces",
                delta="incl. 38 carshare per regels",
                delta_color="off",
            )

    trace = programme.get("reasoning_trace") or []
    with st.expander(f"Reasoning trace ({len(trace)} steps)", expanded=False):
        for step in trace:
            if isinstance(step, str):
                st.markdown(f"- {step}")
                continue
            n = step.get("step", "?")
            decision = step.get("decision", "")
            evidence = _emphasise_geo_citations(step.get("evidence") or "")
            sconf = step.get("confidence_in_step")
            badge = f" `{sconf:.2f}`" if isinstance(sconf, (int, float)) else ""
            st.markdown(
                f"**Step {n}.** {decision}{badge}  \n"
                f"<span style='color:#555;font-size:0.92em;'>{evidence}</span>",
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Neighbourhood context panel
# ---------------------------------------------------------------------------


AMENITY_GROUPS = {
    "playgrounds": ("playground",),
    "schools": ("school", "kindergarten"),
    "supermarkets": ("shop_supermarket", "shop_convenience"),
    "parks": ("park",),
    "restaurants": ("restaurant", "cafe", "bar"),
}


def _grouped_amenities(amenities: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for label, keys in AMENITY_GROUPS.items():
        total = sum(int(amenities.get(k, 0) or 0) for k in keys)
        if total > 0:
            out[label] = total
    return out


def _h_bar(items: dict[str, int | float], title: str, colour: str) -> go.Figure:
    sorted_items = sorted(items.items(), key=lambda kv: kv[1], reverse=True)[:5]
    labels = [k for k, _ in sorted_items]
    values = [v for _, v in sorted_items]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=colour,
            text=[str(v) for v in values],
            textposition="auto",
        )
    )
    fig.update_layout(
        template="simple_white",
        height=240,
        margin=dict(l=20, r=20, t=40, b=20),
        title=title,
        yaxis=dict(autorange="reversed"),
    )
    return fig


def render_neighbourhood_panel(geo: dict[str, Any]) -> None:
    """Render the neighbourhood-context panel. Pure rendering, no IO."""
    st.markdown("## Neighbourhood context")
    nb = geo.get("nearby_buildings") or None
    demo = geo.get("demographics") or None
    transit = geo.get("transit") or geo.get("transit_access") or None
    amenities = geo.get("nearby_amenities") or {}

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### Nearby buildings")
        if not nb:
            st.info("No BAG snapshot available.")
        else:
            st.metric(
                label=f"Buildings within {_fmt(nb.get('radius_m'))} m",
                value=_fmt(nb.get("count")),
            )
            dom = nb.get("dominant_uses") or []
            if dom:
                bar_items = (
                    {str(d): 1 for d in dom[:5]}
                    if isinstance(dom[0], str)
                    else {str(d.get("use", "?")): int(d.get("count", 0)) for d in dom[:5]}
                )
                st.plotly_chart(
                    _h_bar(bar_items, "Dominant uses", USE_COLOURS["residential"]),
                    use_container_width=True,
                )
            else:
                st.caption("Dominant uses: not classified.")
            heights = nb.get("typical_heights_m")
            if heights and len(heights) == 2:
                median_h = (heights[0] + heights[1]) / 2.0
                st.metric(
                    label="Typical heights",
                    value=f"{_fmt(heights[0])} to {_fmt(heights[1])} m",
                    delta=f"median ≈ {_fmt(median_h)} m",
                    delta_color="off",
                )
            else:
                st.caption("Typical heights: unavailable.")
            yr = nb.get("typical_year_built")
            if yr and len(yr) == 2:
                st.metric(label="Year built range", value=f"{int(yr[0])}–{int(yr[1])}")
            if nb.get("has_3d_bag_data"):
                st.markdown(
                    f"<span style='background:{COLOURS['green']};color:white;"
                    "padding:3px 8px;border-radius:3px;font-size:0.85em;'>"
                    "3D data available</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<span style='background:{COLOURS['grey']};color:white;"
                    "padding:3px 8px;border-radius:3px;font-size:0.85em;'>"
                    "2D only</span>",
                    unsafe_allow_html=True,
                )

    with col2:
        st.markdown("### Demographics (CBS)")
        if not demo:
            st.info("No CBS demographics available.")
        else:
            buurt = demo.get("buurt_name") or demo.get("buurt_code") or "buurt"
            st.caption(f"Buurt: `{buurt}`")
            st.metric(label="Population", value=_fmt(demo.get("population")))
            st.metric(label="Households", value=_fmt(demo.get("household_count")))
            st.metric(
                label="Avg household size",
                value=_fmt(demo.get("average_household_size")),
            )
            st.metric(label="Median age", value=_fmt(demo.get("median_age")))
            age_dist = demo.get("age_distribution")
            if isinstance(age_dist, dict) and age_dist:
                fig = go.Figure(
                    data=[
                        go.Pie(
                            labels=list(age_dist.keys()),
                            values=list(age_dist.values()),
                            hole=0.55,
                        )
                    ]
                )
                fig.update_layout(
                    template="simple_white",
                    height=220,
                    margin=dict(l=20, r=20, t=30, b=20),
                    title="Age distribution",
                )
                st.plotly_chart(fig, use_container_width=True)

    with col3:
        st.markdown("### Transit & amenities (OSM)")
        if not transit and not amenities:
            st.info("No OSM enrichment available.")
        else:
            if transit:
                pairs = [
                    ("tram", transit.get("nearest_tram_m")),
                    ("metro", transit.get("nearest_metro_m")),
                    ("train", transit.get("nearest_train_m")),
                    ("bus", transit.get("nearest_bus_m")),
                ]
                near_400 = sum(1 for _, d in pairs if d is not None and d <= 400)
                near_800 = sum(1 for _, d in pairs if d is not None and d <= 800)
                a, b = st.columns(2)
                a.metric("Transit stops ≤400 m", _fmt(near_400))
                b.metric("Transit stops ≤800 m", _fmt(near_800))
                for label, d in pairs:
                    if d is not None:
                        st.caption(f"{label}: {_fmt(d)} m")
            grouped = _grouped_amenities(amenities)
            if grouped:
                st.plotly_chart(
                    _h_bar(grouped, "Amenities nearby", USE_COLOURS["productive"]),
                    use_container_width=True,
                )

    used = set(geo.get("data_sources_used") or [])
    failed = set(geo.get("data_sources_failed") or [])
    all_sources = ["pdok_bag", "pdok_3d_bag", "cbs_demographics", "osm_overpass"]
    chunks = []
    for src in all_sources:
        if src in used:
            chunks.append(f"<span style='color:{COLOURS['green']};'>✓</span> <code>{src}</code>")
        elif src in failed:
            chunks.append(f"<span style='color:{COLOURS['red']};'>✗</span> <code>{src}</code>")
        else:
            chunks.append(f"<span style='color:{COLOURS['grey']};'>•</span> <code>{src}</code>")
    st.markdown(
        "<div style='margin-top:8px;font-size:0.9em;'>Sources: " + " · ".join(chunks) + "</div>",
        unsafe_allow_html=True,
    )


def render_zones_panel(zone_summaries: list[dict[str, Any]]) -> None:
    """Render the per-bouwvlak zone-to-rule mapping.

    Driven entirely by ``zone_programme_summary.json``. Row colour is a
    health signal for the zone-label-to-applies_to matching: green when at
    least two rules matched and the height has a textual source, yellow
    when rules matched but the height came from the verbeelding without a
    regels confirmation, red when nothing matched.
    """
    if not zone_summaries:
        st.info("Zone programme summary not found. Re-run the pipeline to generate it.")
        return

    st.markdown("## Zones")
    st.info(
        "Zone programme rules are matched from the extracted constraints. "
        "Zones with 0 matched rules indicate a label normalisation "
        "mismatch — check that the extracted NumericalConstraints have "
        "`applies_to` fields referencing the zone codes shown in the "
        "table."
    )

    def _row_colour(z: dict[str, Any]) -> str:
        rc = z.get("rule_count", 0)
        hs = z.get("height_source")
        if rc == 0:
            return "background-color: #fde2e1"
        if hs == "verbeelding_uncorrected":
            return "background-color: #fff4cd"
        if rc >= 2 and hs in ("regels", "verbeelding"):
            return "background-color: #dcefdc"
        return ""

    rows = []
    for z in zone_summaries:
        rows.append(
            {
                "Zone": z.get("zone_name") or z.get("zone_id") or "?",
                "Height (m)": z.get("height_m"),
                "Source": z.get("height_source") or "—",
                "Rules": z.get("rule_count", 0),
                "Categories": ", ".join(sorted((z.get("rules_by_category") or {}).keys())) or "—",
            }
        )

    import pandas as pd

    df = pd.DataFrame(rows)
    styled = df.style.apply(
        lambda row: [_row_colour(zone_summaries[row.name])] * len(row),
        axis=1,
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    zone_names = [z.get("zone_name") or z.get("zone_id") or "?" for z in zone_summaries]
    selected = st.selectbox("Inspect zone", zone_names, key="zone_inspect")
    z = zone_summaries[zone_names.index(selected)]

    with st.expander(f"Details — {selected}", expanded=True):
        st.write(f"**Zone codes:** {', '.join(z.get('zone_codes') or []) or '—'}")
        overlays = z.get("acoustic_overlays") or []
        if overlays:
            st.write(f"**Acoustic overlays:** {', '.join(overlays)}")
        h = z.get("height_m")
        h_txt = f"{h} m" if h is not None else "—"
        st.write(f"**Height:** {h_txt} (source: {z.get('height_source') or '—'})")
        rule_count = z.get("rule_count", 0)
        if rule_count == 0:
            st.warning(
                "No rules matched. Likely cause: the extracted "
                "NumericalConstraints' `applies_to` codes do not match "
                "any of this zone's codes after normalisation. Confirm "
                "that the regels actually reference these codes."
            )
        for cat, items in (z.get("rules_by_category") or {}).items():
            st.markdown(f"**{cat}**")
            for r in items:
                val = r.get("value")
                unit = r.get("unit") or ""
                cond = r.get("condition")
                src = r.get("source") or "—"
                line = f"- `{r.get('id')}` {r.get('name')}: **{val} {unit}**"
                if cond:
                    line += f" — _{cond}_"
                line += f"  \n  source: {src}"
                st.markdown(line)
        narr = z.get("narrative_rules") or []
        if narr:
            st.markdown("**Narrative**")
            for n in narr:
                st.write(f"- [{n.get('category')}] {n.get('statement')}")


def _resolve_sibling(base: Path, override: str | None, default_name: str) -> Path:
    """Resolve a sibling JSON path next to the framework file, or a sidebar override."""
    if override:
        return Path(override)
    return base.parent / default_name


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def page_review(
    payload_path: Path,
    programme_path: Path | None = None,
    geo_path: Path | None = None,
) -> None:
    payload = load_payload(payload_path)
    fw = framework_body(payload)
    meta = fw.get("metadata", {})
    status = meta.get("verification_status", "extracted")
    reviewed = status == "reviewed"

    header_banner = payload.get("header", {}).get("banner") or (
        "Human-reviewed output. Verified by reviewer."
        if reviewed
        else "PROTOTYPE OUTPUT, NOT VERIFIED"
    )
    banner_colour = COLOURS["green"] if reviewed else COLOURS["red"]
    st.markdown(
        f"<div style='background:{banner_colour};color:white;padding:10px;"
        f"border-radius:4px;font-weight:bold;text-align:center;'>"
        f"{header_banner}</div>",
        unsafe_allow_html=True,
    )

    st.subheader(meta.get("project_name", "(unnamed project)"))
    loc = meta.get("location", {})
    st.caption(
        f"{loc.get('municipality', '?')} · {loc.get('neighbourhood', '')} · "
        f"plan_id: {loc.get('plan_id') or 'none'} · status: {status}"
    )

    if not reviewed and st.button("Mark as verified", type="primary"):
        meta["verification_status"] = "reviewed"
        if "header" in payload:
            payload["header"]["verification_status"] = "reviewed"
            payload["header"]["banner"] = "Human-reviewed output. Verified by reviewer."
            payload["header"]["reviewed_at"] = datetime.now(UTC).isoformat()
        save_payload(payload_path, payload)
        st.success("Marked as reviewed. Reload to refresh.")
        st.rerun()

    st.markdown("---")

    # --- Massings (top) ---
    massings = fw.get("massings", []) or []
    if massings:
        st.markdown("## Example massings")
        st.caption(
            "Variant A is the maximum envelope; variant B applies setbacks above the "
            "threshold height. Both are derived from the validated constraints; "
            "neither is a finished design."
        )
        constraints_by_id_for_massings = {
            c["id"]: c for c in fw.get("constraints", {}).get("numerical", [])
        }
        palette = ["#4e79a7", "#f28e2b"]
        mcols = st.columns(min(len(massings), 2))
        for idx, m in enumerate(massings[:2]):
            with mcols[idx]:
                _render_massing(m, constraints_by_id_for_massings, palette[idx % len(palette)])
        st.markdown("---")

    # --- Programme proposal ---
    programme_inline = fw.get("programme")
    programme_loaded: dict[str, Any] | None = None
    if programme_path and programme_path.exists():
        try:
            programme_loaded = load_payload(programme_path)
        except Exception as exc:
            st.warning(f"Could not load programme file {programme_path}: {exc}")
    programme_data = programme_loaded or programme_inline
    if programme_data:
        render_programme_panel(programme_data)
    else:
        st.markdown("## Programme proposal")
        st.info("No programme proposal found. Run programme inference (Stage 5) to populate.")
    st.markdown("---")

    # --- Neighbourhood context ---
    if geo_path and geo_path.exists():
        try:
            geo_data = load_payload(geo_path)
            render_neighbourhood_panel(geo_data)
        except Exception as exc:
            st.warning(f"Could not load geo_context file {geo_path}: {exc}")
    else:
        st.markdown("## Neighbourhood context")
        st.info("No geo enrichment data. Run enrich_geo() to populate.")
    st.markdown("---")

    # --- Constraints table (bottom) ---
    constraints = fw.get("constraints", {})
    numerical = constraints.get("numerical", [])

    disagreements = [
        c for c in numerical if (c.get("cross_validation") or {}).get("agreement") == "disagreement"
    ]
    if disagreements:
        st.markdown("### IMRO API disagreements")
        for c in disagreements:
            render_constraint_card(c, reviewed)

    st.markdown("### Numerical constraints")
    if not numerical:
        st.info("No numerical constraints.")
    for c in numerical:
        render_constraint_card(c, reviewed)

    # --- Zone programme summary (per-bouwvlak rule mapping) ---
    zone_summary_inline = payload.get("zone_programme_summary")
    zone_summary_path = payload_path.parent / "zone_programme_summary.json"
    zone_summary: list[dict[str, Any]] | None = None
    if isinstance(zone_summary_inline, list):
        zone_summary = zone_summary_inline
    elif zone_summary_path.exists():
        try:
            loaded = json.loads(zone_summary_path.read_text())
            if isinstance(loaded, list):
                zone_summary = loaded
        except Exception as exc:
            st.warning(f"Could not load {zone_summary_path}: {exc}")
    if zone_summary is not None:
        render_zones_panel(zone_summary)
    else:
        st.markdown("## Zones")
        st.info("Zone programme summary not found. Re-run the pipeline to generate it.")
    st.markdown("---")

    st.markdown("### Geometric constraints")
    for g in constraints.get("geometric", []):
        st.write(
            f"- **{g['name']}** (`{g['id']}`) — "
            f"{g['feature_type']} · LOD {g.get('lod', 0)} · "
            f"CRS {g.get('crs', '?')} · {len(g.get('coordinates', []))} pts"
        )

    st.markdown("### Narrative constraints")
    for n in constraints.get("narrative", []):
        score = n.get("confidence", {}).get("score", 0.0)
        st.write(f"- [{score:.2f}] {n.get('statement', '')}")


# ---------------------------------------------------------------------------
# Approach 2 — GML
# ---------------------------------------------------------------------------


def _normalise_code(code: str) -> str:
    """Normalise a zone code for cross-approach matching.

    Strips brackets/parens, lowercases, converts hyphens to underscores.
    """
    if code is None:
        return ""
    s = str(code).strip()
    for ch in "[](){}":
        s = s.replace(ch, "")
    return s.strip().lower().replace("-", "_")


def _zone_label_pdf(bv: dict[str, Any]) -> str:
    parts = (
        (bv.get("bouwaanduidingen") or [])
        + (bv.get("function_aanduidingen") or [])
        + (bv.get("bestemming_codes") or [])
    )
    return ", ".join(parts) if parts else "(no codes)"


def _zone_label_gml(z: dict[str, Any]) -> str:
    sgd = z.get("sgd_code") or ""
    sbas = z.get("sba_codes") or []
    extras = ", ".join(sbas) if sbas else ""
    return f"{sgd} ({extras})" if extras else sgd


def _match_pdf_to_gml(
    bouwvlakken: list[dict[str, Any]], zones: list[dict[str, Any]]
) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None, set[str]]]:
    """Match by overlap of normalised zone codes; returns (pdf, gml, shared).

    Uses greedy bipartite matching: pre-compute all (pdf, gml) pair scores,
    then assign highest-scoring pairs first so that a PDF zone with more codes
    in common beats one with fewer — preventing a weak match from consuming a
    GML zone that belongs to a stronger candidate.
    """
    pdf_norm: list[set[str]] = []
    for bv in bouwvlakken:
        codes = (
            (bv.get("bouwaanduidingen") or [])
            + (bv.get("function_aanduidingen") or [])
            + (bv.get("bestemming_codes") or [])
        )
        pdf_norm.append({_normalise_code(c) for c in codes if c})

    gml_norm: list[set[str]] = []
    gml_sgd: list[str] = []
    for z in zones:
        codes = [z.get("sgd_code")] + (z.get("sba_codes") or [])
        gml_norm.append({_normalise_code(c) for c in codes if c})
        gml_sgd.append(_normalise_code(z.get("sgd_code") or ""))

    # Score: (sgd_exact_match, shared_count).  SGD match is the primary signal.
    candidates: list[tuple[float, int, int, set[str]]] = []
    for i in range(len(bouwvlakken)):
        for j in range(len(zones)):
            shared = pdf_norm[i] & gml_norm[j]
            if not shared:
                continue
            sgd_bonus = 1 if (gml_sgd[j] and gml_sgd[j] in pdf_norm[i]) else 0
            score = (sgd_bonus, len(shared))
            candidates.append((-score[0] * 1000 - score[1], i, j, shared))

    candidates.sort(key=lambda t: t[0])

    used_pdf: set[int] = set()
    used_gml: set[int] = set()
    matched_pdf: dict[int, tuple[int, set[str]]] = {}
    for _, i, j, shared in candidates:
        if i in used_pdf or j in used_gml:
            continue
        used_pdf.add(i)
        used_gml.add(j)
        matched_pdf[i] = (j, shared)

    rows: list[tuple[dict[str, Any] | None, dict[str, Any] | None, set[str]]] = []
    for i, bv in enumerate(bouwvlakken):
        if i in matched_pdf:
            j, shared = matched_pdf[i]
            rows.append((bv, zones[j], shared))
        else:
            rows.append((bv, None, set()))
    for j, z in enumerate(zones):
        if j not in used_gml:
            rows.append((None, z, set()))
    return rows


def _height_row_colour(delta: float | None) -> str:
    if delta is None:
        return f"background-color: {COLOURS['red']}33"
    a = abs(delta)
    if a <= 1.0:
        return f"background-color: {COLOURS['green']}33"
    if a <= 5.0:
        return f"background-color: {COLOURS['amber']}33"
    return f"background-color: {COLOURS['red']}33"


def _find_constraint(
    numerical: list[dict[str, Any]], id_substrings: tuple[str, ...]
) -> dict[str, Any] | None:
    for c in numerical:
        cid = (c.get("id") or "").lower()
        if any(s in cid for s in id_substrings):
            return c
    return None


def _cv(c: dict[str, Any] | None) -> Any:
    if not c:
        return None
    return c.get("value")


def _match_marker(a: Any, b: Any) -> str:
    if a is None or b is None:
        return "✗"
    try:
        af = float(a)
        bf = float(b)
    except (TypeError, ValueError):
        return "✓" if a == b else "✗"
    if af == 0 and bf == 0:
        return "✓"
    denom = max(abs(af), abs(bf), 1e-9)
    diff = abs(af - bf) / denom
    if diff <= 0.01:
        return "✓"
    if diff <= 0.10:
        return "⚠"
    return "✗"


def _render_pair_row(field: str, a: Any, b: Any, unit: str = "") -> dict[str, Any]:
    def fmt(v: Any) -> str:
        return "—" if v is None else (f"{v:,.0f}" if isinstance(v, (int, float)) else str(v))

    mark = _match_marker(a, b)
    return {
        "Field": field,
        "Approach 1 (PDF)": f"{fmt(a)} {unit}".strip() if a is not None else "—",
        "Approach 2 (GML)": f"{fmt(b)} {unit}".strip() if b is not None else "—",
        "Match?": mark,
    }


def _prism_mesh3d(
    polygon: list[list[float]],
    height: float,
    origin: tuple[float, float],
    colour: str,
    name: str,
) -> go.Mesh3d | None:
    """Build a Mesh3d prism by extruding a 2D polygon (RD metres) to `height`."""
    if not polygon or height is None or height <= 0:
        return None
    ox, oy = origin
    pts = [(p[0] - ox, p[1] - oy) for p in polygon]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return None
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for x, y in pts:
        xs.append(x)
        ys.append(y)
        zs.append(0.0)
    for x, y in pts:
        xs.append(x)
        ys.append(y)
        zs.append(float(height))
    i: list[int] = []
    j: list[int] = []
    k: list[int] = []
    for a in range(1, n - 1):
        i.append(0)
        j.append(a)
        k.append(a + 1)
    for a in range(1, n - 1):
        i.append(n)
        j.append(n + a + 1)
        k.append(n + a)
    for a in range(n):
        b = (a + 1) % n
        i.append(a)
        j.append(b)
        k.append(n + b)
        i.append(a)
        j.append(n + b)
        k.append(n + a)
    return go.Mesh3d(
        x=xs,
        y=ys,
        z=zs,
        i=i,
        j=j,
        k=k,
        color=colour,
        opacity=0.6,
        flatshading=True,
        name=name,
        hovertext=name,
        hoverinfo="text",
    )


def _flat_polygon_trace(
    polygon: list[list[float]],
    origin: tuple[float, float],
    z: float,
    fill_colour: str,
    line_colour: str,
    name: str,
    opacity: float = 0.4,
) -> list[Any]:
    """Flat filled polygon at height z, with outline. Returns Mesh3d + Scatter3d."""
    if not polygon:
        return []
    ox, oy = origin
    pts = [(p[0] - ox, p[1] - oy) for p in polygon]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [z] * n
    i: list[int] = []
    j: list[int] = []
    k: list[int] = []
    for a in range(1, n - 1):
        i.append(0)
        j.append(a)
        k.append(a + 1)
    mesh = go.Mesh3d(
        x=xs,
        y=ys,
        z=zs,
        i=i,
        j=j,
        k=k,
        color=fill_colour,
        opacity=opacity,
        flatshading=True,
        name=name,
        hovertext=name,
        hoverinfo="text",
        showlegend=True,
    )
    outline = go.Scatter3d(
        x=[*xs, xs[0]],
        y=[*ys, ys[0]],
        z=[*zs, zs[0]],
        mode="lines",
        line=dict(color=line_colour, width=3),
        name=name,
        showlegend=False,
        hoverinfo="skip",
    )
    return [mesh, outline]


def _wgs_to_local_m(polygon_wgs: list[list[float]], lat0: float, lon0: float) -> list[list[float]]:
    """Equirectangular approximation, OK at site scale (<2 km)."""
    import math

    cos_lat = math.cos(math.radians(lat0))
    out = []
    for p in polygon_wgs:
        lon, lat = p[0], p[1]
        x = (lon - lon0) * 111320.0 * cos_lat
        y = (lat - lat0) * 110540.0
        out.append([x, y])
    return out


def _wgs_centroid(polygon_wgs: list[list[float]]) -> tuple[float, float]:
    lons = [p[0] for p in polygon_wgs]
    lats = [p[1] for p in polygon_wgs]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _render_gml_3d(
    zones: list[dict[str, Any]],
    site_boundary_rd: list[list[float]] | None,
    no_build: list[dict[str, Any]] | None = None,
    overlays: list[dict[str, Any]] | None = None,
    site_boundary_wgs84: list[list[float]] | None = None,
) -> None:
    if not zones:
        st.info("No zones to render.")
        return
    xs_all = [p[0] for z in zones for p in (z.get("polygon_rd") or [])]
    ys_all = [p[1] for z in zones for p in (z.get("polygon_rd") or [])]
    if not xs_all:
        st.info("Zones have no RD polygons.")
        return
    ox = (min(xs_all) + max(xs_all)) / 2
    oy = (min(ys_all) + max(ys_all)) / 2
    palette = [
        "#4e79a7",
        "#f28e2b",
        "#e15759",
        "#76b7b2",
        "#59a14f",
        "#edc948",
        "#b07aa1",
        "#ff9da7",
    ]
    traces: list[Any] = []
    for idx, z in enumerate(zones):
        poly = z.get("polygon_rd")
        h = z.get("max_height_m") or 0
        if not poly or h <= 0:
            continue
        name = f"{z.get('sgd_code')} h={h}m"
        mesh = _prism_mesh3d(poly, h, (ox, oy), palette[idx % len(palette)], name)
        if mesh is not None:
            traces.append(mesh)
    if site_boundary_rd:
        sb = [(p[0] - ox, p[1] - oy) for p in site_boundary_rd]
        traces.append(
            go.Scatter3d(
                x=[p[0] for p in sb] + [sb[0][0]],
                y=[p[1] for p in sb] + [sb[0][1]],
                z=[0] * (len(sb) + 1),
                mode="lines",
                line=dict(color="#333", width=4),
                name="site boundary",
            )
        )

    # No-build zones (Groen / Verkeer / vrijwaringszone) - have polygon_rd directly.
    NO_BUILD_COLOURS = {
        "Groen": "#2ca02c",
        "Verkeer": "#7f7f7f",
        "vrijwaringszone - vaarweg": "#1f77b4",
    }
    seen_nb_legend: set[str] = set()
    for nb in no_build or []:
        poly = nb.get("polygon_rd")
        naam = nb.get("naam") or "no_build"
        colour = NO_BUILD_COLOURS.get(naam, "#999999")
        label = f"no-build: {naam}"
        # Only show legend entry for first instance of each naam.
        show_in_legend = naam not in seen_nb_legend
        seen_nb_legend.add(naam)
        sub = _flat_polygon_trace(
            poly,
            (ox, oy),
            z=0.05,
            fill_colour=colour,
            line_colour=colour,
            name=label,
            opacity=0.55,
        )
        for t in sub:
            if hasattr(t, "showlegend"):
                t.showlegend = show_in_legend and isinstance(t, go.Mesh3d)
            traces.append(t)

    # Overlay zones only have WGS84 - convert via site_boundary_wgs84 centroid.
    if overlays and site_boundary_wgs84:
        lat0, lon0 = _wgs_centroid(site_boundary_wgs84)
        # Need to subtract the equivalent local origin of the RD origin (ox, oy).
        # Since both meshes share the site, we re-anchor overlays so their site
        # boundary aligns with the RD one: compute the WGS84 boundary in local
        # metres, then translate by the offset between that centroid and the
        # RD boundary's centroid (which is at 0,0 because zones were centred).
        wgs_site_local = _wgs_to_local_m(site_boundary_wgs84, lat0, lon0)
        wsc_x = sum(p[0] for p in wgs_site_local) / len(wgs_site_local)
        wsc_y = sum(p[1] for p in wgs_site_local) / len(wgs_site_local)
        OVERLAY_COLOURS = {
            "Waarde - Archeologie": "#b07aa1",
            "overige zone - 2": "#edc948",
            "vrijwaringszone - vaarweg": "#1f77b4",
            "geluidzone - industrie": "#e15759",
        }
        z_levels = {
            "Waarde - Archeologie": -0.3,
            "overige zone - 2": -0.2,
            "vrijwaringszone - vaarweg": -0.4,
            "geluidzone - industrie": -0.5,
        }
        for ov in overlays:
            poly_wgs = ov.get("polygon_wgs84")
            if not poly_wgs:
                continue
            local = _wgs_to_local_m(poly_wgs, lat0, lon0)
            # Anchor relative to RD site centroid (which is 0,0 in local frame).
            anchored = [[p[0] - wsc_x, p[1] - wsc_y] for p in local]
            naam = ov.get("naam") or "overlay"
            colour = OVERLAY_COLOURS.get(naam, "#ccaa66")
            z = z_levels.get(naam, -0.3)
            label = f"overlay: {naam}"
            # Pass through as already-localised polygon (origin 0,0).
            sub = _flat_polygon_trace(
                anchored,
                (0.0, 0.0),
                z=z,
                fill_colour=colour,
                line_colour=colour,
                name=label,
                opacity=0.3,
            )
            traces.extend(sub)

    if not traces:
        st.info("No prisms to render (missing heights or polygons).")
        return
    fig = go.Figure(data=traces)
    fig.update_layout(
        scene=dict(
            aspectmode="data",
            xaxis=dict(title="x (m)"),
            yaxis=dict(title="y (m)"),
            zaxis=dict(title="z (m)"),
        ),
        margin=dict(l=0, r=0, t=10, b=0),
        height=520,
        showlegend=True,
        legend=dict(orientation="h", y=-0.05),
    )
    st.plotly_chart(fig, use_container_width=True)


def page_approach_gml(
    geometry_path: Path,
    gml_framework_path: Path,
    framework_path: Path,
    programme_path: Path,
    gml_parameters_path: Path,
) -> None:
    """Approach 2 - GML view with comparison, zone programme, detail, validation."""
    import pandas as pd

    st.subheader("Approach 2 — GML")
    st.caption(
        "Compares PDF-extracted geometry and rules (Approach 1) with the "
        "authoritative GML + DSO-teksten flow (Approach 2)."
    )

    missing = [p for p in [geometry_path, gml_framework_path] if not p.exists()]
    if missing:
        st.error(f"Missing files: {', '.join(str(p) for p in missing)}")
        return

    geometry = load_payload(geometry_path)
    gml_fw = load_payload(gml_framework_path)
    bouwvlakken = geometry.get("bouwvlakken") or []
    zones = gml_fw.get("zones") or []
    matches = _match_pdf_to_gml(bouwvlakken, zones)

    # -------- 3D viewer --------
    st.markdown("### 3D model (CityGML zones, extruded to max_height_m)")
    st.caption(
        "Each prism is a bouwvlak polygon from the GML, extruded to its "
        "authoritative max height. Coordinates localised to site centroid (RD)."
    )
    # Load gml_params early so we can pass no_build + overlay polygons too.
    gml_params_early: dict[str, Any] = {}
    if gml_parameters_path.exists():
        try:
            gml_params_early = load_payload(gml_parameters_path)
        except Exception as exc:
            st.warning(f"Could not load {gml_parameters_path}: {exc}")
    _render_gml_3d(
        zones,
        gml_fw.get("site_boundary_rd"),
        no_build=gml_params_early.get("no_build_zones") or [],
        overlays=gml_params_early.get("overlay_zones") or [],
        site_boundary_wgs84=gml_params_early.get("site_boundary_wgs84"),
    )

    # -------- Section A: Height comparison --------
    st.markdown("### A. Height comparison")

    height_rows: list[dict[str, Any]] = []
    agree_within_1 = 0
    total_matched = 0
    for bv, z, _shared in matches:
        pdf_h = bv.get("height_m") if bv else None
        gml_h = z.get("max_height_m") if z else None
        if pdf_h is not None and gml_h is not None:
            total_matched += 1
            delta = float(pdf_h) - float(gml_h)
            if abs(delta) <= 1.0:
                agree_within_1 += 1
        else:
            delta = None
        if delta is None:
            agreement = "missing"
        elif abs(delta) <= 1.0:
            agreement = "agree"
        elif abs(delta) <= 5.0:
            agreement = "drift"
        else:
            agreement = "conflict"
        label_parts = []
        if z is not None:
            label_parts.append(_zone_label_gml(z))
        if bv is not None:
            label_parts.append(f"PDF: {_zone_label_pdf(bv)}")
        height_rows.append(
            {
                "Zone": " | ".join(label_parts) if label_parts else "?",
                "PDF height (m)": pdf_h,
                "GML height (m)": gml_h,
                "Delta (m)": None if delta is None else round(delta, 2),
                "Agreement": agreement,
            }
        )

    total_zones = len(matches)
    st.info(
        f"Approach 1 (PDF extraction) vs Approach 2 (GML authoritative): "
        f"{agree_within_1}/{total_zones} zones agree within 1 m "
        f"(of {total_matched} pairs with heights on both sides)."
    )

    df_h = pd.DataFrame(height_rows)

    def _h_row_style(row: pd.Series) -> list[str]:
        idx = row.name
        delta = height_rows[idx]["Delta (m)"]
        return [_height_row_colour(delta)] * len(row)

    st.dataframe(df_h.style.apply(_h_row_style, axis=1), use_container_width=True, hide_index=True)

    # -------- Section B: Zone programme table --------
    st.markdown("### B. Zone programme")
    st.caption(
        "Spatial geometry from GML combined with programme rules per zone "
        "(rules hardcoded from regels for this prototype)."
    )
    prog_rows: list[dict[str, Any]] = []
    for z in zones:
        eff = z.get("effective") or {}
        sgd_rule = z.get("sgd_rule") or {}
        prog_rows.append(
            {
                "Zone": _zone_label_gml(z),
                "Height (m)": z.get("max_height_m"),
                "Allows wonen": "yes" if eff.get("allows_wonen") else "no",
                "Productive req (m²)": eff.get("productive_required_first_m2"),
                "Floorplate cap exempt": "yes" if eff.get("floor_plate_cap_exempt") else "no",
                "Setback trigger (m)": eff.get("setback_trigger_m"),
                "Source": sgd_rule.get("source") or "—",
            }
        )
    st.dataframe(pd.DataFrame(prog_rows), use_container_width=True, hide_index=True)

    # -------- Section C: Zone detail --------
    st.markdown("### C. Zone detail")
    if zones:
        labels = [_zone_label_gml(z) for z in zones]
        sel = st.selectbox("Inspect GML zone", labels, key="gml_zone_inspect")
        z = zones[labels.index(sel)]
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Spatial**")
            st.write(f"- bouwvlak id: `{z.get('bouwvlak_id')}`")
            st.write(f"- bestemmingsvlak id: `{z.get('bestemmingsvlak_id')}`")
            st.write(f"- sgd: `{z.get('sgd_code')}` — {z.get('sgd_full_name')}")
            st.write(f"- max height: **{z.get('max_height_m')} m**")
            st.write(f"- all heights: {z.get('all_heights_m')}")
            st.write(f"- footprint: {_fmt(z.get('footprint_area_m2'))} m²")
            st.write(f"- sba codes: {', '.join(z.get('sba_codes') or []) or '—'}")
            st.write(f"- overlaps WRA: {z.get('overlaps_wra')}")
            st.write(f"- overlaps geluidzone: {z.get('overlaps_geluidzone')}")
        with col2:
            st.markdown("**Programme rules (sgd_rule)**")
            st.json(z.get("sgd_rule") or {})
            st.markdown("**SBA rules**")
            st.json(z.get("sba_rules") or [])
        st.markdown("**Acoustic overlays (DVG)**")
        overlays = z.get("acoustic_overlays") or []
        st.write(", ".join(overlays) if overlays else "—")
        dvg = z.get("dvg_rules") or []
        if dvg:
            st.json(dvg)
        st.markdown("**Effective combined**")
        st.json(z.get("effective") or {})

    # -------- Section D: Validation --------
    st.markdown("### D. Validation — Approach 1 vs Approach 2")
    st.markdown(
        f"""<div style="background:#eef;padding:10px;border-radius:4px;
        border-left:4px solid {COLOURS["amber"]};margin:6px 0;">
        <b>Approach 1:</b> LLM extraction from PDF regels + kaveltekening drawing.<br>
        <b>Approach 2:</b> Authoritative GML geometry + DSO teksten API values
        (rules hardcoded for prototype, would be API-derived in production).
        </div>""",
        unsafe_allow_html=True,
    )

    have_prog = programme_path.exists()
    have_gml_params = gml_parameters_path.exists()
    have_fw = framework_path.exists()
    if not (have_prog and have_gml_params and have_fw):
        st.warning(
            "One or more inputs missing for full validation: "
            f"programme={have_prog}, gml_parameters={have_gml_params}, framework={have_fw}"
        )

    programme = load_payload(programme_path) if have_prog else {}
    gml_params = load_payload(gml_parameters_path) if have_gml_params else {}
    site_c = gml_params.get("site_constraints") or {}
    fw_root = load_payload(framework_path) if have_fw else {}
    fw = framework_body(fw_root)
    numerical = fw.get("constraints", {}).get("numerical", []) or []
    use_split = (programme.get("use_split") or {}) if isinstance(programme, dict) else {}

    site_rows = [
        _render_pair_row(
            "Total GFA cap",
            programme.get("target_total_gfa_m2"),
            site_c.get("max_bvo_total_m2"),
            "m²",
        ),
        _render_pair_row(
            "Max residential m²",
            use_split.get("residential_m2"),
            site_c.get("max_bvo_residential_m2"),
            "m²",
        ),
        _render_pair_row(
            "Min productive m²",
            use_split.get("productive_m2"),
            site_c.get("min_bvo_productive_m2"),
            "m²",
        ),
        _render_pair_row(
            "Max office m²",
            use_split.get("office_m2"),
            site_c.get("max_bvo_office_m2"),
            "m²",
        ),
        _render_pair_row(
            "Max horeca m²",
            use_split.get("retail_horeca_m2"),
            site_c.get("max_bvo_horeca_m2"),
            "m²",
        ),
        _render_pair_row(
            "Max cultural m²",
            use_split.get("cultural_m2"),
            site_c.get("max_bvo_cultural_m2"),
            "m²",
        ),
        _render_pair_row(
            "Max social m²",
            use_split.get("social_m2"),
            site_c.get("max_bvo_social_m2"),
            "m²",
        ),
        _render_pair_row(
            "Target dwellings",
            programme.get("target_dwelling_count"),
            site_c.get("target_dwelling_count"),
        ),
        _render_pair_row(
            "Parking spaces",
            programme.get("parking_demand"),
            site_c.get("parking_spaces_total"),
        ),
    ]

    def _style_pair_rows(rows: list[dict[str, Any]]) -> Any:
        df = pd.DataFrame(rows)

        def _row_style(row: pd.Series) -> list[str]:
            mark = row["Match?"]
            if mark == "✓":
                bg = f"background-color: {COLOURS['green']}22"
            elif mark == "⚠":
                bg = f"background-color: {COLOURS['amber']}33"
            else:
                bg = f"background-color: {COLOURS['red']}33"
            return [bg] * len(row)

        return df.style.apply(_row_style, axis=1)

    st.markdown("**Site-level programme**")
    st.dataframe(_style_pair_rows(site_rows), use_container_width=True, hide_index=True)

    # Per-zone heights
    zone_rows: list[dict[str, Any]] = []
    matched_zone_count = 0
    zone_agree = 0
    for bv, z, _shared in matches:
        if not (bv and z):
            continue
        matched_zone_count += 1
        pdf_h = bv.get("height_m")
        gml_h = z.get("max_height_m")
        delta = None if pdf_h is None or gml_h is None else round(float(pdf_h) - float(gml_h), 2)
        if delta is not None and abs(delta) <= 1.0:
            zone_agree += 1
        zone_rows.append(
            {
                "Zone": _zone_label_gml(z),
                "PDF height": pdf_h,
                "GML height": gml_h,
                "Delta": delta,
                "Source (PDF)": bv.get("height_reconciled_from") or "kaveltekening",
                "Source (GML)": (z.get("sgd_rule") or {}).get("source") or "GML",
            }
        )
    st.markdown("**Per-zone heights**")
    if zone_rows:
        df_z = pd.DataFrame(zone_rows)

        def _zone_style(row: pd.Series) -> list[str]:
            d = row["Delta"]
            return [_height_row_colour(None if d is None else float(d))] * len(row)

        st.dataframe(
            df_z.style.apply(_zone_style, axis=1), use_container_width=True, hide_index=True
        )

    # Site rules from framework.json
    plint = _find_constraint(numerical, ("min_plint_height", "plint_min", "hamerblok_plint"))
    setback_trig = _find_constraint(numerical, ("setback_above_21m_general",))
    setback_dep = _find_constraint(
        numerical, ("setback_above_21m_general", "setback_above_30_5m_sba3")
    )
    bvo_21_50 = _find_constraint(numerical, ("max_bvo_per_floor_high_rise_21_50m",))
    bvo_50p = _find_constraint(numerical, ("max_bvo_per_floor_high_rise_above_50m",))

    rule_rows = [
        _render_pair_row(
            "Plint min height",
            _cv(plint),
            site_c.get("plint_min_height_m"),
            "m",
        ),
        _render_pair_row(
            "Setback trigger",
            _cv(setback_trig),
            site_c.get("setback_standard_trigger_m"),
            "m",
        ),
        _render_pair_row(
            "Setback depth",
            _cv(setback_dep),
            site_c.get("setback_standard_depth_m"),
            "m",
        ),
        _render_pair_row(
            "Max bvo per floor 21–50m",
            _cv(bvo_21_50),
            site_c.get("max_bvo_per_floor_21_50m"),
            "m²",
        ),
        _render_pair_row(
            "Max bvo per floor above 50m",
            _cv(bvo_50p),
            site_c.get("max_bvo_per_floor_above_50m"),
            "m²",
        ),
    ]
    st.markdown("**Site rules**")
    st.dataframe(_style_pair_rows(rule_rows), use_container_width=True, hide_index=True)

    site_agree = sum(1 for r in site_rows if r["Match?"] == "✓")
    rule_agree = sum(1 for r in rule_rows if r["Match?"] == "✓")
    st.success(
        f"{site_agree}/{len(site_rows)} site-level values agree · "
        f"{zone_agree}/{matched_zone_count} zone heights agree · "
        f"{rule_agree}/{len(rule_rows)} site rules agree"
    )


def _mesh3d_from_triangles(triangles: list[list[list[float]]], colour: str) -> go.Mesh3d | None:
    """Build a plotly Mesh3d trace from an inline triangle list."""
    if not triangles:
        return None
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    i: list[int] = []
    j: list[int] = []
    k: list[int] = []
    for tri in triangles:
        base = len(xs)
        for pt in tri:
            xs.append(pt[0])
            ys.append(pt[1])
            zs.append(pt[2])
        i.append(base)
        j.append(base + 1)
        k.append(base + 2)
    return go.Mesh3d(
        x=xs,
        y=ys,
        z=zs,
        i=i,
        j=j,
        k=k,
        color=colour,
        opacity=0.85,
        flatshading=True,
    )


def _render_massing(
    massing: dict[str, Any],
    constraints_by_id: dict[str, dict[str, Any]],
    colour: str,
) -> None:
    """Render one Massing card with a plotly Mesh3d figure."""
    st.markdown(f"#### {massing.get('name', massing.get('id', 'massing'))}")

    if massing.get("uses_unverified_inputs"):
        st.markdown(
            f"<div style='background:{COLOURS['amber']};color:white;padding:6px 10px;"
            "border-radius:4px;font-weight:bold;text-align:center;margin-bottom:6px;'>"
            "preview based on unverified inputs</div>",
            unsafe_allow_html=True,
        )

    triangles = massing.get("mesh_polygons") or []
    trace = _mesh3d_from_triangles(triangles, colour)
    if trace is None:
        st.info("No mesh geometry available for this variant.")
    else:
        fig = go.Figure(data=[trace])
        fig.update_layout(
            scene=dict(aspectmode="data"),
            margin=dict(l=0, r=0, t=0, b=0),
            height=420,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.caption(massing.get("rationale", ""))

    with st.expander("moves and rules", expanded=False):
        for move in massing.get("moves", []):
            refs = move.get("driven_by", [])
            cited = ", ".join(
                f"`{r}` ({constraints_by_id.get(r, {}).get('name', '?')})" for r in refs
            )
            st.markdown(f"- {move.get('description', '')}  \n  rules: {cited or '—'}")
        prov = massing.get("provenance") or {}
        if prov.get("inferred_from"):
            st.write("inferred from: " + ", ".join(prov["inferred_from"]))
        if massing.get("geometry_file"):
            st.caption(f"COMPAS JSON: `{massing['geometry_file']}`")
        if massing.get("obj_file"):
            st.caption(f"OBJ: `{massing['obj_file']}`")


def page_massings(payload_path: Path) -> None:
    """Side-by-side rendering of the two example massings from a framework.json."""
    payload = load_payload(payload_path)
    fw = framework_body(payload)
    massings = fw.get("massings", []) or []

    st.subheader("Example massings")
    st.caption(
        "Variant A is the maximum envelope; variant B applies setbacks above the "
        "threshold height. Both are derived from the validated constraints; "
        "neither is a finished design."
    )

    if not massings:
        st.info("No massings on this framework. Run massing.generate_example_massings.")
        return

    constraints_by_id = {c["id"]: c for c in fw.get("constraints", {}).get("numerical", [])}
    palette = ["#4e79a7", "#f28e2b"]

    cols = st.columns(min(len(massings), 2))
    for idx, massing in enumerate(massings[:2]):
        with cols[idx]:
            _render_massing(massing, constraints_by_id, palette[idx % len(palette)])


# ---------------------------------------------------------------------------
# App entry
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="OMRT framework viewer", layout="wide")
    st.title("OMRT framework viewer")
    st.caption("Safety-net review surface. Not a dashboard.")

    mode = st.sidebar.radio("Mode", ["Review", "Massings", "Approach 2 — GML"])

    if mode == "Review":
        path_str = st.sidebar.text_input(
            "framework.json path",
            value="data/outputs/draka/framework.json",
        )
        path = Path(path_str)
        if not path.exists():
            st.warning(f"Not found: {path}")
            return
        prog_default = str(_resolve_sibling(path, None, "draka_programme.json"))
        geo_default = str(_resolve_sibling(path, None, "geo_context.json"))
        prog_override = st.sidebar.text_input("programme.json path", value=prog_default)
        geo_override = st.sidebar.text_input("geo_context.json path", value=geo_default)
        page_review(
            path,
            programme_path=Path(prog_override) if prog_override else None,
            geo_path=Path(geo_override) if geo_override else None,
        )
    elif mode == "Massings":
        path_str = st.sidebar.text_input(
            "framework.json path",
            value="data/outputs/draka/framework.json",
        )
        path = Path(path_str)
        if not path.exists():
            st.warning(f"Not found: {path}")
            return
        page_massings(path)
    elif mode == "Approach 2 — GML":
        geom_path = Path(
            st.sidebar.text_input(
                "geometry.json (Approach 1)",
                value="data/outputs/draka/geometry.json",
            )
        )
        gml_fw_path = Path(
            st.sidebar.text_input(
                "zone_framework_with_rules.json (Approach 2)",
                value="data/outputs/draka/approach_gml/zone_framework_with_rules.json",
            )
        )
        fw_path = Path(
            st.sidebar.text_input(
                "framework.json (Approach 1)",
                value="data/outputs/draka/framework.json",
            )
        )
        prog_path = Path(
            st.sidebar.text_input(
                "programme.json (Approach 1)",
                value="data/outputs/draka/programme.json",
            )
        )
        gml_params_path = Path(
            st.sidebar.text_input(
                "draka_gml_parameters.json (Approach 2)",
                value="data/outputs/draka/approach_gml/draka_gml_parameters.json",
            )
        )
        page_approach_gml(
            geometry_path=geom_path,
            gml_framework_path=gml_fw_path,
            framework_path=fw_path,
            programme_path=prog_path,
            gml_parameters_path=gml_params_path,
        )


if __name__ == "__main__":
    main()
else:
    main()
