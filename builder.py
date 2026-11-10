"""
builder.py - Report Builder engine.

Every report is a table of ROWS (questions / indicators) x COLUMNS (Total + the categories of a
break-down variable) x a chosen set of STATISTICS / VALUES. Three families:
    freq    choice questions and rating distributions: Count, Column %, Row %, Base
    scores  rated indicators (pillars, sub-groups, questions): any statistic
    numeric numeric measures (spend, age, SIMs ...): any statistic
plus a correlation matrix. Works for any survey: rows come from the script, the Topline structure
and the dataset. Segment questions follow the script's skip logic (see skip.py).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats as sps

import core
import general as G

STATS = {**G.STATS, "avg_q": "Average of question means"}
VALUES = {"count": "Count", "col_pct": "Column %", "row_pct": "Row %"}
PCT_STATS = {"pct_low", "pct_mid", "pct_high", "top2"}
INT_STATS = {"n", "missing", "sum"}


# ------------------------------------------------------------------ segment resolution
def resolve_segment(df, form, var, var2, value_labels, pop, follow=True):
    """Prepare the break-down variable (cleaned text, nested, skip logic). Returns dict with
    df, var, labels {code: label}, pop (mask), rules (skip-logic text), counts {code: n}."""
    vl = dict(value_labels or {})
    dfg, col = df, var

    def clean(v):
        nonlocal dfg
        d2, c2, lab = G.clean_text_segment(dfg, form, v)
        if lab is not None:
            dfg = d2; vl[c2] = lab
        return c2

    col = clean(var)
    if var2:
        col2 = clean(var2)
        dfg, col, comb = G.combo_column(dfg, form, col, col2, vl)
        vl[col] = comb
    rules, ok = [], True
    pop = pop.copy()
    if follow:
        am, rules, ok = G.asked_mask(df, form, var, [var2] if var2 else [])
        pop &= am
    opts = core.segment_options(dfg, form, col, {col: vl[col]} if col in vl else None)
    if core.is_multi(form, col):
        counts = {c: int(core.segment_mask(dfg, form, col, [c])[pop].sum()) for c in opts}
    else:
        vc = core.segment_codes(dfg, col)[pop].value_counts()
        counts = {c: int(vc.get(c, 0)) for c in opts}
    opts = {c: l for c, l in opts.items() if counts[c] > 0}
    return dict(df=dfg, var=col, labels=opts, pop=pop, rules=rules, ok=ok, counts=counts)


def segment_masks(df, form, var, cats: Dict[str, str], pop, include_total=True) -> Dict[str, pd.Series]:
    out = {"Total": pop} if include_total else {}
    for code, lab in cats.items():
        name = lab if lab not in out else f"{lab} ({code})"
        out[name] = core.segment_mask(df, form, var, [code]) & pop
    return out


# ------------------------------------------------------------------ rows
@dataclass
class RowDef:
    label: str
    variable: str
    qs: List[str]
    level: str          # oss | pillar | sub | question
    kind: str = "rating"  # rating | numeric


def indicator_rows(tree, form, V) -> List[dict]:
    """All Topline rows (OSS, pillars, sub-groups, questions) with the pillar each belongs to."""
    t = core.compute_topline(V, tree, form)
    rows, pillar = [], ""
    for _, r in t.iterrows():
        if r["kind"] == "pillar":
            pillar = r["Indicator"]
        rows.append(dict(row=RowDef(r["Indicator"], r["Variable"], list(r["leaves"]), r["kind"]),
                         pillar=pillar if r["kind"] != "oss" else ""))
    return rows


# ------------------------------------------------------------------ statistics
def _stats_block(a2: np.ndarray, keys: List[str], rating: bool, missing=np.nan) -> dict:
    """a2: respondents x questions array with NaN = no valid answer."""
    a = a2[~np.isnan(a2)]
    out = G.describe(pd.Series(a), [k for k in keys if k != "avg_q"], rating, 0)
    if "missing" in keys:
        out["missing"] = missing
    if "avg_q" in keys:
        cnt = (~np.isnan(a2)).sum(axis=0)
        out["avg_q"] = float(np.nanmean(np.nansum(a2, axis=0)[cnt > 0] / cnt[cnt > 0])) if a2.shape[1] > 1 and (cnt > 0).any() else np.nan
    return out


def score_long(df, form, V, rows: List[RowDef], segs: Dict[str, pd.Series], pop, keys: List[str],
               sig=False, alpha=0.05) -> pd.DataFrame:
    recs = []
    for r in rows:
        if r.kind == "numeric":
            a2 = pd.to_numeric(df[r.qs[0]], errors="coerce").to_numpy(float)[:, None]
            raw_n = df[r.qs[0]].notna().to_numpy()
        else:
            a2 = V[[q for q in r.qs if q in V.columns]].to_numpy(float)
            raw_n = df[r.qs[0]].notna().to_numpy() if len(r.qs) == 1 and r.qs[0] in df.columns else None
        resp = np.nanmean(a2, axis=1) if a2.shape[1] > 1 else a2[:, 0]
        popn = pop.to_numpy()
        for name, m in segs.items():
            mm = m.to_numpy()
            sub = a2[mm]
            miss = (raw_n[mm].sum() - (~np.isnan(sub)).sum()) if raw_n is not None else np.nan
            rec = dict(Row=r.label, Variable=r.variable if len(r.qs) == 1 or r.variable else "", Level=r.level, Segment=name,
                       **_stats_block(sub, keys, r.kind == "rating", miss))
            rec["Sig"] = ""
            if sig and name != "Total" and "mean" in keys:
                x, y = resp[mm], resp[popn & ~mm]
                x, y = x[~np.isnan(x)], y[~np.isnan(y)]
                if len(x) > 1 and len(y) > 1 and (x.std() > 0 or y.std() > 0):
                    p = sps.ttest_ind(x, y, equal_var=False).pvalue
                    if p < alpha:
                        rec["Sig"] = "▲" if x.mean() > y.mean() else "▼"
            recs.append(rec)
    return pd.DataFrame(recs)


def freq_long(df, form, items: List[G.Item], segs: Dict[str, pd.Series], pop, value_labels,
              sig=False, alpha=0.05) -> pd.DataFrame:
    recs = []
    for it in items:
        M, A, lab = G.cat_matrix(df, form, it, value_labels)
        if it.kind == "rating":
            lab = {c: ("Don't know" if c == "99" else l) for c, l in lab.items()}
        base_pop = A & pop
        tot_cnt = M[base_pop].sum()
        for name, m in segs.items():
            sel = A & m
            n = int(sel.sum())
            cnt = M[sel].sum()
            rest = A & pop & ~m
            n2 = int(rest.sum()); cnt2 = M[rest].sum()
            for code in M.columns:
                c = int(cnt[code])
                rec = dict(Question=it.label, Variable=it.name, Kind=it.kind, Code=code, Answer=lab[code], Segment=name,
                           Count=c, Col=c / n if n else np.nan,
                           Row=c / tot_cnt[code] if tot_cnt[code] else np.nan, Base=n, Sig="")
                if sig and name != "Total" and n >= 5 and n2 >= 5:
                    p = G._ztest(c, n, int(cnt2[code]), n2)
                    if not np.isnan(p) and p < alpha:
                        rec["Sig"] = "▲" if c / n > cnt2[code] / n2 else "▼"
                recs.append(rec)
    return pd.DataFrame(recs)


# ------------------------------------------------------------------ report tables (shared by UI + Excel)
@dataclass
class ReportTable:
    family: str                         # freq | scores | numeric | corr
    title: str
    subtitle: str
    lead: List[str]                     # leading text columns
    cols: List[dict]                    # [{key, block, seg, fmt}]
    data: pd.DataFrame                  # lead cols + '_kind' + one column per cols[i]['key']
    sig: Optional[pd.DataFrame] = None  # arrows aligned with data (same keys)
    decimals: int = 2
    segments: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    chart: Optional[pd.DataFrame] = None   # long frame for charts: Item, Segment, Block, Value, Fmt
    layout: str = "block"                  # block = statistic groups first, segment = segment groups first

    def label(self, c: dict) -> str:
        if len(self.blocks) == 1:
            return c["seg"]
        if len(self.segments) == 1:
            return c["block"]
        return f"{c['block']} · {c['seg']}" if self.layout == "block" else f"{c['seg']} · {c['block']}"

    def flat(self, fmt_values=True) -> pd.DataFrame:
        """Display / CSV frame with 'Block · Segment' headers."""
        out = self.data[self.lead].copy()
        for c in self.cols:
            out[self.label(c)] = self.data[c["key"]]
        return out


def _order_cols(blocks: List[str], segs: List[str], fmts: Dict[str, str], layout: str) -> List[dict]:
    pairs = [(b, s) for b in blocks for s in segs] if layout == "block" else [(b, s) for s in segs for b in blocks]
    return [dict(key=f"{b}||{s}", block=b, seg=s, fmt=fmts[b]) for b, s in pairs]


def make_scores_table(long: pd.DataFrame, keys: List[str], segs: List[str], title, subtitle,
                      layout="block", decimals=2, family="scores") -> ReportTable:
    blocks = [STATS[k] for k in keys]
    fm = {STATS[k]: ("int" if k in INT_STATS else "pct" if k in PCT_STATS else "num") for k in keys}
    order = list(dict.fromkeys(zip(long["Row"], long["Variable"], long["Level"])))
    data = pd.DataFrame(order, columns=["Indicator", "Variable", "_kind"])
    sig = pd.DataFrame(index=data.index)
    idx = {k: i for i, k in enumerate(order)}
    cols = _order_cols(blocks, segs, fm, layout)
    for c in cols:
        data[c["key"]] = np.nan
        sig[c["key"]] = ""
    inv = {STATS[k]: k for k in keys}
    for rec in long.itertuples(index=False):
        i = idx[(rec.Row, rec.Variable, rec.Level)]
        for c in cols:
            if c["seg"] == rec.Segment:
                k = inv[c["block"]]
                v = getattr(rec, k) if k not in ("var",) else np.nan
                data.at[i, c["key"]] = v / 100 if k in PCT_STATS and pd.notna(v) else v
                if k == "mean":
                    sig.at[i, c["key"]] = rec.Sig
    long_chart = long.melt(id_vars=["Row", "Segment", "Level"], value_vars=keys, var_name="k", value_name="Value")
    long_chart["Block"] = long_chart["k"].map(STATS)
    long_chart["Fmt"] = long_chart["k"].map(lambda k: "int" if k in INT_STATS else "pct" if k in PCT_STATS else "num")
    long_chart["Value"] = np.where(long_chart["k"].isin(PCT_STATS), long_chart["Value"] / 100, long_chart["Value"])
    long_chart = long_chart.rename(columns={"Row": "Item"})[["Item", "Segment", "Block", "Value", "Fmt", "Level"]]
    return ReportTable(family, title, subtitle, ["Indicator", "Variable"], cols, data, sig, decimals, segs, blocks, long_chart, layout)


def make_freq_table(long: pd.DataFrame, values: List[str], segs: List[str], title, subtitle,
                    layout="block", decimals=1, show_base=True) -> ReportTable:
    blocks = [VALUES[v] for v in values]
    fm = {"Count": "int", "Column %": "pct", "Row %": "pct"}
    cols = _order_cols(blocks, segs, fm, layout)
    inv = {"Count": "Count", "Column %": "Col", "Row %": "Row"}
    rows = []
    sigrows = []
    for (q, var), g in long.groupby(["Question", "Variable"], sort=False):
        rows.append({"Question": q, "Variable": var, "Answer": "", "_kind": "qhead"})
        sigrows.append({})
        for (code, ans), gg in g.groupby(["Code", "Answer"], sort=False):
            r = {"Question": q, "Variable": var, "Answer": ans, "_kind": "row"}
            s = {}
            for rec in gg.itertuples(index=False):
                for c in cols:
                    if c["seg"] == rec.Segment:
                        r[c["key"]] = getattr(rec, inv[c["block"]])
                        if c["block"] == "Column %":
                            s[c["key"]] = rec.Sig
            rows.append(r); sigrows.append(s)
        if show_base:
            r = {"Question": q, "Variable": var, "Answer": "Base (N answering)", "_kind": "base"}
            for rec in g.drop_duplicates("Segment").itertuples(index=False):
                for c in cols:
                    if c["seg"] == rec.Segment and c["block"] == blocks[0]:
                        r[c["key"]] = rec.Base
            rows.append(r); sigrows.append({})
    data = pd.DataFrame(rows)
    sig = pd.DataFrame(sigrows).reindex(columns=[c["key"] for c in cols]).fillna("")
    for c in cols:
        if c["key"] not in data.columns:
            data[c["key"]] = np.nan
    chart = long.rename(columns={"Question": "Item"}).copy()
    return ReportTable("freq", title, subtitle, ["Question", "Answer"], cols, data, sig, decimals, segs, blocks, chart, layout)


def corr_table(df, form, V, tree, names: List[str], method="pearson", pop=None) -> pd.DataFrame:
    sc = core.respondent_pillar_scores(V[pop] if pop is not None else V, tree)
    sc = sc[[n for n in names if n in sc.columns]]
    return sc.corr(method=method, min_periods=30)
