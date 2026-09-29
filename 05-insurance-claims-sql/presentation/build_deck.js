// Builds presentation/insurance_claims_fraud_signals.pptx from the query results in data/results/.
// Run after the notebook:  node presentation/build_deck.js   (requires `npm install pptxgenjs`)
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const RES = path.join(ROOT, "data", "results");

// ---------- tiny CSV reader (handles quoted fields) ----------
function readCsv(name) {
  const text = fs.readFileSync(path.join(RES, name + ".csv"), "utf8").trim();
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const out = []; let cur = ""; let q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else q = !q; }
      else if (ch === "," && !q) { out.push(cur); cur = ""; }
      else cur += ch;
    }
    out.push(cur); rows.push(out);
  }
  const [head, ...body] = rows;
  return body.map(r => Object.fromEntries(head.map((h, i) => [h, isNaN(r[i]) || r[i] === "" ? r[i] : Number(r[i])])));
}

const kpi = readCsv("00_kpis")[0];
const reasons = readCsv("02_rejection_reasons");
const spec = readCsv("03_rejection_reason_by_specialty");
const dx = readCsv("04_avg_cost_by_diagnosis");
const tat = readCsv("05_approval_turnaround");
const tatTrend = readCsv("06_turnaround_trend_and_backlog");
const deciles = readCsv("08_cost_concentration");
const hcm = readCsv("07_high_cost_members");
const dups = readCsv("09_duplicate_claims");
const outliers = readCsv("10_billed_amount_outliers");
const risk = readCsv("11_provider_fraud_risk_score");
const trend = readCsv("12_mom_cost_trends");
const provRej = readCsv("01_rejection_rate_by_provider");

const SHORT_REASON = { R01: "Duplicate claim", R02: "Missing prior auth", R03: "Not covered by plan", R04: "Member not eligible",
  R05: "Out-of-network (no OON benefit)", R06: "Coding mismatch / invalid code", R07: "Missing / incomplete info",
  R08: "Timely filing exceeded", R09: "Not medically necessary", R10: "Exceeds reasonable & customary" };
const SHORT_DX = { "O80": "Normal delivery", "K80.20": "Gallstones", "C50.911": "Breast cancer", "S82.201A": "Tibia fracture",
  "M17.11": "Knee osteoarthritis", "I25.10": "Coronary artery disease", "S06.0X0A": "Concussion", "C34.90": "Lung cancer",
  "R07.9": "Chest pain", "K21.9": "GERD", "J18.9": "Pneumonia", "I48.91": "Atrial fibrillation", "M54.50": "Low back pain",
  "I10": "Hypertension", "E78.5": "Hyperlipidemia", "E11.9": "Type 2 diabetes", "F41.1": "Anxiety", "F32.9": "Depression" };
const dxName = r => SHORT_DX[r.diagnosis_code] || r.description.split(",")[0];
const fmtM = v => "$" + (v / 1e6).toFixed(1) + "M";
const fmtK = v => "$" + Math.round(v / 1e3).toLocaleString("en-US") + "K";
const fmtN = v => Math.round(v).toLocaleString("en-US");
const sum = (a, f) => a.reduce((s, r) => s + f(r), 0);

// ---------- theme ----------
const C = {
  navy: "0B1F3A", card: "13294A", card2: "1B3560", teal: "14B8A6", tealDark: "0F9D8F",
  white: "FFFFFF", ink: "E6EDF5", muted: "A7B4C8", grid: "24406A", coral: "F4845F", gold: "E3B04B",
};
const FONT = "Calibri", HFONT = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
pres.title = "Health Insurance Claims & Fraud Signals Analysis";
pres.defineSlideMaster({ title: "DARK", background: { color: C.navy } });

let slideNo = 0;
function base(tag, title) {
  const s = pres.addSlide({ masterName: "DARK" });
  slideNo++;
  s.addText(tag.toUpperCase(), { x: 0.5, y: 0.32, w: 7, h: 0.28, fontFace: FONT, fontSize: 11, bold: true,
    color: C.teal, charSpacing: 3, margin: 0, isTextBox: true });
  s.addText(title, { x: 0.5, y: 0.62, w: 9, h: 0.55, fontFace: HFONT, fontSize: 24, bold: true, color: C.white,
    margin: 0, valign: "top", fit: "shrink", isTextBox: true });
  s.addText(String(slideNo), { x: 9.1, y: 5.2, w: 0.4, h: 0.25, fontFace: FONT, fontSize: 9, color: C.muted,
    align: "right", margin: 0, isTextBox: true });
  return s;
}
function card(s, x, y, w, h, fill = C.card) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill }, rectRadius: 0.08 });
}
function stat(s, x, y, w, value, label, color = C.teal, h = 1.05, size = 26) {
  card(s, x, y, w, h);
  s.addText(value, { x: x + 0.18, y: y + 0.12, w: w - 0.36, h: 0.5, fontFace: HFONT, fontSize: size, bold: true,
    color, margin: 0, isTextBox: true });
  s.addText(label, { x: x + 0.18, y: y + 0.6, w: w - 0.36, h: h - 0.68, fontFace: FONT, fontSize: 10.5,
    color: C.muted, margin: 0, valign: "top", isTextBox: true });
}
function bullets(s, items, x, y, w, h, size = 12.5) {
  s.addText(items.map((t, i) => {
    const parts = Array.isArray(t) ? t : [null, t];
    const runs = [];
    if (parts[0]) runs.push({ text: parts[0] + " ", options: { bold: true, color: C.white } });
    runs.push({ text: parts[1], options: { color: C.ink, breakLine: i < items.length - 1 } });
    runs[0].options.bullet = { code: "25A0" };
    runs[0].options.paraSpaceAfter = 8;
    return runs;
  }).flat(), { x, y, w, h, fontFace: FONT, fontSize: size, valign: "top", margin: 0, isTextBox: true });
}
function chartOpts(extra) {
  return Object.assign({
    catAxisLabelColor: C.muted, valAxisLabelColor: C.muted, catAxisLabelFontFace: FONT, valAxisLabelFontFace: FONT,
    catAxisLabelFontSize: 10, valAxisLabelFontSize: 9, valGridLine: { color: C.grid, size: 0.75 },
    catGridLine: { style: "none" }, catAxisLineShow: false, valAxisLineShow: false,
    dataLabelColor: C.white, dataLabelFontSize: 9, dataLabelFontFace: FONT, showLegend: false,
    titleColor: C.white, titleFontFace: FONT, titleFontSize: 12,
  }, extra);
}
function note(s, text) {
  s.addText(text, { x: 0.5, y: 5.2, w: 8.4, h: 0.25, fontFace: FONT, fontSize: 9, italic: true, color: C.muted,
    margin: 0, isTextBox: true });
}

// derived numbers
const rejected = sum(reasons, r => r.rejected_claims);
const avoidable = sum(reasons.filter(r => r.avoidability === "Avoidable"), r => r.rejected_claims);
const autoAppr = tat.find(r => r.claim_type === "Professional" && r.review_path.startsWith("Auto") && r.claim_status === "Approved");
const manAppr = tat.find(r => r.claim_type === "Professional" && r.review_path.startsWith("Manual") && r.claim_status === "Approved");
const flagged = risk.filter(r => r.red_flags >= 3);
const dupPaid = sum(dups.filter(r => r.dup_type !== "Same-day repeat service"), r => r.dollars_paid_on_duplicates);
const exact = dups.find(r => r.dup_type === "Exact duplicate");
const near = dups.find(r => r.dup_type === "Near duplicate");
const y25 = trend.filter(r => r.month.startsWith("2025"));
const yoyAvg = sum(y25, r => r.yoy_pmpm_change_pct) / y25.length;
const firstTat = tatTrend[0].avg_turnaround_days, lastTat = tatTrend[tatTrend.length - 1].avg_turnaround_days;

// ================= 1. Title =================
{
  const s = pres.addSlide({ masterName: "DARK" }); slideNo++;
  s.addShape(pres.shapes.OVAL, { x: 6.9, y: -1.2, w: 4.6, h: 4.6, fill: { color: C.tealDark, transparency: 82 }, line: { color: C.navy, transparency: 100 } });
  s.addShape(pres.shapes.OVAL, { x: 8.0, y: 2.6, w: 3.2, h: 3.2, fill: { color: C.teal, transparency: 88 }, line: { color: C.navy, transparency: 100 } });
  s.addText("PROJECT 05  ·  HEALTH INSURANCE ANALYTICS", { x: 0.6, y: 0.75, w: 7, h: 0.3, fontFace: FONT, fontSize: 11,
    bold: true, color: C.teal, charSpacing: 3, margin: 0, isTextBox: true });
  s.addText("Health Insurance Claims\n& Fraud Signals", { x: 0.6, y: 1.1, w: 8.0, h: 1.4, fontFace: HFONT, fontSize: 40,
    bold: true, color: C.white, margin: 0, valign: "top", isTextBox: true });
  s.addText("Payer efficiency, cost containment and claims integrity across two years of claims — SQL (SQLite) + Python",
    { x: 0.6, y: 2.6, w: 6.6, h: 0.6, fontFace: FONT, fontSize: 14, color: C.muted, margin: 0, isTextBox: true });
  const w = 2.0, gap = 0.2;
  [[fmtN(kpi.claims), "claims, Jan 2024 – Dec 2025"], [fmtM(kpi.billed), "billed charges"],
   [fmtM(kpi.approved), "approved (allowed) amount"], [kpi.rejected_pct.toFixed(1) + "%", "initial rejection rate"]]
    .forEach(([v, l], i) => stat(s, 0.6 + i * (w + gap), 3.75, w, v, l, C.teal, 1.05, 24));
  note(s, "Synthetic dataset — 10,000 members · 1,200 providers · 19,854 policies. Built for portfolio demonstration.");
}

// ================= 2. Data & approach =================
{
  const s = base("Data & approach", "A 7-table claims warehouse and 12 SQL queries");
  card(s, 0.5, 1.4, 5.0, 3.65, "F8FAFC");
  s.addImage({ path: path.join(ROOT, "images", "schema_diagram.png"), x: 0.6, y: 1.5, w: 4.8, h: 3.45, sizing: { type: "contain", w: 4.8, h: 3.45 } });
  bullets(s, [
    ["Claims grain:", "one line per claim with ICD-10 dx, CPT/HCPCS px, billed vs approved, status, reason."],
    ["Dimensions:", "members, annual policies (HMO/PPO/EPO/HDHP), providers, code lookups, 10 denial reasons."],
    ["SQL toolkit:", "multi-step CTEs, joins, RANK / NTILE / PERCENT_RANK, LAG / rolling windows, window medians, recursive calendar."],
    ["Pipeline:", "Python generator → SQLite → .sql files → notebook charts → this deck."],
  ], 5.8, 1.45, 3.75, 3.6, 12);
}

// ================= 3. Rejection reasons =================
{
  const s = base("Payer efficiency · denials", `${Math.round(100 * avoidable / rejected)}% of denials were avoidable up front`);
  const r = [...reasons].reverse();
  s.addChart(pres.charts.BAR, [{ name: "Rejected claims", labels: r.map(x => x.reason_code + "  " + SHORT_REASON[x.reason_code]), values: r.map(x => x.rejected_claims) }],
    chartOpts({ x: 0.4, y: 1.35, w: 6.1, h: 3.8, barDir: "bar", chartColors: [C.teal], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "#,##0", valAxisHidden: true, valGridLine: { style: "none" }, catAxisLabelFontSize: 9, barGapWidthPct: 45 }));
  stat(s, 6.8, 1.4, 2.7, fmtN(rejected), `claims rejected (${kpi.rejected_pct}% of all claims)`);
  stat(s, 6.8, 2.6, 2.7, `${Math.round(100 * avoidable / rejected)}%`, "network, coding, missing info, duplicates, filing & eligibility — preventable", C.teal, 1.25);
  const top3 = reasons.slice(0, 3);
  stat(s, 6.8, 4.0, 2.7, `${Math.round(top3[top3.length - 1].cumulative_pct)}%`, "of denials come from the top 3 reasons alone", C.gold);
}

// ================= 4. Where denials concentrate =================
{
  const s = base("Payer efficiency · providers", "Network gaps and prior auth drive specialty denials");
  const sp = spec.slice(0, 10).reverse();
  s.addChart(pres.charts.BAR, [{ name: "Rejection rate", labels: sp.map(x => x.specialty), values: sp.map(x => x.rejection_rate_pct / 100) }],
    chartOpts({ x: 0.4, y: 1.35, w: 5.0, h: 3.8, barDir: "bar", chartColors: [C.teal], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "0.0%", valAxisHidden: true, valGridLine: { style: "none" }, barGapWidthPct: 45,
      showTitle: true, title: "Rejection rate — top 10 specialties" }));
  const oonAll = provRej.every(p => p.network_status === "Out-of-Network");
  card(s, 5.7, 1.4, 3.8, 3.7);
  s.addText("What the provider ranking shows", { x: 5.9, y: 1.55, w: 3.4, h: 0.35, fontFace: FONT, fontSize: 14, bold: true, color: C.white, margin: 0, isTextBox: true });
  bullets(s, [
    ["Network, not behaviour:", `${oonAll ? "all" : "most"} of the 25 providers furthest above their specialty rate are out-of-network, billing HMO/EPO members with no OON benefit.`],
    ["Prior auth:", `drives ${spec.find(x => x.specialty === "General Surgery").prior_auth_pct.toFixed(0)}% of General Surgery and ${spec.find(x => x.specialty === "Oncology").prior_auth_pct.toFixed(0)}% of Oncology denials.`],
    ["Coding:", "the top driver for Cardiology, Behavioral Health, Neurology and Nephrology — a provider-education target."],
  ], 5.9, 2.0, 3.45, 3.0, 11.5);
}

// ================= 5. Turnaround =================
{
  const s = base("Payer efficiency · turnaround", `Adjudication time fell from ${firstTat.toFixed(1)} to ${lastTat.toFixed(1)} days`);
  s.addChart(pres.charts.LINE, [{ name: "Avg days to adjudicate", labels: tatTrend.map(r => r.month), values: tatTrend.map(r => r.avg_turnaround_days) },
                                 { name: "3-month rolling", labels: tatTrend.map(r => r.month), values: tatTrend.map(r => r.rolling_3m_days) }],
    chartOpts({ x: 0.4, y: 1.35, w: 5.9, h: 3.8, chartColors: [C.teal, C.muted], lineSize: 2, lineDataSymbol: "circle", lineDataSymbolSize: 5,
      valAxisMinVal: 0, valAxisLabelFormatCode: "0.0", catAxisLabelFontSize: 8, showLegend: true, legendPos: "b", legendColor: C.muted, legendFontSize: 9,
      showTitle: true, title: "Days from submission to decision, by submission month" }));
  stat(s, 6.6, 1.4, 2.9, `${autoAppr.median_days}d vs ${manAppr.median_days}d`, "median days, approved claims: auto-adjudicated vs manual review");
  stat(s, 6.6, 2.65, 2.9, `${manAppr.pct_within_15d.toFixed(0)}%`, "of manual-review claims decided within 15 days — the bottleneck", C.gold);
  stat(s, 6.6, 3.9, 2.9, `${tatTrend[tatTrend.length - 1].pct_within_15d.toFixed(1)}%`, "of all claims decided within 15 days (Nov 2025)");
}

// ================= 6. Cost by diagnosis =================
{
  const s = base("Cost containment · conditions", "Surgical and maternity episodes set cost per claim");
  const d = dx.slice(0, 10).reverse();
  s.addChart(pres.charts.BAR, [{ name: "Avg approved / claim", labels: d.map(x => dxName(x) + " (" + x.diagnosis_code + ")"), values: d.map(x => x.avg_approved) }],
    chartOpts({ x: 0.4, y: 1.35, w: 6.0, h: 3.8, barDir: "bar", chartColors: [C.teal], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "$#,##0", valAxisHidden: true, valGridLine: { style: "none" }, catAxisLabelFontSize: 9, barGapWidthPct: 45,
      showTitle: true, title: "Average approved amount per claim — top 10 diagnoses" }));
  const byTotal = [...dx].sort((a, b) => b.total_approved - a.total_approved);
  card(s, 6.7, 1.4, 2.8, 3.7);
  s.addText("Largest total spend", { x: 6.9, y: 1.55, w: 2.4, h: 0.3, fontFace: FONT, fontSize: 13, bold: true, color: C.white, margin: 0, isTextBox: true });
  byTotal.slice(0, 5).forEach((r, i) => {
    const y = 1.98 + i * 0.42;
    s.addText(fmtM(r.total_approved), { x: 6.9, y, w: 0.95, h: 0.36, fontFace: HFONT, fontSize: 15, bold: true, color: C.teal, margin: 0, valign: "middle", isTextBox: true });
    s.addText(dxName(r), { x: 7.85, y, w: 1.55, h: 0.36, fontFace: FONT, fontSize: 11, color: C.ink, margin: 0, valign: "middle", isTextBox: true });
  });
  s.addText("Mean far above median (e.g. gallstones, tibia fracture) = cost driven by a few surgical episodes → site-of-care and prior-auth levers.",
    { x: 6.9, y: 4.15, w: 2.45, h: 0.85, fontFace: FONT, fontSize: 9.5, italic: true, color: C.muted, margin: 0, valign: "top", isTextBox: true });
}

// ================= 7. Concentration & trend =================
{
  const s = base("Cost containment · members & trend", `Top 10% of members drive ${Math.round(deciles[0].pct_of_spend)}% of spend`);
  s.addChart(pres.charts.BAR, [{ name: "Share of spend", labels: deciles.map(r => "D" + r.decile), values: deciles.map(r => r.pct_of_spend / 100) }],
    chartOpts({ x: 0.4, y: 1.35, w: 4.4, h: 2.9, barDir: "col", chartColors: [C.teal], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "0%", valAxisHidden: true, valGridLine: { style: "none" }, barGapWidthPct: 35,
      showTitle: true, title: "Share of approved spend by member decile" }));
  s.addChart(pres.charts.LINE, [{ name: "Approved PMPM", labels: trend.map(r => r.month), values: trend.map(r => r.approved_pmpm) }],
    chartOpts({ x: 5.0, y: 1.35, w: 4.6, h: 2.9, chartColors: [C.teal], lineSize: 2, lineDataSymbol: "circle", lineDataSymbolSize: 5,
      valAxisMinVal: 0, valAxisLabelFormatCode: "$#,##0", catAxisLabelFontSize: 8, showTitle: true, title: `Approved PMPM — 2025 avg YoY ${yoyAvg >= 0 ? "+" : ""}${yoyAvg.toFixed(1)}%` }));
  const medAge = [...hcm.map(r => r.age)].sort((a, b) => a - b)[Math.floor(hcm.length / 2)];
  const medDx = [...hcm.map(r => r.chronic_dx_count)].sort((a, b) => a - b)[Math.floor(hcm.length / 2)];
  const items = [[fmtK(deciles[0].avg_member_spend), "avg 2-yr spend, top-decile member"],
                 [String(medDx), `chronic dx (median) for top-50 members, median age ${medAge}`],
                 ["Jan", "peak month: winter respiratory season + deductible reset"]];
  items.forEach(([v, l], i) => {
    const x = 0.5 + i * 3.05;
    card(s, x, 4.35, 2.85, 0.8);
    s.addText(v, { x: x + 0.15, y: 4.42, w: 1.15, h: 0.65, fontFace: HFONT, fontSize: 17, bold: true, color: C.teal, margin: 0, valign: "middle", isTextBox: true });
    s.addText(l, { x: x + 1.3, y: 4.42, w: 1.45, h: 0.65, fontFace: FONT, fontSize: 9.5, color: C.muted, margin: 0, valign: "middle", isTextBox: true });
  });
}

// ================= 8. Duplicates & outliers =================
{
  const s = base("Claims integrity · duplicates & outliers", "Near-duplicates slip past edits at 3x the rate");
  const types = [exact, near];
  s.addChart(pres.charts.BAR, [
    { name: "Caught by edits (R01)", labels: types.map(t => t.dup_type), values: types.map(t => t.caught_by_edits) },
    { name: "Paid", labels: types.map(t => t.dup_type), values: types.map(t => t.paid_duplicates) },
  ], chartOpts({ x: 0.4, y: 1.35, w: 5.2, h: 2.6, barDir: "bar", barGrouping: "stacked", chartColors: [C.teal, C.coral], showValue: true,
    dataLabelPosition: "ctr", dataLabelFormatCode: "#,##0", valAxisHidden: true, valGridLine: { style: "none" }, barGapWidthPct: 40,
    showLegend: true, legendPos: "b", legendColor: C.muted, legendFontSize: 9, showTitle: true, title: "Duplicate submissions: caught vs paid" }));
  stat(s, 0.5, 4.1, 2.45, `${Math.round(exact.leakage_rate_pct)}% vs ${Math.round(near.leakage_rate_pct)}%`, "paid-through rate: exact vs near duplicates", C.coral, 1.05, 22);
  stat(s, 3.1, 4.1, 2.45, fmtK(dupPaid), "paid on exact + near duplicates — recoverable", C.coral);
  card(s, 5.9, 1.4, 3.6, 3.75);
  const outApproved = sum(outliers.filter(o => o.claim_status === "Approved"), o => o.approved_amount || 0);
  const outBilled = sum(outliers, o => o.billed_amount);
  s.addText("Billed-amount outliers", { x: 6.1, y: 1.55, w: 3.2, h: 0.3, fontFace: FONT, fontSize: 14, bold: true, color: C.white, margin: 0, isTextBox: true });
  s.addText(fmtN(outliers.length), { x: 6.1, y: 1.95, w: 3.2, h: 0.55, fontFace: HFONT, fontSize: 30, bold: true, color: C.teal, margin: 0, isTextBox: true });
  s.addText(`claims with |z| > 3 and ≥ 3x the procedure median, billing ${fmtM(outBilled)}`, { x: 6.1, y: 2.5, w: 3.2, h: 0.5, fontFace: FONT, fontSize: 10.5, color: C.muted, margin: 0, isTextBox: true });
  bullets(s, [
    ["Fee schedule works:", `approved outliers paid only ${fmtK(outApproved)} — allowed amounts cap exposure in-network.`],
    ["Real risk:", "outliers cluster in E&M codes at a few providers — a behavioural signal, not a typo."],
  ], 6.1, 3.15, 3.2, 1.9, 10.5);
}

// ================= 9. Provider risk scorecard =================
{
  const s = base("Claims integrity · provider scorecard", `${flagged.length} providers show 3+ red flags vs. peers`);
  const hdr = ["Provider", "Specialty", "Markup", "% 99215", "Dup %", "Flags", "Score"].map(t => ({ text: t, options: { bold: true, color: C.teal, fill: { color: C.card2 } } }));
  const rows = risk.slice(0, 8).map(r => [r.provider_name.replace("Associates", "Assoc."), r.specialty, r.markup_ratio.toFixed(1) + "x", r.pct_99215.toFixed(0) + "%",
    r.dup_rate_pct.toFixed(1) + "%", String(r.red_flags), r.risk_score.toFixed(0)].map((t, j) => ({ text: t, options: { color: j === 6 ? C.white : C.ink, bold: j === 6 } })));
  s.addTable([hdr, ...rows], { x: 0.5, y: 1.4, w: 6.2, colW: [1.95, 1.3, 0.62, 0.66, 0.58, 0.5, 0.59], fontFace: FONT, fontSize: 9.5,
    fill: { color: C.card }, border: { type: "solid", color: C.navy, pt: 1 }, rowH: 0.38, valign: "middle", margin: 0.06 });
  const bookMarkup = 1.95, bookUpcode = 5;
  stat(s, 7.0, 1.4, 2.5, `${(sum(flagged, r => r.markup_ratio) / flagged.length).toFixed(1)}x`, `avg billed-to-reference markup (book ≈ ${bookMarkup}x)`, C.coral);
  stat(s, 7.0, 2.6, 2.5, `${Math.round(sum(flagged, r => r.pct_99215) / flagged.length)}%`, `of E&M visits coded 99215 (book ≈ ${bookUpcode}%) — upcoding`, C.coral);
  stat(s, 7.0, 3.8, 2.5, fmtM(sum(flagged, r => r.approved_paid)), "approved to flagged providers — SIU review scope", C.gold);
  note(s, "Score = within-specialty PERCENT_RANK of markup (30%), duplicates (25%), 99215 share (20%), outliers (15%), claims per member (10%).");
}

// ================= 10. Recommendations =================
{
  const s = base("Recommendations", "Three levers, sized from the data");
  const cols = [
    ["Payer efficiency", [`Front-end claim scrubber for coding & missing-info edits (${Math.round(100 * (reasons.find(r => r.reason_code === "R06").rejected_claims + reasons.find(r => r.reason_code === "R07").rejected_claims) / rejected)}% of denials)`,
      "Steer HMO/EPO members to in-network care; fix directory accuracy", "Gold-card high-approval providers to shrink the manual-review queue"]],
    ["Cost containment", [`Case management for the top decile (${Math.round(deciles[0].pct_of_spend)}% of spend), prioritising multi-morbid members`,
      "Site-of-care & prior-auth review for surgical episodes", "Monthly PMPM trend monitoring with run-out-adjusted months"]],
    ["Claims integrity", ["Add a ±5% tolerance band to the duplicate edit; recover paid duplicates",
      `Refer the ${flagged.length} flagged providers to SIU; pre-payment review on 99215`, "Productionise the scorecard as a monthly refresh"]],
  ];
  cols.forEach(([head, items], i) => {
    const x = 0.5 + i * 3.05;
    card(s, x, 1.4, 2.85, 3.7);
    s.addShape(pres.shapes.OVAL, { x: x + 0.2, y: 1.58, w: 0.5, h: 0.5, fill: { color: C.teal }, line: { color: C.teal } });
    s.addText(String(i + 1), { x: x + 0.2, y: 1.58, w: 0.5, h: 0.5, fontFace: HFONT, fontSize: 16, bold: true, color: C.navy, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText(head, { x: x + 0.85, y: 1.58, w: 1.9, h: 0.5, fontFace: FONT, fontSize: 15, bold: true, color: C.white, valign: "middle", margin: 0, isTextBox: true });
    bullets(s, items, x + 0.2, 2.3, 2.5, 2.7, 11);
  });
  note(s, "All figures from synthetic data; methods transfer directly to production claims warehouses.");
}

const out = path.join(__dirname, "insurance_claims_fraud_signals.pptx");
pres.writeFile({ fileName: out }).then(() => console.log("wrote " + out));
