"""
core.py - calculation engine for the Ethio telecom satisfaction-survey topline.

Nothing in here is specific to one round. Everything comes from
  1. the SurveyCTO/XLSForm script   (questions, groups, labels, choice lists)
  2. the wide dataset               (one row per respondent)
  3. structure.json                 (how groups map to report pillars; editable)

METHOD (reverse-engineered from the Round-14 Topline and verified against it)
  * A response is VALID only if it is a number on the rating scale (1..10).
    Blanks, nulls, 99 "Don't know" and any other non-scale code are ignored.
  * BASE of a question  = number of valid responses.
  * MEAN of a question  = average of its valid responses.
  * MEAN of a group / subgroup / pillar = POOLED mean of every valid response of
    every question underneath it (== sum(question mean x base) / sum(base)).
    It is NOT the simple average of question means.
  * Overall Satisfaction Score (OSS) = pooled mean over all questions in all
    pillars (== base-weighted mean of the pillar means, as in the Topline).
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# 1. Reading files (robust to the malformed cells SurveyCTO exports sometimes
#    contain, e.g. a number cell holding the text "nan")
# --------------------------------------------------------------------------- #

def read_table(file, sheet=0) -> pd.DataFrame:
    """Read an xlsx/xls/csv into a DataFrame; falls back to python-calamine when
    openpyxl/pandas choke on invalid cells."""
    name = getattr(file, "name", str(file)).lower()
    if hasattr(file, "seek"):
        file.seek(0)
    if name.endswith(".csv"):
        return pd.read_csv(file, low_memory=False)
    try:
        return pd.read_excel(file, sheet_name=sheet)
    except Exception:
        if hasattr(file, "seek"):
            file.seek(0)
        from python_calamine import CalamineWorkbook  # pip install python-calamine
        if hasattr(file, "read"):
            wb = CalamineWorkbook.from_filelike(file)
        else:
            wb = CalamineWorkbook.from_path(str(file))
        ws = wb.get_sheet_by_index(sheet) if isinstance(sheet, int) else wb.get_sheet_by_name(sheet)
        rows = ws.to_python()
        return pd.DataFrame(rows[1:], columns=rows[0]).replace("", np.nan)


def clean_label(text) -> str:
    """Strip HTML + grey hint text (<span ...>hint</span>) from an XLSForm label."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    t = str(text)
    t = re.sub(r"<span[^>]*>.*?</span>", "", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------- #
# 2. Parsing the XLSForm
# --------------------------------------------------------------------------- #

@dataclass
class Question:
    name: str
    qtype: str
    list_name: Optional[str]
    label: str
    group_path: List[str]          # names of enclosing groups, outermost first
    relevance: str = ""            # XLSForm skip logic of the question itself


@dataclass
class Form:
    questions: Dict[str, Question]           # in form order
    group_labels: Dict[str, str]             # group name -> label
    choices: Dict[str, Dict[str, str]]       # list_name -> {value(str): label}
    rating_list: str
    scale: List[int]                         # e.g. [1..10]
    group_order: List[str] = field(default_factory=list)
    group_relevance: Dict[str, str] = field(default_factory=dict)
    title: str = ""

    def rating_questions(self) -> List[str]:
        return [q.name for q in self.questions.values() if q.list_name == self.rating_list]

    def questions_in_group(self, group: str) -> List[str]:
        return [q for q in self.rating_questions() if group in self.questions[q].group_path]


def _pick_label_col(cols) -> Optional[str]:
    cols = [str(c) for c in cols]
    for c in cols:
        if c.lower() in ("label", "label::english", "label:english"):
            return c
    for c in cols:
        if c.lower().startswith("label"):
            return c
    return None


def _norm(v) -> str:
    """Normalise a code to a comparable string: 1.0 -> '1'."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return str(int(v)) if float(v).is_integer() else str(v)
    return str(v).strip()


def _rel(r) -> str:
    v = r.get("relevance")
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip()


def parse_xlsform(file) -> Form:
    survey = read_table(file, "survey")
    choices = read_table(file, "choices")
    survey.columns = [str(c).strip() for c in survey.columns]
    choices.columns = [str(c).strip() for c in choices.columns]
    lab_s, lab_c = _pick_label_col(survey.columns), _pick_label_col(choices.columns)
    list_col = "list_name" if "list_name" in choices.columns else "list name"

    ch: Dict[str, Dict[str, str]] = {}
    for _, r in choices.iterrows():
        if pd.isna(r.get(list_col)):
            continue
        ch.setdefault(str(r[list_col]).strip(), {})[_norm(r["value"])] = clean_label(r.get(lab_c))

    questions: Dict[str, Question] = {}
    group_labels: Dict[str, str] = {}
    group_order: List[str] = []
    group_rel: Dict[str, str] = {}
    stack: List[str] = []
    for _, r in survey.iterrows():
        t = str(r.get("type", "")).strip() if not pd.isna(r.get("type")) else ""
        name = str(r.get("name", "")).strip() if not pd.isna(r.get("name")) else ""
        label = clean_label(r.get(lab_s)) if lab_s else ""
        tl = t.lower().replace("_", " ")
        if tl in ("begin group", "begin repeat"):
            stack.append(name)
            group_labels[name] = label
            group_order.append(name)
            group_rel[name] = _rel(r)
        elif tl in ("end group", "end repeat"):
            if stack:
                stack.pop()
        elif t and name:
            parts = t.split()
            lst = parts[1] if len(parts) > 1 and parts[0] in ("select_one", "select_multiple") else None
            questions[name] = Question(name, parts[0], lst, label, list(stack), _rel(r))

    # rating list = the select_one list with a numeric scale that most questions use
    best, best_n = None, 0
    for lst, vals in ch.items():
        numeric = [v for v, l in vals.items() if re.fullmatch(r"\d+", l or v)]
        n_used = sum(1 for q in questions.values() if q.list_name == lst)
        if len(numeric) >= 5 and n_used > best_n:
            best, best_n = lst, n_used
    if best is None:
        raise ValueError("Could not detect the rating-scale choice list in the script.")
    # scale = choices whose LABEL is a number (99 "Don't Know" is excluded automatically)
    scale = sorted(int(l) for l in ch[best].values() if re.fullmatch(r"\d+", l))
    title = ""
    try:
        st_ = read_table(file, "settings")
        for col in st_.columns:
            if str(col).strip().lower() == "form_title" and len(st_):
                title = str(st_[col].iloc[0]).strip()
    except Exception:
        pass
    return Form(questions, group_labels, ch, best, scale, group_order, group_rel, title)


# --------------------------------------------------------------------------- #
# 3. Structure (hierarchy of pillars / sub-groups / questions)
# --------------------------------------------------------------------------- #

@dataclass
class Node:
    title: str
    questions: List[str] = field(default_factory=list)   # scored leaf questions (direct)
    children: List["Node"] = field(default_factory=list)
    show_header: bool = True
    level: int = 0
    info_questions: List[str] = field(default_factory=list)  # shown in the report but NOT scored
    info_only: bool = False                                   # whole block shown but NOT scored

    def leaves(self, include_info: bool = False) -> List[str]:
        """Scored questions beneath this node (include_info=True also returns shown-only ones)."""
        if self.info_only and not include_info:
            return []
        out = list(self.questions)
        if include_info:
            out += self.info_questions
        for ch in self.children:
            out += ch.leaves(include_info)
        return list(dict.fromkeys(out))


def _build_node(spec: dict, form: Form, level: int) -> Node:
    node = Node(spec.get("title", ""), show_header=spec.get("show_header", True), level=level,
                info_only=bool(spec.get("info_only", False)))
    qs: List[str] = []
    if "group" in spec:
        qs += form.questions_in_group(spec["group"])
    qs += spec.get("questions", [])
    if "match" in spec:
        qs = [q for q in qs if re.search(spec["match"], q)]
    qs = [q for q in qs if q in form.questions and q not in spec.get("exclude", [])]
    node.info_questions = [q for q in spec.get("info_questions", []) if q in form.questions]
    if spec.get("children"):
        node.children = [_build_node(ch, form, level + 1) for ch in spec["children"]]
        node.questions = qs if ("questions" in spec or "group" in spec) else []
    else:
        node.questions = qs
    return node


def build_tree(structure: dict, form: Form) -> List[Node]:
    return [_build_node(p, form, 0) for p in structure["pillars"]]


def auto_structure(form: Form) -> dict:
    """Draft a structure straight from the script's groups (used when no
    structure.json is supplied). Top-level groups that hold rating questions
    become pillars; their child groups become sub-groups."""
    rq = form.rating_questions()
    pillars = []
    seen = set()
    for g in form.group_order:
        qs = form.questions_in_group(g)
        if not qs:
            continue
        qpaths = [form.questions[q].group_path for q in qs]
        depth = min(p.index(g) for p in qpaths)
        # take the group that sits directly above the questions, skip already-used
        if all(q in seen for q in qs):
            continue
        title = form.group_labels.get(g) or g.replace("_", " ").title()
        pillars.append({"title": title, "group": g})
        seen.update(qs)
    return {"pillars": pillars}


def load_structure(path_or_file=None, form: Optional[Form] = None) -> dict:
    if path_or_file is not None:
        if hasattr(path_or_file, "read"):
            path_or_file.seek(0)
            return json.load(path_or_file)
        return json.loads(Path(path_or_file).read_text(encoding="utf-8"))
    return auto_structure(form)


# --------------------------------------------------------------------------- #
# 4. Data preparation + calculation
# --------------------------------------------------------------------------- #

LOW_MAX = 5     # ratings 1-5  = "low"      (used for the % low / % high columns)
HIGH_MIN = 8    # ratings 8-10 = "high"


def valid_matrix(df: pd.DataFrame, form: Form, questions: List[str]) -> pd.DataFrame:
    """Respondent x question matrix of VALID ratings (NaN elsewhere)."""
    cols = [q for q in questions if q in df.columns]
    v = df[cols].apply(pd.to_numeric, errors="coerce")
    lo, hi = min(form.scale), max(form.scale)
    v = v.where((v >= lo) & (v <= hi) & (v == v.round()))
    return v


def is_multi(form: Optional[Form], col: str) -> bool:
    q = form.questions.get(col) if form else None
    return bool(q and q.qtype == "select_multiple")


def segment_codes(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].map(_norm)


def segment_mask(df: pd.DataFrame, form: Optional[Form], col: str, codes) -> pd.Series:
    """Respondents belonging to ANY of `codes` for variable `col`
    (select_multiple: respondents who ticked any of the codes)."""
    codes = [str(c) for c in codes]
    if is_multi(form, col):
        tok = df[col].astype(str).str.split()
        return tok.map(lambda t: any(c in t for c in codes))
    return segment_codes(df, col).isin(codes)


def segment_options(df, form, col, value_labels=None) -> Dict[str, str]:
    """{code: label} for one segment variable (only codes present in the data)."""
    if is_multi(form, col):
        present = {t for v in df[col].dropna().astype(str) for t in v.split()}
    else:
        present = {c for c in segment_codes(df, col).unique() if c != ""}
    lab = {}
    q = form.questions.get(col) if form else None
    if q and q.list_name and q.list_name in form.choices:
        lab.update(form.choices[q.list_name])
    if value_labels and col in value_labels:
        lab.update({str(k): v for k, v in value_labels[col].items()})
    def key(c):
        return (0, int(c)) if re.fullmatch(r"\d+", c) else (1, c)
    return {c: lab.get(c, c) for c in sorted(present, key=key)}


def apply_filters(df: pd.DataFrame, filters: Dict[str, List[str]], form: Optional[Form] = None) -> pd.Series:
    """Boolean mask. filters = {column: [selected codes]}; AND across variables,
    OR within a variable. An empty selection means 'no filter'."""
    mask = pd.Series(True, index=df.index)
    for col, codes in filters.items():
        if codes and col in df.columns:
            mask &= segment_mask(df, form, col, codes)
    return mask


def add_numeric_groups(df: pd.DataFrame, col: str, edges: List[float], new_col: str):
    """Bin a numeric column. edges=[15,20,30,45] -> '15-19','20-29','30-44','45+'.
    Returns (df_with_new_col, {code: label})."""
    edges = sorted(set(float(e) for e in edges))
    x = pd.to_numeric(df[col], errors="coerce")
    labels, codes = {}, pd.Series(np.nan, index=df.index, dtype=object)
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else None
        f = (lambda v: str(int(v)) if float(v).is_integer() else str(v))
        lab = f"{f(lo)}+" if hi is None else f"{f(lo)}-{f(hi - 1) if float(hi).is_integer() else f(hi)}"
        labels[str(i + 1)] = lab
        m = (x >= lo) & ((x < hi) if hi is not None else True)
        codes[m] = str(i + 1)
    df = df.copy()
    df[new_col] = codes
    return df, labels


def _stats(V: pd.DataFrame, qs: List[str], round_q: bool = False) -> dict:
    """Pooled stats over a set of questions."""
    qs = [q for q in qs if q in V.columns]
    if not qs:
        return dict(mean=np.nan, n=0, wsum=np.nan, avg_q=np.nan, low=np.nan, high=np.nan)
    sub = V[qs]
    n_q, s_q = sub.notna().sum(), sub.sum()
    means = s_q / n_q.replace(0, np.nan)
    n = int(n_q.sum())
    wsum = float(((means.round(2) * n_q).sum()) if round_q else s_q.sum())
    arr = sub.to_numpy()
    return dict(mean=wsum / n if n else np.nan, n=n, wsum=wsum if n else np.nan,
                avg_q=float(means.mean()) if n else np.nan,
                low=float(np.nansum(arr <= LOW_MAX) / n * 100) if n else np.nan,
                high=float(np.nansum(arr >= HIGH_MIN) / n * 100) if n else np.nan)


@dataclass
class Row:
    kind: str          # 'oss' | 'pillar' | 'sub' | 'question'
    level: int
    qname: str
    label: str
    mean: float
    base: int
    wsum: float
    avg_q: float
    low: float
    high: float
    leaves: list = field(default_factory=list)


def compute_topline(V: pd.DataFrame, tree: List[Node], form: Form,
                    mask: Optional[pd.Series] = None, round_q: bool = False) -> pd.DataFrame:
    """Topline table. Columns: Indicator, Variable, MEAN, BASE (N responded),
    WEIGHTED (= sum of ratings = mean x base), AVG_Q (simple average of the
    question means beneath a group), PCT_LOW, PCT_HIGH (+ kind/level/leaves)."""
    if mask is not None:
        V = V[mask.reindex(V.index, fill_value=False)]
    rows: List[Row] = []

    def mk(kind, level, q, label, qs):
        st_ = _stats(V, qs, round_q)
        rows.append(Row(kind, level, q, label, st_["mean"], st_["n"], st_["wsum"],
                        st_["avg_q"] if kind != "question" else np.nan, st_["low"], st_["high"], list(qs)))

    all_q = list(dict.fromkeys(q for p in tree for q in p.leaves()))
    mk("oss", 0, "", "Overall Satisfaction Score (OSS)", all_q)

    def walk(node: Node, is_pillar: bool):
        leaves = node.leaves(include_info=node.info_only)
        scored_children = [ch for ch in node.children if not ch.info_only]
        single = len(leaves) == 1 and not scored_children
        if node.show_header:
            mk("pillar" if is_pillar else "sub", node.level, leaves[0] if single else "", node.title, leaves)
            if single:
                rows[-1].avg_q = np.nan
        qlevel = node.level + 1 if node.show_header else node.level
        for q in node.questions:
            if single and node.show_header:
                continue  # one-question block: the header row already carries mean + base
            mk("question", qlevel, q, form.questions[q].label, [q])
        for ch in node.children:
            walk(ch, False)
        for q in node.info_questions:          # shown for information, not part of any mean / the OSS
            mk("question", qlevel, q, form.questions[q].label, [q])

    for p in tree:
        walk(p, True)
    t = pd.DataFrame([r.__dict__ for r in rows]).rename(columns={
        "label": "Indicator", "qname": "Variable", "mean": "MEAN", "base": "BASE",
        "wsum": "WEIGHTED", "avg_q": "AVG_Q", "low": "PCT_LOW", "high": "PCT_HIGH"})
    return t


def compute_by_segment(df, V, tree, form, var, codes_labels: Dict[str, str], round_q=False) -> pd.DataFrame:
    """Wide table: indicator x [Total, cat1, cat2 ...] means, plus bases."""
    base_tbl = compute_topline(V, tree, form, round_q=round_q)
    out = base_tbl[["kind", "level", "Variable", "Indicator"]].copy()
    out["Total"] = base_tbl["MEAN"]
    out["Total (n)"] = base_tbl["BASE"]
    for code, lab in codes_labels.items():
        m = segment_mask(df, form, var, [code])
        t = compute_topline(V, tree, form, mask=m, round_q=round_q)
        out[lab] = t["MEAN"].values
        out[f"{lab} (n)"] = t["BASE"].values
    return out


# --------------------------------------------------------------------------- #
# 5. Driver analysis (standardized regression coefficients) + round comparison
# --------------------------------------------------------------------------- #

def respondent_pillar_scores(V: pd.DataFrame, tree: List[Node]) -> pd.DataFrame:
    """Per-respondent score of each pillar = mean of that respondent's valid items."""
    out = {}
    for p in tree:
        qs = [q for q in p.leaves() if q in V.columns]
        out[p.title] = V[qs].mean(axis=1, skipna=True)
    return pd.DataFrame(out)


def driver_analysis(V: pd.DataFrame, tree: List[Node], mask=None, min_n: int = 30) -> dict:
    """Key-driver analysis exactly as used in Round 14 (reproduces the deck's
    standardized coefficients and R2 = 0.98):
        y  = respondent's composite CSS = mean of all their valid item ratings
             across every pillar
        X  = respondent's score on each pillar (mean of their valid items)
        OLS on z-scored variables, listwise (only respondents who rated ALL pillars)
    Returns {'table': DataFrame[Indicator, Std. coefficient, Rank], 'r2', 'n'}."""
    if mask is not None:
        V = V[mask.reindex(V.index, fill_value=False)]
    X = respondent_pillar_scores(V, tree)
    all_q = list(dict.fromkeys(q for p in tree for q in p.leaves() if q in V.columns))
    y = V[all_q].mean(axis=1, skipna=True).rename("_y")
    d = pd.concat([X, y], axis=1).dropna()
    if len(d) < max(min_n, X.shape[1] + 2):
        return {"table": pd.DataFrame(columns=["Indicator", "Std. coefficient", "Rank"]), "r2": np.nan, "n": len(d)}
    sd = d.std(ddof=1).replace(0, np.nan)
    Z = ((d - d.mean()) / sd).fillna(0)
    A = Z.drop(columns="_y").to_numpy()
    beta, *_ = np.linalg.lstsq(A, Z["_y"].to_numpy(), rcond=None)
    resid = Z["_y"].to_numpy() - A @ beta
    r2 = 1 - (resid ** 2).sum() / (Z["_y"].to_numpy() ** 2).sum()
    res = pd.DataFrame({"Indicator": X.columns, "Std. coefficient": beta})
    res["Rank"] = res["Std. coefficient"].rank(ascending=False, method="min").astype(int)
    return {"table": res, "r2": float(r2), "n": int(len(d))}


def pillar_comparison(V_now, V_prev, tree, form, mask_now=None, mask_prev=None) -> pd.DataFrame:
    """Pillar means for this round vs previous round, rank and % change."""
    t_now = compute_topline(V_now, tree, form, mask_now)
    t_prev = compute_topline(V_prev, tree, form, mask_prev)
    a = t_now[t_now.kind == "pillar"].set_index("Indicator")["MEAN"]
    b = t_prev[t_prev.kind == "pillar"].set_index("Indicator")["MEAN"]
    out = pd.DataFrame({"Mean": a, "Rank": a.rank(ascending=False, method="min").astype(int),
                        "Previous mean": b})
    out["% growth in mean"] = (out["Mean"] / out["Previous mean"] - 1) * 100
    return out.reset_index()


# --------------------------------------------------------------------------- #
# 6. Sanity checks (shown in the app so a new round never fails silently)
# --------------------------------------------------------------------------- #

def check_structure(form: Form, tree: List[Node], df: pd.DataFrame) -> List[str]:
    msgs = []
    used = set(q for p in tree for q in p.leaves(include_info=True))
    for q in sorted(used):
        if q not in df.columns:
            msgs.append(f"Question '{q}' is in the structure/script but NOT in the dataset (column renamed or dropped?).")
        elif pd.to_numeric(df[q], errors="coerce").notna().sum() == 0:
            msgs.append(f"Question '{q}' has no responses at all.")
    unused = [q for q in form.rating_questions() if q not in used]
    if unused:
        msgs.append("Rating questions in the script that are NOT in any pillar (ignored in the report - expected for telebirr / attitude questions, but check new ones): "
                    + ", ".join(unused))
    new_cols = [q for q in used if q in df.columns]
    vals = pd.concat([pd.to_numeric(df[q], errors="coerce") for q in new_cols]) if new_cols else pd.Series(dtype=float)
    odd = sorted(set(vals.dropna().unique()) - set(form.scale))
    if odd:
        msgs.append(f"Non-scale codes found and excluded from means/bases: {', '.join(str(int(o)) if float(o).is_integer() else str(o) for o in odd)}")
    return msgs


# --------------------------------------------------------------------------- #
# 7. Script <-> dataset column mapping and survey-structure detection
# --------------------------------------------------------------------------- #

def _rating_like(s: pd.Series, form: Form) -> bool:
    """True if a dataset column looks like a rating answer (values on the scale, or 99 / blank)."""
    x = pd.to_numeric(s, errors="coerce").dropna()
    if len(x) == 0:
        return False
    ok = ((x >= min(form.scale)) & (x <= max(form.scale))) | (x == 99)
    return bool(ok.mean() >= 0.95 and ((x >= min(form.scale)) & (x <= max(form.scale))).any())


def suggest_column_mapping(form: Form, df: pd.DataFrame) -> List[dict]:
    """Rating questions that are in the script but missing from the dataset, paired with unmatched
    dataset columns sitting in the same position (between the same neighbouring questions).
    Returns [{question, label, column, confidence, candidates}] - 'high' = same count in the same slot."""
    cols = list(df.columns)
    pos = {c: i for i, c in enumerate(cols)}
    qnames = list(form.questions)
    miss = [q for q in qnames if q not in df.columns]
    rating = set(form.rating_questions())
    unmatched = [c for c in cols if c not in form.questions and _rating_like(df[c], form)]
    out, i = [], 0
    while i < len(qnames):
        if qnames[i] in df.columns:
            i += 1
            continue
        j = i
        while j + 1 < len(qnames) and qnames[j + 1] not in df.columns:
            j += 1
        run = [q for q in qnames[i:j + 1] if q in rating]
        if run:
            prev_pos = next((pos[qnames[k]] for k in range(i - 1, -1, -1) if qnames[k] in df.columns), -1)
            next_pos = next((pos[qnames[k]] for k in range(j + 1, len(qnames)) if qnames[k] in df.columns), len(cols))
            cand = [c for c in unmatched if prev_pos < pos[c] < next_pos]
            for k, q in enumerate(run):
                out.append({"question": q, "label": form.questions[q].label, "candidates": cand,
                            "column": cand[k] if len(cand) == len(run) else None,
                            "confidence": "high" if len(cand) == len(run) else "none"})
        i = j + 1
    return out


def structure_files(folder: Path) -> List[Path]:
    return sorted(Path(folder).glob("structures/*.json"))


def detect_structure(form: Form, df: pd.DataFrame, folder: Path) -> List[dict]:
    """Score every bundled structure against the script + data: share of the data's answered rating
    questions that the structure covers (and that exist). Best first. Also uses the survey title."""
    answered = {q for q in form.rating_questions() if q in df.columns and
                pd.to_numeric(df[q], errors="coerce").notna().any()}
    res = []
    for p in structure_files(folder):
        try:
            st_ = json.loads(p.read_text(encoding="utf-8"))
            tree = build_tree(st_, form)
        except Exception:
            continue
        leaves = {q for n in tree for q in n.leaves(include_info=True)}
        have = leaves & answered
        cov = len(have) / max(len(answered), 1)
        hint = 0.0
        nm = st_.get("name", p.stem).lower()
        if nm and nm in form.title.lower():
            hint = 0.25
        res.append({"name": st_.get("name", p.stem), "path": p, "score": cov + hint, "coverage": cov,
                    "questions": len(have)})
    return sorted(res, key=lambda r: -r["score"])
