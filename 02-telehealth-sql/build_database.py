"""
Build telehealth.db from the Synthea CSV export.

Pipeline
--------
1. Load Synthea CSVs from data/raw/ (patients, encounters, conditions,
   medications, providers, organizations, payers).
2. Restrict to the study window 2019-01-01 .. 2025-12-31 (seven full years) and to living
   patients with at least one encounter in the window. Drop direct
   identifiers (names, SSN, street address) even though they are synthetic.
3. Assign a visit *modality* (telehealth / in person). Synthea only tags a
   handful of visits as "virtual", far below the 15-20 % telehealth share that
   US ambulatory care has settled at since 2021, and it has no notion of a
   booking or a missed appointment. So two thin simulation layers are added on
   top of the Synthea clinical record:

   a. Modality model: each *eligible* visit (problem, follow-up, symptom,
      check-up or consultation visits; not procedures, immunisations,
      prenatal care, emergency or inpatient stays) is switched to telehealth
      with a probability that depends on calendar year (near zero before
      March 2020, a spike in 2020, settling around 18 %), the patient's age
      band, the visit reason (behavioural health and chronic-disease
      management lean virtual, acute symptoms and physicals lean in person),
      and a per-patient propensity so that telehealth use clusters in
      repeat users, as it does in practice.

   b. Scheduling model: every scheduled-type encounter becomes a completed
      appointment. Missed (no_show) and cancelled appointments are then
      generated with probabilities driven by modality, age band, booking
      lead time, weekday, visit reason and a per-patient reliability effect.

   Both models are seeded (SEED = 42) so the database is reproducible, and
   every parameter lives in this file so the assumptions can be audited or
   changed. Nothing in the clinical record (diagnoses, medications, visit
   dates, costs) is altered.
4. Tag chronic conditions into analyst buckets (condition_group).
5. Write everything into SQLite using sql/schema.sql.

Run:  python build_database.py
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "telehealth.db"
SCHEMA = ROOT / "sql" / "schema.sql"

SEED = 42
STUDY_START = pd.Timestamp("2019-01-01")
STUDY_END = pd.Timestamp("2025-12-31 23:59:59")
REFERENCE_DATE = date(2025, 12, 31)

rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def read_csv(name: str) -> pd.DataFrame:
    path = RAW / f"{name}.csv.gz"
    if not path.exists():
        path = RAW / f"{name}.csv"
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def age_group(age: int) -> str:
    if age < 18:
        return "0-17"
    if age < 35:
        return "18-34"
    if age < 50:
        return "35-49"
    if age < 65:
        return "50-64"
    return "65+"


def years_between(birth: str, ref: date) -> int:
    b = datetime.strptime(birth, "%Y-%m-%d").date()
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


# Chronic-condition buckets. Matching is on the Synthea SNOMED description.
CONDITION_GROUPS: dict[str, list[str]] = {
    "Hypertension": ["Essential hypertension"],
    "Type 2 diabetes": ["Diabetes mellitus type 2", "Type 2 diabetes"],
    "Prediabetes": ["Prediabetes"],
    "Hyperlipidemia": ["Hyperlipidemia"],
    "Heart disease": ["Ischemic heart disease", "Chronic congestive heart failure",
                      "Coronary Heart Disease", "Myocardial infarction"],
    "Asthma": ["Asthma", "Childhood asthma"],
    "COPD": ["Chronic obstructive bronchitis", "Pulmonary emphysema", "COPD"],
    "Chronic kidney disease": ["Chronic kidney disease"],
    "Obesity": ["Body mass index 30+ - obesity", "Body mass index 40+ - severely obese"],
    "Behavioural health": ["Major depressive disorder", "Major depression", "Posttraumatic stress disorder",
                           "Severe anxiety (panic)", "Anxiety disorder", "Child attention deficit disorder",
                           "Attention deficit hyperactivity disorder", "Generalized anxiety disorder",
                           "Bipolar", "Opioid abuse", "Alcoholism", "Drug overdose"],
    "Chronic pain": ["Chronic pain", "Chronic low back pain", "Chronic neck pain", "Fibromyalgia"],
    "Cancer": ["Malignant neoplasm", "Malignant tumor", "Carcinoma", "Non-small cell lung cancer",
               "Neoplasm of prostate", "Metastasis"],
}

BEHAVIOURAL_KEYWORDS = ["anxiety", "depress", "stress disorder", "attention deficit", "bipolar",
                        "mental", "panic", "overdose", "abuse", "alcohol", "misuses"]
CHRONIC_KEYWORDS = ["hypertension", "diabetes", "hyperlipidemia", "heart", "asthma", "bronchitis",
                    "emphysema", "obesity", "chronic"]
# Visit reasons that need hands-on care and are never switched to telehealth:
# dialysis for advanced kidney disease, dental care, pregnancy, injuries and wound care.
IN_PERSON_ONLY_KEYWORDS = ["kidney disease", "dialysis", "renal", "dental", "gingiv", "tooth", "teeth", "caries",
                           "pregnan", "fracture", "laceration", "sprain", "burn", "wound", "injury", "concussion"]

# Encounter descriptions that could plausibly be delivered virtually.
TELEHEALTH_ELIGIBLE_TYPES = {
    "Encounter for problem (procedure)": 1.0,
    "Follow-up encounter (procedure)": 1.3,
    "Follow-up consultation (procedure)": 1.3,
    "Postoperative follow-up visit (procedure)": 1.1,
    "Encounter for symptom (procedure)": 0.9,
    "Encounter for check up (procedure)": 0.7,
    "Consultation for treatment (procedure)": 0.8,
    "Asthma follow-up (regime/therapy)": 1.2,
    "Urgent care clinic (environment)": 0.4,
    "Telemedicine consultation with patient (procedure)": None,  # already virtual
    "Telephone encounter (procedure)": None,
    "Videotelephony encounter (procedure)": None,
    "Indirect encounter (procedure)": None,
}
ELIGIBLE_CLASSES = {"ambulatory", "outpatient", "wellness", "urgentcare"}
SCHEDULED_CLASSES = {"ambulatory", "outpatient", "wellness", "virtual"}  # visits that are booked in advance

# Telehealth probability by year for an "average" eligible visit (before multipliers).
# Calibrated so that telehealth settles near 10 % of all visits and a third of
# eligible visits from 2022 on, in line with US ambulatory care after the pandemic.
YEAR_BASE = {2019: 0.02, 2020: 0.55, 2021: 0.42, 2022: 0.34,
             2023: 0.30, 2024: 0.30, 2025: 0.30}
AGE_MULT_TELE = {"0-17": 0.75, "18-34": 1.35, "35-49": 1.20, "50-64": 0.95, "65+": 0.60}
CLASS_MULT_TELE = {"ambulatory": 1.0, "outpatient": 0.8, "wellness": 0.35, "urgentcare": 0.6}

# No-show model.
NOSHOW_BASE = {"in_person": 0.125, "telehealth": 0.075}
CANCEL_BASE = {"in_person": 0.055, "telehealth": 0.045}
AGE_MULT_NOSHOW = {"0-17": 1.05, "18-34": 1.50, "35-49": 1.15, "50-64": 0.85, "65+": 0.70}
WEEKDAY_MULT_NOSHOW = {0: 1.15, 1: 1.0, 2: 0.95, 3: 0.95, 4: 1.10, 5: 0.9, 6: 0.9}  # Monday .. Sunday


# ---------------------------------------------------------------------------
# 1-2. Load and restrict
# ---------------------------------------------------------------------------
def load_frames() -> dict[str, pd.DataFrame]:
    patients = read_csv("patients")
    encounters = read_csv("encounters")
    conditions = read_csv("conditions")
    medications = read_csv("medications")
    providers = read_csv("providers")
    organizations = read_csv("organizations")
    payers = read_csv("payers")

    encounters["start_ts"] = pd.to_datetime(encounters["START"], utc=True).dt.tz_localize(None)
    encounters["stop_ts"] = pd.to_datetime(encounters["STOP"].replace("", None), utc=True).dt.tz_localize(None)
    encounters = encounters[(encounters["start_ts"] >= STUDY_START) & (encounters["start_ts"] <= STUDY_END)].copy()

    patients = patients[patients["DEATHDATE"] == ""].copy()
    active = set(encounters["PATIENT"]) & set(patients["Id"])
    patients = patients[patients["Id"].isin(active)].copy()
    encounters = encounters[encounters["PATIENT"].isin(active)].copy()
    conditions = conditions[conditions["PATIENT"].isin(active)].copy()
    medications = medications[medications["PATIENT"].isin(active)].copy()
    conditions = conditions[conditions["START"].str[:10] <= "2025-12-31"]
    medications = medications[medications["START"].str[:10] <= "2025-12-31"]

    patients["age_years"] = patients["BIRTHDATE"].map(lambda b: years_between(b, REFERENCE_DATE))
    patients["age_group"] = patients["age_years"].map(age_group)

    return dict(patients=patients, encounters=encounters, conditions=conditions,
                medications=medications, providers=providers, organizations=organizations, payers=payers)


# ---------------------------------------------------------------------------
# 3a. Modality model
# ---------------------------------------------------------------------------
def reason_multiplier(reason: str, description: str) -> float:
    text = f"{reason} {description}".lower()
    if any(k in text for k in IN_PERSON_ONLY_KEYWORDS):
        return 0.0
    if any(k in text for k in BEHAVIOURAL_KEYWORDS):
        return 1.8
    if any(k in text for k in CHRONIC_KEYWORDS):
        return 1.3
    return 1.0


def assign_modality(enc: pd.DataFrame, patients: pd.DataFrame) -> pd.DataFrame:
    enc = enc.merge(patients[["Id", "age_group"]], left_on="PATIENT", right_on="Id", suffixes=("", "_p"))
    # Per-patient propensity: most people sit near 1, a minority are heavy virtual users.
    pid = patients["Id"].to_numpy()
    propensity = pd.Series(rng.lognormal(mean=0.0, sigma=0.55, size=len(pid)), index=pid)
    enc["propensity"] = enc["PATIENT"].map(propensity)

    year = enc["start_ts"].dt.year
    month = enc["start_ts"].dt.month
    base = year.map(YEAR_BASE).fillna(0.0)
    # Telehealth only took off from March 2020.
    base = np.where((year == 2020) & (month < 3), 0.02, base)

    type_mult = enc["DESCRIPTION"].map(TELEHEALTH_ELIGIBLE_TYPES)
    eligible = enc["DESCRIPTION"].isin(TELEHEALTH_ELIGIBLE_TYPES) & enc["ENCOUNTERCLASS"].isin(ELIGIBLE_CLASSES)
    already_virtual = enc["ENCOUNTERCLASS"].eq("virtual") | type_mult.isna() & enc["DESCRIPTION"].isin(TELEHEALTH_ELIGIBLE_TYPES)

    p = (base
         * type_mult.fillna(0).astype(float)
         * enc["age_group"].map(AGE_MULT_TELE)
         * enc["ENCOUNTERCLASS"].map(CLASS_MULT_TELE).fillna(0.0)
         * enc.apply(lambda r: reason_multiplier(r["REASONDESCRIPTION"], r["DESCRIPTION"]), axis=1)
         * enc["propensity"]).clip(upper=0.85)
    p = np.where(eligible, p, 0.0)
    draw = rng.random(len(enc))
    telehealth = already_virtual.to_numpy() | (draw < p)

    enc["modality"] = np.where(telehealth, "telehealth", "in_person")
    return enc


# ---------------------------------------------------------------------------
# 3b. Scheduling model
# ---------------------------------------------------------------------------
def build_appointments(enc: pd.DataFrame, patients: pd.DataFrame) -> pd.DataFrame:
    sched = enc[enc["ENCOUNTERCLASS"].isin(SCHEDULED_CLASSES)].copy()
    sched = sched.sort_values(["PATIENT", "start_ts"]).reset_index(drop=True)

    pid = patients["Id"].to_numpy()
    reliability = pd.Series(rng.lognormal(mean=0.0, sigma=0.45, size=len(pid)), index=pid)
    sched["reliability"] = sched["PATIENT"].map(reliability)

    # Booking lead time depends on visit type: physicals are booked far ahead, problems soon.
    def lead_for(row) -> int:
        d = row["DESCRIPTION"]
        if row["ENCOUNTERCLASS"] == "wellness" or "check up" in d or "General examination" in d:
            return int(np.clip(rng.gamma(4.0, 9.0), 3, 90))
        if "Follow-up" in d or "follow-up" in d:
            return int(np.clip(rng.gamma(3.0, 6.0), 2, 60))
        if "symptom" in d:
            return int(np.clip(rng.gamma(1.5, 1.6), 0, 14))
        return int(np.clip(rng.gamma(2.5, 4.0), 1, 45))

    sched["lead_days"] = sched.apply(lead_for, axis=1)
    sched["visit_category"] = sched["ENCOUNTERCLASS"].replace({"virtual": "ambulatory"})
    sched["reason_mult"] = sched.apply(
        lambda r: 1.3 if any(k in f"{r['REASONDESCRIPTION']} {r['DESCRIPTION']}".lower() for k in BEHAVIOURAL_KEYWORDS) else 1.0,
        axis=1)

    def lead_mult(lead: int) -> float:
        if lead <= 3:
            return 0.7
        if lead <= 14:
            return 1.0
        if lead <= 30:
            return 1.25
        return 1.5

    rows = []
    for r in sched.itertuples(index=False):
        sched_date = r.start_ts.date()
        # Completed appointment (the Synthea encounter itself).
        rows.append(dict(patient_id=r.PATIENT, encounter_id=r.Id, provider_id=r.PROVIDER,
                         scheduled_date=sched_date, booked_date=sched_date - timedelta(days=int(r.lead_days)),
                         lead_days=int(r.lead_days), modality=r.modality, visit_category=r.visit_category,
                         status="completed"))

        # A missed or cancelled earlier slot for the same visit, with probability chosen so the
        # observed no-show rate lands near the target for that segment.
        p_ns = (NOSHOW_BASE[r.modality] * AGE_MULT_NOSHOW[r.age_group] * lead_mult(int(r.lead_days))
                * r.reason_mult * r.reliability)
        p_ns = min(p_ns, 0.45)
        p_cx = min(CANCEL_BASE[r.modality] * (1.2 if r.lead_days > 14 else 1.0) * r.reliability ** 0.5, 0.3)
        for status, p in (("no_show", p_ns), ("cancelled", p_cx)):
            odds = p / (1 - p)
            if rng.random() < odds:
                gap = int(rng.integers(3, 22))
                missed_date = sched_date - timedelta(days=gap)
                # Weekday effect applied as a thinning step: Monday and Friday slots are missed most.
                if status == "no_show" and rng.random() > WEEKDAY_MULT_NOSHOW[missed_date.weekday()] / 1.15:
                    continue
                lead = int(max(1, r.lead_days + rng.integers(-3, 4)))
                rows.append(dict(patient_id=r.PATIENT, encounter_id=None, provider_id=r.PROVIDER,
                                 scheduled_date=missed_date, booked_date=missed_date - timedelta(days=lead),
                                 lead_days=lead, modality=r.modality, visit_category=r.visit_category,
                                 status=status))
    appts = pd.DataFrame(rows)
    appts = appts[(pd.to_datetime(appts["scheduled_date"]) >= STUDY_START)]
    return appts.sort_values(["patient_id", "scheduled_date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. Condition groups
# ---------------------------------------------------------------------------
def tag_condition_group(description: str) -> str | None:
    for group, needles in CONDITION_GROUPS.items():
        if any(n.lower() in description.lower() for n in needles):
            return group
    return None


# ---------------------------------------------------------------------------
# 5. Write SQLite
# ---------------------------------------------------------------------------
def write_db(f: dict[str, pd.DataFrame], enc: pd.DataFrame, appts: pd.DataFrame) -> None:
    """Write all tables. Synthea UUIDs are replaced with integer surrogate keys
    (the patient's UUID is kept in patients.source_id for traceability)."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA.read_text())

    def key_map(ids) -> dict[str, int]:
        return {u: i + 1 for i, u in enumerate(sorted(set(ids)))}

    p = f["patients"].sort_values("Id")
    pmap = key_map(p["Id"])
    con.executemany(
        "INSERT INTO patients VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(pmap[r.Id], r.Id, r.BIRTHDATE, r.DEATHDATE or None, r.GENDER, r.RACE, r.ETHNICITY, r.MARITAL or None,
          r.CITY, r.STATE, r.COUNTY, r.ZIP or None, int(float(r.INCOME)) if r.INCOME else None,
          int(r.age_years), r.age_group) for r in p.itertuples()])

    o = f["organizations"]
    o = o[o["Id"].isin(set(enc["ORGANIZATION"]) | set(f["providers"]["ORGANIZATION"]))]
    omap = key_map(o["Id"])
    con.executemany("INSERT INTO organizations VALUES (?,?,?,?,?)",
                    [(omap[r.Id], r.NAME, r.CITY, r.STATE, r.ZIP) for r in o.itertuples()])

    pr = f["providers"]
    pr = pr[pr["Id"].isin(set(enc["PROVIDER"]))]
    prmap = key_map(pr["Id"])
    con.executemany("INSERT INTO providers VALUES (?,?,?,?,?,?)",
                    [(prmap[r.Id], omap.get(r.ORGANIZATION), r.GENDER, r.SPECIALITY, r.CITY, r.STATE)
                     for r in pr.itertuples()])

    py = f["payers"]
    pymap = key_map(py["Id"])
    con.executemany("INSERT INTO payers VALUES (?,?,?)",
                    [(pymap[r.Id], r.NAME, r.OWNERSHIP) for r in py.itertuples()])

    enc = enc.sort_values(["start_ts", "Id"])
    emap = {u: i + 1 for i, u in enumerate(enc["Id"])}
    con.executemany(
        "INSERT INTO encounters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(emap[r.Id], pmap[r.PATIENT], omap.get(r.ORGANIZATION), prmap.get(r.PROVIDER), pymap.get(r.PAYER),
          r.start_ts.strftime("%Y-%m-%d %H:%M:%S"),
          r.stop_ts.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(r.stop_ts) else None,
          r.start_ts.strftime("%Y-%m-%d"), r.ENCOUNTERCLASS, r.modality, r.CODE, r.DESCRIPTION,
          r.REASONCODE or None, r.REASONDESCRIPTION or None,
          round(float(r.BASE_ENCOUNTER_COST or 0), 2), round(float(r.TOTAL_CLAIM_COST or 0), 2),
          round(float(r.PAYER_COVERAGE or 0), 2))
         for r in enc.itertuples()])

    c = f["conditions"]
    con.executemany(
        "INSERT INTO conditions (patient_id, encounter_id, onset_date, resolved_date, code_system, code, description, condition_group) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(pmap[r.PATIENT], emap.get(r.ENCOUNTER), r.START, r.STOP or None, r.SYSTEM, r.CODE,
          r.DESCRIPTION, tag_condition_group(r.DESCRIPTION)) for r in c.itertuples()])

    m = f["medications"]
    con.executemany(
        "INSERT INTO medications (patient_id, encounter_id, payer_id, start_date, stop_date, code, description, "
        "dispenses, base_cost, total_cost, reason_code, reason_description) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(pmap[r.PATIENT], emap.get(r.ENCOUNTER), pymap.get(r.PAYER),
          r.START[:10], r.STOP[:10] or None, r.CODE, r.DESCRIPTION, int(float(r.DISPENSES or 0)),
          round(float(r.BASE_COST or 0), 2), round(float(r.TOTALCOST or 0), 2),
          r.REASONCODE or None, r.REASONDESCRIPTION or None)
         for r in m.itertuples()])

    con.executemany(
        "INSERT INTO appointments (patient_id, encounter_id, provider_id, scheduled_date, booked_date, lead_days, "
        "modality, visit_category, status) VALUES (?,?,?,?,?,?,?,?,?)",
        [(pmap[r.patient_id], emap.get(r.encounter_id) if r.encounter_id else None, prmap.get(r.provider_id),
          str(r.scheduled_date), str(r.booked_date), int(r.lead_days), r.modality, r.visit_category, r.status)
         for r in appts.itertuples()])

    con.commit()
    con.execute("VACUUM")
    con.close()


def main() -> None:
    f = load_frames()
    enc = assign_modality(f["encounters"], f["patients"])
    appts = build_appointments(enc, f["patients"])
    write_db(f, enc, appts)

    con = sqlite3.connect(DB_PATH)
    for t in ["patients", "encounters", "conditions", "medications", "appointments", "providers", "organizations", "payers"]:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t:14s} {n:>8,}")
    share = con.execute("SELECT ROUND(100.0*SUM(modality='telehealth')/COUNT(*),1) FROM encounters "
                        "WHERE start_date >= '2021-01-01'").fetchone()[0]
    ns = con.execute("SELECT ROUND(100.0*SUM(status='no_show')/COUNT(*),1) FROM appointments").fetchone()[0]
    print(f"telehealth share of all visits 2021-25: {share}%   no-show rate: {ns}%")
    con.close()


if __name__ == "__main__":
    main()
