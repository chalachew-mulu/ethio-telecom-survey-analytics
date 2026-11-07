"""
skip.py - evaluate XLSForm skip logic (the `relevance` column) against the dataset.

Used so that segments follow the questionnaire: e.g. name_of_city is only asked when
selected(${location_of_resident}, '2'), so a city break-down is automatically limited to
respondents who were actually asked (and 'rest of sample' means the other cities, not everybody).

Supported: selected(${v},'x'), ${v} = / != / > / >= / < / <= literal, string-length(${v}) > n,
count-selected(${v}) > n, and / or / not(...) and parentheses, plus inherited group relevance.
Anything unsupported returns None (= no restriction) and is reported, never silently wrong.
"""
from __future__ import annotations
import re
from typing import Optional, Tuple
import numpy as np
import pandas as pd
import core

TOKEN = re.compile(r"\s*(\$\{[^}]+\}|'[^']*'|\"[^\"]*\"|-?\d+(?:\.\d+)?|>=|<=|!=|=|>|<|\(|\)|,|[A-Za-z_][\w\-]*)")


class Unsupported(Exception):
    pass


def _tokens(expr: str):
    pos, out = 0, []
    expr = expr.strip()
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        if not m:
            raise Unsupported(expr[pos:pos + 20])
        out.append(m.group(1)); pos = m.end()
    return out


class _P:
    def __init__(self, toks, df, form):
        self.t, self.i, self.df, self.form = toks, 0, df, form

    def peek(self): return self.t[self.i] if self.i < len(self.t) else None
    def take(self, x=None):
        v = self.peek()
        if v is None or (x is not None and v.lower() != x): raise Unsupported(f"expected {x}")
        self.i += 1; return v

    def col(self, ref):
        name = ref[2:-1]
        if name not in self.df.columns: raise Unsupported(f"{name} not in data")
        return name

    def parse(self):
        r = self.p_or()
        if self.peek() is not None: raise Unsupported("trailing")
        return r

    def p_or(self):
        a = self.p_and()
        while (self.peek() or "").lower() == "or":
            self.take(); a = a | self.p_and()
        return a

    def p_and(self):
        a = self.p_atom()
        while (self.peek() or "").lower() == "and":
            self.take(); a = a & self.p_atom()
        return a

    def lit(self):
        v = self.take()
        return v[1:-1] if v[0] in "'\"" else float(v)

    def cmp(self, left_series, numeric_ok=True):
        op = self.take()
        if op not in ("=", "!=", ">", ">=", "<", "<="): raise Unsupported(op)
        lit = self.lit()
        if isinstance(lit, str):
            s = left_series.map(core._norm)
            r = (s == lit) if op == "=" else (s != lit) if op == "!=" else None
            if r is None: raise Unsupported("string compare")
            return r
        x = pd.to_numeric(left_series, errors="coerce")
        r = {"=": x == lit, "!=": x != lit, ">": x > lit, ">=": x >= lit, "<": x < lit, "<=": x <= lit}[op]
        return r.fillna(False) if op != "!=" else (r | x.isna())

    def p_atom(self):
        t = self.peek()
        if t is None: raise Unsupported("end")
        tl = t.lower()
        if t == "(":
            self.take(); r = self.p_or(); self.take(")"); return r
        if tl == "not":
            self.take(); self.take("("); r = self.p_or(); self.take(")"); return ~r
        if tl == "selected":
            self.take(); self.take("("); c = self.col(self.take()); self.take(","); v = self.lit(); self.take(")")
            s = self.df[c]
            if self.form.questions.get(c) and self.form.questions[c].qtype == "select_multiple":
                return s.map(lambda x: str(v) in str(x).split() if pd.notna(x) else False)
            return s.map(core._norm) == str(v)
        if tl in ("string-length", "count-selected"):
            self.take(); self.take("("); c = self.col(self.take()); self.take(")")
            s = self.df[c]
            ln = s.map(lambda x: len(str(x).strip()) if pd.notna(x) else 0) if tl == "string-length" else \
                s.map(lambda x: len(str(x).split()) if pd.notna(x) else 0)
            return self.cmp(ln)
        if t.startswith("${"):
            c = self.col(self.take()); return self.cmp(self.df[c])
        raise Unsupported(t)


def _eval(expr: str, df, form) -> pd.Series:
    return _P(_tokens(expr), df, form).parse().fillna(False).astype(bool)


def chain(form, qname: str):
    """List of relevance expressions that apply to a question (own + enclosing groups)."""
    q = form.questions.get(qname)
    if not q: return []
    ex = [form.group_relevance.get(g, "") for g in q.group_path] + [q.relevance]
    return [e for e in ex if e]


def eligible_mask(df: pd.DataFrame, form, qname: str) -> Tuple[pd.Series, bool, list]:
    """(mask, interpreted_ok, expressions). mask = respondents for whom the question was relevant."""
    m = pd.Series(True, index=df.index)
    exprs = chain(form, qname)
    ok = True
    for e in exprs:
        try:
            m &= _eval(e, df, form)
        except Unsupported:
            ok = False
    return m, ok, exprs


def in_words(expr: str, form) -> str:
    """Readable version: selected(${location_of_resident}, '2') -> Location ... = Other Regions."""
    def lab_var(v):
        q = form.questions.get(v); return (q.label.split("  ")[0][:60] if q and q.label else v)
    def lab_val(v, c):
        q = form.questions.get(v)
        return form.choices.get(q.list_name, {}).get(c, c) if q and q.list_name else c
    s = re.sub(r"selected\(\s*\$\{([^}]+)\}\s*,\s*'([^']*)'\s*\)", lambda m: f"{lab_var(m.group(1))} = {lab_val(m.group(1), m.group(2))}", expr)
    s = re.sub(r"\$\{([^}]+)\}\s*(=|!=)\s*'([^']*)'", lambda m: f"{lab_var(m.group(1))} {m.group(2)} {lab_val(m.group(1), m.group(3))}", s)
    return re.sub(r"\$\{([^}]+)\}", lambda m: lab_var(m.group(1)), s)
