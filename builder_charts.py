"""builder_charts.py - Altair charts for the Report Builder (driven by ReportTable.chart)."""
import altair as alt
import pandas as pd

PALETTE = ["#1F3864", "#2E75B6", "#ED7D31", "#548235", "#7030A0", "#BF9000", "#C00000", "#00A3A3",
           "#8C564B", "#E377C2", "#7F7F7F", "#17BECF", "#9467BD", "#AEC7E8", "#FFBB78", "#98DF8A"]
CHART_TYPES_FREQ = ["Clustered columns", "Horizontal bars", "Stacked 100% by segment", "Heatmap"]
CHART_TYPES_SCORE = ["Clustered columns", "Horizontal bars", "Heatmap"]


def _fmt(fmt, dec):
    return {"pct": f".{dec}%", "int": ",d", "num": f".{dec}f"}.get(fmt, ".2f")


def _short(s, n=60):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _style(ch):
    return (ch.properties(background="#FFFFFF", padding={"left": 12, "right": 12, "top": 12, "bottom": 12})
              .configure_axis(labelFontSize=12, titleFontSize=12, labelColor="#222222", titleColor="#222222",
                              domainColor="#999999", tickColor="#999999", gridColor="#E6E6E6")
              .configure_legend(labelFontSize=12, titleFontSize=12, orient="bottom", labelColor="#222222", titleColor="#222222")
              .configure_title(fontSize=15, anchor="start", color="#1F3864")
              .configure_view(strokeWidth=0))


def build(frame: pd.DataFrame, kind: str, fmt: str, decimals: int, title: str, labels: bool,
          item_col="Item", series_col="Segment", order=None, color_by=None, height=None):
    """frame: columns Item, Segment, Value (+ Answer for stacked). Returns an Altair chart."""
    f = frame.copy()
    f["Item"] = f[item_col].map(_short)
    f["ItemFull"] = f[item_col]
    order = [_short(o) for o in (order or list(dict.fromkeys(f["Item"])))]
    segs = list(dict.fromkeys(f[series_col]))
    n_items, n_seg = len(order), len(segs)
    vf = _fmt(fmt, decimals)
    tip = [alt.Tooltip("ItemFull:N", title="Item"), alt.Tooltip(f"{series_col}:N"), alt.Tooltip("Value:Q", format=vf)]
    scale = alt.Scale(domain=segs, range=[PALETTE[i % len(PALETTE)] for i in range(n_seg)])
    ax = alt.Axis(format=vf)

    if kind == "Heatmap":
        base = alt.Chart(f).encode(x=alt.X(f"{series_col}:N", sort=segs, title=None, axis=alt.Axis(labelAngle=-30)),
                                   y=alt.Y("Item:N", sort=order, title=None, axis=alt.Axis(labelLimit=420)))
        rect = base.mark_rect().encode(color=alt.Color("Value:Q", scale=alt.Scale(scheme="blues"), legend=alt.Legend(title=None, format=vf)), tooltip=tip)
        txt = base.mark_text(fontSize=11).encode(text=alt.Text("Value:Q", format=vf),
                                                 color=alt.condition(alt.datum.Value > f["Value"].quantile(.6), alt.value("white"), alt.value("#111")))
        return _style((rect + txt).properties(height=max(160, 28 * n_items), width=max(320, 90 * n_seg), title=title))

    if kind == "Stacked 100% by segment":
        a = f.copy()
        ans = list(dict.fromkeys(a["Answer"]))
        w = max(420, 120 * n_seg)
        enc = dict(
            x=alt.X(f"{series_col}:N", sort=segs, title=None, axis=alt.Axis(labelAngle=-25, labelLimit=170)),
            y=alt.Y("Value:Q", stack="normalize", axis=alt.Axis(format="%"), title="Share"),
            order=alt.Order("Answer:N", sort="ascending"))
        bars = alt.Chart(a).mark_bar().encode(
            color=alt.Color("Answer:N", sort=ans, scale=alt.Scale(domain=ans, range=[PALETTE[(i + 1) % len(PALETTE)] for i in range(len(ans))]),
                            legend=alt.Legend(title=None, labelLimit=300, columns=1, orient="right")),
            tooltip=[alt.Tooltip("Answer:N"), alt.Tooltip(f"{series_col}:N"), alt.Tooltip("Value:Q", format=vf)], **enc)
        ch = bars
        if labels:
            a = a.copy()
            a["Answer"] = pd.Categorical(a["Answer"], categories=ans, ordered=True)
            a = a.sort_values([series_col, "Answer"])
            a["share"] = a["Value"] / a.groupby(series_col, observed=True)["Value"].transform("sum").replace(0, float("nan"))
            a["mid"] = a.groupby(series_col, observed=True)["share"].cumsum() - a["share"] / 2
            lab = a[a["share"] >= 0.05].copy()
            lab["Answer"] = lab["Answer"].astype(str)
            ch = bars + alt.Chart(lab).mark_text(fontSize=11, color="white", fontWeight="bold").encode(
                x=alt.X(f"{series_col}:N", sort=segs), y=alt.Y("mid:Q", scale=alt.Scale(domain=[0, 1])),
                text=alt.Text("Value:Q", format=vf))
        return _style(ch.properties(height=380, width=w, title=title))

    horizontal = kind == "Horizontal bars"
    if horizontal:
        bars = alt.Chart(f).mark_bar().encode(
            y=alt.Y("Item:N", sort=order, title=None, axis=alt.Axis(labelLimit=420)),
            yOffset=alt.YOffset(f"{series_col}:N", sort=segs),
            x=alt.X("Value:Q", title=None, axis=ax),
            color=alt.Color(f"{series_col}:N", scale=scale, sort=segs, legend=alt.Legend(title=None)), tooltip=tip)
        if labels:
            bars = bars + alt.Chart(f).mark_text(align="left", dx=3, fontSize=11).encode(
                y=alt.Y("Item:N", sort=order), yOffset=alt.YOffset(f"{series_col}:N", sort=segs),
                x="Value:Q", text=alt.Text("Value:Q", format=vf))
        h = height or max(200, 18 * n_items * max(n_seg, 1) + 60)
        return _style(bars.properties(height=h, title=title))
    bars = alt.Chart(f).mark_bar().encode(
        x=alt.X("Item:N", sort=order, title=None, axis=alt.Axis(labelAngle=-30, labelLimit=240)),
        xOffset=alt.XOffset(f"{series_col}:N", sort=segs),
        y=alt.Y("Value:Q", title=None, axis=ax),
        color=alt.Color(f"{series_col}:N", scale=scale, sort=segs, legend=alt.Legend(title=None)), tooltip=tip)
    if labels:
        bars = bars + alt.Chart(f).mark_text(dy=-6, fontSize=10).encode(
            x=alt.X("Item:N", sort=order), xOffset=alt.XOffset(f"{series_col}:N", sort=segs),
            y="Value:Q", text=alt.Text("Value:Q", format=vf))
    return _style(bars.properties(height=height or 380, width=max(420, 34 * n_items * max(n_seg, 1) + 80), title=title))
