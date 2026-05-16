"""Streamlit viewer for human review of extracted ParametricFrameworks.

Single page, four panels:
1. Project overview (metadata, plan_id, source documents, verification status)
2. Constraints (numerical + geometric + narrative) with colour coding:
     red    confidence < 0.85 OR imro_api_disagreement flag
     amber  inferred values, dual_pass_disagreement, ambiguous_clause
     green  human-verified (verification_status='reviewed')
3. Programme proposal with reasoning trace
4. Example massings (two variants, plotly Mesh3d with 3D BAG context)

IMRO disagreements get a dedicated section at the top because they are
the strongest Scenario 1 signal. Each shows extracted value, authoritative
value, and the quoted source text side by side.

Click any value to see Provenance (document, page, quoted text). The
banner at the top reads "PROTOTYPE OUTPUT, NOT VERIFIED" until the PM
marks the project as reviewed.

Stage 6 of the build plan.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="OMRT doc-extractor viewer", layout="wide")
st.title("OMRT doc-extractor viewer")
st.info("TODO Stage 6: implement viewer")
