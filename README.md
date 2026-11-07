# Satisfaction Survey Topline Generator

Upload the SurveyCTO script + the dataset -> get the Topline (Indicator / MEAN / BASE),
filter by segments, compare segments, run the driver analysis, download a formatted Excel file.

## Run
```
pip install -r requirements.txt
streamlit run app.py
```
Then in the browser: upload the **script (.xlsx)** and **dataset (.xlsx/.csv)** in the sidebar,
pick segment filters, read the tabs, click **Excel report**.

## Residential AND Enterprise (and any future survey) - one app
Upload the script + dataset of either survey. The app detects which one it is (it scores every file in
`structures/` against your script and data) and loads the matching report structure. Everything else
(filters, charts, General report, skip logic, Excel) works the same.
* `structures/residential.json`, `structures/enterprise.json` - one file per survey type. For a new survey type
  (e.g. SME), copy one of them, edit the pillars and drop it in `structures/`; it appears in the *Survey type* box.
  Choose *Automatic* to build a draft structure from the script's groups.
* **Shown but not scored**: `info_questions` / `info_only` display questions or whole blocks in the Topline
  without counting them in the pillar means or the OSS (Enterprise: the 7.1/7.2 price blocks and the 8.x "recommend"
  questions, exactly as in the Ethio telecom Enterprise Topline).
* **Column mapping**: if a rating question is in the script but its column has another name in the dataset (Enterprise
  Round 14: the 15 Corporate price items), the sidebar proposes a pairing by position, which you can edit. Nothing is dropped silently.

## For Round 15, 16, ...
1. Upload the new script + new dataset. Nothing else is needed if the pillar group names are unchanged.
2. Optional: upload the previous round's dataset -> % change in mean and last round's coefficients.
3. Check the **Checks** tab: it warns about renamed/missing columns and rating questions not in any pillar.
4. If the questionnaire changed (new group, new question), edit the matching file in `structures/` (or upload an edited copy).

## What you get
* **Topline tab** - Label name | Variable name | Mean | N responded | Weighted mean (Mean x N) | Average of question means |
  % Low | % High. Pillars have their own colour, sub-groups are tinted, mean cells are red / amber / green.
* **Charts tab** - pillar scorecard, questions in any group, low/mid/high mix, top & bottom 10 questions,
  segment heatmap, segment comparison.
* **Compare segments** - any variable broken down side by side. **Drivers & trend** - coefficients, ranks, % change.
* **Excel export** - Topline (group rows are live formulas over their questions), Group summary, segment sheet with
  colour scale, native Charts sheet, Drivers, Round comparison, Method.
* Tick *Match Ethio telecom's sheet* in Report settings to compute Weighted mean as 2-decimal mean x N, exactly like
  Ethio telecom's file (15,675 for TV; 230,325 and 7.42 for the information block).

## General report (tab "General report (all parts)")
Covers EVERY question in the script - all PART groups (subscription, quality of information ... telebirr,
attitudes, competitor, respondent profile), nested sub-groups, in script order - not only the rated indicators.
* Question types are detected automatically: rating (1-10 list), numeric, single choice, multiple choice, open text (optional).
* **Choose your statistics**: N, missing, mean, median, mode, std, variance, std error, 95% CI, min, Q1, Q3, max, IQR, range,
  sum (= weighted mean), CV, skewness, % low / mid / high, top-2 box.
* **Break down by ANY variable** (including text ones such as `name_of_city`, or custom numeric groups) and pick the categories.
* Significance tests: each category vs the rest (Welch t-test / two-proportion z-test, with Cohen's d), overall ANOVA,
  Kruskal-Wallis, chi-square + Cramer's V. Green/red / arrows mark significant differences.
* **Key findings** are written automatically (strongest / weakest items, share of low ratings, profile snapshot, biggest
  significant segment gaps with Benjamini-Hochberg correction, segment ranking).
* Question explorer (frequency table + chart + segment cross-tab per question), correlations (Pearson / Spearman),
  and a colour-coded Excel (overview, frequencies, segment sheets, findings, gaps, correlations, method).

### Segments that follow the script's skip logic (city, sub-city, zone, region ...)
* The tool reads the `relevance` column of the script (including group-level rules) and evaluates it on the data.
  e.g. `name_of_city` is asked only if location = Other Regions, `name_subcity` / `telecom_zone` only if Addis Ababa.
  When you break down by such a variable, the analysis population is automatically limited to respondents who were
  asked it (a banner shows the rule and N), and "vs the rest" compares the other cities, not the whole sample.
  Untick *Follow the script's skip logic* to turn this off.
* **Drill down**: "only respondents where Telecom region = South Region" -> then break down by city.
* **Nested segments**: "Break down by Telecom region, then by City" gives Region > City categories
  (also Zone > Sub-city, Region > Gender ...).
* Free-text segments (city names) merge spelling variants that differ only in case or spaces.
* Each question in the explorer shows who was asked it, eligible N, answered N and response rate.
* The Topline sidebar also accepts these text variables via *Add more segments* (largest 12 categories shown by default).

### Adding new questions next round (e.g. 5G)
1. Add them to the SurveyCTO script (inside any group) - they appear in the General report automatically, with the right type.
2. To include them in the Topline pillars/OSS, add the group or questions to `structures/*.json`
   (e.g. a child `{"title": "5G", "group": "mobile_network", "match": "_5g$"}` under "Mobile internet (data)").
   Nested levels (pillar > sub-group > sub-sub-group) are unlimited. The Checks tab lists rating questions not yet in any pillar.

## More segments
Sidebar -> *Add more segments*: any single- or multiple-choice question (services used, how long a customer,
SIMs, devices, education, occupation, network type, recharge method, Safaricom use ...).
Sidebar -> *Custom numeric groups*: bin age, spend, SIM count, e.g. `15, 20, 30, 45, 66`.
Edit `extra_segments` in structure.json to change the suggested list; `bands` for colour thresholds.

## structures/*.json
* `pillars`: the report hierarchy. Each node: `title`, plus one of
  `group` (every rating question inside that script group), `questions` (explicit list),
  `children` (sub-groups), optional `match` (regex on question names, e.g. `_3g$`),
  `show_header: false` (list questions without a header row).
* `segments`: filter variables (`var`, `title`, optional `alias` and `value_labels`).
  Add/remove lines to change the filter list. Any other single-choice question can also be added in the app.
* If the file matches nothing, an automatic structure is drafted from the script's groups.

## How numbers are calculated (verified on Round 14)
* Valid response = number 1-10 (scale read from the script's rating list). Blank / 99 Don't know excluded.
* Question: mean and base of valid responses.
* Sub-group / group / pillar: **pooled mean** of all valid responses beneath it
  (= sum(question mean x base) / sum(base)), not the average of question means.
* OSS: pooled mean across all pillars.
* Drivers: OLS of each respondent's composite score (mean of all their valid ratings) on their 8 pillar
  scores, z-scored, only respondents who rated every pillar. Reproduces the Round-14 deck (R2 0.98).

## Verify
`python tests/verify_r14.py` (Residential) and `python tests/verify_enterprise.py` (Enterprise) reproduce the Round-14 Toplines from the raw files (0 base differences; Enterprise OSS 7.684 on N=37,817).

## Files
`app.py` interface | `core.py` calculations | `charts.py` charts | `export.py` Excel | `structures/` per-survey configs
