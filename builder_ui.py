"""builder_ui.py - the REPORT BUILDER tab (any survey: Residential, Enterprise, ...)."""
import re

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import chartkit

import builder as B
import builder_charts as BC
import core
import export
import export_builder as EB
import general as G

FREQ, SCORE, NUM, CORR = "Profile & choice questions", "Satisfaction scores", "Numeric measures", "Indicator relationships"
TYPE_OF = {"freq": FREQ, "scores": SCORE, "numeric": NUM, "corr": CORR}
NONE_BY, NONE2 = "— Total only —", "— none —"
MAIN_STATS = ["n", "mean", "median", "mode", "std", "min", "max", "pct_high", "pct_low"]
VAL_NAMES = {"Count": "count", "Column %": "col_pct", "Row %": "row_pct"}
LEVELS = {"Overall score": "oss", "Pillars": "pillar", "Sub-groups": "sub", "Questions": "question"}
PCOL = export.PILLAR_COLORS


def _part_short(p):
    m = re.match(r"^(PART \d+|General)", p, re.I)
    return (m.group(1).title() if m else p[:18]).replace("Part", "Part")


def _fmt(v, fmt, dec, kind=""):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if kind == "base" or fmt == "int":
        return f"{v:,.0f}"
    if fmt == "pct":
        return f"{v * 100:.{dec}f}%"
    return f"{v:,.{dec}f}"


def render(df, form, tree, V, mask, filter_text, structure, survey_name, min_base, low_t, high_t):
    ss = st.session_state
    value_labels = {s["var"]: s["value_labels"] for s in structure.get("segments", []) if s.get("value_labels")}
    over = structure.get("labels", {})
    templates = structure.get("report_templates", [])

    items_all = G.build_inventory(form, df, value_labels, include_text=False)
    for it in items_all:
        it.label = over.get(it.name, it.label)
    by_name = {i.name: i for i in items_all}
    freq_items = [i for i in items_all if i.kind in ("single", "multi", "rating")]
    num_items = [i for i in items_all if i.kind == "numeric"]
    ind = B.indicator_rows(tree, form, V)
    in_tree = {q for p in tree for q in p.leaves(include_info=True)}
    other_rated = [i for i in items_all if i.kind == "rating" and i.name not in in_tree]
    pillars = [p.title for p in tree]

    cand = G.segment_candidates(df, form)
    pref = [s["var"] for s in structure.get("segments", [])] + structure.get("extra_segments", [])
    cand = [c for c in pref if c in cand] + [c for c in cand if c not in pref]

    def nm(c):
        if c in (NONE_BY, NONE2):
            return c
        lab = over.get(c) or (form.questions[c].label if c in form.questions else c)
        return f"{lab[:55]}  ({c})"

    def short(c):
        return (over.get(c) or (form.questions[c].label if c in form.questions else c)).split("  (")[0][:40]

    # ---------------------------------------------------------------- defaults
    def init(k, v):
        if k not in ss:
            ss[k] = v
    init("rb_type", FREQ); init("rb_by", NONE_BY); init("rb_by2", NONE2)
    init("rb_rows_freq", []); init("rb_rows_num", []); init("rb_rows_other", [])
    init("rb_levels", ["Overall score", "Pillars"]); init("rb_pillars", pillars)
    init("rb_values", ["Count", "Column %"]); init("rb_stats", ["mean", "n"]); init("rb_stats_more", [])
    init("rb_chart", None); init("rb_corr_vars", pillars); init("rb_rowsrc", "Topline indicators")

    # ---------------------------------------------------------------- template callback
    def apply_template():
        t = next((x for x in templates if x["name"] == ss.get("rb_tpl")), None)
        if not t:
            return
        ss["rb_type"] = TYPE_OF[t["type"]]
        by = t.get("by")
        ss["rb_by"] = by if by in cand else NONE_BY
        ss["rb_by2"] = t.get("by2") if t.get("by2") in cand else NONE2
        if t["type"] == "freq":
            ss["rb_rows_freq"] = [v for v in t.get("rows", []) if v in {i.name for i in freq_items}]
            ss["rb_values"] = [k for k, v in VAL_NAMES.items() if v in t.get("values", ["count", "col_pct"])]
        elif t["type"] == "numeric":
            ss["rb_rows_num"] = [v for v in t.get("rows", []) if v in {i.name for i in num_items}]
        elif t["type"] == "scores":
            ss["rb_rowsrc"] = "Topline indicators"
            ss["rb_levels"] = [k for k, v in LEVELS.items() if v in t.get("levels", ["oss", "pillar"])]
            ss["rb_pillars"] = pillars
        if t["type"] in ("scores", "numeric"):
            st_ = [k for k in t.get("stats", ["mean", "n"]) if k in B.STATS]
            ss["rb_stats"] = [k for k in st_ if k in MAIN_STATS]
            ss["rb_stats_more"] = [k for k in st_ if k not in MAIN_STATS]
        ss["rb_chart"] = t.get("chart")

    def add_part():
        p = ss.get("rb_part_add")
        if p and p != "—":
            cur = list(ss["rb_rows_freq"])
            ss["rb_rows_freq"] = cur + [i.name for i in freq_items if i.part == p and i.name not in cur]

    # ================================================================= layout
    st.markdown("### Custom report builder")
    st.caption("Build any table in five steps (left). Use a ready-made template to start. The report updates as you choose; "
               "download it as Excel, CSV or a chart image.")
    left, right = st.columns([1, 2.35], gap="large")

    with left:
        if templates:
            with st.container(border=True):
                st.markdown("**Quick start — ready-made reports**")
                st.selectbox("Template", [t["name"] for t in templates], index=None, placeholder="Choose a ready-made report…",
                             key="rb_tpl", label_visibility="collapsed")
                st.button("Use this template", on_click=apply_template, disabled=not ss.get("rb_tpl"), width="stretch")

        with st.container(border=True):
            st.markdown("**Step 1 · What kind of report?**")
            rtype = st.radio("type", [FREQ, SCORE, NUM, CORR], key="rb_type", label_visibility="collapsed",
                             captions=["Counts and % of answers (demographics, usage, ratings distribution)",
                                       "Mean, median and other statistics of rated indicators",
                                       "Spend, age, SIMs, branches …",
                                       "Correlation between indicators"])

        with st.container(border=True):
            st.markdown("**Step 2 · What should the rows show?**")
            rows_freq, rows_num, rows_ind, rows_other, corr_vars = [], [], [], [], []
            if rtype == FREQ:
                parts = list(dict.fromkeys(i.part for i in freq_items))
                st.multiselect("Questions", [i.name for i in freq_items], key="rb_rows_freq",
                               format_func=lambda n: f"{_part_short(by_name[n].part)} › {by_name[n].label[:75]}",
                               placeholder="Search and pick questions…")
                a, b = st.columns([3, 1])
                a.selectbox("Add a whole part", ["—"] + parts, key="rb_part_add", format_func=lambda p: p[:48], label_visibility="collapsed")
                b.button("Add", on_click=add_part, width="stretch")
                rows_freq = [by_name[n] for n in ss["rb_rows_freq"] if n in by_name]
            elif rtype == SCORE:
                st.radio("Rows from", ["Topline indicators", "Other rated questions"], key="rb_rowsrc", horizontal=True)
                if ss["rb_rowsrc"] == "Topline indicators":
                    st.pills("Levels", list(LEVELS), selection_mode="multi", key="rb_levels")
                    st.multiselect("Limit to pillars", pillars, key="rb_pillars")
                    lv = {LEVELS[k] for k in ss["rb_levels"]}
                    sel_p = set(ss["rb_pillars"])
                    rows_ind = [r["row"] for r in ind if r["row"].level in lv and (r["row"].level == "oss" or r["pillar"] in sel_p)]
                else:
                    st.multiselect("Rated questions", [i.name for i in other_rated], key="rb_rows_other",
                                   format_func=lambda n: f"{_part_short(by_name[n].part)} › {by_name[n].label[:75]}")
                    rows_other = [B.RowDef(by_name[n].label, n, [n], "question") for n in ss["rb_rows_other"] if n in by_name]
            elif rtype == NUM:
                st.multiselect("Numeric measures", [i.name for i in num_items], key="rb_rows_num",
                               format_func=lambda n: f"{by_name[n].label[:70]}  ({n})")
                rows_num = [B.RowDef(by_name[n].label, n, [n], "question", "numeric") for n in ss["rb_rows_num"] if n in by_name]
            else:
                st.multiselect("Indicators", pillars, key="rb_corr_vars")
                st.radio("Method", ["pearson", "spearman"], key="rb_corr_method", horizontal=True)
                corr_vars = ss["rb_corr_vars"]

        by = by2 = None
        pop0 = mask.copy()
        cats, seg = {}, None
        if rtype != CORR:
            with st.container(border=True):
                st.markdown("**Step 3 · How should the columns split the data?**")
                st.selectbox("Split by", [NONE_BY] + cand, key="rb_by", format_func=nm)
                opts2 = [NONE2] + [c for c in cand if c != ss["rb_by"] and not core.is_multi(form, c)]
                if ss["rb_by2"] not in opts2:
                    ss["rb_by2"] = NONE2
                st.selectbox("Then split each group by (optional)", opts2, key="rb_by2", format_func=nm, disabled=ss["rb_by"] == NONE_BY)
                with st.expander("Who to include (optional)"):
                    follow = st.checkbox("Only respondents who were asked this question (follows the questionnaire)", value=True, key="rb_skip")
                    pv = st.selectbox("Restrict to respondents where…", [NONE2] + [c for c in cand if not core.is_multi(form, c)],
                                      key="rb_popvar", format_func=nm)
                    if pv != NONE2:
                        d2, pc, plab = G.clean_text_segment(df, form, pv)
                        popts = core.segment_options(d2, form, pc, {pc: plab} if plab is not None else
                                                     ({pv: value_labels[pv]} if pv in value_labels else None))
                        sel = st.multiselect("…is", list(popts.values()), key=f"rb_popvals_{pv}")
                        inv = {v: k for k, v in popts.items()}
                        if sel:
                            pop0 &= core.segment_mask(d2, form, pc, [inv[x] for x in sel])
                by = ss["rb_by"] if ss["rb_by"] != NONE_BY else None
                by2 = ss["rb_by2"] if (by and ss["rb_by2"] != NONE2) else None
                if by:
                    seg = B.resolve_segment(df, form, by, by2, value_labels, pop0, follow)
                    opts, counts = seg["labels"], seg["counts"]
                    ntop = st.number_input("Number of largest groups to preselect", 2, max(2, len(opts)), min(10, max(2, len(opts))), key="rb_ntop")
                    top = sorted(opts, key=lambda c: -counts[c])[: int(ntop)]
                    chosen = st.multiselect(f"Groups to show ({len(opts)} available)", list(opts), default=[c for c in opts if c in top],
                                            format_func=lambda c: f"{opts[c]}  ·  n={counts[c]:,}",
                                            key=f"rb_cats_{seg['var']}_{int(ntop)}_{int(seg['pop'].sum())}")
                    cats = {c: opts[c] for c in chosen}
                    st.checkbox("Include Total column", value=True, key="rb_total")
                    if seg["rules"]:
                        st.caption("Asked only if: " + "; ".join(seg["rules"]))

        with st.container(border=True):
            st.markdown("**Step 4 · Which measures?**" if rtype in (SCORE, NUM) else "**Step 4 · Which values?**" if rtype == FREQ else "**Step 4 · Options**")
            keys = []
            if rtype == FREQ:
                st.pills("Values", list(VAL_NAMES), selection_mode="multi", key="rb_values", label_visibility="collapsed")
                st.checkbox("Show base (N) under each question", value=True, key="rb_base")
            elif rtype in (SCORE, NUM):
                st.pills("Statistics", MAIN_STATS, selection_mode="multi", key="rb_stats", format_func=lambda k: B.STATS[k],
                         label_visibility="collapsed")
                with st.expander("More measures"):
                    st.multiselect("More", [k for k in B.STATS if k not in MAIN_STATS], key="rb_stats_more",
                                   format_func=lambda k: B.STATS[k], label_visibility="collapsed")
                with st.expander("What do these measures mean?"):
                    st.markdown("- **N** – number of valid answers\n- **Mean** – average score (1–10)\n- **Median** – middle score; half of the answers are above it\n"
                                "- **Mode** – most frequent score\n- **Std. deviation** – how spread out the scores are\n"
                                "- **% High scores** – share of ratings from 8 to 10\n- **% Low scores** – share of ratings from 1 to 5\n"
                                "- **Weighted score** – Mean × N (sum of all ratings)")
                sel_k = set(ss["rb_stats"]) | set(ss["rb_stats_more"])
                keys = [k for k in B.STATS if k in sel_k]
                if rtype == NUM:
                    keys = [k for k in keys if k not in B.PCT_STATS]

        with st.container(border=True):
            st.markdown("**Step 5 · Display options**")
            if rtype != CORR:
                st.checkbox("Mark significant differences (95%)", value=False, key="rb_sig",
                            help="▲▼ = significantly higher / lower than all other respondents.")
                c1, c2 = st.columns(2)
                dec = c1.number_input("Decimals", 0, 4, 1 if rtype == FREQ else 2, key=f"rb_dec_{rtype}")
                layout_lbl = c2.radio("Arrange columns by", ["Statistic", "Segment"], key="rb_layout", horizontal=False)
            st.text_input("Report title (optional)", key="rb_title", placeholder="Auto")

    # ================================================================= build the report
    segs, pop = {"Total": pop0}, pop0
    if seg is not None:
        pop = seg["pop"]
        segs = B.segment_masks(seg["df"], form, seg["var"], cats, pop, include_total=ss.get("rb_total", True))
        dfg = seg["df"]
    else:
        dfg = df
    base_txt = f"Base: {int(pop.sum()):,} respondents"
    seg_title = " › ".join(short(x) for x in (by, by2) if x) if by else ""

    with right:
        if rtype == CORR:
            _corr_view(df, form, V, tree, corr_vars, ss.get("rb_corr_method", "pearson"), pop0, base_txt, survey_name)
            return
        rows_ready = bool(rows_freq or rows_ind or rows_other or rows_num)
        if not rows_ready or (rtype in (SCORE, NUM) and not keys) or (rtype == FREQ and not ss["rb_values"]):
            st.markdown("#### Report")
            st.info("Pick the rows in Step 2" + (" and at least one measure in Step 4" if rtype in (SCORE, NUM) else
                    " and at least one value in Step 4" if rtype == FREQ else "") + " — or choose a template to start.")
            return
        if seg is not None and not cats and not ss.get("rb_total", True):
            st.info("Select at least one group in Step 3.")
            return

        sig = bool(ss.get("rb_sig")) and by is not None
        layout = "block" if layout_lbl == "Statistic" else "segment"
        sub = base_txt + (f"  ·  Filter: {filter_text}" if filter_text and not filter_text.startswith("None") else "")
        title = ss.get("rb_title") or (
            {FREQ: "Profile by", SCORE: "Satisfaction scores by", NUM: "Measures by"}[rtype] + f" {seg_title}" if seg_title
            else {FREQ: "Profile", SCORE: "Satisfaction scores", NUM: "Numeric measures"}[rtype])

        def make(dfx, segs_, pop_, ttl, subtitle):
            if rtype == FREQ:
                long = B.freq_long(dfx, form, rows_freq, segs_, pop_, value_labels, sig)
                return B.make_freq_table(long, [VAL_NAMES[v] for v in ss["rb_values"]], list(segs_), ttl, subtitle,
                                         layout, int(dec), ss.get("rb_base", True))
            rows = (rows_ind + rows_other) if rtype == SCORE else rows_num
            long = B.score_long(dfx, form, V, rows, segs_, pop_, keys, sig)
            return B.make_scores_table(long, keys, list(segs_), ttl, subtitle, layout, int(dec),
                                       "scores" if rtype == SCORE else "numeric")

        rt = make(dfg, segs, pop, title, sub)

        st.markdown(f"#### {title}")
        st.caption(sub + (f"  ·  segment question asked only if: {'; '.join(seg['rules'])}" if seg and seg["rules"] else ""))
        t_table, t_chart, t_dl = st.tabs(["📋 Table", "📊 Chart", "⬇ Download"])
        with t_table:
            _show_table(rt, low_t, high_t, min_base)
        with t_chart:
            chart_kind = _chart_view(rt, rtype, "rb")
        with t_dl:
            st.download_button("⬇ CSV (this table)", _csv(rt), f"{_fname(title)}.csv", "text/csv", width="stretch")
            if st.button("Prepare Excel for this report", width="stretch"):
                with st.spinner("Building workbook…"):
                    ss["rb_xlsx"] = (title, EB.tables_to_excel([{"name": title, "table": rt, "chart": chart_kind}], low_t, high_t))
            if ss.get("rb_xlsx"):
                st.download_button("⬇ Download Excel (table + charts)", ss["rb_xlsx"][1], f"{_fname(ss['rb_xlsx'][0])}.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
                st.caption(f"Prepared: {ss['rb_xlsx'][0]}. Click *Prepare* again after changing the report.")
            st.divider()
            st.markdown("**Report pack** — the same report for several break-downs, one sheet each")
            pack_vars = st.multiselect("Break-downs", cand, key="rb_pack_vars", format_func=nm,
                                       placeholder="e.g. Gender, Location, Region, SIM type …")
            if st.button("Prepare report pack", disabled=not pack_vars, width="stretch"):
                with st.spinner("Building report pack…"):
                    out = []
                    for v in pack_vars:
                        s2 = B.resolve_segment(df, form, v, None, value_labels, pop0, ss.get("rb_skip", True))
                        top = sorted(s2["labels"], key=lambda c: -s2["counts"][c])[: int(ss.get("rb_ntop", 10))]
                        sg = B.segment_masks(s2["df"], form, s2["var"], {c: s2["labels"][c] for c in top}, s2["pop"])
                        ttl = f"{ {FREQ: 'Profile', SCORE: 'Satisfaction scores', NUM: 'Measures'}[rtype] } by {short(v)}"
                        out.append({"name": f"By {short(v)}", "chart": chart_kind,
                                    "table": make(s2["df"], sg, s2["pop"], ttl, f"Base: {int(s2['pop'].sum()):,} respondents")})
                    ss["rb_pack"] = EB.tables_to_excel(out, low_t, high_t, f"{survey_name} · report pack")
            if ss.get("rb_pack"):
                st.download_button("⬇ Download report pack", ss["rb_pack"], f"{_fname(survey_name)}_report_pack.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")


def _fname(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)).strip("_")[:60] or "report"


def _csv(rt):
    f = rt.flat()
    f = f.copy()
    if rt.family == "freq":
        f.loc[f["Answer"] != "", "Question"] = f.loc[f["Answer"] != "", "Question"]
    return f.to_csv(index=False).encode("utf-8-sig")


def _show_table(rt, low_t, high_t, min_base, highlight=False):
    d = rt.data.reset_index(drop=True)
    if rt.family == "freq":
        label = [q if k == "qhead" else a for q, a, k in zip(d["Question"], d["Answer"], d["_kind"])]
        label = [("\u2003" + x) if k in ("row", "base") else x for x, k in zip(label, d["_kind"])]
    else:
        label = [("\u2003" * ({"oss": 0, "pillar": 0, "sub": 1}.get(k, 2))) + x for x, k in zip(d["Indicator"], d["_kind"])]
    out = pd.DataFrame({"Question / Answer" if rt.family == "freq" else "Indicator / question": label})
    for c in rt.cols:
        nm_ = rt.label(c)
        vals = []
        for i, v in enumerate(d[c["key"]]):
            kind = d.at[i, "_kind"]
            s = "" if kind == "qhead" else _fmt(v, c["fmt"], rt.decimals, kind)
            a = rt.sig.at[i, c["key"]] if rt.sig is not None and c["key"] in rt.sig.columns and i in rt.sig.index else ""
            vals.append(s + (f" {a}" if a and s else ""))
        out[nm_] = vals
    kinds = list(d["_kind"])
    pidx, qidx, color = -1, -1, []
    for k in kinds:
        if k == "pillar": pidx += 1
        if k == "qhead": qidx += 1
        color.append(PCOL[(qidx if rt.family == "freq" else max(pidx, 0)) % 8])

    def style(row):
        i = row.name
        k, c = kinds[i], color[i]
        css = {"oss": "background-color:#FFD966;color:#000;font-weight:bold",
               "pillar": f"background-color:#{c};color:#fff;font-weight:bold",
               "qhead": f"background-color:#{c};color:#fff;font-weight:bold",
               "sub": f"background-color:#{export._tint(c, .35)};color:#000;font-weight:bold;font-style:italic",
               "base": "background-color:#F2F2F2;color:#595959;font-style:italic"}.get(k, "background-color:#fff;color:#111")
        out_ = [css] * len(row)
        if rt.family == "scores" and k != "qhead":
            for j, c_ in enumerate(rt.cols, 1):
                if c_["block"] == "Mean":
                    v = d.at[i, c_["key"]]
                    if pd.notna(v) and 1 <= v <= 10:
                        bg, fg = export.BAND["low"] if v < low_t else export.BAND["high"] if v >= high_t else export.BAND["mid"]
                        out_[j] = f"background-color:#{bg};color:#{fg};font-weight:bold"
        if highlight and rt.family == "scores" and k != "qhead":
            seg_cols = [(j, c_) for j, c_ in enumerate(rt.cols, 1) if c_["block"] == "Mean" and c_["seg"] != "Total"]
            vals = [(d.at[i, c_["key"]], j) for j, c_ in seg_cols if pd.notna(d.at[i, c_["key"]])]
            if len(vals) > 1:
                out_[max(vals)[1]] = "background-color:#2E9E4F;color:#fff;font-weight:bold"
                out_[min(vals)[1]] = "background-color:#D9534F;color:#fff;font-weight:bold"
        if rt.sig is not None and not highlight:
            for j, c_ in enumerate(rt.cols, 1):
                a = rt.sig.at[i, c_["key"]] if c_["key"] in rt.sig.columns and i in rt.sig.index else ""
                if a in ("▲", "▼"):
                    out_[j] = f"background-color:#{'C6EFCE' if a == '▲' else 'FFC7CE'};color:#000;font-weight:bold"
        return out_

    height = int(min(740, 38 + 35 * len(out)))
    st.dataframe(out.style.apply(style, axis=1), hide_index=True, width="stretch", height=height)
    st.caption(f"{len(out):,} rows")


def _chart_view(rt, rtype, kp="rb"):
    cf = rt.chart
    if cf is None or not len(cf):
        return None
    c1, c2, c3 = st.columns([2, 2, 1])
    if rt.family == "freq":
        qs = list(dict.fromkeys(cf["Item"]))
        q = c1.selectbox("Question", qs, key=f"{kp}_cq_{abs(hash(tuple(qs))) % 99999}", format_func=lambda s: s[:70])
        meas = {"Count": ("Count", "int"), "Column %": ("Col", "pct"), "Row %": ("Row", "pct")}
        m = c2.selectbox("Value", rt.blocks, key=f"{kp}_cv_{abs(hash(tuple(rt.blocks))) % 99999}")
        col, fmt = meas[m]
        ck = c3.selectbox("Type", BC.CHART_TYPES_FREQ, key=f"{kp}_ct")
        labels = st.checkbox("Data labels", value=True, key=f"{kp}_cl")
        g = cf[cf["Item"] == q][["Answer", "Segment", col]].rename(columns={col: "Value"}).copy()
        if "Total" in rt.segments and not st.checkbox("Include Total", value=True, key=f"{kp}_ctot"):
            g = g[g.Segment != "Total"]
        g["Item"] = g["Answer"]
        order = list(dict.fromkeys(g["Answer"]))
        chartkit.chart(BC.build(g, ck, fmt, rt.decimals, q[:90], labels, order=order))
        return ck
    blk = c1.selectbox("Statistic", rt.blocks, key=f"{kp}_cb_{abs(hash(tuple(rt.blocks))) % 99999}")
    sub = cf[cf["Block"] == blk]
    items = list(dict.fromkeys(sub["Item"]))
    pref = [i for i in dict.fromkeys(sub[sub.Level.isin(["oss", "pillar"])]["Item"])] or items
    sel = c2.multiselect("Rows", items, default=pref[:10], key=f"{kp}_cr_{abs(hash((blk, tuple(items)))) % 99999}",
                         format_func=lambda s: s[:50])
    ck = c3.selectbox("Type", BC.CHART_TYPES_SCORE, key=f"{kp}_ct2")
    labels = st.checkbox("Data labels", value=True, key=f"{kp}_cl2")
    g = sub[sub.Item.isin(sel)]
    if "Total" in rt.segments and not st.checkbox("Include Total", value=True, key=f"{kp}_ctot2"):
        g = g[g.Segment != "Total"]
    if not len(g):
        st.info("Select rows to chart.")
        return ck
    chartkit.chart(BC.build(g, ck, g["Fmt"].iloc[0], rt.decimals, f"{blk}", labels, order=sel))
    return ck


def _corr_view(df, form, V, tree, names, method, pop0, base_txt, survey_name):
    st.markdown("#### Indicator relationships")
    st.caption(base_txt + f"  ·  {method.title()} correlation of respondent-level pillar scores")
    if len(names) < 2:
        st.info("Pick at least two indicators in Step 2.")
        return
    c = B.corr_table(df, form, V, tree, names, method, pop0)
    m = c.reset_index(names="A").melt(id_vars="A", var_name="B", value_name="r")
    m["lab"] = m["r"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}")
    order = list(c.columns)
    base = alt.Chart(m).encode(x=alt.X("B:N", sort=order, title=None, axis=alt.Axis(labelAngle=-35, labelLimit=240)),
                               y=alt.Y("A:N", sort=order, title=None, axis=alt.Axis(labelLimit=240)))
    heat = base.mark_rect().encode(color=alt.Color("r:Q", scale=alt.Scale(domain=[-1, 0, 1], range=["#F4B6B6", "#FFFFFF", "#63BE7B"]),
                                                   legend=alt.Legend(title="r")), tooltip=["A", "B", alt.Tooltip("r:Q", format=".2f")])
    chartkit.chart(BC._style((heat + base.mark_text(fontSize=12, color="#111").encode(text="lab:N")).properties(
        height=max(260, 40 * len(order)), width=max(360, 80 * len(order)))))
    st.dataframe(c.round(2), width="stretch")
    st.download_button("⬇ Excel", EB.corr_to_excel(c, f"{survey_name} · indicator correlations", base_txt),
                       "indicator_correlations.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
