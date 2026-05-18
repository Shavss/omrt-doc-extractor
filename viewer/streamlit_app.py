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

A side-by-side diff view compares two framework.json files (typically
two passes of dual-pass extraction) and lists numerical constraints
that disagree by ID.

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
          <strong>{c['name']}</strong>
          <code>{c['id']}</code><br/>
          <span style="font-size:1.1em;">{format_value(c['value'], c['unit'])}</span>
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
        text[i][j] = (
            f"{_fmt(rng[0])}–{_fmt(rng[1])}"
            if rng[0] is not None else ""
        )
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
        tally[t] = tally.get(t, 0.0) + float(
            item.get("fraction_of_total_dwellings") or 0.0
        )
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
    constraint_citations = [c for c in inferred_from if not any(
        tok in c.lower() for tok in GEO_SOURCE_TOKENS
    )]
    st.caption(
        f"Confidence: {conf:.2f}, anchored in {len(constraint_citations)} "
        f"explicit constraint citations." if conf is not None else ""
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
                bar_items = {
                    str(d): 1 for d in dom[:5]
                } if isinstance(dom[0], str) else {
                    str(d.get("use", "?")): int(d.get("count", 0)) for d in dom[:5]
                }
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
            chunks.append(
                f"<span style='color:{COLOURS['green']};'>✓</span> "
                f"<code>{src}</code>"
            )
        elif src in failed:
            chunks.append(
                f"<span style='color:{COLOURS['red']};'>✗</span> "
                f"<code>{src}</code>"
            )
        else:
            chunks.append(
                f"<span style='color:{COLOURS['grey']};'>•</span> "
                f"<code>{src}</code>"
            )
    st.markdown(
        "<div style='margin-top:8px;font-size:0.9em;'>Sources: "
        + " · ".join(chunks)
        + "</div>",
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
        st.info(
            "Zone programme summary not found. Re-run the pipeline to "
            "generate it."
        )
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
                "Categories": ", ".join(
                    sorted((z.get("rules_by_category") or {}).keys())
                )
                or "—",
            }
        )

    import pandas as pd

    df = pd.DataFrame(rows)
    styled = df.style.apply(
        lambda row: [_row_colour(zone_summaries[row.name])] * len(row),
        axis=1,
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    zone_names = [
        z.get("zone_name") or z.get("zone_id") or "?" for z in zone_summaries
    ]
    selected = st.selectbox("Inspect zone", zone_names, key="zone_inspect")
    z = zone_summaries[zone_names.index(selected)]

    with st.expander(f"Details — {selected}", expanded=True):
        st.write(f"**Zone codes:** {', '.join(z.get('zone_codes') or []) or '—'}")
        overlays = z.get("acoustic_overlays") or []
        if overlays:
            st.write(f"**Acoustic overlays:** {', '.join(overlays)}")
        h = z.get("height_m")
        h_txt = f"{h} m" if h is not None else "—"
        st.write(
            f"**Height:** {h_txt} (source: {z.get('height_source') or '—'})"
        )
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

    header_banner = (
        payload.get("header", {}).get("banner")
        or ("Human-reviewed output. Verified by reviewer." if reviewed
            else "PROTOTYPE OUTPUT, NOT VERIFIED")
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

    if not reviewed:
        if st.button("Mark as verified", type="primary"):
            meta["verification_status"] = "reviewed"
            if "header" in payload:
                payload["header"]["verification_status"] = "reviewed"
                payload["header"]["banner"] = (
                    "Human-reviewed output. Verified by reviewer."
                )
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
                _render_massing(
                    m, constraints_by_id_for_massings, palette[idx % len(palette)]
                )
        st.markdown("---")

    # --- Programme proposal ---
    programme_inline = fw.get("programme")
    programme_loaded: dict[str, Any] | None = None
    if programme_path and programme_path.exists():
        try:
            programme_loaded = load_payload(programme_path)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load programme file {programme_path}: {exc}")
    programme_data = programme_loaded or programme_inline
    if programme_data:
        render_programme_panel(programme_data)
    else:
        st.markdown("## Programme proposal")
        st.info(
            "No programme proposal found. Run programme inference (Stage 5) to populate."
        )
    st.markdown("---")

    # --- Neighbourhood context ---
    if geo_path and geo_path.exists():
        try:
            geo_data = load_payload(geo_path)
            render_neighbourhood_panel(geo_data)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load geo_context file {geo_path}: {exc}")
    else:
        st.markdown("## Neighbourhood context")
        st.info("No geo enrichment data. Run enrich_geo() to populate.")
    st.markdown("---")

    # --- Constraints table (bottom) ---
    constraints = fw.get("constraints", {})
    numerical = constraints.get("numerical", [])

    disagreements = [
        c for c in numerical
        if (c.get("cross_validation") or {}).get("agreement") == "disagreement"
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
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load {zone_summary_path}: {exc}")
    if zone_summary is not None:
        render_zones_panel(zone_summary)
    else:
        st.markdown("## Zones")
        st.info(
            "Zone programme summary not found. Re-run the pipeline to "
            "generate it."
        )
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


def _mesh3d_from_triangles(
    triangles: list[list[list[float]]], colour: str
) -> go.Mesh3d | None:
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

    constraints_by_id = {
        c["id"]: c for c in fw.get("constraints", {}).get("numerical", [])
    }
    palette = ["#4e79a7", "#f28e2b"]

    cols = st.columns(min(len(massings), 2))
    for idx, massing in enumerate(massings[:2]):
        with cols[idx]:
            _render_massing(massing, constraints_by_id, palette[idx % len(palette)])


def page_diff(path_a: Path, path_b: Path) -> None:
    fw_a = framework_body(load_payload(path_a))
    fw_b = framework_body(load_payload(path_b))

    by_id_a = {c["id"]: c for c in fw_a.get("constraints", {}).get("numerical", [])}
    by_id_b = {c["id"]: c for c in fw_b.get("constraints", {}).get("numerical", [])}

    all_ids = sorted(set(by_id_a) | set(by_id_b))

    diffs: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]] = []
    for cid in all_ids:
        a = by_id_a.get(cid)
        b = by_id_b.get(cid)
        if a is None or b is None or a.get("value") != b.get("value"):
            diffs.append((cid, a, b))

    st.caption(f"{len(diffs)} differences across {len(all_ids)} constraints.")

    for cid, a, b in diffs:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Pass A** · `{cid}`")
            if a is None:
                st.write("_missing_")
            else:
                st.write(format_value(a["value"], a["unit"]))
                st.caption(
                    f"conf {a.get('confidence', {}).get('score', 0):.2f} · "
                    f"{a.get('provenance', {}).get('document')} "
                    f"p.{a.get('provenance', {}).get('page')}"
                )
                if a.get("provenance", {}).get("quoted_text"):
                    st.markdown(f"> {a['provenance']['quoted_text']}")
        with col2:
            st.markdown(f"**Pass B** · `{cid}`")
            if b is None:
                st.write("_missing_")
            else:
                st.write(format_value(b["value"], b["unit"]))
                st.caption(
                    f"conf {b.get('confidence', {}).get('score', 0):.2f} · "
                    f"{b.get('provenance', {}).get('document')} "
                    f"p.{b.get('provenance', {}).get('page')}"
                )
                if b.get("provenance", {}).get("quoted_text"):
                    st.markdown(f"> {b['provenance']['quoted_text']}")
        st.markdown("---")


# ---------------------------------------------------------------------------
# App entry
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="OMRT framework viewer", layout="wide")
    st.title("OMRT framework viewer")
    st.caption("Safety-net review surface. Not a dashboard.")

    mode = st.sidebar.radio("Mode", ["Review", "Massings", "Diff two passes"])

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
    else:
        path_a = Path(st.sidebar.text_input("Pass A path", "data/outputs/draka/pass_a.json"))
        path_b = Path(st.sidebar.text_input("Pass B path", "data/outputs/draka/pass_b.json"))
        if not path_a.exists() or not path_b.exists():
            st.warning("Provide two existing framework.json paths.")
            return
        page_diff(path_a, path_b)


if __name__ == "__main__":
    main()
else:
    main()
