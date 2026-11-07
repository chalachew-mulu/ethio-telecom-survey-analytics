"""
Satisfaction-survey topline generator  -  run with:   streamlit run app.py
Upload the SurveyCTO script + the dataset, pick segment filters, read / chart / download the report.
"""
import io
from pathlib import Path

import pandas as pd
import streamlit as st

import charts
import core
import export
import general as _G
import general_ui

HERE = Path(__file__).parent
st.set_page_config(page_title="Satisfaction Survey Topline", layout="wide")
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
st.sidebar.title("1 · Upload")
f_script = st.sidebar.file_uploader("SurveyCTO script (XLSForm .xlsx)", type=["xlsx", "xls"])
f_data = st.sidebar.file_uploader("Dataset (wide .xlsx / .csv)", type=["xlsx", "xls", "csv"])

form = df = None
choice, detected = "Automatic (from script groups)", []
if f_script and f_data:
    form = load_form(f_script.getvalue(), f_script.name)
    df = load_data(f_data.getvalue(), f_data.name)

    # ---- script <-> dataset column mapping (e.g. questions renamed between script and data export)
    sug = core.suggest_column_mapping(form, df)
    if sug:
        pool_cols = [c for c in df.columns if c not in form.questions and core._rating_like(df[c], form)]
        with st.sidebar.expander(f"🔗 Column mapping · {len(sug)} script question(s) not found in the data", expanded=True):
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
    choice = st.sidebar.selectbox("Survey type (report structure)", opts, index=default,
                                  help="Detected automatically from the script and data. 'Automatic' builds the structure from the "
                                       "script's groups. Add your own file in the structures/ folder for other surveys.")
    if detected:
        st.sidebar.caption(f"Detected: **{detected[0]['name']}** ({detected[0]['questions']} rated questions matched).")

with st.sidebar.expander("Optional files"):
    f_struct = st.file_uploader("Structure file (structure.json)", type=["json"],
                                help="Maps script groups to report pillars. Leave empty to use the detected structure from the structures/ folder.")
    f_prev = st.file_uploader("Previous-round dataset (for % change & driver trend)", type=["xlsx", "xls", "csv"])
    round_name = st.text_input("Round name (file names)", f"{choice.split(' ')[0]}_Round", key=f"rn_{choice}")
with st.sidebar.expander("Report settings"):
    min_base = st.number_input("Flag bases below", 1, 500, 30, help="Means with fewer valid responses are shown in grey.")
    round_q = st.checkbox("Match Ethio telecom's sheet (weighted mean = 2-decimal mean × N)", value=False,
                          help="Ethio telecom multiplies the ROUNDED question mean by N. Tick to reproduce their "
                               "weighted-mean column exactly (e.g. 15,675 for TV). Unticked = exact sum of ratings.")
    low_t = st.number_input("Red (low) if mean below", 1.0, 10.0, 7.0, 0.1)
    high_t = st.number_input("Green (high) if mean from", 1.0, 10.0, 8.0, 0.1)

st.title("Customer satisfaction topline generator")
if not (f_script and f_data):
    st.info("Upload the **SurveyCTO script** and the **dataset** in the sidebar to begin.")
    st.stop()

if f_struct:
    structure = core.load_structure(f_struct, form)
elif choice != "Automatic (from script groups)":
    structure = core.load_structure(next(d["path"] for d in detected if d["name"] == choice), form)
else:
    structure = core.auto_structure(form)
survey_name = structure.get("name") or "Customer"
tree = core.build_tree(structure, form)
st.caption(f"Survey: **{form.title or survey_name}** · structure: **{structure.get('name', 'automatic')}**")
if not any(p.leaves() for p in tree):
    st.warning("The structure file matches no questions in this script - using an automatic structure built from the script's groups.")
    structure = core.auto_structure(form)
    tree = core.build_tree(structure, form)

# ---------------------------------------------------------------- custom numeric groups
with st.sidebar.expander("➕ Custom numeric groups (age, spend, SIMs…)"):
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
                {"var": f"custom_{cc}", "title": f"{cc} (custom groups)", "value_labels": {f"custom_{cc}": lab}})
            structure["segments"][-1]["value_labels"] = lab
        except ValueError:
            st.error("Enter numbers separated by commas.")

V = core.valid_matrix(df, form, form.rating_questions())

# ---------------------------------------------------------------- segments
seg_defs = []
for s in structure.get("segments", []):
    col = next((c for c in [s["var"]] + s.get("alias", []) if c in df.columns), None)
    if col:
        seg_defs.append({**s, "var": col})
used = {s["var"] for s in seg_defs}
pool = [c for c, q in form.questions.items()
        if c in df.columns
        and (q.qtype in ("select_one", "select_multiple") or (q.qtype == "text" and not _G.SKIP_NAME.search(c) and df[c].notna().mean() >= 0.15))
        and q.list_name != form.rating_list
        and c not in used and c not in ("supervisor_name", "enumerator_name") and 1 < df[c].nunique() <= 80]
sugg = [c for c in structure.get("extra_segments", []) if c in pool]
pool = sugg + [c for c in pool if c not in sugg]

st.sidebar.title("2 · Segment filters")
extra = st.sidebar.multiselect(
    "Add more segments", pool, format_func=lambda c: f"{form.questions[c].label[:58]}  ({c})",
    help="Any single-choice or multiple-choice question can be used to filter or break down the report.")
for c in extra:
    title = form.questions[c].label[:45] or c
    if form.questions[c].qtype == "text":              # merge spelling variants (case / spaces) of free-text answers
        df, c2, lab = _G.clean_text_segment(df, form, c)
        seg_defs.append({"var": c2, "title": title, "value_labels": lab})
    else:
        seg_defs.append({"var": c, "title": title})

filters, label_maps = {}, {}
for s in seg_defs:
    opts = core.segment_options(df, form, s["var"], {s["var"]: s.get("value_labels", {})} if s.get("value_labels") else None)
    label_maps[s["var"]] = opts
    chosen = st.sidebar.multiselect(s.get("title", s["var"]), list(opts.values()), key=f"f_{s['var']}")
    inv = {v: k for k, v in opts.items()}
    filters[s["var"]] = [inv[c] for c in chosen]

mask = core.apply_filters(df, filters, form)
active = {s.get("title", s["var"]): [label_maps[s["var"]][c] for c in filters[s["var"]]]
          for s in seg_defs if filters[s["var"]]}
filter_text = "; ".join(f"{k}: {', '.join(v)}" for k, v in active.items()) or "None (all respondents)"

c1, c2, c3 = st.columns(3)
c1.metric("Respondents in dataset", f"{len(df):,}")
c2.metric("Respondents in selected segment", f"{int(mask.sum()):,}")
c3.metric("Filters applied", filter_text if len(filter_text) < 40 else f"{len(active)} variables")
if mask.sum() == 0:
    st.error("No respondents match this combination of filters.")
    st.stop()

topline = core.compute_topline(V, tree, form, mask, round_q)

# ---------------------------------------------------------------- break-down variable (used by several tabs + Excel)
var_title = {s["var"]: s.get("title", s["var"]) for s in seg_defs}
bcol1, bcol2 = st.columns([2, 3])
var = bcol1.selectbox("Break the report down by (for comparison tab, charts & Excel)", list(var_title),
                      format_func=lambda v: var_title[v])
opts = label_maps[var]
chosen_codes = filters[var] or list(opts)
if not filters[var] and len(opts) > 25 and not core.is_multi(form, var):      # e.g. 69 cities: show the 12 largest unless chosen
    _vc = core.segment_codes(df, var)[mask].value_counts()
    chosen_codes = [c for c in _vc.index[:12] if c in opts]
    bcol2.caption(f"{len(opts)} categories: showing the 12 largest. Pick values in the sidebar filter to choose others.")
wide = core.compute_by_segment(df[mask], V[mask], tree, form, var, {c: opts[c] for c in chosen_codes}, round_q)


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
    show = pd.DataFrame({"Label name": ind, "Variable": d["Variable"], "Mean": d["MEAN"], "N responded": d["BASE"],
                         "Weighted mean": d["WEIGHTED"], "Avg of Q means": d["AVG_Q"],
                         "% Low (1-5)": d["PCT_LOW"], "% High (8-10)": d["PCT_HIGH"]})

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
        out[2] = _band_css(row["Mean"])
        return out

    sty = show.style.apply(style, axis=1).format(
        {"Mean": "{:.2f}", "N responded": "{:,.0f}", "Weighted mean": "{:,.0f}", "Avg of Q means": "{:.2f}",
         "% Low (1-5)": "{:.1f}%", "% High (8-10)": "{:.1f}%"}, na_rep="")
    st.dataframe(sty, width="stretch", height=660, hide_index=True)


tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📋 Topline", "📊 Charts", "↔ Compare segments", "🎯 Drivers & trend", "✅ Checks", "📘 General report (all parts)"])

# ---------------------------------------------------------------- tab 1
with tab1:
    show_topline(topline)
    st.caption("**Mean** of a group = pooled mean of every valid response beneath it (= Weighted mean ÷ N). "
               "**Weighted mean** = Mean × N responded (sum of ratings). **Avg of Q means** = simple average of the question means "
               "beneath the group. Mean colour: red < %.1f, amber, green ≥ %.1f. Faded rows = base below %d." % (low_t, high_t, min_base))

# ---------------------------------------------------------------- tab 2: charts
with tab2:
    kind = st.selectbox("Chart", ["Pillar scorecard", "Questions in a group", "Satisfaction mix (low / mid / high)",
                                  "Top & bottom 10 questions", "Segment heatmap", "Segment comparison"])
    groups = topline[topline.kind.isin(["pillar", "sub"])]["Indicator"].tolist()
    if kind == "Pillar scorecard":
        st.altair_chart(charts.scorecard(topline, low_t, high_t), width="stretch")
    elif kind == "Questions in a group":
        g = st.selectbox("Pillar / sub-group", groups)
        st.altair_chart(charts.question_bars(topline, g, low_t, high_t), width="stretch")
    elif kind.startswith("Satisfaction mix"):
        lvl = st.radio("Show", ["Pillars", "Questions of a group"], horizontal=True)
        if lvl == "Pillars":
            st.altair_chart(charts.mix(topline, topline[topline.kind == "pillar"], "Share of low / mid / high ratings by pillar"), width="stretch")
        else:
            g = st.selectbox("Pillar / sub-group", groups, key="mixg")
            row = topline[(topline.Indicator == g) & topline.kind.isin(["pillar", "sub"])].iloc[0]
            q = topline[(topline.kind == "question") & topline.Variable.isin(row["leaves"])]
            st.altair_chart(charts.mix(topline, q if len(q) else topline[topline.Indicator == g], g), width="stretch")
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
            col.altair_chart(charts._style(ch.properties(height=360, title=ttl)), width="stretch")
    elif kind == "Segment heatmap":
        lvl = st.radio("Rows", ["Pillars & sub-groups", "All questions"], horizontal=True)
        kinds = ["oss", "pillar", "sub"] if lvl.startswith("Pillars") else ["oss", "pillar", "sub", "question"]
        st.altair_chart(charts.heatmap(wide, kinds, low_t, high_t, f"Mean by {var_title[var]}"), width="stretch")
    else:
        inds = st.multiselect("Indicators", wide.Indicator.tolist(),
                              default=wide[wide.kind == "pillar"].Indicator.tolist()[:8])
        if inds:
            st.altair_chart(charts.grouped(wide, inds, f"Means by {var_title[var]}"), width="stretch")

# ---------------------------------------------------------------- tab 3
with tab3:
    only = st.radio("Rows", ["Pillars & sub-groups only", "All indicators"], horizontal=True)
    w = wide if only == "All indicators" else wide[wide.kind.isin(["oss", "pillar", "sub"])]
    mean_cols = [c for c in w.columns if c not in ("kind", "level", "Variable", "Indicator") and not c.endswith("(n)")]
    sty = w[["Indicator"] + mean_cols].style.format({c: "{:.2f}" for c in mean_cols}, na_rep="") \
        .background_gradient(subset=mean_cols, cmap="RdYlGn", axis=None, vmin=low_t - 1.5, vmax=high_t + 1.2) \
        .set_properties(subset=mean_cols, **{"color": "#111", "font-weight": "bold", "text-align": "center"})
    st.dataframe(sty, width="stretch", height=560, hide_index=True)
    st.caption(f"Breakdown by **{var_title[var]}**. Colours run red (lower) → green (higher). "
               "Bases per category are in the Excel download.")

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

# ---------------------------------------------------------------- tab 6: general report (all parts of the questionnaire)
with tab6:
    general_ui.render(df, form, tree, V, mask, filter_text, structure, min_base, low_t, high_t)

# ---------------------------------------------------------------- download
st.sidebar.title("3 · Download")
xl = export.to_excel(topline, filter_text, int(mask.sum()), int(min_base), wide, f"By {var_title[var]}"[:31],
                     drivers, comparison, round_q, low_t, high_t, f"{survey_name} Customers' Satisfaction Survey - Topline")
st.sidebar.download_button("⬇ Excel report (colour-coded)", xl, file_name=f"{round_name}_topline.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
