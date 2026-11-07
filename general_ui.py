"""general_ui.py - the 'General report' tab of the app (all parts of the questionnaire)."""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import charts
import core
import export
import export_general
import general as G


def _part_css(color):
    return f"background-color:#{export._tint(color, .30)};color:#111;font-weight:bold"


def render(df, form, tree, V, mask, filter_text, structure, min_base, low_t, high_t):
    value_labels = {s["var"]: s["value_labels"] for s in structure.get("segments", []) if s.get("value_labels")}

    # ---------------------------------------------------------------- controls
    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 1, 1])
        include_text = c1.checkbox("Include open-text questions (top answers)", value=False)
        items_all = G.build_inventory(form, df, value_labels, include_text)
        parts = G.parts_of(items_all)
        sel_parts = c1.multiselect("Parts of the questionnaire", parts, default=parts,
                                   format_func=lambda p: p[:70])
        kinds = c2.multiselect("Question types", list(G.KIND_NAMES), default=["rating", "numeric", "single", "multi"],
                               format_func=lambda k: G.KIND_NAMES[k])
        stat_keys = c2.multiselect("Statistics to show (rating & numeric)", list(G.STATS), default=G.DEFAULT_STATS,
                                   format_func=lambda k: G.STATS[k])
        cands = G.segment_candidates(df, form)
        nm = lambda c: c if c == "— none —" else f"{(form.questions[c].label[:48] if c in form.questions else c)}  ({c})"
        var = c3.selectbox("Break down by (any variable)", ["— none —"] + cands, format_func=nm,
                           help="Any single-choice, text (e.g. city) or calculated variable.")
        var2 = c3.selectbox("…then by (optional, nested: Region › City)",
                            ["— none —"] + [c for c in cands if c != var and not core.is_multi(form, c)],
                            format_func=nm, disabled=(var == "— none —"))
        a1, a2 = c3.columns(2)
        alpha = a1.selectbox("Significance level", [0.10, 0.05, 0.01], index=1)
        min_diff = a2.number_input("Min. gap (points)", 0.0, 3.0, 0.3, 0.1)

        # ---- drill-down + skip logic
        d1, d2, d3 = st.columns([1, 1, 1])
        within = d1.selectbox("Drill down: only respondents where…", ["— none —"] + [c for c in cands if not core.is_multi(form, c)],
                              format_func=nm, help="e.g. Telecom region = Oromia → then break down by city.")
        wvals, wcol, df_w = [], within, df
        if within != "— none —":
            df_w, wcol, wlab = G.clean_text_segment(df, form, within)
            wopts = core.segment_options(df_w, form, wcol, {wcol: wlab} if wlab is not None else
                                         ({within: value_labels[within]} if within in value_labels else None))
            wsel = d2.multiselect("…is", list(wopts.values()))
            winv = {v: k for k, v in wopts.items()}
            wvals = [winv[x] for x in wsel]
        follow = d3.checkbox("Follow the script's skip logic", value=True,
                             help="Only respondents who were actually asked the segment question are used "
                                  "(e.g. city = Other Regions residents only), and 'rest' means the other categories.")

    # ---- effective data / population for everything in this tab
    seg_var, df_g, vlabels = None, df, dict(value_labels)
    def _clean(v):
        nonlocal df_g
        d2, c2, lab = G.clean_text_segment(df_g, form, v)
        if lab is not None:
            df_g = d2; vlabels[c2] = lab
        return c2
    if var != "— none —":
        seg_var = _clean(var)
        if var2 != "— none —":
            col2 = _clean(var2)                      # clean first, then build the nested segment on the updated data
            df_g, seg_var, combo_lab = G.combo_column(df_g, form, seg_var, col2, vlabels)
            vlabels[seg_var] = combo_lab
    tab_mask = mask.copy()
    if within != "— none —" and wvals:
        tab_mask &= core.segment_mask(df_w, form, wcol, wvals)
    rules, ok_rules = [], True
    if var != "— none —" and follow:
        am, rules, ok_rules = G.asked_mask(df, form, var, [var2] if var2 != "— none —" else [])
        tab_mask &= am
    pop = tab_mask
    if var != "— none —":
        msg = f"**Analysis population: {int(pop.sum()):,} of {len(df):,} respondents.**"
        if rules:
            msg += " The segment question was asked only if: " + "; ".join(rules) + "."
        if not ok_rules:
            msg += " (Some skip-logic rules could not be interpreted and were not applied.)"
        st.info(msg)
    elif within != "— none —" and wvals:
        st.info(f"**Analysis population: {int(pop.sum()):,} respondents** (drill-down applied).")
    if int(pop.sum()) == 0:
        st.warning("No respondents in this selection.")
        return

    cats = {}
    if seg_var:
        opts = core.segment_options(df_g, form, seg_var, {seg_var: vlabels[seg_var]} if seg_var in vlabels else None)
        if core.is_multi(form, seg_var):
            counts = {c: int(core.segment_mask(df_g, form, seg_var, [c])[pop].sum()) for c in opts}
        else:
            vc = core.segment_codes(df_g, seg_var)[pop].value_counts()
            counts = {c: int(vc.get(c, 0)) for c in opts}
        opts = {c: l for c, l in opts.items() if counts[c] > 0}
        n_top = st.number_input("Show the largest N categories (default selection)", 2, max(2, len(opts)), min(10, max(2, len(opts))),
                                help=f"{len(opts)} categories available. Change the selection below freely.")
        top = sorted(opts, key=lambda c: -counts[c])[:int(n_top)]
        chosen = st.multiselect(f"Categories to compare ({len(opts)} available)", list(opts), default=top,
                                format_func=lambda c: f"{opts[c]} (n={counts[c]:,})", key=f"cats_{seg_var}_{int(n_top)}_{int(pop.sum())}")
        cats = {c: opts[c] for c in chosen}
    var_title = " › ".join(nm(x).split("  (")[0] for x in (var, var2) if x != "— none —") if seg_var else None
    filter_text = filter_text + (f" | Segment: {var_title}" if var_title else "") + \
        (f" | Drill-down: {within} in {[wopts[c] for c in wvals]}" if within != "— none —" and wvals else "")
    df, mask, var_ = df_g, pop, seg_var
    value_labels = vlabels

    items = [i for i in items_all if i.part in sel_parts and i.kind in kinds]
    if not items:
        st.warning("Nothing selected.")
        return
    pcolor = {p: export.PILLAR_COLORS[i % 8] for i, p in enumerate(parts)}
    parts_with = [x for x in parts if any(i.part == x for i in items)]
    d = df[mask]

    t_over, t_freq, t_find, t_corr, t_exp = st.tabs(
        ["🗂 Overview (all questions)", "🔎 Question explorer", "💡 Key findings", "🔗 Correlations", "⬇ Export"])

    # ---------------------------------------------------------------- overview
    with t_over:
        ov = G.overview(df, form, items, mask, stat_keys, value_labels)
        q = st.text_input("Search question / variable", "")
        if q:
            ov = ov[ov["Question"].str.contains(q, case=False, na=False) | ov["Variable"].str.contains(q, case=False, na=False)]
        kind_of = {i.name: i.kind for i in items}
        show = ov.rename(columns={**{k: G.STATS[k] for k in stat_keys}, "n": "N (valid)"})
        show["Part"] = show["Part"].str[:40]

        def style(row):
            css = [""] * len(row)
            css[0] = _part_css(pcolor.get(ov.loc[row.name, "Part"], "1F3864"))
            if "Mean" in show.columns and kind_of.get(ov.loc[row.name, "Variable"]) == "rating" and pd.notna(row.get("Mean")):
                m = row["Mean"]
                bg, fg = export.BAND["low"] if m < low_t else export.BAND["high"] if m >= high_t else export.BAND["mid"]
                css[list(show.columns).index("Mean")] = f"background-color:#{bg};color:#{fg};font-weight:bold"
            return css
        fm = {G.STATS[k]: ("{:,.0f}" if k in ("n", "missing", "sum") else "{:.1f}" if k.startswith("pct") or k in ("top2", "cv") else "{:.2f}")
              for k in stat_keys if G.STATS[k] in show.columns}
        fm["N (valid)"] = "{:,.0f}"
        st.dataframe(show.style.apply(style, axis=1).format(fm, na_rep=""), width="stretch", height=640, hide_index=True)
        st.caption(f"{len(ov)} questions · {len(sel_parts)} parts · respondents in selection: {int(mask.sum()):,}. "
                   "Mean colour (rating questions) uses the red/amber/green thresholds from Report settings.")

    # ---------------------------------------------------------------- explorer
    with t_freq:
        p = st.selectbox("Part", parts_with, format_func=lambda x: x[:90])
        its = [i for i in items if i.part == p]
        it = st.selectbox("Question", its, format_func=lambda i: f"{i.label[:110]}  [{i.name}]")
        st.markdown(f"**{it.label}**  \n`{it.name}` · {G.KIND_NAMES[it.kind]}")
        am_q, rules_q, ok_q = G.asked_mask(df, form, it.name)
        n_el, n_ans = int(am_q[mask].sum()), int(df.loc[mask, it.name].notna().sum())
        st.caption(("Asked only if: " + "; ".join(rules_q) + f" · " if rules_q else "Asked to everyone · ")
                   + f"eligible respondents: {n_el:,} · answered: {n_ans:,}" + (f" ({n_ans / n_el:.0%})" if n_el else ""))
        if it.kind in ("single", "multi"):
            M, A, lab = G.cat_matrix(df, form, it, value_labels)
            f = G.freq_table(M, A, lab, mask, multi=it.kind == "multi")
            ch = alt.Chart(f).mark_bar(color="#2E75B6").encode(
                y=alt.Y("Label:N", sort=f["Label"].tolist(), title=None, axis=alt.Axis(labelLimit=420)),
                x=alt.X("% of answering:Q", title="% of respondents answering"),
                tooltip=["Label", "Count", alt.Tooltip("% of answering:Q", format=".1f")])
            txt = ch.mark_text(align="left", dx=3).encode(text=alt.Text("% of answering:Q", format=".1f"))
            cA, cB = st.columns([2, 3])
            cA.dataframe(f.style.format({"% of answering": "{:.1f}%", "Cumulative %": "{:.1f}%", "Count": "{:,}"}),
                         hide_index=True, width="stretch")
            cB.altair_chart(charts._style((ch + txt).properties(height=max(120, 28 * len(f)))), width="stretch")
            st.caption(f"N answering = {f.attrs['n']:,}" + ("  ·  multiple choice: percentages add up to more than 100%." if it.kind == "multi" else ""))
            if cats:
                pct, sig, cnt, meta = G.breakdown_categorical(df, form, it, var_, cats, mask, value_labels, alpha)
                txt_tbl = pct.copy().astype(object)
                for r in pct.index:
                    for c in pct.columns:
                        v = pct.at[r, c]
                        txt_tbl.at[r, c] = "" if pd.isna(v) else f"{v:.1f}%{sig.at[r, c]}"
                st.markdown(f"**By {var_}** (column %, ▲▼ = significantly higher/lower than the rest at p < {alpha})")
                st.dataframe(txt_tbl, width="stretch")
                if "p" in meta:
                    st.info(f"Chi-square test across categories: p = {meta['p']:.4f}, Cramér's V = {meta['Cramér' + chr(39) + 's V']:.2f} "
                            f"({'significant' if meta['p'] < alpha else 'not significant'}).")
                st.caption("N answering: " + " · ".join(f"{k}: {v:,}" for k, v in meta["n"].items()))
        elif it.kind in ("rating", "numeric"):
            x = G.numeric_series(d, form, it).dropna()
            allk = list(G.STATS)
            full = G.describe(x, allk, it.kind == "rating", int(d[it.name].notna().sum() - len(x)))
            keys = [k for k in allk if (it.kind == "rating" or k not in G.RATING_ONLY)]
            st.dataframe(pd.DataFrame({"Statistic": [G.STATS[k] for k in keys], "Value": [full[k] for k in keys]})
                         .style.format({"Value": "{:,.2f}"}), hide_index=True, width="stretch", height=300)
            if it.kind == "rating":
                dist = x.astype(int).value_counts().reindex(form.scale, fill_value=0).rename_axis("Rating").reset_index(name="Count")
                dist["%"] = dist["Count"] / max(dist["Count"].sum(), 1) * 100
                dist["Band"] = ["Low" if r <= core.LOW_MAX else "High" if r >= core.HIGH_MIN else "Mid" for r in dist["Rating"]]
                hist = alt.Chart(dist).mark_bar().encode(x=alt.X("Rating:O", title="Rating"), y=alt.Y("%:Q", title="% of valid ratings"),
                                                         color=alt.Color("Band:N", scale=charts._scale(), legend=None),
                                                         tooltip=["Rating", "Count", alt.Tooltip("%:Q", format=".1f")])
            else:
                hist = alt.Chart(pd.DataFrame({"v": x})).mark_bar(color="#2E75B6").encode(alt.X("v:Q", bin=alt.Bin(maxbins=30), title=it.name), y="count()")
            st.altair_chart(charts._style(hist.properties(height=260, title="Distribution")), width="stretch")
            if cats:
                b = G.breakdown_numeric(df, form, it, var_, cats, mask, list(dict.fromkeys(stat_keys + ["n", "mean", "ci_lo", "ci_hi"])), alpha)
                shown = ["Segment"] + [k for k in stat_keys if k in b.columns] + ["Diff vs rest", "p (vs rest)", "Cohen d", "Sig."]
                st.markdown(f"**By {var_}**  (Welch t-test of each category vs the rest; ▲▼ significant at p < {alpha})")
                st.dataframe(b[shown].rename(columns=G.STATS).style.format(
                    {"p (vs rest)": "{:.4f}", "Diff vs rest": "{:+.2f}", "Cohen d": "{:.2f}"}, precision=2, na_rep=""),
                    hide_index=True, width="stretch")
                ov_t = b.attrs.get("overall")
                if ov_t:
                    st.info("Across categories: " + ", ".join(f"{k} = {v:.4f}" if "p" in k else f"{k} = {v:.2f}" for k, v in ov_t.items()))
                bb = b.iloc[1:].dropna(subset=["mean"]).copy()
                if len(bb):
                    bar = alt.Chart(bb).mark_bar().encode(x=alt.X("Segment:N", sort=None), y=alt.Y("mean:Q", scale=alt.Scale(domain=[0, bb["mean"].max() * 1.15 if it.kind == "numeric" else 10]), title="Mean"),
                                                         color=alt.Color("Segment:N", legend=None, scale=alt.Scale(scheme="tableau10")))
                    err = alt.Chart(bb).mark_errorbar().encode(x="Segment:N", y="ci_lo:Q", y2="ci_hi:Q")
                    st.altair_chart(charts._style((bar + err).properties(height=300, title="Mean by segment with 95% CI")), width="stretch")
        else:
            t = G.text_table(df, it, mask)
            st.dataframe(t.style.format({"% of answering": "{:.1f}%"}), hide_index=True, width="stretch")

    # ---------------------------------------------------------------- findings
    # memoised: the findings / gap tests are the slow part, so only recompute when a setting changes
    key = (filter_text, var_, tuple(cats), alpha, min_diff, int(min_base), tuple(sel_parts), tuple(kinds), len(df), int(mask.sum()))
    memo = st.session_state.setdefault("_gen_memo", {})
    if key not in memo:
        memo.clear()
        gaps_ = G.segment_gap_table(df, form, items, var_, cats, mask) if cats else None
        memo[key] = (G.key_findings(df, form, items, mask, var_, cats, value_labels, alpha, min_diff, int(min_base), gaps_), gaps_)
    findings, gaps = memo[key]
    with t_find:
        if not findings:
            st.info("Not enough data for automatic findings in this selection.")
        for h, txt in findings:
            st.markdown(f"##### {h}")
            for line in str(txt).split("\n"):
                st.markdown(f"- {line}")
        if gaps is not None and len(gaps):
            with st.expander("All segment gaps (rating questions × categories, BH-adjusted)"):
                st.dataframe(gaps.sort_values("p (BH adj.)").style.format(
                    {"Segment mean": "{:.2f}", "Rest mean": "{:.2f}", "Diff": "{:+.2f}", "p": "{:.4f}", "p (BH adj.)": "{:.4f}"}),
                    hide_index=True, width="stretch")
        st.caption("Findings are generated from the data + script structure. Segment gaps use Welch t-tests with Benjamini-Hochberg "
                   "adjustment across all question × category tests, so they are protected against false positives.")

    # ---------------------------------------------------------------- correlations
    corr, method = None, "pearson"
    with t_corr:
        cc1, cc2 = st.columns(2)
        what = cc1.radio("Variables", ["Pillar scores (Topline)", "Rating questions of a Part"], horizontal=True)
        method = cc2.radio("Method", ["pearson", "spearman"], horizontal=True)
        if what.startswith("Pillar"):
            cols = core.respondent_pillar_scores(V[mask], tree).to_dict("series")
        else:
            pp = st.selectbox("Part", [x for x in parts if x in sel_parts], key="corrpart", format_func=lambda x: x[:90])
            rq = [i for i in items_all if i.part == pp and i.kind == "rating"][:25]
            cols = {i.label[:38] + f" [{i.name}]": G.numeric_series(d, form, i) for i in rq}
        if len(cols) >= 2:
            corr = G.correlations(d, form, cols, method)
            m = corr.reset_index(names="A").melt(id_vars="A", var_name="B", value_name="r")
            m["lab"] = m["r"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}")
            order = list(corr.columns)
            base = alt.Chart(m).encode(x=alt.X("B:N", sort=order, title=None, axis=alt.Axis(labelAngle=-40, labelLimit=240)),
                                       y=alt.Y("A:N", sort=order, title=None, axis=alt.Axis(labelLimit=240)))
            heat = base.mark_rect().encode(color=alt.Color("r:Q", scale=alt.Scale(domain=[-1, 0, 1], range=["#F4B6B6", "#FFFFFF", "#63BE7B"]), legend=alt.Legend(title="r")),
                                           tooltip=["A", "B", alt.Tooltip("r:Q", format=".2f")])
            st.altair_chart(charts._style((heat + base.mark_text(fontSize=11, color="#111").encode(text="lab:N")).properties(
                height=max(250, 32 * len(order)), width=max(350, 70 * len(order)))), width="stretch")
            pairs = m[m.A < m.B].assign(abs_r=lambda t: t.r.abs()).sort_values("abs_r", ascending=False).head(10)
            st.markdown("**Strongest relationships**")
            st.dataframe(pairs[["A", "B", "r"]].rename(columns={"A": "Variable 1", "B": "Variable 2", "r": "Correlation"}).style.format({"Correlation": "{:.2f}"}),
                         hide_index=True, width="stretch")
        else:
            st.info("Need at least two variables.")

    # ---------------------------------------------------------------- export
    with t_exp:
        st.write("The Excel contains: General overview (all parts, your chosen statistics), Frequencies, "
                 "Segments – scores, Segments – choices (with significance colours), Key findings, Segment gaps, Correlations and Method.")
        if st.button("Prepare General report Excel"):
            with st.spinner("Building workbook…"):
                st.session_state["gen_xlsx"] = export_general.to_excel(
                    df, form, items, mask, stat_keys, value_labels, filter_text, var_, cats, findings, gaps, corr, method,
                    alpha, min_diff, low_t, high_t, var_title)
        if "gen_xlsx" in st.session_state:
            st.download_button("⬇ Download General report (Excel)", st.session_state["gen_xlsx"], "General_report.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.caption("Re-click *Prepare* after changing selections so the file reflects them.")
