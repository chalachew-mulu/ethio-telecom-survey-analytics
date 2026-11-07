"""export_general.py - colour-coded Excel for the GENERAL report (all parts, selected statistics, segments, tests)."""
from __future__ import annotations
import io
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

import core
import general as G
import export as X

FONT = "Arial"
thin = Side(style="thin", color="D0D0D0")
BORDER = Border(bottom=thin, top=thin, left=thin, right=thin)
SIG_UP, SIG_DN = "C6EFCE", "FFC7CE"


def _fill(h): return PatternFill("solid", fgColor=h)


def _band_fill(m, lo, hi):
    b = X._band(m, lo, hi)
    return b


def _part_style(ws, r, ncols, color, text, size=11):
    for c in range(1, ncols + 1):
        x = ws.cell(r, c); x.fill = _fill(color); x.font = Font(name=FONT, bold=True, color="FFFFFF", size=size)
    ws.cell(r, 1, text)
    ws.row_dimensions[r].height = 20


def _sheet_setup(ws):
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0


def _overview(ws, ov: pd.DataFrame, items, stat_keys, filter_text, n, low_t, high_t):
    cols = ["Question", "Variable name", "Type"] + [STAT_LABEL(k) for k in stat_keys if k in ov.columns] + ["Most common answer"]
    X._title(ws, "General report - all questions", f"Filters: {filter_text}   |   Respondents: {n:,}", len(cols))
    for j, c in enumerate(cols, 1): ws.cell(4, j, c)
    X._hdr(ws, 4, 1, len(cols))
    r = 5
    parts = list(dict.fromkeys(ov["Part"]))
    kind = {i.name: i.kind for i in items}
    for pi, part in enumerate(parts):
        col = X.PILLAR_COLORS[pi % 8]
        _part_style(ws, r, len(cols), col, part); r += 1
        last_sec = None
        for _, row in ov[ov.Part == part].iterrows():
            if row["Section"] and row["Section"] != last_sec:
                for c in range(1, len(cols) + 1):
                    ws.cell(r, c).fill = _fill(X._tint(col, .35)); ws.cell(r, c).font = Font(name=FONT, bold=True, italic=True, size=10)
                ws.cell(r, 1, row["Section"]); r += 1
            last_sec = row["Section"] or last_sec
            vals = [row["Question"], row["Variable"], row["Type"]] + [row.get(k) for k in stat_keys if k in ov.columns] + [row.get("Top answer")]
            for j, v in enumerate(vals, 1):
                v = None if (v is not None and not isinstance(v, str) and pd.isna(v)) else (v.item() if hasattr(v, "item") else v)
                c = ws.cell(r, j, v); c.border = BORDER; c.font = Font(name=FONT, size=10, color="595959" if j == 2 else "000000")
                c.fill = _fill(X._tint(col, .08) if r % 2 else "FFFFFF")
                if j == 1: c.alignment = Alignment(wrap_text=True, vertical="center", indent=2)
                if j > 3 and j < len(vals): c.alignment = Alignment(horizontal="center")
            for j, k in enumerate([k for k in stat_keys if k in ov.columns], 4):
                c = ws.cell(r, j)
                c.number_format = "#,##0" if k in ("n", "missing", "sum") else "0.0" if k.startswith("pct") or k in ("top2", "cv") else "0.00"
                if k == "mean" and kind.get(row["Variable"]) == "rating" and c.value is not None:
                    b = _band_fill(c.value, low_t, high_t)
                    if b: c.fill = _fill(b[0]); c.font = Font(name=FONT, size=10, bold=True, color=b[1])
            r += 1
    for j, w in enumerate([80, 24, 14] + [11] * (len(cols) - 4) + [48], 1): ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "B5"


def STAT_LABEL(k): return G.STATS[k]


def _freqs(ws, df, form, items, mask, vl, parts_colors):
    X._title(ws, "Frequency tables - single & multiple choice questions", "Count and % of respondents who answered the question.", 5)
    r = 4
    for it in items:
        if it.kind not in ("single", "multi", "text"): continue
        col = parts_colors[it.part]
        if it.kind == "text":
            t = G.text_table(df[mask] if False else df, it, mask); head = ["Answer", "", "Count", "% of answering", ""]
            rows = [[a, "", c, p / 100, None] for a, c, p in zip(t["Answer"], t["Count"], t["% of answering"])]
            n = t.attrs["n"]
        else:
            M, A, lab = G.cat_matrix(df, form, it, vl)
            t = G.freq_table(M, A, lab, mask, multi=it.kind == "multi"); n = t.attrs["n"]
            head = ["Code", "Label", "Count", "% of answering", "Cumulative %" if it.kind == "single" else ""]
            rows = [[c, l, k, p / 100, (cu / 100 if it.kind == "single" else None)] for c, l, k, p, cu in
                    zip(t["Code"], t["Label"], t["Count"], t["% of answering"], t["Cumulative %"] if it.kind == "single" else [None] * len(t))]
        _part_style(ws, r, 5, col, f"{it.label}   [{it.name}]  |  {G.KIND_NAMES[it.kind]}  |  N = {n:,}", 10)
        ws.cell(r, 1).alignment = Alignment(wrap_text=False); r += 1
        for j, h in enumerate(head, 1):
            c = ws.cell(r, j, h); c.font = Font(name=FONT, bold=True, size=10); c.fill = _fill(X._tint(col, .3)); c.border = BORDER
        r += 1; r0 = r
        for row in rows:
            for j, v in enumerate(row, 1):
                c = ws.cell(r, j, v); c.border = BORDER; c.font = Font(name=FONT, size=10)
                if j == 3: c.number_format = "#,##0"
                if j in (4, 5): c.number_format = "0.0%"
            r += 1
        if rows:
            ws.conditional_formatting.add(f"D{r0}:D{r - 1}", DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1, color=col))
        r += 1
    for col, w in zip("ABCDE", [14, 70, 11, 15, 14]): ws.column_dimensions[col].width = w


def _seg_scores(ws, df, form, items, var, cats, mask, primary, alpha, title):
    labs = list(cats.values())
    ncols = 3 + 2 * len(labs)
    X._title(ws, title, f"Statistic shown: {G.STATS[primary]}.  Green = significantly higher than the rest, red = significantly lower (Welch t-test, p < {alpha}).", ncols)
    ws.cell(4, 1, "Question"); ws.cell(4, 2, "Variable name"); ws.cell(4, 3, "Total")
    for k, l in enumerate(labs):
        c1 = 4 + 2 * k
        ws.cell(3, c1, l); ws.merge_cells(start_row=3, start_column=c1, end_row=3, end_column=c1 + 1)
        X._hdr(ws, 3, c1, c1 + 1, color=X.PILLAR_COLORS[k % 8], height=20)
        ws.cell(4, c1, G.STATS[primary]); ws.cell(4, c1 + 1, "N")
    X._hdr(ws, 4, 1, ncols, height=22)
    r = 5
    for pi, part in enumerate(dict.fromkeys(i.part for i in items)):
        col = X.PILLAR_COLORS[pi % 8]
        its = [i for i in items if i.part == part and i.kind in ("rating", "numeric")]
        if not its: continue
        _part_style(ws, r, ncols, col, part, 10); r += 1
        for it in its:
            b = G.breakdown_numeric(df, form, it, var, cats, mask, list(dict.fromkeys([primary, "n"])), alpha)
            ws.cell(r, 1, it.label).alignment = Alignment(wrap_text=True, indent=2, vertical="center")
            ws.cell(r, 2, it.name).font = Font(name=FONT, size=9, color="595959")
            ws.cell(r, 3, None if pd.isna(b.iloc[0][primary]) else float(b.iloc[0][primary])).number_format = "0.00"
            for k in range(len(labs)):
                row = b.iloc[1 + k]
                v = row[primary]; c = ws.cell(r, 4 + 2 * k, None if pd.isna(v) else float(v)); c.number_format = "0.00"
                ws.cell(r, 5 + 2 * k, int(row["n"]) if not pd.isna(row["n"]) else None).number_format = "#,##0"
                if row["Sig."]:
                    c.fill = _fill(SIG_UP if row["Sig."] == "▲" else SIG_DN); c.font = Font(name=FONT, size=10, bold=True)
                if not pd.isna(row["n"]) and row["n"] < 30:
                    ws.cell(r, 5 + 2 * k).font = Font(name=FONT, size=10, italic=True, color="808080")
            for c in range(1, ncols + 1):
                ws.cell(r, c).border = BORDER
                if c > 2: ws.cell(r, c).alignment = Alignment(horizontal="center")
            r += 1
    ws.column_dimensions["A"].width = 78; ws.column_dimensions["B"].width = 22
    for c in range(3, ncols + 1): ws.column_dimensions[get_column_letter(c)].width = 10
    ws.freeze_panes = "D5"


def _seg_choices(ws, df, form, items, var, cats, mask, vl, alpha, parts_colors, title):
    labs = list(cats.values())
    ncols = 2 + len(labs) + 1
    X._title(ws, title, f"Column % of respondents answering. Green/red = significantly higher/lower than the rest (z-test, p < {alpha}). Header shows chi-square p and Cramér's V (single choice).", ncols)
    r = 4
    for it in items:
        if it.kind not in ("single", "multi"): continue
        pct, sig, cnt, meta = G.breakdown_categorical(df, form, it, var, cats, mask, vl, alpha)
        col = parts_colors[it.part]
        extra = f"   |   chi2 p = {meta['p']:.3f}, Cramér's V = {meta['Cramér' + chr(39) + 's V']:.2f}" if "p" in meta else ""
        _part_style(ws, r, ncols, col, f"{it.label}   [{it.name}]{extra}", 10); r += 1
        ws.cell(r, 1, "Answer"); ws.cell(r, 2, "Total")
        for k, l in enumerate(labs): ws.cell(r, 3 + k, l)
        for c in range(1, ncols):
            x = ws.cell(r, c); x.font = Font(name=FONT, bold=True, size=10); x.fill = _fill(X._tint(col, .3)); x.border = BORDER
            if c > 1: x.alignment = Alignment(horizontal="center")
        r += 1
        for opt in pct.index:
            ws.cell(r, 1, opt).font = Font(name=FONT, size=10); ws.cell(r, 1).border = BORDER
            for k, name in enumerate(["Total"] + labs):
                v = pct.at[opt, name]; c = ws.cell(r, 2 + k, None if pd.isna(v) else float(v) / 100)
                c.number_format = "0.0%"; c.border = BORDER; c.alignment = Alignment(horizontal="center"); c.font = Font(name=FONT, size=10)
                s = sig.at[opt, name]
                if s: c.fill = _fill(SIG_UP if s == "▲" else SIG_DN); c.font = Font(name=FONT, size=10, bold=True)
            r += 1
        ws.cell(r, 1, "N answering").font = Font(name=FONT, size=9, italic=True, color="595959")
        for k, name in enumerate(["Total"] + labs):
            c = ws.cell(r, 2 + k, meta["n"][name]); c.number_format = "#,##0"; c.font = Font(name=FONT, size=9, italic=True, color="595959"); c.alignment = Alignment(horizontal="center")
        r += 2
    ws.column_dimensions["A"].width = 60
    for c in range(2, ncols + 1): ws.column_dimensions[get_column_letter(c)].width = 11


def _findings(ws, findings):
    X._title(ws, "Key findings (auto-generated)", "Generated from the data and the questionnaire structure; no manual input.", 2)
    r = 4
    for h, t in findings:
        c = ws.cell(r, 1, h); c.font = Font(name=FONT, bold=True, size=11, color="FFFFFF"); c.fill = _fill(X.NAVY)
        ws.cell(r, 2).fill = _fill(X.NAVY); r += 1
        for line in str(t).split("\n"):
            c = ws.cell(r, 1, line); c.font = Font(name=FONT, size=10); c.alignment = Alignment(wrap_text=True, vertical="top", indent=1)
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
            ws.row_dimensions[r].height = 15 * max(1, len(line) // 150 + 1); r += 1
        r += 1
    ws.column_dimensions["A"].width = 110; ws.column_dimensions["B"].width = 40


def _df_sheet(ws, d: pd.DataFrame, title, fmt=None):
    X._write_df(ws, d, fmt or {}, title)
    ws.column_dimensions["A"].width = 70


def _corr(ws, corr: pd.DataFrame, method):
    n = len(corr)
    X._title(ws, f"Correlation matrix ({method})", "", n + 1)
    ws.cell(4, 1, "")
    for j, c in enumerate(corr.columns, 2): ws.cell(4, j, c[:30])
    X._hdr(ws, 4, 1, n + 1, height=60)
    for i, (idx, row) in enumerate(corr.iterrows()):
        ws.cell(5 + i, 1, idx).font = Font(name=FONT, bold=True, size=10)
        for j, v in enumerate(row, 2):
            c = ws.cell(5 + i, j, None if pd.isna(v) else float(v)); c.number_format = "0.00"; c.alignment = Alignment(horizontal="center"); c.border = BORDER
    ws.conditional_formatting.add(f"B5:{get_column_letter(n + 1)}{4 + n}", ColorScaleRule(
        start_type="num", start_value=-1, start_color="F8A5A5", mid_type="num", mid_value=0, mid_color="FFFFFF", end_type="num", end_value=1, end_color="63BE7B"))
    ws.column_dimensions["A"].width = 45
    for j in range(2, n + 2): ws.column_dimensions[get_column_letter(j)].width = 14


def method_lines(stat_keys, alpha, min_diff):
    L = ["Methodology - General report",
         "Scope: every question in the SurveyCTO script (all PART groups and nested sub-groups), in script order. Notes, IDs, GPS, audio, dates and contact fields are excluded.",
         "Question types: Rating (the script's 1-10 choice list; 99/'Don't know' and other non-scale codes are excluded from the statistics), Numeric (integer/decimal/calculated), Single choice, Multiple choice, Open text (optional).",
         "N (valid) = respondents with a valid answer to the question (skip-logic means N varies by question).",
         "Frequencies: Count and % of respondents answering the question. Multiple-choice percentages add up to more than 100%.",
         "Selected statistics: " + "; ".join(G.STATS[k] for k in stat_keys) + ".",
         "Mean/Median/Mode/Std/Quartiles are computed on valid answers. Mode = most frequent value (lowest value if tied). Std. error = SD / sqrt(N); 95% CI = mean +/- 1.96 x SE.",
         "Sum = mean x N (the 'weighted mean' of the Ethio telecom sheet). CV % = SD / mean x 100. % Low = ratings 1-5, % Mid = 6-7, % High = 8-10, Top-2 = 9-10.",
         f"Segment comparison (rating / numeric): each category vs all other respondents with Welch's t-test (unequal variances), Cohen's d effect size; overall ANOVA and Kruskal-Wallis across categories (only when categories do not overlap). Significance level alpha = {alpha}.",
         "Segment comparison (choices): each option's % in a category vs the rest with a two-proportion z-test; overall chi-square test and Cramér's V for single-choice questions.",
         f"Key findings use Benjamini-Hochberg adjusted p-values across all question x category tests (controls false discoveries) and report gaps of at least {min_diff} points.",
         "Small bases: categories with fewer than 30 valid answers are shown in grey italics and should be read with caution; tests need at least 2 observations per side (z-test: 5).",
         "Correlations: Pearson (linear) or Spearman (rank) on respondents' scores with pairwise-complete observations."]
    return L


def to_excel(df, form, items, mask, stat_keys, vl, filter_text, var=None, cats=None, findings=None, gaps=None,
             corr=None, corr_method="pearson", alpha=0.05, min_diff=0.3, low_t=7.0, high_t=8.0, var_title=None) -> bytes:
    wb = Workbook(); ws = wb.active; ws.title = "General overview"
    ov = G.overview(df, form, items, mask, stat_keys, vl)
    _overview(ws, ov, items, stat_keys, filter_text, int(mask.sum()), low_t, high_t)
    pcol = {p: X.PILLAR_COLORS[i % 8] for i, p in enumerate(G.parts_of(items))}
    _freqs(wb.create_sheet("Frequencies"), df, form, items, mask, vl, pcol)
    if var and cats:
        vt = f"by {var_title or var}"
        primary = "mean" if "mean" in stat_keys else next((k for k in stat_keys if k not in ("n", "missing") and k not in G.RATING_ONLY), "mean")
        _seg_scores(wb.create_sheet("Segments - scores"), df, form, items, var, cats, mask, primary, alpha, f"Rating & numeric questions {vt}")
        _seg_choices(wb.create_sheet("Segments - choices"), df, form, items, var, cats, mask, vl, alpha, pcol, f"Choice questions {vt}")
    if findings:
        _findings(wb.create_sheet("Key findings"), findings)
    if gaps is not None and len(gaps):
        g = gaps.sort_values("p (BH adj.)").copy()
        _df_sheet(wb.create_sheet("Segment gaps"), g[["Question", "Variable", "Part", "Segment", "N", "Segment mean", "Rest mean", "Diff", "p", "p (BH adj.)"]],
                  "Every rating question x segment category vs the rest",
                  {"Segment mean": "0.00", "Rest mean": "0.00", "Diff": "+0.00;-0.00", "p": "0.0000", "p (BH adj.)": "0.0000"})
    if corr is not None and len(corr):
        _corr(wb.create_sheet("Correlations"), corr, corr_method)
    m = wb.create_sheet("Method")
    for i, line in enumerate(method_lines(stat_keys, alpha, min_diff), 1):
        m.cell(i, 1, line).font = Font(name=FONT, size=10, bold=(i == 1)); m.cell(i, 1).alignment = Alignment(wrap_text=True, vertical="top")
    m.column_dimensions["A"].width = 150
    for sh in wb.worksheets: _sheet_setup(sh)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
