"""Reproduce the Round-14 ENTERPRISE Topline (sheet 'Enterprise') from the raw script + dataset."""
import sys, re, html, openpyxl
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core
U = "/mnt/user-data/uploads/"
form = core.parse_xlsform(U + "Enterprise_Customers__Satisfaction_survey_final121111__2_.xlsx")
df = core.read_table(U + "Enterprise_Customers__Satisfaction_Survey_14th_Round_WIDE_V1__3_.xlsx")
sug = core.suggest_column_mapping(form, df)
df = df.rename(columns={s["column"]: s["question"] for s in sug if s["column"]})
best = core.detect_structure(form, df, ROOT)[0]
print("detected:", best["name"], round(best["score"], 2))
tree = core.build_tree(core.load_structure(best["path"]), form)
V = core.valid_matrix(df, form, form.rating_questions())
t = core.compute_topline(V, tree, form)
norm = lambda s: re.sub(r"\s+", " ", html.unescape(str(s))).strip().lower()
ws = openpyxl.load_workbook(U + "Topline__2_.xlsx", data_only=True)["Enterprise"]
ref = {}
for r in range(2, 142):
    b, c, d = ws.cell(r, 2).value, ws.cell(r, 3).value, ws.cell(r, 4).value
    if b and d: ref[norm(b)[:60]] = (c, d, r)
n = bm = bb = 0
for _, r in t[t.kind == "question"].iterrows():
    k = norm(r["Indicator"])[:60]
    if k not in ref: print("not in reference:", r["Variable"], k[:50]); continue
    m, b, row = ref[k]; n += 1
    if r["BASE"] != b: bb += 1; print("BASE", r["Variable"], r["BASE"], b)
    if abs(r["MEAN"] - m) > 0.006: bm += 1; print("MEAN", r["Variable"], round(r["MEAN"], 3), m)
print(f"{n} questions compared | base mismatches {bb} | mean mismatches {bm}")
oss = t[t.kind == "oss"].iloc[0]
print(f"OSS {oss.MEAN:.3f} (ref 7.684) N {oss.BASE} (ref 37817)")
for _, r in t[t.kind == "pillar"].iterrows(): print(f"  {r.Indicator[:40]:40s} {r.MEAN:.3f}  N={r.BASE}")
