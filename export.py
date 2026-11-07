"""export.py - professional, colour-coded Excel report.

Topline sheet columns: Label name | Variable name | Mean | N responded (Base) |
Weighted mean (= mean x N = sum of ratings) | Average of question means | % Low | % High.
Question rows hold the data; group / sub-group / pillar / OSS rows are live Excel
formulas over the question rows beneath them (so the sheet can be audited):
    Weighted = SUM(weighted of its questions)   N = SUM(N of its questions)
    Mean = Weighted / N      Avg of question means = AVERAGE(question means)
"""
from __future__ import annotations
import io
from typing import Optional
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "Arial"
NAVY = "1F3864"
PILLAR_COLORS = ["1F4E79", "2E7D32", "6A1B9A", "B45F06", "C0392B", "00796B", "5D4037", "37474F"]
BAND = {"low": ("F4B6B6", "7A0000"), "mid": ("FFE699", "6B4F00"), "high": ("B7E1B1", "1E5128")}
thin = Side(style="thin", color="D0D0D0")
BORDER = Border(bottom=thin, top=thin, left=thin, right=thin)


def _tint(hex_, f):
    """Blend colour with white. f=1 -> colour, f=0 -> white."""
    r, g, b = (int(hex_[i:i + 2], 16) for i in (0, 2, 4))
    m = lambda c: int(255 - (255 - c) * f)
    return f"{m(r):02X}{m(g):02X}{m(b):02X}"


def _fill(h): return PatternFill("solid", fgColor=h)


def _band(m, low_t, high_t):
    if m is None or pd.isna(m): return None
    return BAND["low"] if m < low_t else BAND["high"] if m >= high_t else BAND["mid"]


def _hdr(ws, row, c1, c2, color=NAVY, height=34):
    for c in range(c1, c2 + 1):
        x = ws.cell(row, c)
        x.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        x.fill = _fill(color)
        x.alignment = Alignment(horizontal="left" if c == c1 else "center", vertical="center", wrap_text=True)
        x.border = BORDER
    ws.row_dimensions[row].height = height


def _refs(col, rows):
    """'D5:D9,D12' from a sorted list of row numbers (collapses consecutive rows)."""
    rows = sorted(rows); out = []; i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1] == rows[j] + 1: j += 1
        out.append(f"{col}{rows[i]}" if i == j else f"{col}{rows[i]}:{col}{rows[j]}")
        i = j + 1
    return ",".join(out)


def _title(ws, text, sub, ncols):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    ws.cell(1, 1, text).font = Font(name=FONT, bold=True, size=14, color="FFFFFF")
    ws.cell(1, 1).fill = _fill(NAVY)
    ws.cell(1, 1).alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 28
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    ws.cell(2, 1, sub).font = Font(name=FONT, italic=True, size=10, color="404040")
    ws.cell(2, 1).alignment = Alignment(wrap_text=True, vertical="top", indent=1)
    ws.row_dimensions[2].height = 30


def _write_topline(ws, t, filter_text, n_resp, round_q, low_t, high_t, title="Customers' Satisfaction Survey - Topline"):
    _title(ws, title,
           f"Filters: {filter_text}   |   Respondents: {n_resp:,}   |   "
           f"Weighted mean = Mean x N responded ({'2-dp rounded means, as in the Ethio telecom sheet' if round_q else 'exact sum of ratings'})", 8)
    heads = ["Label name", "Variable name", "Mean", "N responded (Base)", "Weighted mean\n(Mean x N)",
             "Average of\nquestion means", "% Low\n(1-5)", "% High\n(8-10)"]
    for j, h in enumerate(heads, 1): ws.cell(4, j, h)
    _hdr(ws, 4, 1, 8)
    first = 5
    rowmap, pcolor, cur = {}, {}, NAVY
    # first pass: assign rows
    for i, r in t.iterrows():
        rr = first + i
        if r["kind"] == "question" or (r["kind"] == "pillar" and r["Variable"]):
            rowmap[r["Variable"]] = rr
    pidx = -1
    for i, r in t.iterrows():
        rr, kind = first + i, r["kind"]
        if kind == "pillar":
            pidx += 1
        base = PILLAR_COLORS[pidx % len(PILLAR_COLORS)] if pidx >= 0 else "BF9000"
        is_leaf_pillar = kind == "pillar" and r["Variable"] != ""
        is_group = kind in ("oss", "pillar", "sub") and not is_leaf_pillar
        ws.cell(rr, 1, r["Indicator"]); ws.cell(rr, 2, r["Variable"] or None)
        if kind in ("question",) or is_leaf_pillar:
            ws.cell(rr, 3, None if pd.isna(r["MEAN"]) else float(r["MEAN"]))
            ws.cell(rr, 4, int(r["BASE"]))
            ws.cell(rr, 5, f"=ROUND(C{rr},2)*D{rr}" if round_q else f"=C{rr}*D{rr}")
        else:
            leaves = [rowmap[q] for q in r["leaves"] if q in rowmap]
            if leaves:
                ws.cell(rr, 4, f"=SUM({_refs('D', leaves)})")
                ws.cell(rr, 5, f"=SUM({_refs('E', leaves)})")
                ws.cell(rr, 3, f'=IFERROR(E{rr}/D{rr},"")')
                ws.cell(rr, 6, f'=IFERROR(AVERAGE({_refs("C", leaves)}),"")')
        ws.cell(rr, 7, None if pd.isna(r["PCT_LOW"]) else r["PCT_LOW"] / 100)
        ws.cell(rr, 8, None if pd.isna(r["PCT_HIGH"]) else r["PCT_HIGH"] / 100)
        # styling
        if kind == "oss":
            fill, fcol, bold = "FFD966", "000000", True
        elif kind == "pillar":
            fill, fcol, bold = base, "FFFFFF", True
        elif kind == "sub":
            fill, fcol, bold = _tint(base, 0.35), "000000", True
        else:
            fill, fcol, bold = (_tint(base, 0.09) if i % 2 else "FFFFFF"), "000000", False
        for c in range(1, 9):
            x = ws.cell(rr, c)
            x.fill = _fill(fill); x.border = BORDER
            x.font = Font(name=FONT, size=10, bold=bold, color=fcol, italic=(kind == "sub"))
        ws.cell(rr, 1).alignment = Alignment(indent=0 if kind in ("oss", "pillar") else (1 if kind == "sub" else 2 if t.at[i, "level"] <= 1 else 3),
                                             wrap_text=True, vertical="center")
        ws.cell(rr, 2).font = Font(name=FONT, size=9, color=fcol if kind in ("oss", "pillar") else "595959", bold=False)
        ws.cell(rr, 3).number_format = "0.00"; ws.cell(rr, 4).number_format = "#,##0"
        ws.cell(rr, 5).number_format = "#,##0"; ws.cell(rr, 6).number_format = "0.00"
        ws.cell(rr, 7).number_format = "0.0%"; ws.cell(rr, 8).number_format = "0.0%"
        for c in range(3, 9): ws.cell(rr, c).alignment = Alignment(horizontal="center", vertical="center")
        b = _band(r["MEAN"], low_t, high_t)           # mean cell colour = performance band
        if b:
            ws.cell(rr, 3).fill = _fill(b[0]); ws.cell(rr, 3).font = Font(name=FONT, size=10, bold=True, color=b[1])
    last = first + len(t) - 1
    lg = last + 2
    ws.cell(lg, 1, "Mean colour key:").font = Font(name=FONT, bold=True, size=9)
    for k, (key, txt) in enumerate([("low", f"below {low_t:g}"), ("mid", f"{low_t:g} to <{high_t:g}"), ("high", f"{high_t:g} and above")]):
        c = ws.cell(lg + 1 + k, 1, txt)
        c.fill = _fill(BAND[key][0]); c.font = Font(name=FONT, size=9, color=BAND[key][1], bold=True)
    for col, w in zip("ABCDEFGH", [88, 24, 9, 13, 15, 14, 9, 9]): ws.column_dimensions[col].width = w
    ws.freeze_panes = "C5"
    ws.sheet_view.zoomScale = 90
    return first


def _write_summary(ws, t, low_t, high_t):
    g = t[t.kind.isin(["oss", "pillar", "sub"])].reset_index(drop=True)
    heads = ["Group / sub-group", "Type", "Mean", "Average of question means", "N responded", "Weighted mean", "% Low", "% High", "Rank (pillars)"]
    _title(ws, "Group & sub-group summary", "Mean = pooled (weighted) mean of every valid response beneath the group.", len(heads))
    for j, h in enumerate(heads, 1): ws.cell(4, j, h)
    _hdr(ws, 4, 1, len(heads))
    pm = g[g.kind == "pillar"]["MEAN"].rank(ascending=False, method="min")
    for i, r in g.iterrows():
        rr = 5 + i
        vals = [r["Indicator"], {"oss": "Overall", "pillar": "Pillar", "sub": "Sub-group"}[r["kind"]], r["MEAN"],
                None if pd.isna(r["AVG_Q"]) else r["AVG_Q"], r["BASE"], r["WEIGHTED"], r["PCT_LOW"] / 100, r["PCT_HIGH"] / 100,
                int(pm[i]) if r["kind"] == "pillar" else None]
        for j, v in enumerate(vals, 1):
            x = ws.cell(rr, j, None if (v is not None and not isinstance(v, str) and pd.isna(v)) else v)
            x.border = BORDER
            x.font = Font(name=FONT, size=10, bold=r["kind"] != "sub")
            if j >= 3: x.alignment = Alignment(horizontal="center")
        ws.cell(rr, 1).alignment = Alignment(indent=2 if r["kind"] == "sub" else 0)
        for j, f in {3: "0.00", 4: "0.00", 5: "#,##0", 6: "#,##0", 7: "0.0%", 8: "0.0%"}.items(): ws.cell(rr, j).number_format = f
        fill = "FFD966" if r["kind"] == "oss" else "D9E1F2" if r["kind"] == "pillar" else "F2F2F2"
        for j in range(1, 10): ws.cell(rr, j).fill = _fill(fill)
        b = _band(r["MEAN"], low_t, high_t)
        if b: ws.cell(rr, 3).fill = _fill(b[0]); ws.cell(rr, 3).font = Font(name=FONT, size=10, bold=True, color=b[1])
    for col, w in zip("ABCDEFGHI", [48, 11, 9, 14, 13, 14, 9, 9, 11]): ws.column_dimensions[col].width = w
    ws.freeze_panes = "A5"


def _write_wide(ws, w, low_t, high_t, title, min_base=30):
    cats = [c for c in w.columns if c not in ("kind", "level", "Variable", "Indicator") and not str(c).endswith("(n)")]
    ncols = 2 + 2 * len(cats)
    _title(ws, title, "Means (and N responded) per category. Colour scale: red = lower, green = higher across each row block.", ncols)
    ws.cell(4, 1, "Label name"); ws.cell(4, 2, "Variable name")
    ws.cell(3, 1, None)
    for k, c in enumerate(cats):
        c1 = 3 + 2 * k
        ws.merge_cells(start_row=3, start_column=c1, end_row=3, end_column=c1 + 1)
        ws.cell(3, c1, c)
        _hdr(ws, 3, c1, c1 + 1, color=PILLAR_COLORS[k % 8], height=22)
        ws.cell(4, c1, "Mean"); ws.cell(4, c1 + 1, "N")
    _hdr(ws, 4, 1, ncols, height=22)
    for i, r in w.reset_index(drop=True).iterrows():
        rr = 5 + i
        ws.cell(rr, 1, r["Indicator"]); ws.cell(rr, 2, r["Variable"] or None)
        for k, c in enumerate(cats):
            m, n = r[c], r[f"{c} (n)"]
            ws.cell(rr, 3 + 2 * k, None if pd.isna(m) else float(m)).number_format = "0.00"
            ws.cell(rr, 4 + 2 * k, None if pd.isna(n) else int(n)).number_format = "#,##0"
        kind = r["kind"]
        fill = "FFD966" if kind == "oss" else "D9E1F2" if kind == "pillar" else "EEF2F9" if kind == "sub" else None
        for c in range(1, ncols + 1):
            x = ws.cell(rr, c); x.border = BORDER
            x.font = Font(name=FONT, size=10 if c > 2 else 10, bold=kind != "question", color="595959" if c == 2 else "000000")
            if c > 2: x.alignment = Alignment(horizontal="center")
            if fill and (c <= 2 or c % 2 == 0 and False): x.fill = _fill(fill)
            if fill and c <= 2: x.fill = _fill(fill)
        ws.cell(rr, 1).alignment = Alignment(indent={"oss": 0, "pillar": 0, "sub": 1}.get(kind, 2), wrap_text=True)
        if r[["BASE" if False else "Total (n)"]].iloc[0] is not None:
            pass
        for k in range(len(cats)):
            n = ws.cell(rr, 4 + 2 * k).value
            if n is not None and n < min_base:
                for cc in (3 + 2 * k, 4 + 2 * k): ws.cell(rr, cc).font = Font(name=FONT, size=10, italic=True, color="808080")
    last = 4 + len(w)
    for k in range(len(cats)):
        col = get_column_letter(3 + 2 * k)
        ws.conditional_formatting.add(f"{col}5:{col}{last}", ColorScaleRule(
            start_type="num", start_value=low_t - 1.0, start_color="F8A5A5",
            mid_type="num", mid_value=(low_t + high_t) / 2, mid_color="FFF2AE",
            end_type="num", end_value=high_t + 0.7, end_color="8FD18F"))
    ws.column_dimensions["A"].width = 80; ws.column_dimensions["B"].width = 22
    for c in range(3, ncols + 1): ws.column_dimensions[get_column_letter(c)].width = 10
    ws.freeze_panes = "C5"


def _write_df(ws, d, fmt, title):
    _title(ws, title, "", len(d.columns))
    for j, c in enumerate(d.columns, 1): ws.cell(4, j, c)
    _hdr(ws, 4, 1, len(d.columns))
    for i, (_, r) in enumerate(d.iterrows()):
        for j, c in enumerate(d.columns, 1):
            v = r[c]; v = None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)
            x = ws.cell(5 + i, j, v); x.font = Font(name=FONT, size=10); x.border = BORDER
            if c in fmt: x.number_format = fmt[c]
            if j > 1: x.alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 45
    for j in range(2, len(d.columns) + 1): ws.column_dimensions[get_column_letter(j)].width = 16


def _write_charts(ws, t, wide):
    p = t[t.kind == "pillar"]
    ws["A1"], ws["B1"] = "Pillar", "Mean"
    for i, (_, r) in enumerate(p.iterrows(), 2):
        ws.cell(i, 1, r["Indicator"]); ws.cell(i, 2, round(float(r["MEAN"]), 2))
    _hdr(ws, 1, 1, 2, height=20)
    ch = BarChart(); ch.type = "bar"; ch.style = 10
    ch.title = "Mean by pillar"; ch.y_axis.scaling.min = 0; ch.y_axis.scaling.max = 10
    ch.add_data(Reference(ws, min_col=2, min_row=1, max_row=1 + len(p)), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=1 + len(p)))
    ch.legend = None; ch.height, ch.width = 9, 20
    ch.dataLabels = __import__("openpyxl").chart.label.DataLabelList(); ch.dataLabels.showVal = True
    ch.x_axis.delete = False; ch.y_axis.delete = False
    ws.add_chart(ch, "D1")
    if wide is not None:
        cats = [c for c in wide.columns if c not in ("kind", "level", "Variable", "Indicator") and not str(c).endswith("(n)") and c != "Total"]
        wp = wide[wide.kind == "pillar"].reset_index(drop=True)
        if 1 <= len(cats) <= 8 and len(wp):
            r0 = len(p) + 4
            ws.cell(r0, 1, "Pillar")
            for k, c in enumerate(cats): ws.cell(r0, 2 + k, c)
            _hdr(ws, r0, 1, 1 + len(cats), height=20)
            for i, r in wp.iterrows():
                ws.cell(r0 + 1 + i, 1, r["Indicator"])
                for k, c in enumerate(cats):
                    v = r[c]; ws.cell(r0 + 1 + i, 2 + k, None if pd.isna(v) else round(float(v), 2))
            c2 = BarChart(); c2.type = "col"; c2.style = 10; c2.title = "Pillar means by segment"
            c2.add_data(Reference(ws, min_col=2, max_col=1 + len(cats), min_row=r0, max_row=r0 + len(wp)), titles_from_data=True)
            c2.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=r0 + len(wp)))
            c2.y_axis.scaling.min = 0; c2.y_axis.scaling.max = 10; c2.height, c2.width = 10, 26
            c2.x_axis.delete = False; c2.y_axis.delete = False
            ws.add_chart(c2, "D20")
    ws.column_dimensions["A"].width = 38


METHOD = [
    "How the numbers are calculated",
    "Valid response = a number on the rating scale (1-10). Blanks, nulls, 99 'Don't know' and other codes are excluded.",
    "N responded (Base) of a question = number of valid responses. Mean of a question = average of its valid responses.",
    "Weighted mean = Mean x N responded (= the sum of all valid ratings). For a group it is the sum of its questions' weighted means.",
    "Mean of a group / sub-group / pillar = Weighted mean / N responded, i.e. the pooled mean of every valid response beneath it.",
    "Average of question means = simple average of the question means beneath the group (shown for comparison with the pooled mean).",
    "Overall Satisfaction Score (OSS) = pooled mean over all questions in all pillars.",
    "% Low = share of valid ratings from 1 to 5; % High = share from 8 to 10.",
    "Driver analysis = OLS of respondents' composite score (mean of all their valid ratings) on their pillar scores, z-scored, listwise. Reported: standardized coefficients, rank, R2.",
    "% growth = (this round mean / previous round mean - 1) x 100.",
    "Greyed italic numbers = fewer than 30 valid responses (low base).",
]


def to_excel(topline, filter_text, n_resp=0, min_base=30, wide=None, wide_title="By segment",
             drivers=None, comparison=None, round_q=False, low_t=7.0, high_t=8.0,
             title="Customers' Satisfaction Survey - Topline") -> bytes:
    wb = Workbook()
    ws = wb.active; ws.title = "Topline"
    _write_topline(ws, topline, filter_text, n_resp, round_q, low_t, high_t, title)
    _write_summary(wb.create_sheet("Group summary"), topline, low_t, high_t)
    if wide is not None:
        import re as _re
        safe = _re.sub(r'[\\/?*\[\]:]', '', str(wide_title)).strip()[:31] or 'By segment'
        _write_wide(wb.create_sheet(safe), wide, low_t, high_t, wide_title, min_base)
    _write_charts(wb.create_sheet("Charts"), topline, wide)
    if comparison is not None and len(comparison):
        _write_df(wb.create_sheet("Round comparison"), comparison,
                  {"Mean": "0.00", "Previous mean": "0.00", "% growth in mean": "0.0"}, "Round comparison")
    if drivers is not None and len(drivers["table"]):
        d = drivers["table"]
        s = wb.create_sheet("Drivers")
        _write_df(s, d, {"Std. coefficient": "0.000"}, f"Standardized coefficients (R2 = {drivers['r2']:.3f}, n = {drivers['n']:,})")
    m = wb.create_sheet("Method")
    for i, line in enumerate(METHOD, 1):
        m.cell(i, 1, line).font = Font(name=FONT, size=10, bold=(i == 1))
        m.cell(i, 1).alignment = Alignment(wrap_text=True, vertical="top")
    m.column_dimensions["A"].width = 140
    from openpyxl.worksheet.properties import PageSetupProperties
    for sh in wb.worksheets:
        sh.page_setup.orientation = "landscape"
        sh.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        sh.page_setup.fitToWidth, sh.page_setup.fitToHeight = 1, 0
    wb.calculation.fullCalcOnLoad = True
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()
