"""
Generate a Power BI Project (.pbip) for the Population Health & Preventive Care
Dashboard:

  * Semantic model in TMDL  (powerbi/pbip/<name>.SemanticModel/definition/*.tmdl)
      - one table per star-schema CSV, typed columns, hidden keys, sort-by columns
      - relationships (active + inactive) exactly as in dashboard_spec.md §3
      - every measure from powerbi/measures.dax, grouped in display folders
      - a DataFolder parameter pointing at data/star_schema
  * Report in PBIR (powerbi/pbip/<name>.Report/definition/pages/**)
      - the pages and visuals described in dashboard_spec.md §4
      - the navy & teal theme from powerbi/theme_navy_teal.json

Usage:
    python src/build_pbip.py                       # writes powerbi/pbip/
    python src/build_pbip.py --data-folder "D:\\repo\\03-population-health-powerbi\\data\\star_schema"

Everything is deterministic (GUIDs are derived from names) so re-running
produces the same files and clean git diffs.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NAME = "Population_Health_Dashboard"
NS = uuid.UUID("6f1a2f4e-4a2b-4a53-9d4e-0c3c0f3b7e11")


def guid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "|".join(parts)))


# =============================================================================
#  Semantic model (TMDL)
# =============================================================================
DATE_COLUMNS = {"date", "birth_date", "app_enrollment_date", "last_event_date", "month_start_date"}
DATETIME_COLUMNS = {"event_timestamp"}
HIDDEN_COLUMNS = {"completed_flag_raw"}
SORT_BY = {  # table -> {column: sort_by_column}
    "dim_patient": {"age_band": "age_band_order", "risk_tier": "risk_tier_order"},
    "dim_date": {"month_name": "month", "day_name": "day_of_week", "quarter_label": "quarter"},
    "fact_patient_risk_snapshot": {},
}
COLUMN_FORMATS = {
    "bmi": "0.0", "height_cm": "0.0", "weight_kg": "0.0", "avg_daily_steps_12m": "#,0", "avg_daily_steps": "#,0",
    "avg_sleep_hours": "0.0", "avg_sleep_hours_12m": "0.0", "avg_resting_hr": "0.0", "avg_resting_hr_12m": "0.0",
    "measure_value": "0.0", "secondary_measure_value": "0", "session_minutes": "0.0", "years_since_onset": "0.0",
    "screening_completion_rate": "0.0%",
}
RELATIONSHIPS = [
    # (from_table, from_col, to_table, to_col, active)
    ("fact_screening", "patient_key", "dim_patient", "patient_key", True),
    ("fact_condition", "patient_key", "dim_patient", "patient_key", True),
    ("fact_wearable_monthly", "patient_key", "dim_patient", "patient_key", True),
    ("fact_engagement_event", "patient_key", "dim_patient", "patient_key", True),
    ("fact_patient_risk_snapshot", "patient_key", "dim_patient", "patient_key", True),
    ("dim_patient", "geo_key", "dim_geography", "geo_key", True),
    ("fact_condition", "condition_key", "dim_condition", "condition_key", True),
    ("fact_screening", "screening_key", "dim_screening", "screening_key", True),
    ("fact_engagement_event", "event_type_key", "dim_event_type", "event_type_key", True),
    ("fact_engagement_event", "date_key", "dim_date", "date_key", True),
    ("fact_wearable_monthly", "month_date_key", "dim_date", "date_key", True),
    ("fact_screening", "last_completed_date_key", "dim_date", "date_key", False),
    ("fact_condition", "onset_date_key", "dim_date", "date_key", False),
    ("dim_patient", "app_enrollment_date_key", "dim_date", "date_key", False),
]
MEASURES_TABLE = "_Measures"


def tmdl_name(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else f"'{name}'"


def infer_columns(csv_path: Path) -> list[tuple[str, str, str]]:
    """Return [(column, tmdl_type, m_type)] using a sample of the CSV."""
    df = pd.read_csv(csv_path, nrows=5000)
    cols = []
    for c in df.columns:
        if c in DATE_COLUMNS:
            cols.append((c, "dateTime", "type date"))
        elif c in DATETIME_COLUMNS:
            cols.append((c, "dateTime", "type datetime"))
        elif c.endswith("_key") or c in {"days_since_last", "days_overdue"}:
            cols.append((c, "int64", "Int64.Type"))
        elif str(df[c].dtype).startswith("int"):
            cols.append((c, "int64", "Int64.Type"))
        elif str(df[c].dtype).startswith("float"):
            cols.append((c, "double", "type number"))
        else:
            cols.append((c, "string", "type text"))
    return cols


def parse_measures(dax_path: Path) -> list[dict]:
    """Parse powerbi/measures.dax into [{name, expression, format, folder, description}]."""
    measures, folder, cur = [], "", None
    fmt_like = re.compile(r"^(#|0|\+|text)")

    def flush():
        nonlocal cur
        if cur:
            cur["expression"] = "\n".join(cur["lines"]).strip()
            del cur["lines"]
            measures.append(cur)
        cur = None

    for raw in dax_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        m_group = re.match(r"^//\s+(\d+)\.\s+(.+?)\s*$", line)
        if m_group:
            folder = f"{m_group.group(1)}. {m_group.group(2)}"
            continue
        if not line.strip():
            flush()
            continue
        if line.startswith("//"):
            continue
        m_start = re.match(r"^([A-Za-z][^=]*?)\s*=\s*(.*)$", line) if not line.startswith((" ", "\t")) else None
        if m_start:
            flush()
            name, rest = m_start.group(1).strip(), m_start.group(2)
            cur = {"name": name, "folder": folder, "format": None, "description": None, "lines": []}
            if "//" in rest:
                expr, comment = rest.split("//", 1)
                rest = expr.rstrip()
                cur["format"], cur["description"] = split_format_comment(comment)
            if rest.strip():
                cur["lines"].append(rest.strip())
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if stripped.startswith("//"):
            comment = stripped[2:].strip()
            if cur["format"] is None and not cur["lines"] and fmt_like.match(comment):
                cur["format"], cur["description"] = split_format_comment(comment)
            elif cur["description"] is None and not cur["lines"]:
                cur["description"] = comment
            continue
        cur["lines"].append(line[4:] if line.startswith("    ") else line)
    flush()
    return measures


def split_format_comment(comment: str) -> tuple[str | None, str | None]:
    comment = comment.strip()
    parts = re.split(r"\s+—\s+|\s+-\s+", comment, maxsplit=1)
    fmt = parts[0].strip()
    desc = parts[1].strip() if len(parts) > 1 else None
    if fmt.startswith("text") or not fmt:
        return None, desc or (comment if not fmt.startswith("text") else None)
    return fmt, desc


def build_table_tmdl(table: str, columns: list[tuple[str, str, str]], csv_rel: str, is_date_table: bool, measures: list[dict] | None = None, hidden=False) -> str:
    out = [f"table {table}", f"\tlineageTag: {guid('table', table)}"]
    if is_date_table:
        out.append("\tdataCategory: Time")
    if hidden:
        out.append("\tisHidden")
    out.append("")

    for m in measures or []:
        expr_lines = m["expression"].splitlines()
        if m["description"]:
            out.append(f"\t/// {m['description']}")
        if len(expr_lines) == 1:
            out.append(f"\tmeasure {tmdl_name(m['name'])} = {expr_lines[0]}")
        else:
            out.append(f"\tmeasure {tmdl_name(m['name'])} =")
            out.extend("\t\t\t" + l for l in expr_lines)
        if m["format"]:
            out.append(f"\t\tformatString: {m['format']}")
        out.append(f"\t\tdisplayFolder: {m['folder']}")
        out.append(f"\t\tlineageTag: {guid('measure', m['name'])}")
        out.append("")

    sort_map = SORT_BY.get(table, {})
    for col, ttype, _ in columns:
        out.append(f"\tcolumn {tmdl_name(col)}")
        out.append(f"\t\tdataType: {ttype}")
        if col.endswith("_key") or col in HIDDEN_COLUMNS or (table == MEASURES_TABLE):
            out.append("\t\tisHidden")
        if is_date_table and col == "date":
            out.append("\t\tisKey")
        if col in DATE_COLUMNS:
            out.append("\t\tformatString: yyyy-mm-dd")
        elif col in DATETIME_COLUMNS:
            out.append("\t\tformatString: yyyy-mm-dd hh:nn:ss")
        elif col in COLUMN_FORMATS:
            out.append(f"\t\tformatString: {COLUMN_FORMATS[col]}")
        if col in sort_map:
            out.append(f"\t\tsortByColumn: {sort_map[col]}")
        out.append(f"\t\tlineageTag: {guid('column', table, col)}")
        summarize = "none" if (table.startswith("dim_") or col.endswith("_key") or col.endswith("_id") or ttype in ("string", "dateTime")) else "sum"
        out.append(f"\t\tsummarizeBy: {summarize}")
        out.append(f"\t\tsourceColumn: {col}")
        out.append("")
        out.append("\t\tannotation SummarizationSetBy = Automatic")
        out.append("")

    if table == MEASURES_TABLE:
        m_source = ['let', '    Source = #table(type table [Column1 = Int64.Type], {})', 'in', '    Source']
    else:
        types = ", ".join(f'{{"{c}", {mt}}}' for c, _, mt in columns)
        m_source = [
            "let",
            f'    Source = Csv.Document(File.Contents(DataFolder & "\\{csv_rel}"), [Delimiter = ",", Columns = {len(columns)}, Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
            '    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),',
            f'    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{{types}}}, "en-US")',
            "in",
            '    #"Changed Type"',
        ]
    out.append(f"\tpartition {table} = m")
    out.append("\t\tmode: import")
    out.append("\t\tsource =")
    out.extend("\t\t\t\t" + l for l in m_source)
    out.append("")
    out.append("\tannotation PBI_ResultType = Table")
    out.append("")
    return "\n".join(out)


def write_semantic_model(base: Path, data_folder: str, tables: dict[str, list], measures: list[dict]) -> None:
    sm = base / f"{NAME}.SemanticModel"
    (sm / "definition" / "tables").mkdir(parents=True, exist_ok=True)
    (sm / "definition" / "cultures").mkdir(parents=True, exist_ok=True)

    (sm / ".platform").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": guid("platform", "semanticmodel")},
    }, indent=2) + "\n")
    (sm / "definition.pbism").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {},
    }, indent=2) + "\n")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1600\n\n")

    table_names = list(tables) + [MEASURES_TABLE]
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3", "\tdiscourageImplicitMeasures",
             "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
             "annotation __PBI_TimeIntelligenceEnabled = 0", "", "annotation PBI_QueryOrder = " + json.dumps(["DataFolder"] + table_names), ""]
    model += [f"ref table {t}" for t in table_names] + ["", "ref cultureInfo en-US", ""]
    (sm / "definition" / "model.tmdl").write_text("\n".join(model))

    (sm / "definition" / "cultures" / "en-US.tmdl").write_text(
        "cultureInfo en-US\n\n\tlinguisticMetadata =\n\t\t\t{\n\t\t\t  \"Version\": \"1.0.0\",\n\t\t\t  \"Language\": \"en-US\"\n\t\t\t}\n\t\tcontentType: json\n\n")

    (sm / "definition" / "expressions.tmdl").write_text(
        f'expression DataFolder = "{data_folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
        f"\tlineageTag: {guid('expression', 'DataFolder')}\n\n\tannotation PBI_ResultType = Text\n\n")

    rels = []
    for ft, fc, tt, tc, active in RELATIONSHIPS:
        rels.append(f"relationship {guid('rel', ft, fc, tt, tc)}")
        if not active:
            rels.append("\tisActive: false")
        rels.append(f"\tfromColumn: {ft}.{fc}")
        rels.append(f"\ttoColumn: {tt}.{tc}")
        rels.append("")
    (sm / "definition" / "relationships.tmdl").write_text("\n".join(rels))

    for t, (cols, csv_rel) in tables.items():
        (sm / "definition" / "tables" / f"{t}.tmdl").write_text(build_table_tmdl(t, cols, csv_rel, is_date_table=(t == "dim_date")))
    (sm / "definition" / "tables" / f"{MEASURES_TABLE}.tmdl").write_text(
        build_table_tmdl(MEASURES_TABLE, [("Column1", "int64", "Int64.Type")], "", False, measures))


# =============================================================================
#  Report (PBIR)
# =============================================================================
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
PAGE_W, PAGE_H = 1280, 720
RAIL_W = 190
_visual_counter = {"n": 0}


def lit(value) -> dict:
    if isinstance(value, bool):
        return {"expr": {"Literal": {"Value": "true" if value else "false"}}}
    if isinstance(value, (int, float)):
        return {"expr": {"Literal": {"Value": f"{value}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(value).replace("'", "''") + "'"}}}


def color(hexcode: str) -> dict:
    return {"solid": {"color": lit(hexcode)}}


def col(table: str, column: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def mea(name: str, table: str = MEASURES_TABLE) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def agg(table: str, column: str, fn: int = 1) -> dict:
    return {"Aggregation": {"Expression": col(table, column), "Function": fn}}


def projection(field: dict, ref: str, native: str | None = None, display: str | None = None) -> dict:
    p = {"field": field, "queryRef": ref, "nativeQueryRef": native or ref.split(".")[-1]}
    if display:
        p["displayName"] = display
    return p


def P(spec) -> dict:
    """Shorthand: ('table','column') → column projection; 'Measure Name' → measure projection;
    ('avg','table','column') → average aggregation; tuples may carry a display-name 4th/3rd element."""
    if isinstance(spec, str):
        return projection(mea(spec), f"{MEASURES_TABLE}.{spec}", spec)
    if spec[0] == "avg":
        _, t, c = spec[:3]
        return projection(agg(t, c, 1), f"Avg({t}.{c})", f"Avg({c})", spec[3] if len(spec) > 3 else None)
    t, c = spec[:2]
    return projection(col(t, c), f"{t}.{c}", c, spec[2] if len(spec) > 2 else None)


def sort_for(spec, direction="Descending") -> dict:
    field = P(spec)["field"]
    return {"sort": [{"field": field, "direction": direction}], "isDefaultSort": True}


def visual(vtype: str, x, y, w, h, roles: dict[str, list], *, title: str | None = None, objects: dict | None = None,
           sort=None, sort_dir="Descending", filters: list | None = None, sync_group: str | None = None, name: str | None = None) -> dict:
    _visual_counter["n"] += 1
    vname = name or f"v{_visual_counter['n']:03d}"
    query_state = {role: {"projections": [P(s) for s in specs]} for role, specs in roles.items() if specs}
    vis: dict = {"visualType": vtype, "drillFilterOtherVisuals": True}
    if query_state:
        vis["query"] = {"queryState": query_state}
        if sort is not None:
            vis["query"]["sortDefinition"] = sort_for(sort, sort_dir)
    if objects:
        vis["objects"] = objects
    if title is not None:
        vis["visualContainerObjects"] = {"title": [{"properties": {"show": lit(True), "text": lit(title)}}]}
    if sync_group:
        vis["syncGroup"] = {"groupName": sync_group, "fieldChanges": True, "filterChanges": True}
    container = {
        "$schema": f"{SCHEMA}/visualContainer/1.0.0/schema.json",
        "name": vname,
        "position": {"x": x, "y": y, "z": _visual_counter["n"], "width": w, "height": h, "tabOrder": _visual_counter["n"]},
        "visual": vis,
    }
    if filters:
        container["filterConfig"] = {"filters": filters}
    return container


def textbox(x, y, w, h, text: str, size="18pt", bold=True, color_hex="#F5F7FA", name=None) -> dict:
    v = visual("textbox", x, y, w, h, {}, name=name)
    v["visual"]["objects"] = {"general": [{"properties": {"paragraphs": [{"textRuns": [
        {"value": text, "textStyle": {"fontSize": size, "fontWeight": "bold" if bold else "normal", "color": color_hex}}]}]}}]}
    return v


def card(x, y, w, h, measure: str, label: str) -> dict:
    return visual("card", x, y, w, h, {"Values": [measure]}, title=label,
                  objects={"labels": [{"properties": {"fontSize": lit(24)}}], "categoryLabels": [{"properties": {"show": lit(False)}}]})


def slicer(x, y, w, h, field, label: str, mode="Basic", dropdown=False, group=None) -> dict:
    objects = {"data": [{"properties": {"mode": lit("Dropdown" if dropdown else mode)}}],
               "header": [{"properties": {"show": lit(True), "text": lit(label)}}]}
    if not dropdown:
        objects["general"] = [{"properties": {"orientation": lit(0)}}]
        objects["selection"] = [{"properties": {"selectAllCheckboxEnabled": lit(True), "singleSelect": lit(False)}}]
    return visual("slicer", x, y, w, h, {"Values": [field]}, objects=objects, sync_group=group)


def categorical_filter(name: str, table: str, column: str, values: list[str]) -> dict:
    return {"name": name, "field": col(table, column), "type": "Categorical", "filter": {
        "Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
        "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}],
                                         "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}]}}


def advanced_filter(name: str, table: str, column: str, kind: int, value: float) -> dict:
    return {"name": name, "field": col(table, column), "type": "Advanced", "filter": {
        "Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
        "Where": [{"Condition": {"Comparison": {"ComparisonKind": kind,
                                                 "Left": {"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}},
                                                 "Right": {"Literal": {"Value": f"{value}L"}}}}}]}}


LEGEND_TOP = {"legend": [{"properties": {"show": lit(True), "position": lit("Top")}}]}
LABELS_ON = {"labels": [{"properties": {"show": lit(True)}}]}


def rail(page_slicers: list[tuple]) -> list[dict]:
    """Standard left slicer rail: (field, label, height, dropdown?)"""
    out, y = [], 60
    for field, label, h, dropdown in page_slicers:
        out.append(slicer(10, y, RAIL_W - 20, h, field, label, dropdown=dropdown, group=f"sync_{label.lower().replace(' ', '_')}"))
        y += h + 8
    return out


STANDARD_RAIL = [
    (("dim_geography", "region"), "Region", 120, False),
    (("dim_geography", "state"), "State", 46, True),
    (("dim_patient", "age_band"), "Age band", 160, False),
    (("dim_patient", "risk_tier"), "Risk tier", 120, False),
    (("dim_patient", "insurance_type"), "Insurance", 46, True),
    (("dim_patient", "adi_band"), "Deprivation", 46, True),
    (("dim_patient", "engagement_segment"), "Engagement", 46, True),
]


def kpi_row(cards: list[tuple[str, str]], y=52, x0=RAIL_W + 10, h=88) -> list[dict]:
    n = len(cards)
    gap = 8
    w = (PAGE_W - x0 - 10 - gap * (n - 1)) / n
    return [card(round(x0 + i * (w + gap)), y, round(w), h, m, label) for i, (m, label) in enumerate(cards)]


def build_pages() -> list[dict]:
    pages = []
    X0 = RAIL_W + 10                       # content left edge
    CW = PAGE_W - X0 - 10                  # content width
    third = (CW - 16) / 3
    half = (CW - 8) / 2

    # ---------------- Page 1: Executive Overview ----------------
    v = [textbox(X0, 8, CW, 40, "Population health at a glance")]
    v += rail(STANDARD_RAIL)
    v += kpi_row([("Total Patients", "Attributed patients"), ("Any Focus Condition %", "Any focus condition"),
                  ("Screening Rate %", "Screening rate"), ("App Engagement Rate %", "App engagement rate"),
                  ("High Risk Share %", "High / very-high risk"), ("Open Care Gaps", "Open care gaps")])
    v.append(visual("clusteredColumnChart", X0, 150, round(third), 270, {"Category": [("dim_patient", "risk_tier")], "Y": ["Risk Tier Share %"]},
                    title="Risk-tier distribution", objects=LABELS_ON))
    v.append(visual("clusteredColumnChart", round(X0 + third + 8), 150, round(third), 270,
                    {"Category": [("dim_geography", "region")], "Y": ["Obesity Prevalence %", "Hypertension Prevalence %", "Diabetes Prevalence %"]},
                    title="Chronic-condition prevalence by region", objects=LEGEND_TOP))
    v.append(visual("lineChart", round(X0 + 2 * (third + 8)), 150, round(third), 270,
                    {"Category": [("dim_date", "year_month")], "Y": ["Monthly Active Users"]}, title="Monthly active users",
                    sort=("dim_date", "year_month"), sort_dir="Ascending"))
    v.append(visual("clusteredBarChart", X0, 430, round(half), 280, {"Category": [("dim_screening", "screening_name")], "Y": ["Screening Rate %"]},
                    title="Screening rate by service (target 75%)", objects=LABELS_ON, sort="Screening Rate %"))
    v.append(visual("pivotTable", round(X0 + half + 8), 430, round(half), 280,
                    {"Rows": [("dim_geography", "region")],
                     "Values": ["Screening Rate %", "App Engagement Rate %", "Hypertension Control %", "Diabetes Control %", "High Risk Share %"]},
                    title="Region scorecard"))
    pages.append(("ExecutiveOverview", "1 · Executive Overview", v))

    # ---------------- Page 2: Prevalence & Control ----------------
    v = [textbox(X0, 8, CW, 40, "Chronic disease prevalence & control")]
    v += rail(STANDARD_RAIL)
    v += kpi_row([("Diabetes Prevalence %", "Diabetes"), ("Hypertension Prevalence %", "Hypertension"), ("Obesity Prevalence %", "Obesity"),
                  ("Multimorbidity %", "Multimorbidity (2+)"), ("Disease Control Rate %", "Disease control rate")])
    v.append(visual("clusteredColumnChart", X0, 150, round(third), 270,
                    {"Category": [("dim_patient", "age_band")], "Y": ["Obesity Prevalence %", "Hypertension Prevalence %", "Diabetes Prevalence %"]},
                    title="Prevalence by age band", objects=LEGEND_TOP, sort=("dim_patient", "age_band"), sort_dir="Ascending"))
    v.append(visual("clusteredBarChart", round(X0 + third + 8), 150, round(third), 270,
                    {"Category": [("dim_geography", "state")], "Y": ["Any Focus Condition %"]}, title="Any focus condition by state",
                    sort="Any Focus Condition %"))
    v.append(visual("hundredPercentStackedBarChart", round(X0 + 2 * (third + 8)), 150, round(third), 270,
                    {"Category": [("dim_condition", "condition_name")], "Series": [("fact_condition", "control_status")], "Y": ["Condition Records"]},
                    title="Control status by condition", objects=LEGEND_TOP))
    v.append(visual("clusteredColumnChart", X0, 430, round(third), 280,
                    {"Category": [("dim_patient", "adi_band")], "Y": ["Obesity Prevalence %", "Hypertension Prevalence %", "Diabetes Prevalence %"]},
                    title="Prevalence by deprivation band", objects=LEGEND_TOP))
    v.append(visual("scatterChart", round(X0 + third + 8), 430, round(third), 280,
                    {"Category": [("dim_geography", "state")], "X": ["Avg Systolic BP"], "Y": ["Avg HbA1c"], "Size": ["Total Patients"]},
                    title="Avg systolic BP vs avg HbA1c by state"))
    v.append(visual("tableEx", round(X0 + 2 * (third + 8)), 430, round(third), 280,
                    {"Values": [("dim_condition", "condition_name", "Condition"), "Patients with Condition", "Condition Prevalence %",
                                "Disease Control Rate %", "On Medication %", "Avg Years Since Onset"]}, title="Condition detail"))
    pages.append(("PrevalenceControl", "2 · Prevalence & Control", v))

    # ---------------- Page 3: Screening & Care Gaps ----------------
    v = [textbox(X0, 8, CW, 40, "Preventive screening & care gaps")]
    v += rail(STANDARD_RAIL)
    v += kpi_row([("Screening Rate %", "Screening rate"), ("Open Care Gaps", "Open care gaps"),
                  ("Patients with Open Care Gaps %", "Patients with a gap"), ("Avg Days Overdue", "Avg days overdue"),
                  ("Digital Engagement Lift (pp)", "Digital engagement lift (pp)")])
    v.append(visual("clusteredBarChart", X0, 150, round(third), 470, {"Category": [("dim_screening", "screening_name")], "Y": ["Screening Rate %"]},
                    title="Completion rate by screening (target 75%)", objects=LABELS_ON, sort="Screening Rate %"))
    v.append(visual("clusteredColumnChart", round(X0 + third + 8), 150, round(third), 230,
                    {"Category": [("dim_screening", "screening_category")], "Y": ["Screening Rate % (Enrolled)", "Screening Rate % (Not Enrolled)"]},
                    title="Enrolled vs not enrolled", objects=LEGEND_TOP))
    v.append(visual("lineChart", round(X0 + third + 8), 390, round(third), 230,
                    {"Category": [("dim_date", "year_month")], "Series": [("dim_screening", "screening_category")], "Y": ["Screenings Completed in Period"]},
                    title="Completions per month", sort=("dim_date", "year_month"), sort_dir="Ascending"))
    v.append(visual("hundredPercentStackedBarChart", round(X0 + 2 * (third + 8)), 150, round(third), 230,
                    {"Category": [("dim_geography", "region")], "Series": [("fact_screening", "screening_status")], "Y": ["Eligible Screenings"]},
                    title="Care-gap status by region", objects=LEGEND_TOP))
    v.append(visual("clusteredBarChart", round(X0 + 2 * (third + 8)), 390, round(third), 230,
                    {"Category": [("dim_patient", "age_band")], "Y": ["Open Care Gaps"]}, title="Open care gaps by age band",
                    sort=("dim_patient", "age_band"), sort_dir="Ascending"))
    v += kpi_row([("Cancer Screening Rate %", "Cancer screening rate"), ("Diabetes Care Bundle %", "Diabetes care bundle"),
                  ("Flu Vaccination Rate %", "Flu vaccination rate"), ("Reminder Coverage %", "Reminder coverage of open gaps")], y=630, h=80)
    pages.append(("ScreeningCareGaps", "3 · Screening & Care Gaps", v))

    # ---------------- Page 4: Digital Engagement ----------------
    v = [textbox(X0, 8, CW, 40, "Digital engagement")]
    v += rail(STANDARD_RAIL)
    v += kpi_row([("App Enrollment Rate %", "Enrollment rate"), ("App Engagement Rate %", "Engagement rate"), ("Active Users", "Active users"),
                  ("Appointment Bookings", "Appointment bookings"), ("Medication Reminder Ack Rate %", "Reminder ack rate"), ("Dormant Rate %", "Dormant rate")])
    v.append(visual("lineChart", X0, 150, round(third), 230, {"Category": [("dim_date", "year_month")], "Y": ["Monthly Active Users"]},
                    title="Monthly active users", sort=("dim_date", "year_month"), sort_dir="Ascending"))
    v.append(visual("funnel", X0, 390, round(third), 230, {"Y": ["Total Patients", "Enrolled Patients", "Engaged Patients"]},
                    title="Population → enrolled → active", objects=LABELS_ON))
    v.append(visual("donutChart", round(X0 + third + 8), 150, round(third), 230,
                    {"Category": [("dim_patient", "engagement_segment")], "Y": ["Total Patients"]}, title="Engagement segments", objects=LABELS_ON))
    v.append(visual("columnChart", round(X0 + third + 8), 390, round(third), 230,
                    {"Category": [("dim_date", "year_month")], "Series": [("dim_event_type", "event_label")], "Y": ["Total Events"]},
                    title="Events by type per month", objects=LEGEND_TOP, sort=("dim_date", "year_month"), sort_dir="Ascending"))
    v.append(visual("pivotTable", round(X0 + 2 * (third + 8)), 150, round(third), 230,
                    {"Rows": [("dim_patient", "age_band")], "Columns": [("dim_geography", "region")], "Values": ["App Engagement Rate %"]},
                    title="Engagement rate: age band × region"))
    v.append(visual("hundredPercentStackedColumnChart", round(X0 + 2 * (third + 8)), 390, round(third), 230,
                    {"Category": [("dim_patient", "age_band")], "Series": [("fact_engagement_event", "channel")], "Y": ["Total Events"]},
                    title="Channel mix by age band", objects=LEGEND_TOP, sort=("dim_patient", "age_band"), sort_dir="Ascending"))
    v.append(visual("tableEx", X0, 630, CW, 80,
                    {"Values": [("dim_patient", "engagement_segment", "Segment"), "Total Patients", "Meaningful Action Rate %", "Events per Active User",
                                "Avg Session Minutes", "Bookings per 100 Enrolled"]}, title="Meaningful-action rate by segment"))
    pages.append(("DigitalEngagement", "4 · Digital Engagement", v))

    # ---------------- Page 5: Wearable Vitals ----------------
    v = [textbox(X0, 8, CW, 40, "Wearable vitals & lifestyle (device users only)")]
    v += rail(STANDARD_RAIL)
    v += kpi_row([("Wearable Adoption %", "Wearable adoption"), ("Avg Daily Steps", "Avg daily steps"), ("Avg Sleep Hours", "Avg sleep hours"),
                  ("Avg Resting HR", "Avg resting HR"), ("Months Meeting 10k Steps %", "Months at 10k+ steps")])
    v.append(visual("lineChart", X0, 150, round(half), 270,
                    {"Category": [("dim_date", "year_month")], "Series": [("dim_patient", "risk_tier")], "Y": ["Avg Daily Steps"]},
                    title="Average daily steps by month and risk tier", objects=LEGEND_TOP, sort=("dim_date", "year_month"), sort_dir="Ascending"))
    v.append(visual("hundredPercentStackedBarChart", round(X0 + half + 8), 150, round(half), 270,
                    {"Category": [("dim_patient", "age_band")], "Series": [("fact_wearable_monthly", "activity_band")], "Y": ["Device Months"]},
                    title="Activity band mix by age band", objects=LEGEND_TOP, sort=("dim_patient", "age_band"), sort_dir="Ascending"))
    v.append(visual("clusteredBarChart", X0, 430, round(third), 280,
                    {"Category": [("dim_patient", "bmi_category")], "Y": ["Median Daily Steps", "Avg Daily Steps"]},
                    title="Steps by BMI category", objects=LEGEND_TOP))
    v.append(visual("hundredPercentStackedBarChart", round(X0 + third + 8), 430, round(third), 280,
                    {"Category": [("dim_patient", "risk_tier")], "Series": [("fact_wearable_monthly", "sleep_band")], "Y": ["Device Months"]},
                    title="Sleep band by risk tier", objects=LEGEND_TOP))
    v.append(visual("tableEx", round(X0 + 2 * (third + 8)), 430, round(third), 280,
                    {"Values": [("dim_patient", "wearable_device", "Device"), "Wearable Users", "Avg Daily Steps", "Avg Active Days per Month", "Avg Resting HR"]},
                    title="Device mix"))
    pages.append(("WearableVitals", "5 · Wearable Vitals", v))

    # ---------------- Page 6: Risk & Outreach ----------------
    v = [textbox(X0, 8, CW, 40, "Risk stratification & outreach")]
    v += rail(STANDARD_RAIL)
    v += kpi_row([("Avg Risk Score", "Avg risk score"), ("High Risk Patients", "High-risk patients"), ("High Risk Share %", "High-risk share"),
                  ("Rising Risk Patients", "Rising-risk patients"), ("Priority Outreach Cohort", "Priority outreach cohort")])
    v.append(visual("clusteredColumnChart", X0, 150, round(third), 230, {"Category": [("dim_patient", "risk_tier")], "Y": ["Patients in Tier"]},
                    title="Risk-tier distribution", objects=LABELS_ON))
    v.append(visual("hundredPercentStackedBarChart", X0, 390, round(third), 320,
                    {"Category": [("dim_geography", "region")], "Series": [("dim_patient", "risk_tier")], "Y": ["Total Patients"]},
                    title="Tier mix by region", objects=LEGEND_TOP))
    v.append(visual("clusteredBarChart", round(X0 + third + 8), 150, round(third), 230,
                    {"Category": [("dim_patient", "risk_tier")],
                     "Y": [("avg", "fact_patient_risk_snapshot", "chronic_points", "Chronic burden"), ("avg", "fact_patient_risk_snapshot", "control_points", "Disease control"),
                           ("avg", "fact_patient_risk_snapshot", "care_gap_points", "Care gaps"), ("avg", "fact_patient_risk_snapshot", "age_points", "Age"),
                           ("avg", "fact_patient_risk_snapshot", "obesity_points", "Obesity"), ("avg", "fact_patient_risk_snapshot", "smoking_points", "Smoking"),
                           ("avg", "fact_patient_risk_snapshot", "inactivity_points", "Inactivity"), ("avg", "fact_patient_risk_snapshot", "social_points", "Deprivation"),
                           ("avg", "fact_patient_risk_snapshot", "access_points", "No PCP")]},
                    title="Average score composition by tier", objects=LEGEND_TOP))
    v.append(visual("clusteredColumnChart", round(X0 + third + 8), 390, round(third), 320,
                    {"Category": [("dim_patient", "risk_tier")], "Y": ["Screening Rate %", "App Engagement Rate %"]},
                    title="Screening rate & engagement by tier", objects={**LEGEND_TOP, **LABELS_ON}))
    v.append(visual("tableEx", round(X0 + 2 * (third + 8)), 150, round(third), 560,
                    {"Values": [("dim_patient", "patient_id", "Patient"), ("dim_patient", "age", "Age"), ("dim_patient", "risk_tier", "Tier"),
                                ("dim_patient", "risk_score", "Score"), ("dim_patient", "chronic_condition_count", "Conditions"),
                                ("dim_patient", "uncontrolled_condition_count", "Uncontrolled"), ("dim_patient", "open_care_gaps", "Open gaps"),
                                ("dim_patient", "engagement_segment", "Engagement")]},
                    title="Priority outreach list (high risk · open gap)", sort=("dim_patient", "risk_score"),
                    filters=[categorical_filter("f_outreach_tier", "dim_patient", "risk_tier", ["High", "Very High"]),
                             advanced_filter("f_outreach_gaps", "dim_patient", "open_care_gaps", 2, 1)]))
    pages.append(("RiskOutreach", "6 · Risk & Outreach", v))

    # ---------------- Page 7: Data Quality ----------------
    v = [textbox(X0, 8, CW, 40, "Data quality & lineage")]
    v += kpi_row([("Total Patients", "Patients after cleaning"), ("BMI Imputed %", "BMI imputed"), ("Screening Flags Downgraded", "Screening flags downgraded"),
                  ("Wearable Months with Missing Steps %", "Device-months missing steps")], x0=10)
    v.append(visual("tableEx", 10, 150, round((PAGE_W - 28) / 2), 560,
                    {"Values": [("data_quality_scorecard", "issue", "Issue"), ("data_quality_scorecard", "rows_before", "Rows before"),
                                ("data_quality_scorecard", "rows_after", "Rows after")]}, title="Data-quality scorecard (before → after cleaning)"))
    v.append(textbox(round(10 + (PAGE_W - 28) / 2 + 8), 150, round((PAGE_W - 28) / 2), 560,
                     "Cleaning rules: duplicates removed on natural keys · region / sex / channel normalised · states to postal codes · "
                     "BMI outside 12–70 nulled and imputed by sex × age band (flag kept) · screenings count only with a documented date inside the "
                     "guideline interval · wearable plausibility: steps 1–50,000, sleep 2–16 h, resting HR 35–200 · events outside enrolment→snapshot dropped. "
                     "Control thresholds: BP < 140/90, HbA1c < 8.0 %, LDL < 130 mg/dL. Risk tiers: Low 0–3 · Moderate 4–7 · High 8–11 · Very High 12+.",
                     size="12pt", bold=False, color_hex="#C7D2E0"))
    pages.append(("DataQuality", "7 · Data Quality", v))

    # ---------------- Page 8: Patient list (drill-through) ----------------
    v = [textbox(X0, 8, CW, 40, "Patient list")]
    v += rail(STANDARD_RAIL[:4])
    v.append(visual("tableEx", X0, 60, CW, 650,
                    {"Values": [("dim_patient", "patient_id", "Patient"), ("dim_patient", "age", "Age"), ("dim_patient", "sex_label", "Sex"),
                                ("dim_geography", "region", "Region"), ("dim_geography", "state", "State"), ("dim_patient", "insurance_type", "Insurance"),
                                ("dim_patient", "risk_tier", "Risk tier"), ("dim_patient", "risk_score", "Score"), ("dim_patient", "has_diabetes", "DM"),
                                ("dim_patient", "has_hypertension", "HTN"), ("dim_patient", "has_obesity", "OB"), ("dim_patient", "open_care_gaps", "Open gaps"),
                                ("dim_patient", "engagement_segment", "Engagement"), ("dim_patient", "wearable_device", "Device"),
                                ("dim_patient", "avg_daily_steps_12m", "Steps/day"), ("dim_patient", "last_event_date", "Last app activity")]},
                    title="Patients in current filter context", sort=("dim_patient", "risk_score")))
    pages.append(("PatientList", "8 · Patient list", v))
    return pages


def write_report(base: Path, theme_src: Path) -> None:
    rp = base / f"{NAME}.Report"
    if rp.exists():
        shutil.rmtree(rp)
    (rp / "definition" / "pages").mkdir(parents=True)
    (rp / "StaticResources" / "RegisteredResources").mkdir(parents=True)
    (rp / "StaticResources" / "SharedResources" / "BaseThemes").mkdir(parents=True)

    (rp / ".platform").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": guid("platform", "report")},
    }, indent=2) + "\n")
    (rp / "definition.pbir").write_text(json.dumps({
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2) + "\n")

    theme_name = "theme_navy_teal.json"
    shutil.copy(theme_src, rp / "StaticResources" / "RegisteredResources" / theme_name)
    base_theme = "CY24SU10"
    (rp / "StaticResources" / "SharedResources" / "BaseThemes" / f"{base_theme}.json").write_text(json.dumps({
        "name": base_theme,
        "dataColors": ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2", "#D9B300", "#D64550"],
        "foreground": "#252423", "foregroundNeutralSecondary": "#605E5C", "foregroundNeutralTertiary": "#B3B0AD",
        "background": "#FFFFFF", "backgroundLight": "#F3F2F1", "backgroundNeutral": "#C8C6C4",
        "tableAccent": "#118DFF", "good": "#1AAB40", "neutral": "#D9B300", "bad": "#D64554",
        "maximum": "#118DFF", "center": "#D9B300", "minimum": "#DEEFFF", "null": "#FF7F48",
        "hyperlink": "#0078D4", "visitedHyperlink": "#0078D4",
        "textClasses": {"callout": {"fontSize": 45, "fontFace": "DIN", "color": "#252423"}, "title": {"fontSize": 12, "fontFace": "DIN", "color": "#252423"},
                        "header": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": "#252423"}, "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": "#252423"}},
    }, indent=2) + "\n")

    (rp / "definition" / "version.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}, indent=2) + "\n")
    (rp / "definition" / "report.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/report/1.0.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": base_theme, "reportVersionAtImport": "5.55", "type": "SharedResources"},
            "customTheme": {"name": theme_name, "reportVersionAtImport": "5.55", "type": "RegisteredResources"},
        },
        "layoutOptimization": "None",
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources", "items": [{"name": base_theme, "path": f"BaseThemes/{base_theme}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": theme_name, "path": theme_name, "type": "CustomTheme"}]},
        ],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized", "defaultDrillFilterOtherVisuals": True,
                     "useEnhancedTooltips": True, "isPersistentUserStateDisabled": False},
        "publicCustomVisuals": [],
    }, indent=2) + "\n")

    pages = build_pages()
    (rp / "definition" / "pages" / "pages.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json", "pageOrder": [p[0] for p in pages], "activePageName": pages[0][0]}, indent=2) + "\n")
    for name, display, visuals in pages:
        pdir = rp / "definition" / "pages" / name
        (pdir / "visuals").mkdir(parents=True)
        page = {"$schema": f"{SCHEMA}/page/1.0.0/schema.json", "name": name, "displayName": display, "displayOption": "FitToPage",
                "height": PAGE_H, "width": PAGE_W}
        if name == "PatientList":
            page["pageBinding"] = {"name": "PatientListDrillthrough", "type": "Drillthrough", "parameters": [
                {"name": "p_region", "boundFilter": "f_dt_region"}, {"name": "p_risk_tier", "boundFilter": "f_dt_risk_tier"}]}
            page["filterConfig"] = {"filters": [{"name": "f_dt_region", "field": col("dim_geography", "region"), "type": "Categorical", "howCreated": "Drillthrough"},
                                                {"name": "f_dt_risk_tier", "field": col("dim_patient", "risk_tier"), "type": "Categorical", "howCreated": "Drillthrough"}]}
        (pdir / "page.json").write_text(json.dumps(page, indent=2) + "\n")
        for vis in visuals:
            (pdir / "visuals" / vis["name"]).mkdir()
            (pdir / "visuals" / vis["name"] / "visual.json").write_text(json.dumps(vis, indent=2) + "\n")


# =============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "powerbi" / "pbip")
    ap.add_argument("--data-folder", default=r"C:\health-analytics\03-population-health-powerbi\data\star_schema",
                    help="Default value of the DataFolder parameter (change it in Power BI: Transform data → Edit parameters)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tables: dict[str, list] = {}
    for csv in sorted((ROOT / "data" / "star_schema").glob("*.csv")):
        tables[csv.stem] = (infer_columns(csv), csv.name)
    tables["data_quality_scorecard"] = (infer_columns(ROOT / "docs" / "data_quality_scorecard.csv"), r"..\..\docs\data_quality_scorecard.csv")

    measures = parse_measures(ROOT / "powerbi" / "measures.dax")
    write_semantic_model(args.out, args.data_folder, tables, measures)
    write_report(args.out, ROOT / "powerbi" / "theme_navy_teal.json")

    (args.out / f"{NAME}.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}}, indent=2) + "\n")
    (args.out / ".gitignore").write_text("# Power BI Desktop local state\n**/.pbi/localSettings.json\n**/.pbi/cache.abf\n**/.pbi/unappliedChanges.json\n")

    n_visuals = sum(len(p[2]) for p in build_pages())
    print(f"PBIP written to {args.out}")
    print(f"  tables: {len(tables) + 1}  measures: {len(measures)}  relationships: {len(RELATIONSHIPS)}  pages: 8  visuals: {n_visuals}")


if __name__ == "__main__":
    main()
