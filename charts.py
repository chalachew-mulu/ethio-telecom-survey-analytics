"""charts.py - Altair charts used in the app (all driven by the topline / by-segment tables)."""
import altair as alt
import pandas as pd

COL = {"Low": "#D9534F", "Mid": "#F0AD4E", "High": "#3FA34D"}


def band(m, low_t, high_t):
    return "Low" if m < low_t else "High" if m >= high_t else "Mid"


def _scale():
    return alt.Scale(domain=list(COL), range=list(COL.values()))


def short(label: str, n: int = 70) -> str:
    return label if len(label) <= n else label[: n - 1] + "…"


def _style(ch):
    return (ch.properties(background="#FFFFFF", padding={"left": 12, "right": 12, "top": 12, "bottom": 12})
              .configure_axis(labelFontSize=12, titleFontSize=12, labelColor="#222222", titleColor="#222222",
                              domainColor="#999999", tickColor="#999999", gridColor="#E6E6E6")
              .configure_legend(labelFontSize=12, titleFontSize=12, labelColor="#222222", titleColor="#222222")
              .configure_title(fontSize=15, anchor="start", color="#1F3864")
              .configure_view(strokeWidth=0))


def scorecard(t, low_t, high_t):
    p = t[t.kind.isin(["pillar"])].copy()
    oss = float(t[t.kind == "oss"]["MEAN"].iloc[0])
    p["Band"] = [band(m, low_t, high_t) for m in p["MEAN"]]
    p["lab"] = p["MEAN"].map("{:.2f}".format)
    order = p.sort_values("MEAN", ascending=False)["Indicator"].tolist()
    base = alt.Chart(p).encode(y=alt.Y("Indicator:N", sort=order, title=None, axis=alt.Axis(labelLimit=320)))
    bars = base.mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("MEAN:Q", scale=alt.Scale(domain=[0, 10]), title="Mean (1-10)"),
        color=alt.Color("Band:N", scale=_scale(), legend=alt.Legend(title="Performance")),
        tooltip=["Indicator", alt.Tooltip("MEAN:Q", format=".2f"), alt.Tooltip("BASE:Q", format=","),
                 alt.Tooltip("PCT_HIGH:Q", format=".1f", title="% High (8-10)")])
    txt = base.mark_text(align="left", dx=4, fontWeight="bold", fontSize=13).encode(x="MEAN:Q", text="lab:N")
    rule = alt.Chart(pd.DataFrame({"x": [oss]})).mark_rule(color="#1F3864", strokeDash=[6, 4], size=2).encode(x="x:Q")
    rl = alt.Chart(pd.DataFrame({"x": [oss], "t": [f"OSS {oss:.2f}"]})).mark_text(
        align="left", dx=4, dy=-6, color="#1F3864", fontWeight="bold").encode(x="x:Q", text="t:N", y=alt.value(0))
    return _style((bars + txt + rule + rl).properties(height=max(220, 38 * len(p)), title="Pillar scorecard"))


def question_bars(t, group_title, low_t, high_t):
    g = t[(t.Indicator == group_title) & t.kind.isin(["pillar", "sub"])].iloc[0]
    q = t[t.kind == "question"]
    q = q[q.Variable.isin(g["leaves"])].copy()
    if q.empty:
        q = t[(t.Indicator == group_title)].copy()
    q["Band"] = [band(m, low_t, high_t) for m in q["MEAN"]]
    q["Question"] = q["Indicator"].map(short)
    q["lab"] = q["MEAN"].map("{:.2f}".format)
    order = q.sort_values("MEAN", ascending=False)["Question"].tolist()
    base = alt.Chart(q).encode(y=alt.Y("Question:N", sort=order, title=None, axis=alt.Axis(labelLimit=520)))
    bars = base.mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("MEAN:Q", scale=alt.Scale(domain=[0, 10]), title="Mean (1-10)"),
        color=alt.Color("Band:N", scale=_scale(), legend=alt.Legend(title="Performance")),
        tooltip=[alt.Tooltip("Indicator", title="Question"), "Variable", alt.Tooltip("MEAN:Q", format=".2f"),
                 alt.Tooltip("BASE:Q", format=",", title="N responded"), alt.Tooltip("WEIGHTED:Q", format=",.0f", title="Weighted mean")])
    txt = base.mark_text(align="left", dx=4, fontWeight="bold").encode(x="MEAN:Q", text="lab:N")
    gm = alt.Chart(pd.DataFrame({"x": [g["MEAN"]]})).mark_rule(color="#1F3864", strokeDash=[6, 4], size=2).encode(x="x:Q")
    return _style((bars + txt + gm).properties(height=max(160, 30 * len(q)),
                                               title=f"{group_title}  (group mean {g['MEAN']:.2f}, dashed line)"))


def mix(t, rows_df, title="Satisfaction mix"):
    d = rows_df.copy()
    d["Item"] = d["Indicator"].map(short)
    d["Mid"] = 100 - d["PCT_LOW"] - d["PCT_HIGH"]
    m = d.melt(id_vars=["Item", "MEAN"], value_vars=["PCT_LOW", "Mid", "PCT_HIGH"], var_name="k", value_name="pct")
    m["Group"] = m["k"].map({"PCT_LOW": "Low (1-5)", "Mid": "Mid (6-7)", "PCT_HIGH": "High (8-10)"})
    order = ["Low (1-5)", "Mid (6-7)", "High (8-10)"]
    ch = alt.Chart(m).mark_bar().encode(
        y=alt.Y("Item:N", sort=alt.EncodingSortField("MEAN", order="descending"), title=None, axis=alt.Axis(labelLimit=520)),
        x=alt.X("pct:Q", stack="normalize", title="Share of responses", axis=alt.Axis(format="%")),
        color=alt.Color("Group:N", sort=order, scale=alt.Scale(domain=order, range=[COL["Low"], COL["Mid"], COL["High"]])),
        order=alt.Order("Group:N", sort="ascending"),
        tooltip=["Item", "Group", alt.Tooltip("pct:Q", format=".1f", title="%")])
    return _style(ch.properties(height=max(160, 30 * len(d)), title=title))


def heatmap(w, kinds, low_t, high_t, title):
    cats = [c for c in w.columns if c not in ("kind", "level", "Variable", "Indicator") and not str(c).endswith("(n)")]
    d = w[w.kind.isin(kinds)].melt(id_vars=["Indicator"], value_vars=cats, var_name="Segment", value_name="Mean")
    d["lab"] = d["Mean"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}")
    d["Indicator"] = d["Indicator"].map(lambda s: short(s, 60))
    order = list(dict.fromkeys(d["Indicator"]))
    ch = alt.Chart(d).encode(x=alt.X("Segment:N", sort=cats, title=None, axis=alt.Axis(labelAngle=-30)),
                             y=alt.Y("Indicator:N", sort=order, title=None, axis=alt.Axis(labelLimit=380)))
    rect = ch.mark_rect().encode(color=alt.Color("Mean:Q", scale=alt.Scale(domain=[low_t - 1, (low_t + high_t) / 2, high_t + 0.7],
                                                                           range=["#F4B6B6", "#FFF2AE", "#9AD59A"], clamp=True),
                                                  legend=alt.Legend(title="Mean")),
                                 tooltip=["Indicator", "Segment", alt.Tooltip("Mean:Q", format=".2f")])
    txt = ch.mark_text(fontWeight="bold", fontSize=12, color="#111").encode(text="lab:N")
    return _style((rect + txt).properties(height=max(180, 28 * len(order)), width=max(320, 85 * len(cats)), title=title))


def grouped(w, indicators, title):
    cats = [c for c in w.columns if c not in ("kind", "level", "Variable", "Indicator") and not str(c).endswith("(n)")]
    d = w[w.Indicator.isin(indicators)].melt(id_vars=["Indicator"], value_vars=cats, var_name="Segment", value_name="Mean")
    d["Indicator"] = d["Indicator"].map(lambda s: short(s, 45))
    ch = alt.Chart(d).mark_bar().encode(
        x=alt.X("Indicator:N", title=None, axis=alt.Axis(labelAngle=-25, labelLimit=260)),
        y=alt.Y("Mean:Q", scale=alt.Scale(domain=[0, 10])),
        xOffset="Segment:N", color=alt.Color("Segment:N", scale=alt.Scale(scheme="tableau10")),
        tooltip=["Indicator", "Segment", alt.Tooltip("Mean:Q", format=".2f")])
    return _style(ch.properties(height=380, title=title))
