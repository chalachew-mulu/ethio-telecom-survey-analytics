"""compare_ui.py - 'Compare segments' tab: indicators x (Total + categories of the chosen variable)."""
import pandas as pd
import streamlit as st

import builder as B
import builder_ui as BU
import export_builder as EB

PRESETS = {"Pillars only": ["pillar"], "Pillars & sub-groups": ["pillar", "sub"],
           "All indicators (incl. questions)": ["pillar", "sub", "question"], "Custom": None}
SHOW = {"Mean": "mean", "Respondents (N)": "n", "Median": "median", "% High scores (8–10)": "pct_high", "% Low scores (1–5)": "pct_low",
        "Weighted score (Mean × N)": "sum", "Std. deviation": "std", "Average of question means": "avg_q"}


def _sort(rt, key, asc):
    d = rt.data
    order = d.sort_values(key, ascending=asc, na_position="last").index
    rt.data = d.loc[order].reset_index(drop=True)
    if rt.sig is not None:
        rt.sig = rt.sig.loc[order].reset_index(drop=True)
    return rt


def render(df_g, form, tree, V, seg, cats, var_title, filter_text, survey_name, min_base, low_t, high_t):
    ss = st.session_state
    if seg is None or not cats:
        st.info("Choose **Split the report by** in *2 · Choose how to split the report* (sidebar) and tick the groups to show. "
                "The table will have **Total** followed by each group.")
        return
    pop = seg["pop"]
    pillars = [p.title for p in tree]
    ind = B.indicator_rows(tree, form, V)

    st.markdown(f"##### Indicator scores by {var_title}")
    note = f"Population: {int(pop.sum()):,} respondents"
    if seg["rules"]:
        note += "  ·  asked only if " + "; ".join(seg["rules"])
    st.caption(note)

    a, b = st.columns([3, 2])
    preset = a.radio("Rows", list(PRESETS), horizontal=True, key="cmp_preset")
    levels = PRESETS[preset]
    if levels is None:
        lv = a.pills("Levels", list(BU.LEVELS)[1:], selection_mode="multi", default=["Pillars"], key="cmp_levels")
        levels = [BU.LEVELS[x] for x in lv]
    sel_p = b.multiselect("Limit to pillars", pillars, placeholder="All pillars", key="cmp_pillars")
    inc_oss = b.checkbox("Include overall score (OSS)", value=True, key="cmp_oss")

    show = st.pills("Show", list(SHOW), selection_mode="multi", default=["Mean"], key="cmp_show")
    keys = [SHOW[x] for x in show]
    o1, o2, o3, o4 = st.columns(4)
    sig = o1.checkbox("Flag significant differences", value=False, key="cmp_sig", help="▲▼ = significantly higher / lower than all other respondents (95%).")
    hl = o2.checkbox("Highlight best and lowest group", value=False, key="cmp_hl", help="Green = highest group, red = lowest group, in each row.")
    tot = o3.checkbox("Show Total column", value=True, key="cmp_total")
    dec = o4.number_input("Decimals", 0, 4, 2, key="cmp_dec")

    rows = [r["row"] for r in ind if (r["row"].level == "oss" and inc_oss) or
            (r["row"].level in levels and (not sel_p or r["pillar"] in sel_p))]
    if not rows or not keys:
        st.info("Select at least one row level and one statistic.")
        return

    segs = B.segment_masks(df_g, form, seg["var"], cats, pop, include_total=tot)
    long = B.score_long(df_g, form, V, rows, segs, pop, keys, sig and len(cats) > 0)
    title = f"Indicator scores by {var_title}"
    sub = f"Population: {int(pop.sum()):,} respondents" + (f"  ·  Filter: {filter_text}" if not filter_text.startswith("None") else "")
    layout = "block" if len(keys) > 1 else "segment"
    rt = B.make_scores_table(long, keys, list(segs), title, sub, layout, int(dec), "scores")

    s1, s2 = st.columns([3, 1])
    cols = {rt.label(c): c["key"] for c in rt.cols}
    single_level = len({r.level for r in rows if r.level != "oss"}) <= 1
    by = s1.selectbox("Sort rows by", ["Script order"] + list(cols), disabled=not single_level, key="cmp_sort",
                      help="Available when one row level is shown (e.g. Pillars only).")
    asc = s2.radio("Order", ["High → low", "Low → high"], horizontal=False, key="cmp_asc", disabled=by == "Script order") == "Low → high"
    if by != "Script order" and single_level:
        rt = _sort(rt, cols[by], asc)

    BU._show_table(rt, low_t, high_t, min_base, highlight=hl)
    small = [f"{n} (n={int(m.sum())})" for n, m in segs.items() if n != "Total" and int(m.sum()) < int(min_base)]
    if small:
        st.warning(f"Small bases (fewer than {int(min_base)} respondents) — read with caution: " + ", ".join(small))

    with st.expander("Chart"):
        chart_kind = BU._chart_view(rt, BU.SCORE, kp="cmp")
    d1, d2 = st.columns(2)
    d1.download_button("⬇ CSV", BU._csv(rt), f"{BU._fname(title)}.csv", "text/csv", width="stretch")
    if d2.button("Prepare Excel", width="stretch", key="cmp_prep"):
        with st.spinner("Building workbook…"):
            ss["cmp_xlsx"] = (title, EB.tables_to_excel([{"name": f"By {var_title}"[:31], "table": rt, "chart": chart_kind or "Clustered columns"}], low_t, high_t))
    if ss.get("cmp_xlsx"):
        st.download_button("⬇ Download Excel (table + chart)", ss["cmp_xlsx"][1], f"{BU._fname(ss['cmp_xlsx'][0])}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
