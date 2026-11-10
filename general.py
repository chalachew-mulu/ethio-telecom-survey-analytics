"""
general.py - GENERAL REPORT engine (everything in the script, not only the rated indicators).

Reads the whole questionnaire (all PART groups, nested sub-groups, every question type) and builds
  * an inventory of questions, grouped Part > section, in script order
  * descriptive statistics (choose which: mean, median, mode, std, quartiles, CI, % low/high ...)
  * frequency tables for single / multiple choice questions
  * segment break-downs with significance tests (Welch t, ANOVA, Kruskal-Wallis, z-test, chi-square)
  * automatic "key findings" and correlations
Fully script-driven: a new question (e.g. about 5G) or a new group appears automatically next round.
Independent of core's Topline logic (it only re-uses its parsing helpers).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats as sps

import warnings
import core
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ------------------------------------------------------------------ statistics catalogue
STATS = {
    "n": "N (valid answers)", "missing": "Missing or Don't know (n)", "mean": "Mean", "median": "Median", "mode": "Mode",
    "std": "Std. deviation", "var": "Variance", "sem": "Std. error", "ci_lo": "95% CI (low)", "ci_hi": "95% CI (high)",
    "min": "Minimum", "q1": "Q1 (25th pct)", "q3": "Q3 (75th pct)", "max": "Maximum", "iqr": "IQR", "range": "Range",
    "sum": "Weighted score (Mean × N)", "cv": "Coeff. of variation %", "skew": "Skewness",
    "pct_low": "% Low scores (1–5)", "pct_mid": "% Mid scores (6–7)", "pct_high": "% High scores (8–10)", "top2": "% Top scores (9–10)",
}
RATING_ONLY = {"pct_low", "pct_mid", "pct_high", "top2"}
DEFAULT_STATS = ["n", "mean", "median", "mode", "std", "min", "max", "pct_high"]
KIND_NAMES = {"rating": "Rating (1-10)", "numeric": "Numeric", "single": "Single choice",
              "multi": "Multiple choice", "text": "Open text"}
SKIP_NAME = re.compile(r"(^duration$|phone|mobile_no|msisdn|enumerator|supervisor|^name_of_respondent|contact|geopoint|audio|uuid)", re.I)


def describe(x: pd.Series, keys: List[str], rating: bool = False, missing: int = 0) -> dict:
    """Descriptive stats of a numeric Series (NaN already removed)."""
    a = pd.to_numeric(x, errors="coerce").dropna().to_numpy(float)
    n = len(a)
    out = {k: np.nan for k in keys}
    if "n" in keys: out["n"] = n
    if "missing" in keys: out["missing"] = missing
    if n == 0:
        return out
    mean, sd = a.mean(), (a.std(ddof=1) if n > 1 else np.nan)
    sem = sd / np.sqrt(n) if n > 1 else np.nan
    q1, med, q3 = np.percentile(a, [25, 50, 75])
    vals, cnt = np.unique(a, return_counts=True)
    full = {"mean": mean, "median": med, "mode": vals[cnt.argmax()], "std": sd, "var": sd ** 2 if n > 1 else np.nan,
            "sem": sem, "ci_lo": mean - 1.96 * sem, "ci_hi": mean + 1.96 * sem, "min": a.min(), "q1": q1, "q3": q3,
            "max": a.max(), "iqr": q3 - q1, "range": a.max() - a.min(), "sum": a.sum(),
            "cv": sd / mean * 100 if n > 1 and mean else np.nan,
            "skew": float(sps.skew(a)) if n > 2 and sd > 0 else np.nan}
    if rating:
        full.update(pct_low=(a <= core.LOW_MAX).mean() * 100, pct_mid=((a > core.LOW_MAX) & (a < core.HIGH_MIN)).mean() * 100,
                    pct_high=(a >= core.HIGH_MIN).mean() * 100, top2=(a >= 9).mean() * 100)
    for k in keys:
        if k in full: out[k] = full[k]
    return out


# ------------------------------------------------------------------ inventory
@dataclass
class Item:
    name: str
    label: str
    kind: str                 # rating | numeric | single | multi | text
    list_name: Optional[str]
    part: str
    section: str              # deeper sub-section title ('' if none)
    order: int


def _title(form: core.Form, g: str) -> str:
    lab = form.group_labels.get(g, "")
    return lab if lab else ""


def build_inventory(form: core.Form, df: pd.DataFrame, value_labels: Optional[dict] = None,
                    include_text: bool = False) -> List[Item]:
    value_labels = value_labels or {}
    items: List[Item] = []
    for i, q in enumerate(form.questions.values()):
        if q.name not in df.columns or q.qtype in ("note", "start", "end", "deviceid", "username", "audio", "geopoint", "date", "today", "begin_repeat"):
            continue
        if SKIP_NAME.search(q.name) or "contact" in " ".join(form.group_labels.get(g, "") for g in q.group_path).lower():
            continue
        titles = [_title(form, g) for g in q.group_path if _title(form, g)]
        part = titles[0] if titles else "Other"
        sect = titles[-1] if len(titles) > 1 else ""
        if q.qtype == "select_one":
            kind = "rating" if q.list_name == form.rating_list else "single"
        elif q.qtype == "select_multiple":
            kind = "multi"
        elif q.qtype in ("integer", "decimal"):
            kind = "numeric"
        elif q.qtype == "calculate":
            nun = df[q.name].nunique()
            num = pd.to_numeric(df[q.name], errors="coerce").notna().mean() > 0.8
            kind = "single" if (nun <= 15 or not num) else "numeric"
            if nun == 0: continue
        elif q.qtype == "text":
            if not include_text: continue
            kind = "text"
        else:
            continue
        if df[q.name].notna().sum() == 0:
            continue
        label = q.label or q.name.replace("_", " ").capitalize()
        items.append(Item(q.name, label, kind, q.list_name, part, sect if sect != part else "", i))
    return items


def parts_of(items: List[Item]) -> List[str]:
    return list(dict.fromkeys(i.part for i in items))


# ------------------------------------------------------------------ series & category matrices
def numeric_series(df, form, it: Item) -> pd.Series:
    if it.kind == "rating":
        return core.valid_matrix(df, form, [it.name])[it.name]
    return pd.to_numeric(df[it.name], errors="coerce")


def cat_matrix(df, form, it: Item, value_labels: Optional[dict] = None):
    """(M, A, labels): M = respondent x option boolean matrix, A = answered flag, labels = {code: label}."""
    raw = df[it.name]
    answered = raw.notna() & (raw.astype(str).str.strip() != "")
    if it.kind == "multi":
        toks = raw.map(lambda v: [core._norm(x) if not isinstance(x, str) else x for x in
                                  (str(v).split() if isinstance(v, str) else [v])] if pd.notna(v) else [])
        codes = sorted({t for v in toks[answered] for t in v})
        M = pd.DataFrame({c: toks.map(lambda t, c=c: c in t) for c in codes}, index=df.index)
    else:
        s = raw.map(core._norm)
        codes = [c for c in s.unique() if c != ""]
        M = pd.DataFrame({c: (s == c) for c in codes}, index=df.index)
    labels = {}
    if it.list_name and it.list_name in form.choices:
        labels.update(form.choices[it.list_name])
    if value_labels and it.name in value_labels:
        labels.update({str(k): v for k, v in value_labels[it.name].items()})
    key = lambda c: (0, int(c)) if re.fullmatch(r"\d+", c) else (1, c)
    codes = sorted(M.columns, key=key)
    return M[codes], answered, {c: labels.get(c, c) for c in codes}


def freq_table(M, A, labels, mask=None, multi=False) -> pd.DataFrame:
    if mask is not None:
        M, A = M[mask], A[mask]
    n = int(A.sum())
    cnt = M.sum()
    t = pd.DataFrame({"Code": cnt.index, "Label": [labels[c] for c in cnt.index], "Count": cnt.values.astype(int)})
    t["% of answering"] = t["Count"] / n * 100 if n else np.nan
    if not multi:
        t["Cumulative %"] = t["% of answering"].cumsum()
    t.attrs["n"] = n
    return t


def text_table(df, it: Item, mask=None, top=15) -> pd.DataFrame:
    s = df[it.name] if mask is None else df.loc[mask, it.name]
    s = s.dropna().astype(str).str.strip().str.lower()
    s = s[s != ""]
    vc = s.value_counts().head(top)
    t = pd.DataFrame({"Answer": vc.index, "Count": vc.values})
    t["% of answering"] = t["Count"] / max(len(s), 1) * 100
    t.attrs["n"] = len(s)
    return t


# ------------------------------------------------------------------ overview
def overview(df, form, items: List[Item], mask: pd.Series, stat_keys: List[str], value_labels=None) -> pd.DataFrame:
    d = df[mask]
    rows = []
    for it in items:
        base = {"Part": it.part, "Section": it.section, "Variable": it.name, "Question": it.label, "Type": KIND_NAMES[it.kind]}
        if it.kind in ("rating", "numeric"):
            x = numeric_series(d, form, it)
            miss = int(d[it.name].notna().sum() - x.notna().sum())
            base.update(describe(x.dropna(), stat_keys, it.kind == "rating", miss))
            if it.kind == "rating":
                base["Top answer"] = ""
        elif it.kind in ("single", "multi"):
            M, A, lab = cat_matrix(d, form, it, value_labels)
            f = freq_table(M, A, lab, multi=it.kind == "multi")
            base["n"] = f.attrs["n"]
            if len(f):
                top = f.sort_values("Count", ascending=False).iloc[0]
                base["Top answer"] = f"{top['Label']} ({top['% of answering']:.1f}%)"
        else:
            tt = text_table(d, it, top=1)
            base["n"] = tt.attrs["n"]
            if len(tt): base["Top answer"] = f"{tt.iloc[0]['Answer']} ({tt.iloc[0]['% of answering']:.1f}%)"
        rows.append(base)
    out = pd.DataFrame(rows)
    cols = ["Part", "Section", "Variable", "Question", "Type"] + [k for k in stat_keys if k in out.columns] + ["Top answer"]
    return out.reindex(columns=[c for c in cols if c in out.columns])


# ------------------------------------------------------------------ segment break-downs + tests
def _masks(df, form, var, cats: Dict[str, str], base_mask) -> Dict[str, pd.Series]:
    return {lab: core.segment_mask(df, form, var, [code]) & base_mask for code, lab in cats.items()}


def exclusive(df, form, var) -> bool:
    return not core.is_multi(form, var)


def breakdown_numeric(df, form, it: Item, var, cats, base_mask, stat_keys, alpha=0.05) -> pd.DataFrame:
    """Rows = Total + categories; stats + difference vs rest, Welch p, Cohen d, significance arrow."""
    x = numeric_series(df, form, it)
    rating = it.kind == "rating"
    rows = []
    tot = describe(x[base_mask].dropna(), stat_keys, rating)
    rows.append({"Segment": "Total", **tot, "Diff vs rest": np.nan, "p (vs rest)": np.nan, "Cohen d": np.nan, "Sig.": ""})
    masks = _masks(df, form, var, cats, base_mask)
    groups = {}
    for lab, m in masks.items():
        a, b = x[m].dropna(), x[base_mask & ~m].dropna()
        groups[lab] = a.to_numpy()
        r = {"Segment": lab, **describe(a, stat_keys, rating)}
        diff = p = d = np.nan
        if len(a) > 1 and len(b) > 1 and (a.std() > 0 or b.std() > 0):
            diff = a.mean() - b.mean()
            p = float(sps.ttest_ind(a, b, equal_var=False).pvalue)
            sp = np.sqrt(((len(a) - 1) * a.var() + (len(b) - 1) * b.var()) / (len(a) + len(b) - 2))
            d = diff / sp if sp > 0 else np.nan
        r.update({"Diff vs rest": diff, "p (vs rest)": p, "Cohen d": d,
                  "Sig.": ("▲" if diff > 0 else "▼") if (not np.isnan(p) and p < alpha) else ""})
        rows.append(r)
    out = pd.DataFrame(rows)
    out.attrs["overall"] = overall_numeric_test(groups) if exclusive(df, form, var) else {}
    return out


def overall_numeric_test(groups: Dict[str, np.ndarray]) -> dict:
    g = [v for v in groups.values() if len(v) > 1]
    if len(g) < 2 or all(np.std(v) == 0 for v in g):
        return {}
    try:
        f = sps.f_oneway(*g); k = sps.kruskal(*g)
        return {"ANOVA F": float(f.statistic), "ANOVA p": float(f.pvalue), "Kruskal-Wallis p": float(k.pvalue)}
    except Exception:
        return {}


def _ztest(x1, n1, x2, n2):
    if min(n1, n2) < 5: return np.nan
    p = (x1 + x2) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0: return np.nan
    return float(2 * (1 - sps.norm.cdf(abs((x1 / n1 - x2 / n2) / se))))


def breakdown_categorical(df, form, it: Item, var, cats, base_mask, value_labels=None, alpha=0.05):
    """Returns (pct table options x [Total, cats...], sig table of arrows, counts table, meta{n, chi2 p, V})."""
    M, A, lab = cat_matrix(df, form, it, value_labels)
    masks = {"Total": base_mask, **_masks(df, form, var, cats, base_mask)}
    cnt, pct, sig, ns = {}, {}, {}, {}
    for name, m in masks.items():
        n = int((A & m).sum())
        c = M[m & A].sum()
        cnt[name], ns[name] = c, n
        pct[name] = c / n * 100 if n else c * np.nan
    cnt, pct = pd.DataFrame(cnt), pd.DataFrame(pct)
    for name, m in masks.items():
        if name == "Total":
            sig[name] = pd.Series("", index=cnt.index); continue
        rest = base_mask & ~m
        n1, n2 = ns[name], int((A & rest).sum())
        arrows = []
        for code in cnt.index:
            x1 = int(cnt.at[code, name]); x2 = int(M[rest & A][code].sum())
            p = _ztest(x1, n1, x2, n2)
            arrows.append("" if np.isnan(p) or p >= alpha else ("▲" if x1 / n1 > x2 / n2 else "▼"))
        sig[name] = pd.Series(arrows, index=cnt.index)
    sig = pd.DataFrame(sig)
    for t in (cnt, pct, sig):
        t.index = [lab[c] for c in t.index]
    meta = {"n": ns}
    if it.kind == "single" and exclusive(df, form, var):
        tbl = cnt.drop(columns="Total")
        tbl = tbl.loc[tbl.sum(axis=1) > 0, tbl.sum(axis=0) > 0]
        if tbl.shape[0] > 1 and tbl.shape[1] > 1:
            chi2, p, dof, _ = sps.chi2_contingency(tbl.to_numpy())
            meta.update({"chi2": float(chi2), "p": float(p), "Cramér's V": float(np.sqrt(chi2 / (tbl.to_numpy().sum() * (min(tbl.shape) - 1))))})
    return pct, sig, cnt, meta


# ------------------------------------------------------------------ key findings
def bh_adjust(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values."""
    p = np.asarray(p, float); n = len(p)
    order = np.argsort(p); ranked = p[order] * n / (np.arange(n) + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n); out[order] = np.minimum(adj, 1)
    return out


def segment_gap_table(df, form, items, var, cats, base_mask) -> pd.DataFrame:
    """Every rating/numeric question x every category vs the rest (Welch t) with BH adjustment."""
    rows = []
    masks = _masks(df, form, var, cats, base_mask)
    for it in items:
        if it.kind != "rating": continue
        x = numeric_series(df, form, it)
        for lab, m in masks.items():
            a, b = x[m].dropna(), x[base_mask & ~m].dropna()
            if len(a) < 30 or len(b) < 30 or (a.std() == 0 and b.std() == 0): continue
            p = float(sps.ttest_ind(a, b, equal_var=False).pvalue)
            rows.append({"Question": it.label, "Variable": it.name, "Part": it.part, "Segment": lab, "N": len(a),
                         "Segment mean": a.mean(), "Rest mean": b.mean(), "Diff": a.mean() - b.mean(), "p": p})
    t = pd.DataFrame(rows)
    if len(t): t["p (BH adj.)"] = bh_adjust(t["p"].to_numpy())
    return t


def key_findings(df, form, items, base_mask, var=None, cats=None, value_labels=None,
                 alpha=0.05, min_diff=0.3, min_base=30, gaps=None) -> List[tuple]:
    """[(heading, text)] auto-generated, script-driven findings."""
    out = []
    d = df[base_mask]
    rat = [i for i in items if i.kind == "rating"]
    if rat:
        V = core.valid_matrix(d, form, [i.name for i in rat])
        n, m = V.notna().sum(), V.mean()
        ok = n[n >= min_base].index
        q = {i.name: i for i in rat}
        if len(ok) >= 6:
            top = m[ok].sort_values(ascending=False)
            bot = m[ok].sort_values()
            out.append(("Strongest rated items", "; ".join(f"{q[k].label[:80]} ({v:.2f})" for k, v in top.head(5).items())))
            out.append(("Weakest rated items", "; ".join(f"{q[k].label[:80]} ({v:.2f})" for k, v in bot.head(5).items())))
            low = {k: float(np.nansum(V[k].to_numpy() <= core.LOW_MAX) / n[k] * 100) for k in ok}
            worst = sorted(low.items(), key=lambda kv: -kv[1])[:5]
            out.append(("Highest share of low ratings (1-5)", "; ".join(f"{q[k].label[:70]} ({v:.0f}% low)" for k, v in worst)))
        pm = {}
        for p in parts_of(rat):
            ks = [i.name for i in rat if i.part == p and i.name in V.columns]
            tot = V[ks].notna().sum().sum()
            if tot >= min_base: pm[p] = np.nansum(V[ks].to_numpy()) / tot
        if len(pm) >= 2:
            s = sorted(pm.items(), key=lambda kv: -kv[1])
            out.append(("Parts of the questionnaire (pooled mean)", f"Highest: {s[0][0][:60]} ({s[0][1]:.2f}); lowest: {s[-1][0][:60]} ({s[-1][1]:.2f})."))
    # profile / categorical modes
    snap = []
    for it in items:
        if it.kind == "single" and re.search(r"profile|subscription|general", it.part, re.I):
            M, A, lab = cat_matrix(d, form, it, value_labels)
            f = freq_table(M, A, lab)
            if f.attrs["n"] >= min_base and len(f) > 1:
                t = f.sort_values("Count", ascending=False).iloc[0]
                snap.append(f"{it.label[:60]}: {t['Label']} ({t['% of answering']:.0f}%)")
    if snap:
        out.append(("Respondent profile snapshot (most common answers)", " | ".join(snap[:10])))
    # segment gaps
    if var and cats:
        g = gaps if gaps is not None else segment_gap_table(df, form, items, var, cats, base_mask)
        if len(g):
            sig = g[(g["p (BH adj.)"] < alpha) & (g["Diff"].abs() >= min_diff)].copy()
            sig["abs"] = sig["Diff"].abs()
            sig = sig.sort_values("abs", ascending=False)
            if len(sig):
                lines = [f"{r.Question[:70]} - {r.Segment}: {r._6:.2f} vs {r._7:.2f} rest ({r.Diff:+.2f}, adj. p={r._10:.3f})"
                         for r in sig.head(10).rename(columns={"Segment mean": "_6", "Rest mean": "_7", "p (BH adj.)": "_10"}).itertuples()]
                out.append((f"Largest significant segment gaps by the selected segment (>= {min_diff} points, BH-adjusted p < {alpha})", "\n".join(lines)))
            else:
                out.append(("Segment gaps", f"No significant gap of at least {min_diff} points at BH-adjusted p < {alpha}."))
            ov = g.groupby("Segment").apply(lambda t: np.average(t["Segment mean"], weights=t["N"]), include_groups=False).sort_values()
            if len(ov) >= 2:
                out.append(("Segment ranking (N-weighted mean over all rating questions)",
                            f"Lowest: {ov.index[0]} ({ov.iloc[0]:.2f}); highest: {ov.index[-1]} ({ov.iloc[-1]:.2f})."))
    return out


def correlations(df, form, cols: Dict[str, pd.Series], method="pearson", min_n=30) -> pd.DataFrame:
    X = pd.DataFrame(cols)
    return X.corr(method=method, min_periods=min_n)


def segment_candidates(df: pd.DataFrame, form: core.Form, max_unique: int = 80) -> List[str]:
    out = []
    for c in df.columns:
        q = form.questions.get(c)
        if q and q.list_name == form.rating_list: continue
        if q and q.qtype in ("note", "geopoint", "audio", "date", "start", "end", "deviceid"): continue
        if SKIP_NAME.search(str(c)): continue
        nu = df[c].nunique()
        if 1 < nu <= max_unique and (q is not None or str(c).startswith("custom_")):
            out.append(c)
    return out


# ------------------------------------------------------------------ skip logic + nested segments
def asked_mask(df, form, var, extra_vars=()):
    """Respondents who were asked `var` (and extra_vars) according to the script's skip logic.
    Returns (mask, readable_rules, all_interpreted)."""
    import skip
    m = pd.Series(True, index=df.index); words = []; ok_all = True
    for v in [var, *extra_vars]:
        if v not in form.questions:
            continue
        mm, ok, ex = skip.eligible_mask(df, form, v)
        m &= mm; ok_all &= ok
        for e in ex:
            w = skip.in_words(e, form)
            if w not in words and "consent" not in w.lower():
                words.append(w)
    return m, words, ok_all


def combo_column(df, form, a: str, b: str, value_labels=None):
    """Nested segment 'A > B' (e.g. Region > City). Returns (df_with_col, colname, {code: label})."""
    la = segment_options(df, form, a, {a: value_labels[a]} if value_labels and a in value_labels else None)
    lb = segment_options(df, form, b, {b: value_labels[b]} if value_labels and b in value_labels else None)
    ca, cb = core.segment_codes(df, a), core.segment_codes(df, b)
    ok = (ca != "") & (cb != "")
    codes = (ca + "|" + cb).where(ok, "")
    name = f"combo__{a}__{b}"
    df = df.copy(); df[name] = codes.replace("", np.nan)
    labels = {}
    for c in codes[ok].unique():
        x, y = c.split("|", 1)
        labels[c] = f"{la.get(x, x)} › {lb.get(y, y)}"
    return df, name, dict(sorted(labels.items(), key=lambda kv: kv[1]))


def segment_options(df, form, col, value_labels=None):
    return core.segment_options(df, form, col, value_labels)


def clean_text_segment(df, form, var):
    """Free-text segment (city, sub-city ...): merge spelling variants that differ only in case / spaces
    ('Yirga Chefe' vs 'Yirga chefe'). Returns (df, column, {code: label}); non-text vars unchanged -> (df, var, None)."""
    q = form.questions.get(var)
    if not q or q.qtype != "text":
        return df, var, None
    vals = [re.sub(r"\s+", " ", str(v)).strip() if pd.notna(v) and str(v).strip() else None for v in df[var]]
    raw = pd.Series(vals, index=df.index, dtype=object)
    key = pd.Series([v.lower() if v else None for v in vals], index=df.index, dtype=object)
    lab = raw.groupby(key).agg(lambda x: x.value_counts().index[0]).to_dict()
    name = f"clean__{var}"
    df = df.copy(); df[name] = key
    return df, name, lab
