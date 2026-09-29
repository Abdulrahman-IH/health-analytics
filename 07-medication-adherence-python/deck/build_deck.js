// Builds the 10-slide deck from outputs/summary_metrics.json (written by the notebook).
// Usage (from the project folder):  npm install pptxgenjs react react-dom react-icons sharp
//                                   node deck/build_deck.js
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const ROOT = path.join(__dirname, "..");
const M = JSON.parse(fs.readFileSync(path.join(ROOT, "outputs", "summary_metrics.json"), "utf8"));

// ---- Theme (same palette as the notebook charts) ----
const C = {
  dark: "0B2E33", teal: "009490", orange: "E26A2C", violet: "5B4BC4",
  ink: "1F2A30", muted: "5E6B70", grid: "E6E9EA", tint: "E3F4F3", white: "FFFFFF",
  tealLight: "7FD1CD", risk: ["F6C9A8", "EE9A68", "E26A2C", "A8441A"],
};
const HEAD = "Cambria", BODY = "Calibri";
const pct = (x, d = 0) => `${(x * 100).toFixed(d)}%`;
const pts = (x, d = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)} pts`;
const fmt = (n) => n.toLocaleString("en-US");

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size }));
  const buf = await sharp(Buffer.from(svg)).resize(size, size).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
  pres.title = "Medication Adherence & Digital Reminder Impact";
  pres.author = "Health Analytics Portfolio";

  const I = {
    pills: await icon(fa.FaPills, C.white), bell: await icon(fa.FaBell, C.white),
    chart: await icon(fa.FaChartLine, C.white), users: await icon(fa.FaUsers, C.white),
    balance: await icon(fa.FaBalanceScale, C.white), mobile: await icon(fa.FaMobileAlt, C.white),
    heart: await icon(fa.FaHeartbeat, C.white), bullseye: await icon(fa.FaBullseye, C.white),
    flask: await icon(fa.FaFlask, C.white), handshake: await icon(fa.FaHandsHelping, C.white),
    calendar: await icon(fa.FaCalendarCheck, C.white), userMd: await icon(fa.FaUserMd, C.white),
  };

  // Motif: white icon inside a teal circle
  const iconCircle = (s, img, x, y, d = 0.5, fill = C.teal) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill } });
    const p = d * 0.26;
    s.addImage({ data: img, x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p });
  };
  const title = (s, text, sub) => {
    s.addText(text, { x: 0.5, y: 0.3, w: 9, h: 0.6, fontFace: HEAD, fontSize: 25, bold: true, color: C.ink, margin: 0, fit: "shrink", isTextBox: true });
    if (sub) s.addText(sub, { x: 0.5, y: 0.88, w: 9, h: 0.35, fontFace: BODY, fontSize: 13, color: C.muted, margin: 0, isTextBox: true });
  };
  const card = (s, x, y, w, h, fill = C.tint) =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill }, rectRadius: 0.08 });
  const footer = (s, n) =>
    s.addText(`Synthetic data · 20,000 patients · 2025 measurement year   |   ${n}`, {
      x: 0.5, y: 5.25, w: 9, h: 0.25, fontFace: BODY, fontSize: 9, color: C.muted, align: "right", margin: 0, isTextBox: true });
  const axisBase = () => ({
    catAxisLabelColor: C.muted, valAxisLabelColor: C.muted, catAxisLabelFontFace: BODY, valAxisLabelFontFace: BODY,
    catAxisLabelFontSize: 10, valAxisLabelFontSize: 9, valGridLine: { color: C.grid, size: 0.75 },
    catGridLine: { style: "none" }, catAxisLineShow: false, valAxisLineShow: false,
    dataLabelColor: C.ink, dataLabelFontFace: BODY, dataLabelFontSize: 10,
  });

  const U = M.users, N = M.non_users, T = M.tests, W = M.iptw;

  // ---------- 1. Title ----------
  {
    const s = pres.addSlide(); s.background = { color: C.dark };
    iconCircle(s, I.pills, 0.6, 0.65, 0.75);
    iconCircle(s, I.bell, 1.5, 0.65, 0.75, C.orange);
    s.addText("Medication Adherence &\nDigital Reminder Impact", {
      x: 0.6, y: 1.65, w: 8.8, h: 1.5, fontFace: HEAD, fontSize: 38, bold: true, color: C.white, margin: 0, isTextBox: true });
    s.addText("How app reminder features change refill behaviour for patients with chronic conditions", {
      x: 0.6, y: 3.15, w: 8.5, h: 0.45, fontFace: BODY, fontSize: 16, italic: true, color: C.tealLight, margin: 0, isTextBox: true });
    const stats = [[fmt(M.n_patients), "patients"], [fmt(M.n_prescriptions), "prescriptions"],
                   [fmt(M.n_fills), "pharmacy fills"], [fmt(M.n_reminders), "reminder events"]];
    stats.forEach(([v, l], i) => {
      const x = 0.6 + i * 2.2;
      s.addText(v, { x, y: 4.05, w: 2.1, h: 0.5, fontFace: HEAD, fontSize: 24, bold: true, color: C.white, margin: 0, isTextBox: true });
      s.addText(l, { x, y: 4.55, w: 2.1, h: 0.3, fontFace: BODY, fontSize: 12, color: C.tealLight, margin: 0, isTextBox: true });
    });
    s.addNotes("Project 7 of the health analytics portfolio. The data are synthetic but structured like real pharmacy claims and app event logs.");
  }

  // ---------- 2. The adherence gap ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    title(s, "Four in ten patients miss the adherence bar", "Share of patients reaching PDC ≥ 80%, the CMS Star Ratings threshold");
    const big = [[pct(M.adherent_rate), "adherent overall\n(mean PDC ≥ 80%)"],
                 [pct(M.adherent_all_meds), "adherent on every\nmaintenance drug"],
                 [pct(M.mean_pdc), "mean proportion of\ndays covered"]];
    big.forEach(([v, l], i) => {
      const y = 1.45 + i * 1.22;
      card(s, 0.5, y, 3.3, 1.05);
      s.addText(v, { x: 0.7, y: y + 0.12, w: 1.5, h: 0.8, fontFace: HEAD, fontSize: 32, bold: true, color: C.teal, margin: 0, valign: "middle", isTextBox: true });
      s.addText(l, { x: 2.15, y: y + 0.12, w: 1.6, h: 0.8, fontFace: BODY, fontSize: 12, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
    });
    const d = M.by_drug;
    s.addChart(pres.charts.BAR, [{ name: "Adherent", labels: d.map(r => r.drug_class), values: d.map(r => r.adherent) }], {
      x: 4.2, y: 1.35, w: 5.4, h: 3.8, barDir: "bar", chartColors: [C.teal], barGapWidthPct: 45,
      ...axisBase(), showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0%",
      valAxisMinVal: 0, valAxisMaxVal: 0.8, valAxisLabelFormatCode: "0%", valAxisHidden: true, valGridLine: { style: "none" },
      showTitle: true, title: "Adherent prescriptions by drug class", titleFontFace: BODY, titleFontSize: 12, titleColor: C.ink,
      showLegend: false,
    });
    footer(s, 2);
    s.addNotes("Statins and COPD inhalers are the weakest classes. Their benefit is invisible to the patient, or the side effects are felt.");
  }

  // ---------- 3. PDC vs MPR ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    title(s, "Measure with PDC, not MPR", "MPR counts early refills twice and overstates adherence");
    const cols = [
      ["PDC · proportion of days covered", C.teal, I.calendar,
       ["Days with drug on hand ÷ days in period", "Early refills shifted forward, never double-counted", "Capped at 100% by construction",
        `Mean ${pct(M.mean_pdc, 1)} in this cohort`]],
      ["MPR · medication possession ratio", C.orange, I.pills,
       ["Days' supply dispensed ÷ days in period", "Overlapping fills counted twice", "Can exceed 100%",
        `Mean ${pct(M.mean_mpr_raw, 1)}; ${pct(M.mpr_pdc_misclassified, 1)} wrongly look adherent`]],
    ];
    cols.forEach(([h, col, ic, items], i) => {
      const x = 0.5, y = 1.45 + i * 1.9;
      card(s, x, y, 4.3, 1.7);
      iconCircle(s, ic, x + 0.2, y + 0.2, 0.45, col);
      s.addText(h, { x: x + 0.8, y: y + 0.2, w: 3.4, h: 0.45, fontFace: BODY, fontSize: 14, bold: true, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
      s.addText(items.map((t, k) => ({ text: t, options: { bullet: { indent: 10 }, breakLine: k < items.length - 1 } })), {
        x: x + 0.8, y: y + 0.68, w: 3.4, h: 0.95, fontFace: BODY, fontSize: 11, color: C.ink, margin: 0, paraSpaceAfter: 2, valign: "top", isTextBox: true });
    });
    const H = M.pdc_hist, tot = (a) => a.reduce((p, q) => p + q, 0);
    const nu = H["Non-users"], us = H["App reminder users"];
    s.addChart(pres.charts.BAR, [
      { name: "Non-users", labels: H.bins, values: nu.map(v => v / tot(nu)) },
      { name: "App reminder users", labels: H.bins, values: us.map(v => v / tot(us)) },
    ], {
      x: 5.1, y: 1.35, w: 4.5, h: 3.8, barDir: "col", barGrouping: "clustered", barGapWidthPct: 40,
      chartColors: [C.orange, C.teal], ...axisBase(), catAxisLabelFontSize: 8, catAxisLabelRotate: -45,
      valAxisLabelFormatCode: "0%", valAxisMinVal: 0,
      showLegend: true, legendPos: "t", legendFontFace: BODY, legendFontSize: 10, legendColor: C.ink,
      showTitle: true, title: "Patient PDC distribution", titleFontFace: BODY, titleFontSize: 12, titleColor: C.ink,
    });
    footer(s, 3);
  }

  // ---------- 4. Users vs non-users ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    title(s, `App reminder users: ${pts(T.rd)} higher adherence`, "Unadjusted comparison with statistical tests");
    card(s, 0.5, 1.45, 1.9, 1.5); card(s, 2.55, 1.45, 1.9, 1.5);
    s.addText(pct(U.adherent), { x: 0.5, y: 1.55, w: 1.9, h: 0.8, fontFace: HEAD, fontSize: 36, bold: true, color: C.teal, align: "center", margin: 0, isTextBox: true });
    s.addText(`App users adherent\n(n=${fmt(U.n)})`, { x: 0.5, y: 2.3, w: 1.9, h: 0.55, fontFace: BODY, fontSize: 11, color: C.ink, align: "center", margin: 0, isTextBox: true });
    s.addText(pct(N.adherent), { x: 2.55, y: 1.55, w: 1.9, h: 0.8, fontFace: HEAD, fontSize: 36, bold: true, color: C.orange, align: "center", margin: 0, isTextBox: true });
    s.addText(`Non-users adherent\n(n=${fmt(N.n)})`, { x: 2.55, y: 2.3, w: 1.9, h: 0.55, fontFace: BODY, fontSize: 11, color: C.ink, align: "center", margin: 0, isTextBox: true });
    const rows = [
      ["Chi-square, adherent rate", `χ² = ${T.chi2.toFixed(0)}, p < 0.001`],
      ["Welch t-test, mean PDC", `t = ${T.welch_t.toFixed(1)}, p < 0.001`],
      ["Mann-Whitney U, PDC", `p < 0.001, r = ${T.rank_biserial.toFixed(2)}`],
      ["Effect size", `Cohen's d = ${T.cohens_d.toFixed(2)}, RR = ${T.rr.toFixed(2)}`],
      ["Risk difference (95% CI)", `${pts(T.rd)} (${pts(T.rd_ci[0])} to ${pts(T.rd_ci[1])})`],
    ];
    s.addTable(rows.map(([a, b]) => [
      { text: a, options: { fontFace: BODY, fontSize: 10.5, color: C.muted } },
      { text: b, options: { fontFace: BODY, fontSize: 10.5, color: C.ink, bold: true } }]), {
      x: 0.5, y: 3.15, w: 3.95, colW: [1.6, 2.35], rowH: 0.36, border: { type: "solid", pt: 0.75, color: C.grid }, margin: 0.04,
    });
    const bc = M.by_condition;
    s.addChart(pres.charts.BAR, [
      { name: "Non-users", labels: bc.map(r => r.condition), values: bc.map(r => r.non_users) },
      { name: "App reminder users", labels: bc.map(r => r.condition), values: bc.map(r => r.users) },
    ], {
      x: 4.8, y: 1.35, w: 4.8, h: 3.8, barDir: "col", barGrouping: "clustered", barGapWidthPct: 50,
      chartColors: [C.orange, C.teal], ...axisBase(), catAxisLabelFontSize: 9,
      showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0%", dataLabelFontSize: 9,
      valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: "0%",
      showLegend: true, legendPos: "t", legendFontFace: BODY, legendFontSize: 10, legendColor: C.ink,
      showTitle: true, title: "Share adherent, by condition", titleFontFace: BODY, titleFontSize: 12, titleColor: C.ink,
    });
    footer(s, 4);
  }

  // ---------- 5. App or user? ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    const shrink = 1 - W.rd / T.rd;
    title(s, "Most of the gap survives adjustment", `Propensity (overlap) weighting shrinks the effect by ${pct(shrink)}, but it stays significant`);
    s.addChart(pres.charts.BAR, [{ name: "Difference", labels: ["Unadjusted", "Adjusted"], values: [T.rd, W.rd] }], {
      x: 0.4, y: 1.35, w: 4.6, h: 3.7, barDir: "col", chartColors: [C.orange, C.teal], barGapWidthPct: 70,
      ...axisBase(), showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "+0.0%", dataLabelFontSize: 14, dataLabelFontBold: true,
      valAxisMinVal: 0, valAxisMaxVal: 0.2, valAxisLabelFormatCode: "0%", showLegend: false,
      showTitle: true, title: "Adherence gain, users vs non-users (pts)", titleFontFace: BODY, titleFontSize: 12, titleColor: C.ink,
    });
    const items = [
      [I.users, "Users self-select", `App users are younger and more digitally literate (max SMD ${W.max_smd_before.toFixed(2)}), and literacy predicts adherence on its own.`],
      [I.balance, "Overlap weighting", `Re-weighting on 19 baseline covariates balances the groups (max SMD ${W.max_smd_after.toFixed(3)}).`],
      [I.chart, "Adjusted effect", `${pts(W.rd)} adherent (95% CI ${pts(W.rd_ci[0])} to ${pts(W.rd_ci[1])}); mean PDC ${pts(W.pdc_diff)}.`],
    ];
    items.forEach(([ic, h, t], i) => {
      const y = 1.45 + i * 1.22;
      iconCircle(s, ic, 5.35, y, 0.5, i === 2 ? C.teal : C.violet);
      s.addText(h, { x: 6.05, y: y - 0.02, w: 3.5, h: 0.32, fontFace: BODY, fontSize: 14, bold: true, color: C.ink, margin: 0, isTextBox: true });
      s.addText(t, { x: 6.05, y: y + 0.3, w: 3.5, h: 0.75, fontFace: BODY, fontSize: 11, color: C.ink, margin: 0, valign: "top", isTextBox: true });
    });
    footer(s, 5);
    s.addNotes("Weighting only removes observed confounding. Unmeasured motivation could remain, hence the recommendation to run a randomised rollout.");
  }

  // ---------- 6. Engagement ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    title(s, "Engagement drives the effect, then fades", "Signing up is not enough: patients have to act on the reminders");
    const dr = M.dose_response;
    s.addChart(pres.charts.BAR, [{ name: "Adherent", labels: dr.bands, values: dr.adherent }], {
      x: 0.4, y: 1.35, w: 4.6, h: 3.4, barDir: "col", chartColors: [C.teal], barGapWidthPct: 45,
      ...axisBase(), showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0%",
      valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: "0%", showLegend: false,
      showTitle: true, title: "Share adherent by engagement quintile", titleFontFace: BODY, titleFontSize: 12, titleColor: C.ink,
    });
    s.addText(`Non-users: ${pct(N.adherent)} adherent. Top-quintile users engage with ${pct(dr.engagement[4])} of reminders, bottom-quintile with ${pct(dr.engagement[0])}.`, {
      x: 0.5, y: 4.75, w: 4.4, h: 0.45, fontFace: BODY, fontSize: 10, color: C.muted, margin: 0, isTextBox: true });
    const f = M.fatigue;
    s.addChart(pres.charts.LINE, [
      { name: "Opened or acted", labels: f.months, values: f.engaged },
      { name: "Refill requested", labels: f.months, values: f.refill },
    ], {
      x: 5.1, y: 1.35, w: 4.5, h: 3.4, chartColors: [C.teal, C.violet], lineSize: 2, lineDataSymbol: "circle", lineDataSymbolSize: 6,
      ...axisBase(), valAxisMinVal: 0, valAxisMaxVal: 0.8, valAxisLabelFormatCode: "0%",
      showLegend: true, legendPos: "t", legendFontFace: BODY, legendFontSize: 10, legendColor: C.ink,
      showTitle: true, title: "Monthly engagement with refill reminders", titleFontFace: BODY, titleFontSize: 12, titleColor: C.ink,
    });
    s.addText(`Engagement drops from ${pct(f.engaged[0])} to ${pct(f.engaged[f.engaged.length - 1])} between Feb and Dec: reminder fatigue.`, {
      x: 5.2, y: 4.75, w: 4.4, h: 0.45, fontFace: BODY, fontSize: 10, color: C.muted, margin: 0, isTextBox: true });
    footer(s, 6);
  }

  // ---------- 7. Features ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    title(s, "What reminders do beats how they arrive", "Adjusted odds ratios for adherence among app users (95% CI)");
    const feats = M.features;
    const icons = [I.mobile, I.bell, I.handshake];
    feats.forEach((r, i) => {
      const x = 0.5 + i * 3.1, y = 1.45, sig = r.ci_low > 1;
      card(s, x, y, 2.85, 2.35, sig ? C.tint : "F2F3F3");
      iconCircle(s, icons[i], x + 0.2, y + 0.2, 0.5, sig ? C.teal : C.muted);
      s.addText(r.feature, { x: x + 0.85, y: y + 0.2, w: 1.9, h: 0.5, fontFace: BODY, fontSize: 13, bold: true, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
      s.addText(`OR ${r.odds_ratio.toFixed(2)}`, { x: x + 0.2, y: y + 0.85, w: 2.5, h: 0.6, fontFace: HEAD, fontSize: 28, bold: true, color: sig ? C.teal : C.muted, margin: 0, isTextBox: true });
      s.addText(`95% CI ${r.ci_low.toFixed(2)}–${r.ci_high.toFixed(2)}${sig ? "" : " · not significant"}`, {
        x: x + 0.2, y: y + 1.45, w: 2.5, h: 0.3, fontFace: BODY, fontSize: 10.5, color: C.muted, margin: 0, isTextBox: true });
      s.addText(`${pct(r.adherent_on)} adherent with feature vs ${pct(r.adherent_off)} without`, {
        x: x + 0.2, y: y + 1.75, w: 2.5, h: 0.5, fontFace: BODY, fontSize: 10.5, color: C.ink, margin: 0, isTextBox: true });
    });
    // funnel as a single stacked bar
    const order = ["Refill requested", "Opened", "Snoozed", "Dismissed", "Ignored"];
    const fcol = [C.teal, C.tealLight, C.violet, "B3AEE0", "C9CFD1"];
    s.addChart(pres.charts.BAR, order.map((k) => ({ name: k, labels: ["Reminder outcome"], values: [M.funnel[k]] })), {
      x: 0.4, y: 3.95, w: 9.2, h: 1.25, barDir: "bar", barGrouping: "percentStacked", chartColors: fcol, barGapWidthPct: 20,
      ...axisBase(), catAxisHidden: true, valAxisHidden: true, valGridLine: { style: "none" },
      showValue: true, dataLabelPosition: "ctr", dataLabelFormatCode: "0%", dataLabelColor: C.ink, dataLabelFontSize: 10,
      showLegend: true, legendPos: "t", legendFontFace: BODY, legendFontSize: 10, legendColor: C.ink,
    });
    footer(s, 7);
  }

  // ---------- 8. Segmentation ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    title(s, "The highest-risk patients enrol the least", "Model-predicted risk tiers: observed non-adherence and app enrolment");
    const t = M.tiers;
    s.addChart(pres.charts.BAR, [{ name: "Non-adherent", labels: t.map(r => `${r.risk_tier}\n${fmt(r.patients)} pts`), values: t.map(r => r.observed_non_adherent) }], {
      x: 0.4, y: 1.35, w: 5.2, h: 3.8, barDir: "col", chartColors: C.risk, barGapWidthPct: 40,
      ...axisBase(), showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0%", dataLabelFontBold: true,
      valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: "0%", showLegend: false,
      showTitle: true, title: "Observed non-adherence by risk tier", titleFontFace: BODY, titleFontSize: 12, titleColor: C.ink,
    });
    // enrolment stat cards
    s.addText("App enrolment in each tier", { x: 5.95, y: 1.4, w: 3.6, h: 0.35, fontFace: BODY, fontSize: 13, bold: true, color: C.ink, margin: 0, isTextBox: true });
    t.forEach((r, i) => {
      const y = 1.85 + i * 0.8;
      card(s, 5.95, y, 3.6, 0.68, C.tint);
      s.addShape(pres.shapes.OVAL, { x: 6.1, y: y + 0.19, w: 0.3, h: 0.3, fill: { color: C.risk[i] }, line: { color: C.risk[i] } });
      s.addText(r.risk_tier, { x: 6.55, y, w: 1.3, h: 0.68, fontFace: BODY, fontSize: 12, bold: true, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
      s.addText(pct(r.app_user), { x: 7.8, y, w: 0.8, h: 0.68, fontFace: HEAD, fontSize: 20, bold: true, color: C.teal, margin: 0, valign: "middle", isTextBox: true });
      s.addText(`${fmt(r.not_enrolled_n)} not enrolled`, { x: 8.55, y, w: 1.0, h: 0.68, fontFace: BODY, fontSize: 9.5, color: C.muted, margin: 0, valign: "middle", isTextBox: true });
    });
    footer(s, 8);
    s.addNotes("Tiers are capacity-based: top 10% Very high, next 20% High, next 30% Moderate, bottom 40% Low, using out-of-fold model scores.");
  }

  // ---------- 9. Model ----------
  {
    const s = pres.addSlide(); s.background = { color: C.white };
    const lr = M.model["Logistic regression"], gb = M.model["Gradient boosting"];
    title(s, "Non-adherence can be predicted on day one", "Logistic regression on baseline features only (no refill history, so no leakage)");
    const st = [[lr.test_auc.toFixed(2), "hold-out ROC AUC"], [`${lr.cv_auc_mean.toFixed(2)} ± ${lr.cv_auc_sd.toFixed(2)}`, "5-fold CV AUC"],
                [gb.test_auc.toFixed(2), "gradient boosting AUC (no gain)"], [lr.brier.toFixed(3), "Brier score, well calibrated"]];
    st.forEach(([v, l], i) => {
      const y = 1.4 + i * 0.93;
      card(s, 0.5, y, 3.2, 0.8);
      s.addText(v, { x: 0.65, y, w: 1.55, h: 0.8, fontFace: HEAD, fontSize: i === 1 ? 17 : 22, bold: true, color: i === 2 ? C.violet : C.teal, margin: 0, valign: "middle", isTextBox: true });
      s.addText(l, { x: 2.2, y, w: 1.45, h: 0.8, fontFace: BODY, fontSize: 10.5, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
    });
    const dv = M.drivers.slice(0, 8).reverse();
    s.addChart(pres.charts.BAR, [{ name: "Change in odds", labels: dv.map(r => r.feature), values: dv.map(r => r.odds_ratio_per_sd - 1) }], {
      x: 4.0, y: 1.35, w: 5.6, h: 3.85, barDir: "bar", chartColors: dv.map(r => (r.odds_ratio_per_sd > 1 ? C.orange : C.teal)), barGapWidthPct: 40,
      ...axisBase(), catAxisLabelFontSize: 9.5, showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "+0%;-0%",
      valAxisMinVal: -1.0, valAxisMaxVal: 0.4, valAxisLabelFormatCode: "+0%;-0%", catAxisLabelPos: "low", showLegend: false,
      showTitle: true, title: "Change in odds of non-adherence per 1 SD (orange = raises risk)", titleFontFace: BODY, titleFontSize: 11, titleColor: C.ink,
    });
    footer(s, 9);
  }

  // ---------- 10. Recommendations ----------
  {
    const s = pres.addSlide(); s.background = { color: C.dark };
    s.addText("From insight to product roadmap", { x: 0.6, y: 0.35, w: 8.8, h: 0.6, fontFace: HEAD, fontSize: 30, bold: true, color: C.white, margin: 0, isTextBox: true });
    const recs = [
      [I.bullseye, "Target enrolment by risk", `Assisted onboarding for the ${fmt(M.tiers[3].not_enrolled_n + M.tiers[2].not_enrolled_n)} High / Very high patients not enrolled, via pharmacist or care manager.`],
      [I.bell, "Default-on dose + caregiver alerts", "Both features show significant, independent lift. Make them opt-out at onboarding."],
      [I.calendar, "Fight reminder fatigue", "Rotate content, adapt timing, and escalate to a human when reminders go ignored."],
      [I.pills, "Pair nudges with 90-day supply", "The strongest protective factor in the model. Offer in-app switching and copay support."],
      [I.flask, "Prove causality", "Run a randomised or stepped-wedge rollout to confirm the adjusted effect."],
      [I.heart, "Track PDC as the north-star", "Report PDC ≥ 80% by tier monthly, aligned with Star Ratings measures."],
    ];
    recs.forEach(([ic, h, t], i) => {
      const col = i % 2, row = Math.floor(i / 2);
      const x = 0.6 + col * 4.5, y = 1.25 + row * 1.3;
      iconCircle(s, ic, x, y, 0.55, i % 2 ? C.orange : C.teal);
      s.addText(h, { x: x + 0.75, y: y - 0.02, w: 3.5, h: 0.35, fontFace: BODY, fontSize: 14, bold: true, color: C.white, margin: 0, isTextBox: true });
      s.addText(t, { x: x + 0.75, y: y + 0.36, w: 3.5, h: 0.75, fontFace: BODY, fontSize: 11, color: "CFE3E3", margin: 0, valign: "top", isTextBox: true });
    });
    s.addText(`Adjusted impact: ${pts(W.rd)} adherent patients. Across 10,000 non-users, that is ~${fmt(Math.round(W.rd * 10000 / 10) * 10)} more patients reaching PDC ≥ 80%.`, {
      x: 0.6, y: 5.0, w: 8.8, h: 0.35, fontFace: BODY, fontSize: 12, italic: true, color: C.tealLight, margin: 0, isTextBox: true });
  }

  const out = path.join(ROOT, "medication_adherence_deck.pptx");
  await pres.writeFile({ fileName: out });
  console.log("wrote", out);
})();
