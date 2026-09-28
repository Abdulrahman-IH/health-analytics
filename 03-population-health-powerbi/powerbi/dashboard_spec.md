# Power BI Dashboard Specification — Population Health & Preventive Care

| | |
|---|---|
| **Report name** | Population Health & Preventive Care Dashboard |
| **Audience** | Population-health leads, care-management teams, quality/HEDIS analysts, digital-health product owners |
| **Data** | Star schema in `data/star_schema/` (11 CSVs) produced by `notebooks/01_clean_and_build_star_schema.ipynb` |
| **Measures** | `powerbi/measures.dax` (≈110 measures, grouped 0–8) |
| **Theme** | `powerbi/theme_navy_teal.json` — dark navy canvas, teal primary, amber/coral for status |
| **Canvas** | 16:9, 1280 × 720, all pages share a synced slicer rail on the left |
| **Snapshot** | 31 Dec 2025 · reporting period Jan–Dec 2025 |

---

## 1. Design principles

1. **Denominators first.** Every rate has an explicit, visible denominator (eligible screenings, enrolled patients, device-months). Cards show `n` in the subtitle so a 90 % rate on 12 patients is never mistaken for a population result.
2. **From population to person.** Each page moves left-to-right from the population KPI → cohort comparison → drill-through to an actionable patient list. The dashboard exists to *generate outreach*, not just describe.
3. **Equity is a lens, not a page.** Region, urbanicity, deprivation (ADI band) and insurance are available as slicers everywhere and as a "disparity" small-multiple on every clinical page.
4. **Clinical thresholds are guideline-based and documented.** Control cut-points (BP < 140/90, A1c < 8 %, LDL < 130), screening intervals and step/sleep bands are the same ones implemented in the notebook and listed on the appendix page.
5. **Dark theme, restrained colour.** Teal carries "good/primary", amber "watch", coral "below target". Categorical series use a fixed six-colour order (teal, sky, amber, coral, lavender, light teal) and never re-map when a filter removes a category.

---

## 2. Global slicer rail (synced on every page)

| Slicer | Field | Style | Notes |
|---|---|---|---|
| Region | `dim_geography[region]` | Tile buttons (4) | Multi-select; drives the `Selected Region Label` title measure |
| State | `dim_geography[state]` | Dropdown, search | Cascades from Region |
| Urbanicity | `dim_geography[urbanicity]` | Tile buttons (3) | |
| Age band | `dim_patient[age_band]` | Vertical list | Sort by `age_band_order` |
| Sex | `dim_patient[sex_label]` | Tile buttons | |
| Chronic condition | `dim_patient` flag fields via field-parameter *Condition Filter* (`has_diabetes`, `has_hypertension`, `has_obesity`, `any_focus_condition`, `multimorbid`) | Dropdown | Filters the **population**; the condition axis on page 2 uses `dim_condition` instead |
| Risk tier | `dim_patient[risk_tier]` | Tile buttons (4), coloured via `Risk Tier Colour` | Sort by `risk_tier_order` |
| Insurance | `dim_patient[insurance_type]` | Dropdown | |
| Deprivation | `dim_patient[adi_band]` | Dropdown | |
| Engagement segment | `dim_patient[engagement_segment]` | Dropdown | |
| Reporting month | `dim_date[year_month]` | Between slider | Only affects time-series visuals (events, wearables, completions in period) |

A **"Reset filters" bookmark button** sits at the bottom of the rail. The rail collapses via a bookmark pair (expanded/collapsed) to give charts full width.

---

## 3. Data model

```
                         dim_date (20,820 rows)
                        /    |     \          \ (inactive)
        fact_engagement_event  fact_wearable_monthly  fact_screening  fact_condition
                 |                    |                  |               |
 dim_event_type ─┘                    |                  |               └─ dim_condition
                                      |                  └─ dim_screening
 dim_geography ── dim_patient ────────┴──────────────────┴──── fact_patient_risk_snapshot
```

### Relationships

| From (many) | To (one) | Active | Purpose |
|---|---|---|---|
| `fact_*[patient_key]` (all five facts) | `dim_patient[patient_key]` | ✔ | Population slicing |
| `dim_patient[geo_key]` | `dim_geography[geo_key]` | ✔ | Region / state / urbanicity (snowflaked to keep `dim_patient` narrow) |
| `fact_condition[condition_key]` | `dim_condition[condition_key]` | ✔ | |
| `fact_screening[screening_key]` | `dim_screening[screening_key]` | ✔ | |
| `fact_engagement_event[event_type_key]` | `dim_event_type[event_type_key]` | ✔ | |
| `fact_engagement_event[date_key]` | `dim_date[date_key]` | ✔ | MAU, trends |
| `fact_wearable_monthly[month_date_key]` | `dim_date[date_key]` | ✔ | Vitals trends |
| `fact_screening[last_completed_date_key]` | `dim_date[date_key]` | ✖ | `Screenings Completed in Period` via USERELATIONSHIP |
| `fact_condition[onset_date_key]` | `dim_date[date_key]` | ✖ | `New Diagnoses in Period` |
| `dim_patient[app_enrollment_date_key]` | `dim_date[date_key]` | ✖ | `New Enrollments in Period` |

All relationships are single-direction (dimension → fact). Mark `dim_date` as the date table (`date` column). Hide every `*_key` column and the raw `completed_flag_raw` column from report view.

### Storage / performance notes
* Import mode; 1.1 M fact rows compress to well under 100 MB in VertiPaq because all keys are integers and text attributes live on small dimensions.
* Set `fact_engagement_event[event_timestamp]` to *Date/time* but keep `date_key` for the relationship; disable auto date/time in Options.
* Pre-aggregated `fact_patient_risk_snapshot` avoids expensive per-patient iterators on the risk page.

### Row-level security (optional)
Role **Regional lead**: `[region] = LOOKUPVALUE(RegionMap[region], RegionMap[upn], USERPRINCIPALNAME())` on `dim_geography`. The snowflake means one filter secures every fact.

---

## 4. Pages

### Page 1 — Executive Overview

**Question answered:** *How healthy is our attributed population, are we closing preventive gaps, and is digital engagement helping?*

| Zone | Visual | Fields / measures | Format |
|---|---|---|---|
| Header | Text + `Population Card Subtitle` | | Title "Population health at a glance" |
| KPI row (6 cards) | Card / KPI | `Total Patients` · `Any Focus Condition %` · `Screening Rate %` (goal `Screening Rate Target`, trend `Screenings Completed in Period` by month) · `App Engagement Rate %` (goal `Engagement Rate Target`) · `High Risk Share %` · `Open Care Gaps` | Card callout 32 pt teal; KPI status colours via theme good/neutral/bad |
| Left middle | Stacked bar — **Risk-tier distribution** | Axis `dim_patient[risk_tier]` (sorted by order), value `Risk Tier Share %`, colour `Risk Tier Colour` | Data labels on, 100 % scale |
| Centre middle | Clustered bar — **Chronic-condition prevalence by region** | Axis `dim_geography[region]`, legend `dim_condition[condition_name]` filtered to `is_focus_condition = 1`, value `Condition Prevalence %` | Legend top; fixed colour order |
| Right middle | Line — **Monthly active users** | Axis `dim_date[year_month]`, value `Monthly Active Users` | Teal 2 px line, markers ≥ 8 px, end-point label |
| Bottom left | Bullet-style bar — **Screening rate vs target by screening** | Axis `dim_screening[screening_name]`, value `Screening Rate %`, constant line `Screening Rate Target`, bar colour `Screening Rate Colour` | Sorted descending |
| Bottom right | Matrix — **Region × KPI heat table** | Rows `dim_geography[region]`; values `Screening Rate %`, `App Engagement Rate %`, `Hypertension Control %`, `Diabetes Control %`, `High Risk Share %` | Background colour scale per column (teal ramp; coral ramp for High Risk) |

Interactions: risk-tier bar cross-filters all visuals; the MAU line is set to *none* from the prevalence chart to avoid confusing partial-line effects.

---

### Page 2 — Chronic Disease Prevalence & Control

**Question:** *Where is the burden of diabetes, hypertension and obesity concentrated, and how well is it controlled?*

| Zone | Visual | Fields / measures |
|---|---|---|
| KPI row | 5 cards | `Diabetes Prevalence %` · `Hypertension Prevalence %` · `Obesity Prevalence %` · `Multimorbidity %` · `Disease Control Rate %` |
| Left | Clustered column — **Prevalence by age band** | Axis `dim_patient[age_band]`, legend `dim_condition[condition_name]` (focus conditions), value `Condition Prevalence %` |
| Centre | Filled map (or shape map of US states) — **Prevalence by state** | Location `dim_geography[state]`, colour saturation `Condition Prevalence %` (sequential teal ramp), tooltip `Total Patients`, `Patients with Condition` |
| Right | 100 % stacked bar — **Control status by condition** | Axis `dim_condition[condition_name]` (hypertension, diabetes, hyperlipidemia), legend `fact_condition[control_status]`, value `COUNTROWS` | Controlled = teal, Uncontrolled = coral |
| Bottom left | Small multiples — **Prevalence by deprivation band** | Multiples `dim_condition[condition_name]`, axis `dim_patient[adi_band]`, value `Condition Prevalence %` |
| Bottom centre | Scatter — **Avg systolic BP vs Avg HbA1c by state** | X `Avg Systolic BP`, Y `Avg HbA1c`, size `Total Patients`, detail `dim_geography[state]`, reference lines at 140 and 8.0 |
| Bottom right | Table — **Condition detail** | `condition_name`, `Patients with Condition`, `Condition Prevalence %`, `Disease Control Rate %`, `On Medication %`, `Avg Years Since Onset` |

Drill-through target: **Patient list** (page 8) with condition context. Tooltip page *Condition tooltip* shows prevalence by sex and insurance.

---

### Page 3 — Preventive Screening & Care Gaps

**Question:** *Which guideline-recommended screenings are we missing, for whom, and does digital enrolment move the needle?*

| Zone | Visual | Fields / measures |
|---|---|---|
| Title | `Screening Page Title` (dynamic) | |
| KPI row | 5 cards | `Screening Rate %` (KPI vs target) · `Open Care Gaps` · `Patients with Open Care Gaps %` · `Avg Days Overdue` · `Digital Engagement Lift (pp)` |
| Left (tall) | Bar — **Completion rate by screening** | Axis `dim_screening[screening_name]`, value `Screening Rate %`, colour `Screening Rate Colour`, constant line target; tooltip `Eligible Screenings`, `Completed Screenings`, `guideline_source` |
| Centre top | Clustered bar — **Enrolled vs not enrolled** | Axis `dim_screening[screening_category]`, values `Screening Rate % (Enrolled)`, `Screening Rate % (Not Enrolled)` |
| Centre bottom | Line — **Completions per month** | Axis `dim_date[year_month]`, value `Screenings Completed in Period`, legend `dim_screening[screening_category]` |
| Right top | Stacked bar — **Care-gap status by region** | Axis `dim_geography[region]`, legend `fact_screening[screening_status]` (Completed / Overdue / Never screened), value `COUNTROWS`, 100 % |
| Right bottom | Decomposition tree — **Open care gaps** | Analyse `Open Care Gaps` by `region` → `age_band` → `insurance_type` → `risk_tier` → `screening_name` | AI splits enabled ("high value") |
| Footer strip | Gauge ×3 | `Cancer Screening Rate %`, `Diabetes Care Bundle %`, `Flu Vaccination Rate %` vs target |

Drill-through: right-click any bar → **Patient list** filtered to that screening & status. Bookmark "Show reminder coverage" swaps the region bar for `Reminder Coverage %` by screening.

---

### Page 4 — Digital Engagement

**Question:** *Who is using the app, how, and is usage translating into care actions?*

| Zone | Visual | Fields / measures |
|---|---|---|
| KPI row | 6 cards | `App Enrollment Rate %` · `App Engagement Rate %` (KPI, goal 60 %) · `Monthly Active Users` (latest month, via `LASTNONBLANK`) · `Appointment Bookings` · `Medication Reminder Ack Rate %` · `Dormant Rate %` |
| Left top | Line + column combo (single axis) — **MAU & MoM growth** | Axis `year_month`, column `Monthly Active Users`, tooltip `MAU Growth MoM %` (no secondary axis — growth shown as data-label suffix) |
| Left bottom | Funnel — **Enrollment → activation** | `Total Patients` → `Enrolled Patients` → `Active Users` → patients with `Meaningful Actions` ≥ 1 |
| Centre | Donut — **Engagement segments** | Legend `dim_patient[engagement_segment]`, value `Total Patients`; centre label `App Engagement Rate %` |
| Centre bottom | Stacked column — **Events by type per month** | Axis `year_month`, legend `dim_event_type[event_label]`, value `Total Events` |
| Right top | Heat matrix — **Engagement rate by age band × region** | Rows `age_band`, columns `region`, value `App Engagement Rate %` (sequential teal background) |
| Right bottom | Clustered bar — **Channel mix by age band** | Axis `age_band`, legend `fact_engagement_event[channel]`, value `Total Events`, 100 % |
| Footer | Ribbon or table — **Meaningful-action rate by segment** | `engagement_segment` × `Meaningful Action Rate %`, `Events per Active User`, `Avg Session Minutes` |

Tooltip page *Hour-of-day* shows `Total Events` by `fact_engagement_event[hour_of_day]` for the hovered month.

---

### Page 5 — Wearable Vitals & Lifestyle

**Question:** *What do connected devices tell us about activity, sleep and cardiovascular load across cohorts?*

| Zone | Visual | Fields / measures |
|---|---|---|
| KPI row | 5 cards | `Wearable Adoption %` · `Avg Daily Steps` (vs `Steps Guideline`) · `Avg Sleep Hours` · `Avg Resting HR` · `Months Meeting 10k Steps %` |
| Left top | Line — **Average daily steps by month** | Axis `year_month`, value `Avg Daily Steps`, legend `dim_patient[risk_tier]` (4 lines, fixed tier colours), constant line 7,500 |
| Left bottom | Stacked bar — **Activity band mix by age band** | Axis `age_band`, legend `fact_wearable_monthly[activity_band]` (ordered sedentary → active), value `Device Months`, 100 % |
| Centre | Box-and-whisker (custom visual) or clustered bar — **Steps by condition** | Axis `dim_condition[condition_name]` via `Patients with Condition` context, value `Median Daily Steps`, `Avg Daily Steps` |
| Right top | Clustered bar — **Sleep band by risk tier** | Axis `risk_tier`, legend `sleep_band`, value `Device Months`, 100 % |
| Right bottom | Scatter — **Resting HR vs steps** (per patient, sampled) | X `dim_patient[avg_daily_steps_12m]`, Y `dim_patient[avg_resting_hr_12m]`, colour `has_hypertension`, size = none, play axis off; use *high-density sampling* |
| Footer | Table — **Device mix** | `wearable_device`, `Wearable Users`, `Avg Daily Steps`, `Avg Active Days per Month` |

Interaction note: wearable metrics only cover the 55 % of patients with a device; every card on this page carries the subtitle "device users only, n = `Wearable Users`".

---

### Page 6 — Risk Stratification & Outreach

**Question:** *Who should the care team call this week?*

| Zone | Visual | Fields / measures |
|---|---|---|
| KPI row | 5 cards | `Avg Risk Score` · `High Risk Patients` · `High Risk Share %` · `Rising Risk Patients` · `Priority Outreach Cohort` |
| Left top | Column — **Risk-tier distribution** | Axis `risk_tier`, value `Patients in Tier`, colour `Risk Tier Colour`, labels `Risk Tier Share %` |
| Left bottom | Stacked bar — **Tier mix by region** | Axis `region`, legend `risk_tier`, value `Risk Tier Share %`, 100 % |
| Centre top | Clustered bar — **Score composition** | Unpivot the nine `*_points` columns of `fact_patient_risk_snapshot` in Power Query into `Component` / `Points`; axis `Component`, value `AVERAGE(Points)`, legend `risk_tier` |
| Centre bottom | Clustered bar — **Screening rate & engagement by tier** | Axis `risk_tier`, values `Screening Rate %`, `App Engagement Rate %` |
| Right (tall) | Table — **Priority outreach list** | `patient_id`, `age`, `sex_label`, `region`, `risk_tier`, `risk_score`, `chronic_condition_count`, `uncontrolled_condition_count`, `open_care_gaps`, `engagement_segment`, `avg_daily_steps_12m`; visual-level filter `risk_tier IN {High, Very High}`, `open_care_gaps ≥ 1`, sorted by `risk_score` desc; conditional colour on tier | Export enabled for care coordinators |
| Footer | Text box | Risk model definition (points table) with link to `docs/` |

Buttons: "Very High only", "Not engaged only", "Uncontrolled only" bookmarks apply filters to the outreach table.

---

### Page 7 — Data Quality & Lineage (appendix)

| Visual | Fields / measures |
|---|---|
| Table — **Before/after scorecard** | Load `docs/data_quality_scorecard.csv` as a disconnected table: `issue`, `rows_before`, `rows_after` with icon set (✔ when after = 0) |
| Cards | `BMI Imputed %` · `Screening Flags Downgraded` · `Wearable Months with Missing Steps %` |
| Text | Cleaning rules, clinical thresholds, screening intervals (copy of notebook §3–4 tables) |
| Table | Row counts per star-schema table (`docs/summary_stats.json → star_schema_rows`) |

---

### Page 8 — Patient list (drill-through, hidden)

Drill-through fields: `dim_patient[patient_key]` plus any of `region`, `risk_tier`, `screening_name`, `condition_name`, `screening_status`.

Table columns: `patient_id`, `age`, `sex_label`, `region`, `state`, `insurance_type`, `risk_tier`, `risk_score`, focus-condition flags as icons, `open_care_gaps`, `engagement_segment`, `wearable_device`, `avg_daily_steps_12m`, `last_event_date`. Back button top-left. Keep "Keep all filters" on.

---

## 5. KPI definitions (business glossary)

| KPI | Definition | Measure | Target / benchmark |
|---|---|---|---|
| Chronic disease prevalence | Patients with ≥1 record for the condition ÷ attributed patients | `Condition Prevalence %` | Context: US adult prevalence ≈ 11 % diabetes, 30–48 % hypertension (definition-dependent), 40 % obesity |
| Disease control rate | Condition records meeting guideline control ÷ records with a control target | `Disease Control Rate %` | ≥ 60 % (HEDIS CBP/HBD-style) |
| Screening rate | Eligible patient–screening pairs documented within interval ÷ eligible pairs | `Screening Rate %` | 75 % stretch target |
| Open care gaps | Eligible pairs not up to date (overdue + never screened) | `Open Care Gaps` | ↓ quarter on quarter |
| App enrollment rate | Enrolled ÷ attributed | `App Enrollment Rate %` | 70 % |
| App engagement rate | Active (3+ active months) ÷ enrolled | `App Engagement Rate %` | 60 % |
| Medication reminder ack rate | Acknowledged ÷ sent | `Medication Reminder Ack Rate %` | ≥ 70 % |
| Risk-tier distribution | Share of patients in Low / Moderate / High / Very High | `Risk Tier Share %` | Monitor High + Very High ≤ 30 % |
| Priority outreach cohort | High/Very High + open gap + not actively engaged | `Priority Outreach Cohort` | Worklist for care management |

---

## 6. Build checklist

1. **Get data → Folder** on `data/star_schema/`; load the 11 CSVs; set data types (all `*_key` = Whole number, `date` = Date, `event_timestamp` = Date/time).
2. In Power Query, unpivot the nine `*_points` columns of `fact_patient_risk_snapshot` into a reference query `fact_risk_components` (Component, Points, patient_key). Load `docs/data_quality_scorecard.csv` as a disconnected table.
3. Create relationships per §3; mark `dim_date` as date table; set inactive relationships.
4. Sort `age_band` by `age_band_order`, `risk_tier` by `risk_tier_order`, `month_name` by `month`.
5. Create the `_Measures` table and paste `powerbi/measures.dax` group by group; set format strings from the comment on each measure.
6. Import `powerbi/theme_navy_teal.json` (View → Themes → Browse for themes).
7. Build pages 1–8 per §4; sync the slicer rail (View → Sync slicers) and set the collapse/expand and reset bookmarks.
8. Configure drill-through on page 8 and tooltip pages (*Condition tooltip*, *Hour-of-day*).
9. Accessibility pass: alt text on every visual, tab order = reading order, confirm teal/amber/coral status is always paired with a label or icon.
10. Publish to a workspace; schedule refresh from the repository folder (or point the folder source at the pipeline's output location).
