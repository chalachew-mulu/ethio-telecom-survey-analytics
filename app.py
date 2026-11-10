"""
Satisfaction-survey topline generator  -  run with:   streamlit run app.py
Upload the SurveyCTO script + the dataset, choose the report columns and filters, read / chart / download the report.
"""
import io
from pathlib import Path

import pandas as pd
import streamlit as st

import chartkit
import charts
import core
import export
import builder as B
import builder_charts as BC
import compare_ui
import general as _G
import builder_ui

HERE = Path(__file__).parent
st.set_page_config(page_title="Ethio Telecom Data Analytics", page_icon="📡", layout="wide")
PCOL = export.PILLAR_COLORS


# ---------------------------------------------------------------- caching
class _F(io.BytesIO):
    def __init__(self, b, name):
        super().__init__(b)
        self.name = name


@st.cache_data(show_spinner="Reading survey script…")
def load_form(b: bytes, name: str):
    return core.parse_xlsform(_F(b, name))


@st.cache_data(show_spinner="Reading dataset…")
def load_data(b: bytes, name: str):
    return core.read_table(_F(b, name))


# ---------------------------------------------------------------- sidebar: inputs
st.sidebar.title("1 · Upload your files")
f_script = st.sidebar.file_uploader("Questionnaire (SurveyCTO form, .xlsx)", type=["xlsx", "xls"], help="The SurveyCTO form definition (XLSForm) of the survey round.")
f_data = st.sidebar.file_uploader("Survey data (.xlsx or .csv)", type=["xlsx", "xls", "csv"], help="The wide-format dataset exported from SurveyCTO.")

form = df = None
choice, detected = "Automatic (from script groups)", []
if f_script and f_data:
    form = load_form(f_script.getvalue(), f_script.name)
    df = load_data(f_data.getvalue(), f_data.name)

    # ---- script <-> dataset column mapping (e.g. questions renamed between script and data export)
    sug = core.suggest_column_mapping(form, df)
    if sug:
        pool_cols = [c for c in df.columns if c not in form.questions and core._rating_like(df[c], form)]
        with st.sidebar.expander(f"🔗 Match question names · {len(sug)} to review", expanded=True):
            st.caption("These rating questions are in the script but their column name is not in the dataset. "
                       "Suggestions are matched by position (same slot between the same neighbouring questions). "
                       "Check them, change if needed, or set to — to ignore.")
            med = pd.DataFrame({"Script question": [s["question"] for s in sug],
                                "Label": [s["label"][:60] for s in sug],
                                "Dataset column": [s["column"] or "—" for s in sug]})
            ed = st.data_editor(med, hide_index=True, disabled=["Script question", "Label"], width="stretch",
                                column_config={"Dataset column": st.column_config.SelectboxColumn(options=["—"] + pool_cols, required=True)},
                                key=f"colmap_{f_data.name}_{len(df)}")
        mapping, seen = {}, set()
        for _, r in ed.iterrows():
            c = r["Dataset column"]
            if c != "—" and c not in seen and r["Script question"] not in df.columns:
                mapping[c] = r["Script question"]; seen.add(c)
        if mapping:
            df = df.rename(columns=mapping)
            st.sidebar.caption(f"✔ {len(mapping)} column(s) mapped to the script.")

    # ---- which survey is this? (Residential / Enterprise / ...) -> picks the matching structure file
    detected = core.detect_structure(form, df, HERE)
    opts = [d["name"] for d in detected] + ["Automatic (from script groups)"]
    default = 0 if detected and detected[0]["score"] >= 0.35 else len(opts) - 1
    choice = st.sidebar.selectbox("Survey (detected automatically)", opts, index=default,
                                  help="Detected automatically from the script and data. 'Automatic' builds the structure from the "
                                       "script's groups. Add your own file in the structures/ folder for other surveys.")
    if detected:
        st.sidebar.caption(f"Detected: **{detected[0]['name']}** ({detected[0]['questions']} rated questions matched).")

# the three segment boxes are created here so they appear in this order, but are filled further down
box_cols = st.sidebar.container()
box_filt = st.sidebar.container()
box_add = st.sidebar.container()

with st.sidebar.expander("Optional: previous round & custom structure"):
    f_struct = st.file_uploader("Custom report structure (.json)", type=["json"],
                                help="Maps script groups to report pillars. Leave empty to use the detected structure from the structures/ folder.")
    f_prev = st.file_uploader("Previous round data (for change vs last round)", type=["xlsx", "xls", "csv"])
    round_name = st.text_input("Round name (used in file names)", f"{choice.split(' ')[0]}_Round", key=f"rn_{choice}")
with st.sidebar.expander("Report settings: colours, rounding, warnings"):
    min_base = st.number_input("Warn when fewer respondents than", 1, 500, 30, help="Results based on fewer valid responses are shown in grey as a small-base warning.")
    round_q = st.checkbox("Use Ethio telecom rounding (weighted score = rounded mean × N)", value=False,
                          help="Ethio telecom multiplies the ROUNDED question mean by N. Tick to reproduce their "
                               "weighted-mean column exactly (e.g. 15,675 for TV). Unticked = exact sum of ratings.")
    low_t = st.number_input("Red when the mean score is below", 1.0, 10.0, 7.0, 0.1)
    high_t = st.number_input("Green when the mean score is at or above", 1.0, 10.0, 8.0, 0.1)

if not (f_script and f_data):
    st.title("Ethio Telecom Data Analytics")
    st.markdown("Customer satisfaction reporting for the **Residential** and **Enterprise** surveys — "
                "from raw survey data to a finished, colour-coded report in a few clicks.")
    steps = [("1 · Upload your files", "Add the questionnaire (SurveyCTO form) and the survey data. The tool recognises whether it is the "
                                      "Residential or the Enterprise survey."),
             ("2 · Split the report", "Choose how to compare customers: by location, city, sub-city, region, gender, SIM type, business sector … "
                                      "You get a Total column plus one column per group."),
             ("3 · Choose respondents", "Optionally narrow the report to a group of respondents. Options that do not apply "
                                        "(for example city for Addis Ababa) are hidden automatically."),
             ("4 · Review and download", "Read the scorecard, charts and comparisons, build any custom report, and download "
                                         "Excel files and chart images.")]
    for col, (h, t) in zip(st.columns(4), steps):
        with col.container(border=True):
            st.markdown(f"**{h}**")
            st.caption(t)
    st.info("Start by uploading the **questionnaire** and the **survey data** in the sidebar (step 1).")
    st.stop()

if f_struct:
    structure = core.load_structure(f_struct, form)
elif choice != "Automatic (from script groups)":
    structure = core.load_structure(next(d["path"] for d in detected if d["name"] == choice), form)
else:
    structure = core.auto_structure(form)
survey_name = structure.get("name") or "Customer"
tree = core.build_tree(structure, form)
st.title(f"Ethio Telecom · {survey_name} Customer Satisfaction Analytics" if structure.get("name") else "Ethio Telecom · Customer Satisfaction Analytics")
st.caption(f"Questionnaire: {form.title or 'n/a'}  ·  {len(df):,} respondents  ·  report structure: {structure.get('name', 'built from the questionnaire')}")
if not any(p.leaves() for p in tree):
    st.warning("The structure file matches no questions in this script - using an automatic structure built from the script's groups.")
    structure = core.auto_structure(form)
    tree = core.build_tree(structure, form)

# ---------------------------------------------------------------- segment variables
ss = st.session_state
NONE_BY, NONE2 = "— Total only —", "— none —"

# (a) custom groups for numeric variables (age, spend, SIMs ...) -> become ordinary segment variables
with box_add:
    with st.expander("➕ Custom groups for a number (age, spend, SIMs…)"):
        num_cols = [c for c, q in form.questions.items() if q.qtype in ("integer", "decimal", "calculate") and c in df.columns
                    and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.8 and df[c].nunique() > 3]
        cc = st.selectbox("Numeric variable", ["—"] + num_cols)
        edges_txt = st.text_input("Group starts (comma separated)", "15, 20, 30, 45, 66",
                                  help="15,20,30,45,66 → 15-19, 20-29, 30-44, 45-65, 66+")
        if cc != "—":
            try:
                edges = [float(x) for x in edges_txt.replace(";", ",").split(",") if x.strip()]
                df, lab = core.add_numeric_groups(df, cc, edges, f"custom_{cc}")
                structure.setdefault("segments", []).append(
                    {"var": f"custom_{cc}", "title": f"{cc} (custom groups)", "value_labels": lab})
            except ValueError:
                st.error("Enter numbers separated by commas.")

V = core.valid_matrix(df, form, form.rating_questions())


def _register(df_, orig, title, vl=None):
    """Segment definition; free-text variables (city, sub-city) get spelling variants merged."""
    q = form.questions.get(orig)
    if q is not None and q.qtype == "text":
        df_, c2, lab = _G.clean_text_segment(df_, form, orig)
        return df_, {"var": c2, "orig": orig, "title": title, "value_labels": lab}
    d_ = {"var": orig, "orig": orig, "title": title}
    if vl:
        d_["value_labels"] = vl
    return df_, d_


seg_defs = []
for s in structure.get("segments", []):
    col = next((c for c in [s["var"]] + s.get("alias", []) if c in df.columns), None)
    if col:
        df, d_ = _register(df, col, s.get("title", col), s.get("value_labels"))
        seg_defs.append(d_)
used = {s["orig"] for s in seg_defs}
pool = [c for c, q in form.questions.items()
        if c in df.columns
        and (q.qtype in ("select_one", "select_multiple") or (q.qtype == "text" and not _G.SKIP_NAME.search(c) and df[c].notna().mean() >= 0.15))
        and q.list_name != form.rating_list
        and c not in used and c not in ("supervisor_name", "enumerator_name") and 1 < df[c].nunique() <= 80]
sugg = [c for c in structure.get("extra_segments", []) if c in pool]
pool = sugg + [c for c in pool if c not in sugg]

with box_add:
    with st.expander("➕ Use another question as a variable"):
        extra = st.multiselect("Questions", pool, format_func=lambda c: f"{form.questions[c].label[:58]}  ({c})",
                               help="Any single-choice, multiple-choice or text question can be used to compare or to filter.",
                               label_visibility="collapsed", placeholder="Search a question…")
for c in extra:
    df, d_ = _register(df, c, form.questions[c].label[:45] or c)
    seg_defs.append(d_)

value_labels = {s["var"]: s["value_labels"] for s in structure.get("segments", []) if s.get("value_labels")}
title_of = {s["orig"]: s["title"] for s in seg_defs}


# ---------------------------------------------------------------- 3 · filters (who is in the report)
def _clear_filters():
    for k in [k for k in ss if str(k).startswith("flt_")]:
        ss[k] = []


filters, label_maps = {}, {}
mask = pd.Series(True, index=df.index)
with box_filt:
    st.subheader("3 · Choose which respondents to include")
    st.caption("Optional. Narrows the respondents used in every tab. Leave empty to include everyone.")
    st.button("🧹 Clear all filters", on_click=_clear_filters, width="stretch")
    for s in seg_defs:
        v = s["var"]
        am, words, _ok = _G.asked_mask(df, form, s["orig"])
        avail = am & mask
        if not avail.any():          # e.g. sub-city once 'Other Regions' is chosen: nobody was asked, so hide it
            continue
        opts = core.segment_options(df, form, v, {v: s["value_labels"]} if s.get("value_labels") else None)
        if core.is_multi(form, v):
            counts = {c: int(core.segment_mask(df, form, v, [c])[avail].sum()) for c in opts}
        else:
            vc = core.segment_codes(df, v)[avail].value_counts()
            counts = {c: int(vc.get(c, 0)) for c in opts}
        opts = {c: l for c, l in opts.items() if counts[c] > 0}
        if not opts:
            continue
        label_maps[v] = opts
        chosen = st.multiselect(s["title"], list(opts), key=f"flt_{f_data.name}_{v}", format_func=lambda c, o=opts, n=counts: f"{o[c]}  ·  {n[c]:,}",
                                help=("Asked only if: " + "; ".join(words)) if words else None)
        if chosen:
            filters[v] = chosen
            mask &= core.segment_mask(df, form, v, chosen)
active = {title_of.get(next((x["orig"] for x in seg_defs if x["var"] == k), k), k): [label_maps[k][c] for c in codes]
          for k, codes in filters.items()}
filter_text = "; ".join(f"{k}: {', '.join(v)}" for k, v in active.items()) or "None (all respondents)"

# ---------------------------------------------------------------- 2 · report columns (compare by)
seg, cats, var_title, wide, dfg = None, {}, "Total", None, df
with box_cols:
    st.subheader("2 · Choose how to split the report")
    st.caption("Every table, chart and Excel file gets a **Total** column plus one column for each group of this variable (e.g. each city or each gender).")
    var_opts = [s["orig"] for s in seg_defs]
    by = st.selectbox("Split the report by", [NONE_BY] + var_opts, index=1 if var_opts else 0, key=f"cmp_by_{f_data.name}",
                      format_func=lambda c: "Total only (no split)" if c == NONE_BY else title_of[c])
    opts2 = [NONE2] + [c for c in var_opts if c != by and not core.is_multi(form, c)]
    by2 = NONE2
    if by != NONE_BY:
        by2 = st.selectbox("…then split each group by (optional)", opts2, key=f"cmp_by2_{f_data.name}_{by}",
                           format_func=lambda c: "— none —" if c == NONE2 else title_of[c])
        seg = B.resolve_segment(df, form, by, None if by2 == NONE2 else by2, value_labels, mask, True)
        dfg = seg["df"]
        opts_, counts_ = seg["labels"], seg["counts"]
        order = sorted(opts_, key=lambda c: -counts_[c]) if len(opts_) > 12 else list(opts_)
        ck = f"cmp_cats_{f_data.name}_{seg['var']}_{int(seg['pop'].sum())}"
        if ck not in ss:
            ss[ck] = order[:12]
        b1, b2 = st.columns(2)
        b1.button("Select all", key=f"{ck}_all", on_click=lambda k=ck, o=order: ss.__setitem__(k, list(o)), width="stretch")
        b2.button("Clear", key=f"{ck}_none", on_click=lambda k=ck: ss.__setitem__(k, []), width="stretch")
        chosen_c = st.multiselect(f"Groups to show ({len(opts_)} available)", order, key=ck,
                                  format_func=lambda c: f"{opts_[c]}  ·  {counts_[c]:,}")
        cats = {c: opts_[c] for c in chosen_c}
        var_title = " › ".join(title_of[x] for x in (by, by2) if x not in (NONE_BY, NONE2))
        if seg["rules"]:
            st.info("Asked only if: " + "; ".join(seg["rules"]) + f"  \nPopulation: **{int(seg['pop'].sum()):,}** respondents.")
        if cats:
            wide = core.compute_by_segment(dfg[seg["pop"]], V[seg["pop"]], tree, form, seg["var"], cats, round_q)

c1, c2, c3 = st.columns(3)
c1.metric("Respondents in dataset", f"{len(df):,}")
c2.metric("Respondents after filters", f"{int(mask.sum()):,}")
c3.metric("Report is split by", ("Total + " + str(len(cats)) + " × " + var_title) if cats else "Total")
if filters:
    st.caption("Filters: " + filter_text)
if mask.sum() == 0:
    st.error("No respondents match this combination of filters.")
    st.stop()

topline = core.compute_topline(V, tree, form, mask, round_q)


# ---------------------------------------------------------------- display helpers
def _band_css(m):
    if pd.isna(m):
        return ""
    bg, fg = export.BAND["low"] if m < low_t else export.BAND["high"] if m >= high_t else export.BAND["mid"]
    return f"background-color:#{bg};color:#{fg};font-weight:bold;text-align:center"


def show_topline(t: pd.DataFrame):
    d = t.reset_index(drop=True)
    pidx, pcolor = -1, []
    for k in d["kind"]:
        pidx += (k == "pillar")
        pcolor.append(PCOL[pidx % 8] if pidx >= 0 else "BF9000")
    ind = ["\u2003" * (0 if k in ("oss", "pillar") else 1 if k == "sub" else 2) + i for i, k in zip(d["Indicator"], d["kind"])]
    show = pd.DataFrame({"Indicator / question": ind, "Variable code": d["Variable"], "Mean score": d["MEAN"], "Respondents (N)": d["BASE"],
                         "Weighted score (Mean × N)": d["WEIGHTED"], "Average of question means": d["AVG_Q"],
                         "% Low scores (1–5)": d["PCT_LOW"], "% High scores (8–10)": d["PCT_HIGH"]})

    def style(row):
        k, pc, i = d.at[row.name, "kind"], pcolor[row.name], row.name
        if k == "oss":
            css = "background-color:#FFD966;color:#000;font-weight:bold"
        elif k == "pillar":
            css = f"background-color:#{pc};color:#fff;font-weight:bold"
        elif k == "sub":
            css = f"background-color:#{export._tint(pc, .35)};color:#000;font-weight:bold;font-style:italic"
        else:
            css = f"background-color:#{export._tint(pc, .09) if i % 2 else 'ffffff'};color:#111"
        if d.at[row.name, "BASE"] < min_base:
            css += ";opacity:.55;font-style:italic"
        out = [css] * len(row)
        out[2] = _band_css(row["Mean score"])
        return out

    sty = show.style.apply(style, axis=1).format(
        {"Mean score": "{:.2f}", "Respondents (N)": "{:,.0f}", "Weighted score (Mean × N)": "{:,.0f}", "Average of question means": "{:.2f}",
         "% Low scores (1–5)": "{:.1f}%", "% High scores (8–10)": "{:.1f}%"}, na_rep="")
    st.dataframe(sty, width="stretch", height=660, hide_index=True)


tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📋 Satisfaction scorecard", "📊 Visual summary", "↔ Compare groups", "🎯 Key drivers & change", "✅ Data quality", "🧱 Custom report builder"])

# ---------------------------------------------------------------- tab 1
with tab1:
    st.caption("All respondents after filters. For side-by-side columns (Total + each group) use the **Compare groups** tab.")
    show_topline(topline)
    st.caption("**Mean score** of a pillar or group = average of every valid rating beneath it (= Weighted score ÷ Respondents). "
               "**Weighted score** = Mean × Respondents (the sum of all ratings). **Average of question means** = simple average of the question means in the group. "
               "**% High / % Low scores** = share of ratings from 8 to 10 / from 1 to 5. "
               f"Colour of the mean: red below {low_t:.1f}, amber in between, green from {high_t:.1f}. Faded rows have fewer than {int(min_base)} respondents.")

# ---------------------------------------------------------------- tab 2: charts
with tab2:
    kind = st.selectbox("Chart", ["Pillar scorecard", "Questions in a group", "Satisfaction mix (low / mid / high)",
                                  "Top & bottom 10 questions", "Segment heatmap", "Segment comparison"])
    groups = topline[topline.kind.isin(["pillar", "sub"])]["Indicator"].tolist()
    if kind in ("Segment heatmap", "Segment comparison") and wide is None:
        st.info("Choose **Split the report by** in *2 · Choose how to split the report* (sidebar) and tick the groups to show.")
    elif kind == "Pillar scorecard":
        chartkit.chart(charts.scorecard(topline, low_t, high_t))
    elif kind == "Questions in a group":
        g = st.selectbox("Pillar / sub-group", groups)
        chartkit.chart(charts.question_bars(topline, g, low_t, high_t))
    elif kind.startswith("Satisfaction mix"):
        lvl = st.radio("Show", ["Pillars", "Questions of a group"], horizontal=True)
        if lvl == "Pillars":
            chartkit.chart(charts.mix(topline, topline[topline.kind == "pillar"], "Share of low / mid / high ratings by pillar"))
        else:
            g = st.selectbox("Pillar / sub-group", groups, key="mixg")
            row = topline[(topline.Indicator == g) & topline.kind.isin(["pillar", "sub"])].iloc[0]
            q = topline[(topline.kind == "question") & topline.Variable.isin(row["leaves"])]
            chartkit.chart(charts.mix(topline, q if len(q) else topline[topline.Indicator == g], g))
    elif kind.startswith("Top"):
        q = topline[topline.kind == "question"].sort_values("MEAN", ascending=False)
        q = q[q.BASE >= min_base]
        n = min(10, len(q) // 2)
        cA, cB = st.columns(2)
        for col, d, ttl in ((cA, q.head(n), "Top 10 questions"), (cB, q.tail(n), "Bottom 10 questions")):
            d = d.copy(); d["Question"] = d.Indicator.map(lambda s: charts.short(s, 60))
            d["Band"] = [charts.band(m, low_t, high_t) for m in d.MEAN]
            ch = charts.alt.Chart(d).mark_bar().encode(
                y=charts.alt.Y("Question:N", sort="-x" if ttl.startswith("Top") else "x", title=None, axis=charts.alt.Axis(labelLimit=300)),
                x=charts.alt.X("MEAN:Q", scale=charts.alt.Scale(domain=[0, 10]), title="Mean"),
                color=charts.alt.Color("Band:N", scale=charts._scale(), legend=None),
                tooltip=["Indicator", charts.alt.Tooltip("MEAN:Q", format=".2f"), charts.alt.Tooltip("BASE:Q", format=",")])
            chartkit.chart(charts._style(ch.properties(height=360, title=ttl)), container=col, name=ttl.lower().replace(" ", "_"))
    else:
        MEAS = {"Mean score": ("mean", "num"), "% High scores (8–10)": ("pct_high", "pct"),
                "% Low scores (1–5)": ("pct_low", "pct"), "Respondents (N)": ("n", "int")}
        measure = st.radio("Measure", list(MEAS), horizontal=True, key="vs_measure",
                           help="Mean score, or the percentage of ratings that are high (8–10) or low (1–5).")
        if kind == "Segment heatmap":
            lvl = st.radio("Rows", ["Pillars & sub-groups", "All questions"], horizontal=True)
            kinds = ["oss", "pillar", "sub"] if lvl.startswith("Pillars") else ["oss", "pillar", "sub", "question"]
            if measure == "Mean score":
                chartkit.chart(charts.heatmap(wide, kinds, low_t, high_t, f"Mean score by {var_title}"), name="heatmap")
            else:
                k_, f_ = MEAS[measure]
                rows_ = [r["row"] for r in B.indicator_rows(tree, form, V) if r["row"].level in kinds]
                sg_ = B.segment_masks(dfg, form, seg["var"], cats, seg["pop"])
                lg_ = B.score_long(dfg, form, V, rows_, sg_, seg["pop"], [k_])
                fr_ = lg_.melt(id_vars=["Row", "Segment"], value_vars=[k_], value_name="Value").rename(columns={"Row": "Item"})
                if f_ == "pct":
                    fr_["Value"] = fr_["Value"] / 100
                chartkit.chart(BC.build(fr_, "Heatmap", f_, 1 if f_ == "pct" else 0, f"{measure} by {var_title}", True,
                                        order=list(dict.fromkeys(fr_["Item"]))), name="heatmap")
        else:
            inds = st.multiselect("Indicators", wide.Indicator.tolist(),
                                  default=wide[wide.kind == "pillar"].Indicator.tolist()[:8])
            if inds and measure == "Mean score":
                chartkit.chart(charts.grouped(wide, inds, f"Mean score by {var_title}"), name="comparison")
            elif inds:
                k_, f_ = MEAS[measure]
                rows_ = [r["row"] for r in B.indicator_rows(tree, form, V) if r["row"].label in inds]
                sg_ = B.segment_masks(dfg, form, seg["var"], cats, seg["pop"])
                lg_ = B.score_long(dfg, form, V, rows_, sg_, seg["pop"], [k_])
                fr_ = lg_.melt(id_vars=["Row", "Segment"], value_vars=[k_], value_name="Value").rename(columns={"Row": "Item"})
                if f_ == "pct":
                    fr_["Value"] = fr_["Value"] / 100
                chartkit.chart(BC.build(fr_, "Clustered columns", f_, 1 if f_ == "pct" else 0, f"{measure} by {var_title}", True,
                                        order=list(dict.fromkeys(fr_["Item"]))), name="comparison")

# ---------------------------------------------------------------- tab 3: compare segments
with tab3:
    compare_ui.render(dfg, form, tree, V, seg, cats, var_title, filter_text, survey_name, min_base, low_t, high_t)

# ---------------------------------------------------------------- tab 4
drivers, comparison = None, None
with tab4:
    drivers = core.driver_analysis(V, tree, mask, min_n=int(min_base))
    prev_drv = None
    if f_prev:
        dp = load_data(f_prev.getvalue(), f_prev.name)
        Vp = core.valid_matrix(dp, form, form.rating_questions())
        pmask = core.apply_filters(dp, {k: v for k, v in filters.items() if k in dp.columns}, form)
        comparison = core.pillar_comparison(V, Vp, tree, form, mask, pmask)
        prev_drv = core.driver_analysis(Vp, tree, pmask, min_n=int(min_base))
    pm = topline[topline.kind == "pillar"][["Indicator", "MEAN"]].rename(columns={"MEAN": "Mean"}).copy()
    pm["Rank"] = pm["Mean"].rank(ascending=False, method="min").astype(int)
    out = pm
    if comparison is not None:
        out = out.merge(comparison[["Indicator", "% growth in mean"]], on="Indicator", how="left")
    if prev_drv is not None and len(prev_drv["table"]):
        out = out.merge(prev_drv["table"].rename(columns={"Std. coefficient": "Prev. coef.", "Rank": "Prev. rank"}),
                        on="Indicator", how="left")
    if len(drivers["table"]):
        out = out.merge(drivers["table"].rename(columns={"Rank": "Driver rank"}), on="Indicator", how="left").sort_values("Driver rank")
        st.markdown(f"**Standardized coefficients** · R² = {drivers['r2']:.2f} · n = {drivers['n']:,} respondents who rated all pillars")
    else:
        st.warning(f"Too few respondents who rated every pillar ({drivers['n']}) for a stable driver analysis in this segment.")
    fm = {"Mean": "{:.2f}", "% growth in mean": "{:+.0f}%", "Prev. coef.": "{:.3f}", "Std. coefficient": "{:.3f}"}
    st.dataframe(out.style.format({k: v for k, v in fm.items() if k in out}), width="stretch", hide_index=True)
    if not f_prev:
        st.caption("Upload the previous-round dataset (sidebar → Optional files) to add % change and last round's coefficients.")

# ---------------------------------------------------------------- tab 5
with tab5:
    msgs = core.check_structure(form, tree, df)
    missing_seg = [s["var"] for s in structure.get("segments", [])
                   if not any(c in df.columns for c in [s["var"]] + s.get("alias", [])) and not s["var"].startswith("custom_")]
    if missing_seg:
        msgs.append("Segment variables in structure.json not found in the dataset: " + ", ".join(missing_seg))
    st.write(f"Rating scale detected: **{min(form.scale)}–{max(form.scale)}** (choice list `{form.rating_list}`); "
             f"{len(form.rating_questions())} rating questions in script; {len(df):,} respondents.")
    for m in msgs:
        (st.info if m.startswith(("Rating questions in the script", "Non-scale")) else st.warning)(m)
    if not msgs:
        st.success("No issues found.")

# ---------------------------------------------------------------- tab 6: report builder (any survey)
with tab6:
    builder_ui.render(df, form, tree, V, mask, filter_text, structure, survey_name, min_base, low_t, high_t)

# ---------------------------------------------------------------- download
st.sidebar.title("4 · Download")
xl = export.to_excel(topline, filter_text, int(mask.sum()), int(min_base), wide, f"By {var_title}"[:31],
                     drivers, comparison, round_q, low_t, high_t, f"{survey_name} Customer Satisfaction Scorecard")
st.sidebar.download_button("⬇ Download scorecard (Excel)", xl, file_name=f"{round_name}_satisfaction_scorecard.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
