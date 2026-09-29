// Build presentation/hospital_operations_bed_utilisation.pptx
// Numbers come from deck_data.json (prepare_deck_data.py), charts are native
// PowerPoint charts except the two heatmaps, which reuse the notebook PNGs.
//
//   python presentation/prepare_deck_data.py && node presentation/build_deck.js

const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data.json"), "utf8"));
const OUT = path.join(__dirname, "hospital_operations_bed_utilisation.pptx");

// ---- theme (shared with the notebook charts) ------------------------------------------
const C = {
  teal: "00949C", deep: "0B3C44", ink: "1B2A32", muted: "5B6B73", grid: "E3E8EA",
  context: "A7B1B6", red: "C0392B", amber: "D99A00", panel: "F1F6F7", white: "FFFFFF",
  orange: "C9572A", violet: "5B4BA8", tealLight: "8CCBCF",
};
const FONT = "Calibri";
const W = 13.333, H = 7.5, M = 0.6;

function pngRatio(file) {
  // height / width from the PNG IHDR header
  const b = fs.readFileSync(file);
  return b.readUInt32BE(20) / b.readUInt32BE(16);
}
const pct = (v, d = 0) => `${(v * 100).toFixed(d)}%`;
const num = (v) => Math.round(v).toLocaleString("en-GB");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.title = "Hospital Operations & Bed Utilisation";
pres.author = "Healthcare operations analytics — project 06";

// ---- helpers --------------------------------------------------------------------------
function tag(slide, n, label, dark = false) {
  // motif: numbered teal circle + section label
  slide.addShape(pres.shapes.OVAL, { x: M, y: 0.42, w: 0.36, h: 0.36, fill: { color: C.teal }, line: { color: C.teal } });
  slide.addText(String(n).padStart(2, "0"), {
    x: M, y: 0.42, w: 0.36, h: 0.36, fontFace: FONT, fontSize: 10, bold: true, color: C.white,
    align: "center", valign: "middle", margin: 0, isTextBox: true,
  });
  slide.addText(label.toUpperCase(), {
    x: M + 0.48, y: 0.42, w: 8, h: 0.36, fontFace: FONT, fontSize: 11, bold: true, charSpacing: 2,
    color: dark ? C.tealLight : C.teal, valign: "middle", margin: 0, isTextBox: true,
  });
}

function title(slide, text, sub, dark = false) {
  slide.addText(text, {
    x: M, y: 0.9, w: W - 2 * M, h: 0.6, fontFace: FONT, fontSize: 26, bold: true,
    color: dark ? C.white : C.ink, valign: "top", margin: 0, isTextBox: true,
  });
  if (sub) {
    slide.addText(sub, {
      x: M, y: 1.52, w: W - 2 * M, h: 0.4, fontFace: FONT, fontSize: 14,
      color: dark ? C.tealLight : C.muted, valign: "top", margin: 0, isTextBox: true,
    });
  }
}

function footer(slide, source, dark = false) {
  slide.addText(source, {
    x: M, y: H - 0.45, w: W - 2 * M, h: 0.28, fontFace: FONT, fontSize: 9,
    color: dark ? C.tealLight : C.muted, margin: 0, isTextBox: true,
  });
}

function stat(slide, x, y, w, value, label, color = C.teal, h = 1.35) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, fill: { color: C.panel }, line: { color: C.panel }, rectRadius: 0.08,
  });
  slide.addText(value, {
    x: x + 0.2, y: y + 0.12, w: w - 0.4, h: 0.62, fontFace: FONT, fontSize: 32, bold: true,
    color, margin: 0, valign: "middle", isTextBox: true,
  });
  slide.addText(label, {
    x: x + 0.2, y: y + 0.74, w: w - 0.4, h: h - 0.82, fontFace: FONT, fontSize: 12,
    color: C.ink, margin: 0, valign: "top", isTextBox: true,
  });
}

function axisOpts(extra = {}) {
  return Object.assign({
    catAxisLabelColor: C.muted, valAxisLabelColor: C.muted, catAxisLabelFontFace: FONT,
    valAxisLabelFontFace: FONT, catAxisLabelFontSize: 10, valAxisLabelFontSize: 10,
    valGridLine: { color: C.grid, size: 0.75 }, catGridLine: { style: "none" },
    catAxisLineShow: false, valAxisLineShow: false, showTitle: false,
    legendFontFace: FONT, legendFontSize: 11, legendColor: C.ink,
  }, extra);
}

// =====================================================================================
// 1. Title
// =====================================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.deep };
  s.addText("PROJECT 06 · HEALTHCARE OPERATIONS ANALYTICS", {
    x: M, y: 1.3, w: 10, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, charSpacing: 3,
    color: C.tealLight, margin: 0, isTextBox: true,
  });
  s.addText("Hospital Operations & Bed Utilisation", {
    x: M, y: 1.85, w: 11.5, h: 1.1, fontFace: FONT, fontSize: 48, bold: true, color: C.white, margin: 0, isTextBox: true,
  });
  s.addText("Where the beds go, why the emergency department waits, and who comes back — a SQL analysis of a 15-hospital network, calendar year 2025", {
    x: M, y: 3.05, w: 10.5, h: 0.9, fontFace: FONT, fontSize: 18, color: C.tealLight, margin: 0, isTextBox: true,
  });
  const facts = [
    ["15", "hospitals"], [num(D.volumes.beds), "staffed inpatient beds"],
    [num(D.volumes.admissions_2025), "admissions"], [num(D.volumes.er_2025), "ED attendances"],
  ];
  facts.forEach(([v, l], i) => {
    const x = M + i * 3.05;
    s.addShape(pres.shapes.OVAL, { x, y: 4.95, w: 0.16, h: 0.16, fill: { color: C.teal }, line: { color: C.teal } });
    s.addText(v, { x: x + 0.3, y: 4.72, w: 2.6, h: 0.6, fontFace: FONT, fontSize: 30, bold: true, color: C.white, margin: 0, isTextBox: true });
    s.addText(l, { x: x + 0.3, y: 5.3, w: 2.6, h: 0.35, fontFace: FONT, fontSize: 13, color: C.tealLight, margin: 0, isTextBox: true });
  });
  footer(s, "Synthetic data generated for this portfolio project · PostgreSQL-compatible schema, SQLite database, 10 SQL queries, Python notebook", true);
  s.addNotes("Project 06 of the health-analytics portfolio. Everything in this deck is produced from the ten SQL queries in sql/ run against a synthetic 15-hospital network. The data is synthetic but the operational mechanics (seasonality, escalation beds, weekend discharge slippage, exit block) are modelled so the patterns behave like a real extract.");
}

// =====================================================================================
// 2. At a glance
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 2, "Network at a glance");
  title(s, "The network sits on its 85% planning line — the pressure is concentrated",
    "Five headline measures, 2025. Each is produced by one of the project's SQL queries.");
  const cards = [
    [pct(D.occupancy.mean), "inpatient bed occupancy\n(planning target 85%)", C.teal],
    [pct(D.occupancy.med_mean), "General Medicine occupancy —\nthe largest specialty", C.red],
    [`${D.los.network_alos.toFixed(1)} d`, `average length of stay\n(P90 ${D.los.network_p90.toFixed(1)} days)`, C.teal],
    [pct(D.ed.network_within4h, 1), "ED attendances completed\nwithin 4 hours", C.teal],
    [pct(D.readmit.network, 1), "30-day unplanned\nreadmission rate", C.teal],
  ];
  const cw = (W - 2 * M - 4 * 0.25) / 5;
  cards.forEach(([v, l, col], i) => stat(s, M + i * (cw + 0.25), 2.3, cw, v, l, col, 1.5));

  const rows = [
    ["Capacity", `${pct(D.occupancy.ward_days_ge95)} of ward-days at ≥95% occupancy; ${D.occupancy.med_hospitals_ge95} hospitals run Medicine at ≥95% for the whole year.`],
    ["Flow", `Stays of 7+ days are ${pct(D.stranded.stranded_share)} of discharges but ${pct(D.stranded.stranded_bed_day_share)} of bed-days; weekends discharge ${pct(1 - D.stranded.weekend_ratio)} fewer patients.`],
    ["Emergency care", `ED boarding rises from ${D.bottleneck.band_boarding[0]} to ${D.bottleneck.band_boarding[4]} minutes as hospital occupancy passes 95% — ward congestion is an ED problem.`],
  ];
  rows.forEach(([h, t], i) => {
    const y = 4.3 + i * 0.78;
    s.addText(h, { x: M, y, w: 2.2, h: 0.6, fontFace: FONT, fontSize: 15, bold: true, color: C.teal, margin: 0, valign: "middle", isTextBox: true });
    s.addText(t, { x: M + 2.3, y, w: W - 2 * M - 2.3, h: 0.6, fontFace: FONT, fontSize: 15, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
  });
  footer(s, "Sources: queries 01, 03, 05, 07 (sql/sqlite, sql/postgres) · synthetic 15-hospital network, 2025");
  s.addNotes("Occupancy is the midnight census divided by staffed beds (query 01). LOS on 2025 discharges (query 03). ED four-hour rate from query 05. Readmissions: emergency re-admission within 30 days of a Jan–Nov discharge, excluding deaths and transfers (query 07).");
}

// =====================================================================================
// 3. Daily occupancy
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 3, "Bed occupancy · query 01");
  title(s, "Occupancy hugs 85% all year; winter and November push it towards 95%",
    "Network inpatient occupancy, 7-day average (weekly points) · midnight census ÷ staffed beds");
  const labels = D.occupancy.weekly_labels;
  s.addChart(pres.charts.LINE, [
    { name: "7-day average occupancy", labels, values: D.occupancy.weekly_values },
    { name: "85% planning target", labels, values: labels.map(() => 85) },
    { name: "95% no-slack line", labels, values: labels.map(() => 95) },
  ], axisOpts({
    x: M, y: 2.1, w: 8.4, h: 4.7, chartColors: [C.teal, C.amber, C.red], lineSize: 2,
    lineDataSymbol: "none", valAxisMinVal: 70, valAxisMaxVal: 100, valAxisMajorUnit: 5,
    valAxisLabelFormatCode: "0\"%\"", catAxisLabelFrequency: 8, showLegend: true, legendPos: "b",
  }));
  const x = M + 8.8, w = W - M - x;
  stat(s, x, 2.15, w, pct(D.occupancy.ward_days_ge95), "of ward-days at or above the 95% no-slack line", C.red);
  stat(s, x, 3.7, w, pct(D.occupancy.ward_days_over100), "of ward-days with more patients than staffed beds", C.red);
  stat(s, x, 5.25, w, pct(D.occupancy.peak, 1), `network peak on ${D.occupancy.peak_date}, in the pre-Christmas flu surge`, C.teal);
  footer(s, "Query 01 · movement-based census: +1 on admission, −1 on discharge, running SUM() OVER (ORDER BY date); staffed beds from the slowly-changing bed_capacity table");
  s.addNotes("The network average looks healthy, but it averages over 108 wards. A third of ward-days are at or above 95% and over a fifth are above staffed capacity, meaning patients are in escalation spaces or outlying on other wards.");
}

// =====================================================================================
// 4. Department x month heatmap
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 4, "Occupancy by department · query 02");
  title(s, "Medicine runs hot every month; capacity decisions show up in the data",
    "Monthly bed occupancy by department, network total (bed-day weighted)");
  const heat = path.join(ROOT, "charts", "02_department_month_heatmap.png");
  // crop the notebook's own title band off the PNG — the slide title replaces it
  const hh = 8.6 * pngRatio(heat), band = hh * 0.095;
  s.addImage({ path: heat, x: M, y: 2.2, w: 8.6, h: hh - band, sizing: { type: "crop", x: 0, y: band, w: 8.6, h: hh - band } });
  const pts = [
    ["General Medicine", `never below 86% in any month, and ${D.occupancy.med_hospitals_ge95} hospitals average ≥95% across the year.`],
    ["Escalation beds", `closed on 31 March: Medicine jumped from ${pct(D.dept_month.med_mar)} in March to ${pct(D.dept_month.med_apr)} in April — demand had not fallen yet.`],
    ["Intensive care", `ran at ${pct(D.dept_month.icu_jan)} of staffed beds in the January flu surge.`],
  ];
  const x = M + 9.0, w = W - M - x;
  pts.forEach(([h, t], i) => {
    const y = 2.2 + i * 1.45;
    s.addText(h, { x, y, w, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: C.teal, margin: 0, isTextBox: true });
    s.addText(t, { x, y: y + 0.4, w, h: 0.95, fontFace: FONT, fontSize: 13, color: C.ink, margin: 0, valign: "top", isTextBox: true });
  });
  s.addText("Maternity and Paediatrics have seasonal slack that could flex to Medicine in summer.", {
    x: M, y: 5.75, w: 8.6, h: 0.5, fontFace: FONT, fontSize: 13, italic: true, color: C.muted, margin: 0, isTextBox: true,
  });
  footer(s, "Query 02 · RANK() within month, LAG() for month-on-month change, share of ward-days ≥85% / ≥95%");
  s.addNotes("The April jump is the clearest capacity-planning signal in the dataset: escalation beds were funded to 30 March, but the medical bed base needed them for several more weeks.");
}

// =====================================================================================
// 5. LOS and discharge pattern
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 5, "Length of stay & discharge · queries 03–04");
  title(s, "Long stays fill the beds, and discharge stops at weekends",
    "Left: mean vs P90 length of stay by department · right: average discharges per day of week, network");
  s.addChart(pres.charts.BAR, [
    { name: "Mean LOS (days)", labels: D.los.depts, values: D.los.alos },
    { name: "P90 LOS (days)", labels: D.los.depts, values: D.los.p90 },
  ], axisOpts({
    x: M, y: 2.1, w: 5.9, h: 3.55, barDir: "bar", barGrouping: "clustered", barGapWidthPct: 45,
    chartColors: [C.teal, C.deep], catAxisOrientation: "maxMin", showValue: true, dataLabelPosition: "outEnd",
    dataLabelFontSize: 9, dataLabelColor: C.ink, dataLabelFormatCode: "0.0", valAxisHidden: true,
    valGridLine: { style: "none" }, showLegend: true, legendPos: "b",
  }));
  s.addChart(pres.charts.BAR, [
    { name: "Discharges per day", labels: D.stranded.dow_labels, values: D.stranded.dow_daily },
  ], axisOpts({
    x: M + 6.3, y: 2.1, w: 5.8, h: 3.55, barDir: "col", barGapWidthPct: 40, chartColors: [C.teal],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelColor: C.ink,
    dataLabelFormatCode: "0", valAxisHidden: true, valGridLine: { style: "none" }, showLegend: false,
  }));
  const st = [
    [pct(D.stranded.stranded_bed_day_share), `of bed-days used by stays of 7+ days (${pct(D.stranded.stranded_share)} of patients)`],
    [`${num(D.los.excess_top[0].bed_days + D.los.excess_top[1].bed_days)}`, `excess bed-days at ${D.los.excess_top[0].hospital} and ${D.los.excess_top[1].hospital} vs specialty benchmark ≈ ${Math.round((D.los.excess_top[0].bed_days + D.los.excess_top[1].bed_days) / 365)} beds`],
    [pct(1 - D.stranded.weekend_ratio), "fewer discharges per weekend day than per weekday"],
    [`${D.stranded.monday_surge.toFixed(2)}×`, "Monday catch-up vs the Tue–Fri average"],
  ];
  const cw = (W - 2 * M - 3 * 0.25) / 4;
  st.forEach(([v, l], i) => stat(s, M + i * (cw + 0.25), 5.75, cw, v, l, C.teal, 1.25));
  footer(s, "Query 03 · P90 via ROW_NUMBER()/COUNT() nearest rank (portable to SQLite) · Query 04 · stranded ≥7 days, super-stranded ≥21 days, PERCENT_RANK()");
  s.addNotes("P90 is roughly twice the mean in every specialty — the long tail, not the typical stay, drives bed demand. Excess bed-days are not case-mix adjusted; teaching hospitals take more complex patients, so treat this as where to look, not a verdict.");
}

// =====================================================================================
// 6. ED waits
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 6, "Emergency department · queries 05–06");
  title(s, `Harbourview's redesign moved its ED from ${D.ed.hbv_pre >= 0 ? "+" : "−"}${pct(Math.abs(D.ed.hbv_pre))} to −${pct(Math.abs(D.ed.hbv_post))} vs the network wait`,
    "Left: door-to-provider minutes, 4-week moving average (HBV rapid-assessment model live from 1 June) · right: share within 4 hours");
  s.addChart(pres.charts.LINE, [
    { name: "Harbourview (HBV)", labels: D.ed.labels, values: D.ed.hbv_ma },
    { name: "Network average", labels: D.ed.labels, values: D.ed.network_ma },
  ], axisOpts({
    x: M, y: 2.1, w: 7.4, h: 4.5, chartColors: [C.teal, C.context], lineSize: 2.5, lineDataSymbol: "none",
    valAxisMinVal: 20, valAxisMaxVal: 90, valAxisMajorUnit: 10, catAxisLabelFrequency: 8,
    showLegend: true, legendPos: "b",
  }));
  s.addChart(pres.charts.BAR, [
    { name: "Within 4 hours (%)", labels: D.ed.within4h_codes, values: D.ed.within4h },
  ], axisOpts({
    x: M + 7.7, y: 2.1, w: W - 2 * M - 7.7, h: 4.5, barDir: "bar", barGapWidthPct: 35, chartColors: [C.teal],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 9, dataLabelColor: C.ink,
    dataLabelFormatCode: "0.0", valAxisMinVal: 60, valAxisMaxVal: 95, valAxisHidden: true,
    valGridLine: { style: "none" }, showLegend: false, catAxisLabelFontSize: 9,
  }));
  footer(s, `Query 05 · 4-week AVG() OVER, LAG() week-on-week, FIRST_VALUE() baseline · Query 06 · waits for triage 3–5 peak at ${String(D.ed.worst_hour).padStart(2, "0")}:00, hours after arrivals plateau`);
  s.addNotes("Comparing Harbourview with the network week by week controls for the seasonal swing every ED shares. Before June it ran about 4% slower than the network; after the rapid-assessment model it ran about 23% faster. The three hospitals below the 78% four-hour standard are also the three fullest inpatient sites.");
}

// =====================================================================================
// 7. Exit block & bottlenecks
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 7, "Capacity bottlenecks · query 09");
  title(s, "Full wards back up into the ED: boarding is 10× longer at 95%+ occupancy",
    "Left: median ED boarding (decision to admit → departure) by same-day hospital occupancy · right: tightest pinch points");
  s.addChart(pres.charts.BAR, [
    { name: "Median boarding (min)", labels: D.bottleneck.band_labels, values: D.bottleneck.band_boarding },
  ], axisOpts({
    x: M, y: 2.1, w: 5.2, h: 4.5, barDir: "col", barGapWidthPct: 40, chartColors: [C.teal],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: C.ink,
    dataLabelFormatCode: "0\" min\"", valAxisHidden: true, valGridLine: { style: "none" }, showLegend: false,
    catAxisTitle: "Hospital inpatient occupancy that day", showCatAxisTitle: true, catAxisTitleColor: C.muted,
    catAxisTitleFontSize: 11,
  }));
  const hdr = ["Ward", "Occupancy", "Days ≥95%", "Longest run", "ED boarders >4h", "Trolley waits >12h"];
  const head = hdr.map((t) => ({ text: t, options: { bold: true, color: C.white, fill: { color: C.deep }, fontSize: 11 } }));
  const body = D.bottleneck.rows.map((r) => [
    { text: `${r.hospital} · ${r.dept}`, options: { bold: true } },
    { text: pct(r.occ) }, { text: String(r.critical_days) }, { text: `${r.longest} days` },
    { text: pct(r.board4h, 1) }, { text: String(r.trolley12) },
  ]);
  s.addTable([head, ...body], {
    x: M + 5.6, y: 2.2, w: W - 2 * M - 5.6, colW: [1.35, 1.0, 0.95, 1.05, 1.2, 1.2],
    fontFace: FONT, fontSize: 12, color: C.ink, border: { type: "solid", pt: 0.75, color: C.grid },
    fill: { color: C.white }, rowH: 0.46, valign: "middle", align: "center",
  });
  s.addText("Ranked by bottleneck score = share of days at ≥95% × (1 + share of ED boarders waiting over 4 hours). Longest run found with gaps-and-islands (day number − ROW_NUMBER()).", {
    x: M + 5.6, y: 5.6, w: W - 2 * M - 5.6, h: 0.8, fontFace: FONT, fontSize: 12, color: C.muted, margin: 0, isTextBox: true,
  });
  footer(s, "Query 09 · critical-occupancy episodes via gaps-and-islands, DENSE_RANK() bottleneck order · boarding joined from er_visits to the admitting ward");
  s.addNotes("Four of the six tightest pinch points are Medicine wards. Every point of hospital occupancy above 90% adds sharply to boarding, which is why ED performance cannot be fixed inside the ED alone.");
}

// =====================================================================================
// 8. Readmissions
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 8, "Readmissions · queries 07–08");
  title(s, `${pct(D.readmit.network, 1)} return as an emergency within 30 days — and the risk is predictable`,
    "Left: 30-day unplanned readmission rate by discharging hospital · right: highest-risk groups (relative risk vs network)");
  s.addChart(pres.charts.BAR, [
    { name: "30-day readmission rate (%)", labels: D.readmit.codes, values: D.readmit.rates },
  ], axisOpts({
    x: M, y: 2.1, w: 5.6, h: 4.6, barDir: "bar", barGapWidthPct: 35, chartColors: [C.teal],
    catAxisOrientation: "maxMin", showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 9,
    dataLabelColor: C.ink, dataLabelFormatCode: "0.0\"%\"", valAxisHidden: true, valAxisMinVal: 0,
    valGridLine: { style: "none" }, showLegend: false, catAxisLabelFontSize: 9,
  }));
  const x0 = M + 6.0, w0 = W - M - x0;
  D.readmit.drivers.forEach((d, i) => {
    const y = 2.1 + i * 0.56;
    const barW = (w0 - 3.6) * (d.rr / 2.5);
    s.addText(d.level, { x: x0, y, w: 2.8, h: 0.5, fontFace: FONT, fontSize: 13, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x0 + 2.9, y: y + 0.1, w: barW, h: 0.3, fill: { color: C.teal }, line: { color: C.teal }, rectRadius: 0.05 });
    s.addText(`${d.rr.toFixed(2)}×`, { x: x0 + 2.95 + barW, y, w: 0.8, h: 0.5, fontFace: FONT, fontSize: 13, bold: true, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
  });
  stat(s, x0, 5.55, w0, pct(D.readmit.elsewhere), "of readmissions land at a different hospital — invisible to single-site reporting", C.teal, 1.2);
  footer(s, "Query 07 · LEAD() over each patient's admissions across all hospitals · Query 08 · relative risk = level rate ÷ overall rate via window SUM()");
  s.addNotes("Community hospitals have the highest rates and teaching hospitals the lowest. Self-discharge, heart failure, COPD and hip fracture are the obvious targets for transitional-care calls, virtual wards and early follow-up clinics.");
}

// =====================================================================================
// 9. Staffing scorecard
// =====================================================================================
{
  const s = pres.addSlide();
  tag(s, 9, "Staffing & scorecard · query 10");
  title(s, "The fullest hospitals are the most stretched — rosters don't flex",
    "Hospital operations scorecard: five KPIs ranked across 15 hospitals, NTILE(3) tiers");
  const card = path.join(ROOT, "charts", "10_scorecard.png");
  // crop the notebook's title line; keep its colour key
  const full = 5.05, band = full * 0.06, iw = full / pngRatio(card);
  s.addImage({ path: card, x: M, y: 2.05, w: iw, h: full - band, sizing: { type: "crop", x: 0, y: band, w: iw, h: full - band } });
  const x = M + iw + 0.35, w = W - M - x;
  stat(s, x, 2.15, w, D.scorecard.corr_occ_breach.toFixed(2), "correlation between occupancy and night shifts over safe-staffing ratio", C.teal);
  stat(s, x, 3.7, w, pct(D.scorecard.sdn_absence, 1), `nurse absence at ${D.scorecard.max_absence_code} after second-half attrition — highest in the network`, C.red);
  stat(s, x, 5.25, w, D.scorecard.bottom.join(" · "), "bottom tier: high occupancy, long stays, ED below standard", C.red);
  footer(s, "Query 10 · night-shift patients per nurse = midnight census ÷ nurses on duty · RANK() per KPI, mean rank, NTILE(3)");
  s.addNotes("Rosters are built for planned occupancy, so every point of occupancy above plan lands on the same number of nurses. The scorecard ranks occupancy, ALOS, ED four-hour rate, readmission and staffing breaches; top tier: EFG, TMS, MRC.");
}

// =====================================================================================
// 10. Recommendations
// =====================================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.deep };
  tag(s, 10, "Recommendations", true);
  title(s, "Five moves to release beds and protect the front door", null, true);
  const recs = [
    ["Plan Medicine capacity to demand, not the calendar", "Hold winter escalation beds until the census falls below 90% instead of a fixed 31 March close; flex summer slack from Maternity and Paediatrics."],
    ["Make discharge a seven-day service", "Weekend discharge teams and criteria-led discharge to lift the weekend ratio from 0.63 towards 0.85 and flatten the Monday surge."],
    ["Run long-stay reviews where the excess sits", "Weekly 7+ day reviews at QET and SAU target ~25 beds of excess stay against specialty benchmarks."],
    ["Scale Harbourview's rapid-assessment model", "Pilot at the three hospitals below the 78% four-hour standard; track door-to-provider weekly against the network, not the prior month."],
    ["Target transitional care and staff to the census", "Follow-up within 72 hours for heart failure, COPD, hip fracture and self-discharge; report readmissions network-wide; set rosters from forecast census."],
  ];
  recs.forEach(([h, t], i) => {
    const y = 1.95 + i * 0.98;
    s.addShape(pres.shapes.OVAL, { x: M, y: y + 0.05, w: 0.5, h: 0.5, fill: { color: C.teal }, line: { color: C.teal } });
    s.addText(String(i + 1), { x: M, y: y + 0.05, w: 0.5, h: 0.5, fontFace: FONT, fontSize: 16, bold: true, color: C.white, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText(h, { x: M + 0.75, y, w: 11.3, h: 0.38, fontFace: FONT, fontSize: 17, bold: true, color: C.white, margin: 0, isTextBox: true });
    s.addText(t, { x: M + 0.75, y: y + 0.38, w: 11.3, h: 0.5, fontFace: FONT, fontSize: 13, color: C.tealLight, margin: 0, valign: "top", isTextBox: true });
  });
  footer(s, "Next steps: case-mix adjusted LOS (expected LOS by diagnosis and age), daily census forecasting, and a live version of this scorecard on the warehouse.", true);
  s.addNotes("Each recommendation maps to a query: 1 → queries 01/02, 2 → query 04, 3 → query 03, 4 → queries 05/06/09, 5 → queries 07/08/10.");
}

pres.writeFile({ fileName: OUT }).then(() => console.log("wrote", OUT));
