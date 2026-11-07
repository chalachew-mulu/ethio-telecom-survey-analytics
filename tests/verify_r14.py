"""Reproduce the Round-14 Topline from the raw files and compare to the analyst's Excel."""
import sys, re, openpyxl, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent)); sys.path.insert(0, ".")
import core
U = "/mnt/user-data/uploads/"
form = core.parse_xlsform(U + "Residential_Customers__Satisfaction_survey_final21111112__2_.xlsx")
df = core.read_table(U + "Residential_Customers__Satisfaction_survey_14th_Round_WIDE_V1__2_.xlsx")
tree = core.build_tree(core.load_structure(__import__("pathlib").Path(__file__).resolve().parent.parent / "structures/residential.json"), form)
V = core.valid_matrix(df, form, form.rating_questions())
t = core.compute_topline(V, tree, form)
print(form.rating_list, form.scale, len(df))
ws = openpyxl.load_workbook(U + "Topline__2_.xlsx", data_only=True)["Residential"]
ref = {}
for r in range(2, 160):
    a, b, c = ws.cell(r, 1).value, ws.cell(r, 2).value, ws.cell(r, 3).value
    if a: ref[re.sub(r"\s+", " ", str(a)).strip()] = (b, c)
bad_m = bad_b = n = 0; maxd = 0
for _, r in t.iterrows():
    k = re.sub(r"\s+", " ", r["Indicator"]).strip()
    if k.startswith("Overall Satisfaction"): k = "Overall Satisfaction Score (OSS)"
    k2 = next((x for x in ref if x.lower().startswith(k.lower()[:40])), None)
    if not k2: print("NOT IN TOPLINE:", k); continue
    rb, rc = ref[k2]; n += 1
    d = abs(r["MEAN"] - rb); maxd = max(maxd, d)
    tol = 0.006 if r["kind"] == "question" else 0.0025
    if d > tol: bad_m += 1; print("MEAN DIFF", k[:60], round(r["MEAN"], 4), rb)
    if rc and r["BASE"] != rc: bad_b += 1; print("BASE DIFF", k[:60], r["BASE"], rc)
print(f"{n} rows compared | mean mismatches: {bad_m} | base mismatches: {bad_b} | max abs diff {maxd:.4f}")
print(t[t.kind.isin(['oss','pillar'])][["Indicator","MEAN","BASE"]].round(4).to_string())
