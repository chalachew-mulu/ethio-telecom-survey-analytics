# Ethio Telecom Data Analytics

Upload the questionnaire (SurveyCTO form) + the survey data -> get the Satisfaction scorecard (Indicator / Mean score / Respondents),
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
(filters, charts, Report builder, skip logic, Excel) works the same.
* `structures/residential.json`, `structures/enterprise.json` - one file per survey type. For a new survey type
  (e.g. SME), copy one of them, edit the pillars and drop it in `structures/`; it appears in the *Survey type* box.
  Choose *Automatic* to build a draft structure from the script's groups.
* **Shown but not scored**: `info_questions` / `info_only` display questions or whole blocks in the Topline
  without counting them in the pillar means or the OSS (Enterprise: the 7.1/7.2 price blocks and the 8.x "recommend"
  questions, exactly as in the Ethio telecom Enterprise Topline).
* **Column mapping**: if a rating question is in the script but its column has another name in the dataset (Enterprise
  Round 14: the 15 Corporate price items), the sidebar proposes a pairing by position, which you can edit. Nothing is dropped silently.

## The sidebar, step by step
1. **Upload** the script and the dataset (the survey type is detected automatically).
2. **Report columns** - pick **Compare by** (Location, Sub-city, City, Region, Gender, SIM type ... or *Total only*), optionally
   *then by* a second variable (Region > City), and tick the categories to show. Every table, chart and Excel then has
   **Total + one column per category**. Cities and sub-cities follow the script's skip logic automatically:
   City = respondents who live in Other Regions; Sub-city = Addis Ababa residents (a note shows the rule and the base).
3. **Filter respondents** (optional) - narrow who is included. Filters that cannot apply are hidden (choose Addis Ababa and the
   Region / City filters disappear). **Clear all filters** resets them. Counts next to each choice show how many respondents.
4. **Download** - the Topline Excel (Topline, Group summary, comparison sheet, charts, drivers, method).
Need another variable? *Add variables* lets you use any question, or group a number (age, spend, SIMs) into custom ranges.

## Compare segments tab
Rows: **Pillars only / Pillars & sub-groups / All indicators / Custom**, limit to chosen pillars, include or hide the overall score.
Show: mean, N, median, % high / low, weighted mean, standard deviation. Options: flag significant differences, highlight best / lowest
category per row, hide Total, decimals, sort rows by any column, chart, CSV and Excel download. Small bases are listed under the table.

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

## Report builder (tab "Report builder") - build any report in five steps
1. **Report type**: Profile & choice questions (counts, column %, row %) | Satisfaction scores (any statistic) |
   Numeric measures (spend, age, SIMs, branches ...) | Indicator relationships (correlation).
2. **Rows**: pick questions (search, or add a whole part), or Topline indicators (overall / pillars / sub-groups / questions).
3. **Break down by**: any variable, optionally nested (Region > City). Every table shows **Total + each category**.
   Segment questions follow the script's skip logic (e.g. city = Other Regions respondents only); you can also restrict the population.
4. **Statistics / values**: tick what you want (N, mean, median, mode, std, quartiles, CI, % low / high ...).
5. **Output**: decimals, flag significant differences (95%), group columns by statistic or by segment.
Results: Table | Chart (clustered, horizontal, stacked 100%, heatmap) | Download (CSV, Excel with native charts,
and a **report pack** = the same report for several break-downs, one sheet each).
**Quick start templates** (Residential and Enterprise): profile by location / gender / region / SIMs / SIM type / sector,
satisfaction scorecards by each of those, indicator detail, spend. Templates live in `structures/*.json`
(`report_templates`); add your own lines there. `labels` in the same file renames variables for display.

### Adding new questions next round (e.g. 5G)
1. Add them to the SurveyCTO script (inside any group) - they appear in the Report builder automatically, with the right type.
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
`app.py` interface | `core.py` Topline calculations | `builder*.py` + `export_builder.py` Report builder | `general.py` question inventory & statistics | `skip.py` skip logic | `charts.py` Topline charts | `export.py` Topline Excel | `structures/` per-survey configs


## Screen names (what each part is called)
Tabs: **Satisfaction scorecard** (overall score, pillars, sub-groups, questions) | **Visual summary** (charts; measure = mean score,
% high scores 8-10, % low scores 1-5 or respondents) | **Compare groups** (Total + each group side by side) |
**Key drivers & change** (importance of each pillar, change vs last round) | **Data quality** (checks) | **Custom report builder**.
Sidebar: 1 Upload your files, 2 Choose how to split the report, 3 Choose which respondents to include, 4 Download.
The page title follows the uploaded survey ("Ethio Telecom - Enterprise / Residential Customer Satisfaction Analytics").
Charts always use a white background with dark text; use the *Prepare chart image (PNG)* button under any chart for a sharp image.
Excel sheets: Scorecard | Pillar summary | By <variable> | Charts | Key drivers | Methodology.
