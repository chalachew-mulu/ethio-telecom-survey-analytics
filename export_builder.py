"""export_builder.py - Excel output of Report Builder tables (formatted table + native charts)."""
from __future__ import annotations
import io
import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

import export as X
from builder import ReportTable

FONT = "Arial"
thin = Side(style="thin", color="D0D0D0")
BORDER = Border(bottom=thin, top=thin, left=thin, right=thin)
SIG = {"▲": "C6EFCE", "▼": "FFC7CE"}


def _fill(h): return PatternFill("solid", fgColor=h)


def safe_name(s, used=()):
    n = re.sub(r"[\\/?*\[\]:]", "", str(s)).strip()[:31] or "Report"
    base, i = n, 2
    while n in used:
        n = f"{base[:28]}_{i}"; i += 1
    return n


def _numfmt(fmt, dec):
    return "#,##0" if fmt == "int" else ("0." + "0" * dec + "%" if dec else "0%") if fmt == "pct" else ("0." + "0" * dec if dec else "0")


def write_table(ws, rt: ReportTable, low_t=7.0, high_t=8.0, color_means=True, min_base=0) -> int:
    lead = ["Question / Answer"] if rt.family == "freq" else rt.lead
    nl = len(lead)
    ncol = nl + len(rt.cols)
    X._title(ws, rt.title, rt.subtitle, ncol)
    # header rows (group header + segment header)
    hr = 4
    blocks_first = rt.layout == "block"
    group_key = "block" if blocks_first else "seg"
    sub_key = "seg" if blocks_first else "block"
    for j, h in enumerate(lead, 1):
        ws.cell(hr, j, {"Indicator": "Indicator / question", "Variable": "Variable code"}.get(h, h)); ws.cell(hr + 1, j, None)
        ws.merge_cells(start_row=hr, start_column=j, end_row=hr + 1, end_column=j)
    j = nl + 1
    gi = 0
    while j <= ncol:
        c = rt.cols[j - nl - 1]
        k2 = j
        while k2 + 1 <= ncol and rt.cols[k2 + 1 - nl - 1][group_key] == c[group_key]:
            k2 += 1
        ws.cell(hr, j, c[group_key])
        if k2 > j: ws.merge_cells(start_row=hr, start_column=j, end_row=hr, end_column=k2)
        X._hdr(ws, hr, j, k2, color=X.PILLAR_COLORS[gi % 8], height=22)
        for t in range(j, k2 + 1):
            ws.cell(hr + 1, t, rt.cols[t - nl - 1][sub_key])
        gi += 1; j = k2 + 1
    X._hdr(ws, hr, 1, nl, height=22)
    X._hdr(ws, hr + 1, 1, ncol, color="44546A", height=30)
    r = hr + 2
    pidx = -1
    qidx = -1
    data, sig = rt.data, rt.sig
    for i, row in data.iterrows():
        kind = row["_kind"]
        if kind == "pillar": pidx += 1
        if kind == "qhead": qidx += 1
        col = X.PILLAR_COLORS[(qidx if rt.family == "freq" else max(pidx, 0)) % 8]
        for j, name in enumerate(lead, 1):
            v = (row["Question"] if kind == "qhead" else row["Answer"]) if rt.family == "freq" else row[name]
            v = None if (isinstance(v, float) and np.isnan(v)) or v == "" else v
            ws.cell(r, j, v)
        for jj, c in enumerate(rt.cols, nl + 1):
            v = row.get(c["key"])
            v = None if v is None or (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, "item") else v)
            cell = ws.cell(r, jj, v)
            cell.number_format = _numfmt("int" if kind == "base" else c["fmt"], rt.decimals)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        # styles
        for j in range(1, ncol + 1):
            x = ws.cell(r, j); x.border = BORDER
            x.font = Font(name=FONT, size=10)
        if kind in ("qhead", "oss", "pillar", "sub"):
            fill = {"qhead": col, "oss": "FFD966", "pillar": col, "sub": X._tint(col, .35)}[kind]
            fc = "FFFFFF" if kind in ("qhead", "pillar") else "000000"
            for j in range(1, ncol + 1):
                ws.cell(r, j).fill = _fill(fill); ws.cell(r, j).font = Font(name=FONT, size=10, bold=True, color=fc, italic=(kind == "sub"))
            if kind == "qhead":
                ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
                ws.cell(r, 1).alignment = Alignment(wrap_text=True, vertical="center"); ws.row_dimensions[r].height = 30
        elif kind == "base":
            for j in range(1, ncol + 1):
                ws.cell(r, j).font = Font(name=FONT, size=9, italic=True, color="595959"); ws.cell(r, j).fill = _fill("F2F2F2")
        else:
            if rt.family != "freq" and i % 2:
                for j in range(1, ncol + 1): ws.cell(r, j).fill = _fill(X._tint(col, .07))
        if rt.family != "freq": ws.cell(r, 1).alignment = Alignment(wrap_text=True, indent={"oss": 0, "pillar": 0, "sub": 1}.get(kind, 2), vertical="center")
        if nl > 1:
            ws.cell(r, 2).font = Font(name=FONT, size=9, color="595959" if kind not in ("pillar", "qhead") else "FFFFFF")
        if rt.family == "freq" and kind in ("row", "base"):
            ws.cell(r, 1).alignment = Alignment(indent=2)
        # significance + performance bands
        for jj, c in enumerate(rt.cols, nl + 1):
            cell = ws.cell(r, jj)
            if sig is not None and c["key"] in sig.columns and sig.at[i, c["key"]] in SIG:
                cell.fill = _fill(SIG[sig.at[i, c["key"]]]); cell.font = Font(name=FONT, size=10, bold=True, color="000000")
            elif color_means and rt.family == "scores" and c["block"] == "Mean" and cell.value is not None and kind != "qhead":
                b = X._band(cell.value, low_t, high_t)
                if b and 1 <= cell.value <= 10: cell.fill = _fill(b[0]); cell.font = Font(name=FONT, size=10, bold=True, color=b[1])
        r += 1
    widths = {"freq": [62, 0], "scores": [78, 22], "numeric": [78, 22], "corr": [40, 0]}.get(rt.family, [60, 20])
    ws.column_dimensions["A"].width = widths[0]
    if nl > 1: ws.column_dimensions["B"].width = widths[1]
    for j in range(nl + 1, ncol + 1): ws.column_dimensions[get_column_letter(j)].width = 13
    ws.freeze_panes = f"{get_column_letter(nl + 1)}{hr + 2}"
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    return r


def _chart_sheet(wb, name, rt: ReportTable, chart_kind, max_items=15, max_questions=6):
    """Native Excel charts on their own sheet (helper data + chart)."""
    cf = rt.chart
    if cf is None or not len(cf): return
    ws = wb.create_sheet(safe_name(name + " chart", wb.sheetnames))
    segs = rt.segments
    row = 1
    if rt.family == "freq":
        block = rt.blocks[0] if "Column %" not in rt.blocks else "Column %"
        key = {"Count": "Count", "Column %": "Col", "Row %": "Row"}[block]
        stacked = chart_kind == "Stacked 100% by segment"
        for qi, (q, g) in enumerate(cf.groupby("Item", sort=False)):
            if qi >= max_questions: break
            piv = g.pivot_table(index="Answer", columns="Segment", values=key, sort=False)[segs]
            if stacked: piv = piv.T
            ws.cell(row, 1, str(q)[:80]).font = Font(name=FONT, bold=True, size=10)
            hdr = row + 1
            ws.cell(hdr, 1, "")
            for j, c in enumerate(piv.columns, 2): ws.cell(hdr, j, str(c))
            for i, (idx, vals) in enumerate(piv.iterrows(), hdr + 1):
                ws.cell(i, 1, str(idx))
                for j, v in enumerate(vals, 2):
                    ws.cell(i, j, None if pd.isna(v) else float(v)).number_format = "0.0%" if key != "Count" else "#,##0"
            _add_chart(ws, hdr, len(piv), len(piv.columns), str(q)[:60], chart_kind, key != "Count", f"A{row}", stacked)
            row += max(len(piv) + 4, 22)
    else:
        blk = rt.blocks[0]
        sub = cf[cf.Block == blk]
        items = list(dict.fromkeys(sub["Item"]))[:max_items]
        piv = sub[sub.Item.isin(items)].pivot_table(index="Item", columns="Segment", values="Value", sort=False).reindex(items)[segs]
        ws.cell(1, 1, f"{blk}").font = Font(name=FONT, bold=True, size=10)
        for j, c in enumerate(piv.columns, 2): ws.cell(2, j, str(c))
        for i, (idx, vals) in enumerate(piv.iterrows(), 3):
            ws.cell(i, 1, str(idx)[:70])
            for j, v in enumerate(vals, 2):
                ws.cell(i, j, None if pd.isna(v) else float(v)).number_format = _numfmt(sub["Fmt"].iloc[0], rt.decimals)
        _add_chart(ws, 2, len(piv), len(piv.columns), f"{blk} by {rt.title}"[:80], chart_kind, False, "A1", False, sub["Fmt"].iloc[0] == "pct")
    ws.column_dimensions["A"].width = 60


def _add_chart(ws, hdr, nrows, ncols, title, kind, pct, anchor_row, stacked=False, pct_axis=False):
    ch = BarChart()
    ch.type = "bar" if kind == "Horizontal bars" else "col"
    ch.style = 10
    ch.title = title
    if stacked:
        ch.grouping = "percentStacked"; ch.overlap = 100
    data = Reference(ws, min_col=2, max_col=1 + ncols, min_row=hdr, max_row=hdr + nrows)
    ch.add_data(data, titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=hdr + 1, max_row=hdr + nrows))
    ch.height, ch.width = 9.5, 24
    from openpyxl.chart.shapes import GraphicalProperties
    ch.graphical_properties = GraphicalProperties(solidFill="FFFFFF")
    ch.plot_area.graphicalProperties = GraphicalProperties(solidFill="FFFFFF")
    ch.legend.position = "b"
    ch.x_axis.delete = False; ch.y_axis.delete = False
    if pct or pct_axis: ch.y_axis.number_format = "0%"
    ch.dataLabels = DataLabelList(); ch.dataLabels.showVal = not stacked; ch.dataLabels.showSerName = False
    ch.dataLabels.showCatName = False; ch.dataLabels.showLegendKey = False
    ws.add_chart(ch, f"{get_column_letter(ncols + 4)}{hdr - 1}")


def tables_to_excel(items: List[dict], low_t=7.0, high_t=8.0, contents_title="Report pack") -> bytes:
    """items: [{name, table: ReportTable, chart: str|None}] -> workbook (one sheet per table + chart sheets)."""
    wb = Workbook()
    wb.remove(wb.active)
    if len(items) > 1:
        cs = wb.create_sheet("Contents")
        X._title(cs, contents_title, "One sheet per breakdown.", 3)
        cs.cell(4, 1, "Sheet"); cs.cell(4, 2, "Report"); cs.cell(4, 3, "Base"); X._hdr(cs, 4, 1, 3)
    for n, it in enumerate(items):
        rt: ReportTable = it["table"]
        name = safe_name(it["name"], wb.sheetnames)
        ws = wb.create_sheet(name)
        write_table(ws, rt, low_t, high_t)
        if it.get("chart"):
            _chart_sheet(wb, name, rt, it["chart"])
        if len(items) > 1:
            r = 5 + n
            cs.cell(r, 1, name).hyperlink = f"#'{name}'!A1"; cs.cell(r, 1).font = Font(name=FONT, size=10, color="0563C1", underline="single")
            cs.cell(r, 2, rt.title).font = Font(name=FONT, size=10); cs.cell(r, 3, rt.subtitle).font = Font(name=FONT, size=10)
    if len(items) > 1:
        cs.column_dimensions["A"].width = 34; cs.column_dimensions["B"].width = 60; cs.column_dimensions["C"].width = 70
    meth = wb.create_sheet("Notes")
    for i, line in enumerate(NOTES, 1):
        meth.cell(i, 1, line).font = Font(name=FONT, size=10, bold=(i == 1)); meth.cell(i, 1).alignment = Alignment(wrap_text=True, vertical="top")
    meth.column_dimensions["A"].width = 130
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


NOTES = [
    "Notes",
    "Valid rating = a score on the 1-10 scale; blank answers, 'Don't know' (99) and other codes are excluded from every statistic and from the respondent counts (N).",
    "Indicator rows (overall, pillars, sub-groups) are pooled over all valid responses of the questions beneath them.",
    "Column % = share of respondents answering the question; Row % = share of an answer's total that falls in the column group.",
    "Segment questions follow the questionnaire's skip logic: only respondents who were asked the question are included.",
    "Green / red shading with arrows = significantly higher / lower than all other respondents at 95% (Welch t-test for means, z-test for percentages).",
    "Mean colours: red below the low threshold, amber between, green at or above the high threshold (rating means only).",
]


def corr_to_excel(corr: pd.DataFrame, title: str, subtitle: str) -> bytes:
    wb = Workbook(); ws = wb.active; ws.title = "Correlations"
    n = len(corr)
    X._title(ws, title, subtitle, n + 1)
    for j, c in enumerate(corr.columns, 2): ws.cell(4, j, str(c)[:30])
    ws.cell(4, 1, "")
    X._hdr(ws, 4, 1, n + 1, height=60)
    for i, (idx, row) in enumerate(corr.iterrows()):
        ws.cell(5 + i, 1, str(idx)).font = Font(name=FONT, bold=True, size=10)
        for j, v in enumerate(row, 2):
            c = ws.cell(5 + i, j, None if pd.isna(v) else float(v)); c.number_format = "0.00"; c.alignment = Alignment(horizontal="center"); c.border = BORDER
    ws.conditional_formatting.add(f"B5:{get_column_letter(n + 1)}{4 + n}", ColorScaleRule(
        start_type="num", start_value=-1, start_color="F8A5A5", mid_type="num", mid_value=0, mid_color="FFFFFF", end_type="num", end_value=1, end_color="63BE7B"))
    ws.column_dimensions["A"].width = 42
    for j in range(2, n + 2): ws.column_dimensions[get_column_letter(j)].width = 14
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
