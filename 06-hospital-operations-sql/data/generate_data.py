"""
Synthetic data generator — Hospital Operations & Bed Utilisation (project 06).

Builds a 15-hospital network for calendar year 2025 (plus a six-week warm-up
from mid-November 2024 so the 1 January bed census is realistic) and writes it
to data/hospital_operations.db using sql/schema.sql.

The data is fully synthetic, but the generator wires in the operational
mechanics an analyst would expect to find in a real extract:

* Demand, not capacity, drives admissions: winter seasonality plus flu surges
  in January and December, weekday-only elective lists, an August elective dip.
* Bed capacity changes over time (winter escalation beds, a ward refurbishment,
  new ICU beds) and is stored as validity ranges.
* Length of stay is log-normal by department and diagnosis, varies by hospital,
  and weekend discharges slip to Monday.
* 30-day readmissions depend on diagnosis, age, disposition and hospital;
  ~12% of readmissions land at a different hospital in the same region.
* ED waits respond to inpatient occupancy (exit block) and nurse absence;
  boarding time rises steeply as the hospital fills; long waits drive
  "left without being seen". One hospital launches a rapid-assessment model
  in June; another loses nursing staff in the second half of the year.

Run:  python data/generate_data.py      (deterministic, seed below)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20250601
rng = np.random.default_rng(SEED)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "hospital_operations.db"
SCHEMA_PATH = ROOT / "sql" / "schema.sql"

START = pd.Timestamp("2024-11-15")          # warm-up start
YEAR_START = pd.Timestamp("2025-01-01")
EXTRACT_TS = pd.Timestamp("2026-01-01")     # data extract: stays open after this have NULL discharge
DAYS = pd.date_range(START, EXTRACT_TS - pd.Timedelta(days=1), freq="D")

# --------------------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------------------
DEPARTMENTS = pd.DataFrame(
    [
        # id, code, name, service line, inpatient, target occ, patients per RN
        (1, "ED",   "Emergency Department",   "Emergency",        0, 0.850, 3.0),
        (2, "ICU",  "Intensive Care",         "Critical Care",    1, 0.800, 1.5),
        (3, "MED",  "General Medicine",       "Medicine",         1, 0.900, 7.0),
        (4, "SURG", "General Surgery",        "Surgery",          1, 0.850, 6.0),
        (5, "CARD", "Cardiology",             "Medicine",         1, 0.850, 5.0),
        (6, "ORTH", "Trauma & Orthopaedics",  "Surgery",          1, 0.850, 6.0),
        (7, "PAED", "Paediatrics",            "Women & Children", 1, 0.750, 4.0),
        (8, "MAT",  "Maternity",              "Women & Children", 1, 0.750, 5.0),
        (9, "ONC",  "Oncology",               "Medicine",         1, 0.850, 5.0),
    ],
    columns=["department_id", "department_code", "department_name", "service_line",
             "is_inpatient", "target_occupancy", "target_patients_per_nurse"],
)
DEPT_ID = dict(zip(DEPARTMENTS.department_code, DEPARTMENTS.department_id))
INPATIENT = [c for c in DEPARTMENTS.department_code if c != "ED"]

# Staffed beds by hospital type (ED = treatment bays); scaled per hospital below.
BED_SCALE = 0.62  # keeps the SQLite file small enough to version-control
BED_TEMPLATE = {
    "Teaching":         dict(ED=30, ICU=16, MED=64, SURG=40, CARD=22, ORTH=20, PAED=16, MAT=18, ONC=18),
    "Regional General": dict(ED=18, ICU=8,  MED=38, SURG=24, CARD=12, ORTH=14, PAED=10, MAT=12, ONC=10),
    "Community":        dict(ED=10, ICU=4,  MED=24, SURG=12, CARD=0,  ORTH=8,  PAED=0,  MAT=8,  ONC=0),
}

HOSPITALS = pd.DataFrame(
    [
        # code, name, type, region, city, opened, size factor, occupancy pressure, LOS mult, readmit base, ED efficiency, nurse vacancy
        ("SAU", "St Aldric University Hospital",   "Teaching",         "North",   "Northam",      1962, 1.10, 0.95, 1.12, 0.090, 1.15, 0.06),
        ("RVG", "Riverside General Hospital",      "Regional General", "North",   "Kelby",        1978, 1.00, 0.90, 1.00, 0.110, 1.00, 0.04),
        ("MRC", "Moorcroft Community Hospital",    "Community",        "North",   "Moorcroft",    1991, 0.95, 0.80, 0.92, 0.125, 0.90, 0.03),
        ("QET", "Queen Eleanor Teaching Hospital", "Teaching",         "Central", "Castleford",   1955, 1.05, 0.96, 1.18, 0.085, 1.25, 0.08),
        ("KMR", "Kingsmead Regional Hospital",     "Regional General", "Central", "Kingsmead",    1983, 0.95, 0.92, 1.05, 0.100, 1.05, 0.05),
        ("ASH", "Ashby Vale Community Hospital",   "Community",        "Central", "Ashby",        1999, 0.90, 0.78, 0.90, 0.120, 0.85, 0.02),
        ("HBV", "Harbourview Medical Centre",      "Regional General", "East",    "Port Harrow",  1986, 1.10, 0.93, 1.02, 0.105, 1.20, 0.05),
        ("EFG", "Eastfield General Hospital",      "Regional General", "East",    "Eastfield",    1974, 1.00, 0.86, 0.95, 0.095, 0.95, 0.03),
        ("SLC", "Saltmarsh Community Hospital",     "Community",        "East",    "Saltmarsh",    2004, 0.85, 0.76, 0.88, 0.130, 0.90, 0.03),
        ("WBG", "Westbrook General Hospital",      "Regional General", "West",    "Westbrook",    1980, 1.05, 0.89, 1.00, 0.100, 1.00, 0.04),
        ("PNT", "Pennant University Hospital",     "Teaching",         "West",    "Pennant",      1968, 1.00, 0.91, 1.06, 0.080, 1.05, 0.05),
        ("CLR", "Clearwater Regional Hospital",    "Regional General", "West",    "Clearwater",   1989, 0.90, 0.88, 1.08, 0.115, 1.10, 0.05),
        ("SDN", "Southdown General Hospital",      "Regional General", "South",   "Southdown",    1976, 1.00, 0.94, 1.10, 0.105, 1.15, 0.06),
        ("BRK", "Bramble Rock Community Hospital", "Community",        "South",   "Bramble Rock", 2008, 0.90, 0.79, 0.92, 0.120, 0.95, 0.03),
        ("TMS", "Thameside General Hospital",      "Regional General", "South",   "Thameside",    1971, 1.00, 0.87, 0.98, 0.100, 1.00, 0.04),
    ],
    columns=["hospital_code", "hospital_name", "hospital_type", "region", "city", "opened_year",
             "size", "pressure", "los_mult", "readmit_base", "ed_eff", "vacancy"],
)
HOSPITALS.insert(0, "hospital_id", np.arange(1, len(HOSPITALS) + 1))
H_IMPROVE = HOSPITALS.set_index("hospital_code").loc["HBV", "hospital_id"]   # rapid-assessment model from June
H_STAFF_LOSS = HOSPITALS.set_index("hospital_code").loc["SDN", "hospital_id"]  # nursing attrition in H2

# Department behaviour: relative occupancy, mean LOS (days), LOS sigma, elective share, winter amplitude
DEPT_PARAMS = {
    "ICU":  dict(rel_occ=0.93, los=3.4, sigma=0.80, elective=0.15, winter=0.08, flu=0.08),
    "MED":  dict(rel_occ=1.00, los=5.6, sigma=0.80, elective=0.03, winter=0.07, flu=0.07),
    "SURG": dict(rel_occ=0.92, los=3.6, sigma=0.75, elective=0.50, winter=0.00, flu=0.00),
    "CARD": dict(rel_occ=0.94, los=4.0, sigma=0.75, elective=0.20, winter=0.05, flu=0.02),
    "ORTH": dict(rel_occ=0.92, los=4.4, sigma=0.75, elective=0.50, winter=0.04, flu=0.00),
    "PAED": dict(rel_occ=0.80, los=2.0, sigma=0.75, elective=0.10, winter=0.16, flu=0.12),
    "MAT":  dict(rel_occ=0.78, los=2.2, sigma=0.55, elective=0.30, winter=-0.02, flu=0.00),
    "ONC":  dict(rel_occ=0.92, los=6.0, sigma=0.80, elective=0.40, winter=0.01, flu=0.02),
}

# Diagnosis groups: (name, mode E/L/B, weight, LOS multiplier, readmission multiplier)
DX = {
    "ICU": [("Sepsis (critical)", "E", .35, 1.2, 1.2), ("Respiratory failure", "E", .30, 1.1, 1.3),
            ("Post-operative critical care", "L", .20, 0.6, 0.7), ("Cardiac arrest", "E", .15, 1.0, 1.0)],
    "MED": [("Pneumonia", "E", .20, 1.1, 1.1), ("COPD exacerbation", "E", .14, 1.0, 1.7),
            ("Sepsis", "E", .12, 1.3, 1.3), ("Urinary tract infection", "E", .12, 0.8, 1.0),
            ("Stroke", "E", .10, 1.6, 0.9), ("Diabetes complications", "B", .10, 0.8, 1.3),
            ("Frailty & falls", "E", .14, 1.4, 1.3), ("Gastrointestinal bleed", "E", .08, 0.9, 1.1)],
    "CARD": [("Heart failure", "E", .30, 1.3, 2.0), ("Acute myocardial infarction", "E", .25, 1.0, 1.1),
             ("Arrhythmia", "B", .20, 0.7, 0.9), ("Chest pain (low risk)", "E", .15, 0.4, 0.6),
             ("Cardiac catheterisation", "L", .10, 0.5, 0.6)],
    "SURG": [("Appendicitis", "E", .25, 0.8, 0.7), ("Cholecystectomy", "B", .25, 0.7, 0.8),
             ("Hernia repair", "L", .20, 0.4, 0.5), ("Bowel obstruction", "E", .15, 1.5, 1.4),
             ("Colorectal resection", "L", .15, 1.8, 1.5)],
    "ORTH": [("Hip fracture", "E", .30, 1.6, 1.4), ("Hip replacement", "L", .22, 0.9, 0.7),
             ("Knee replacement", "L", .22, 0.8, 0.7), ("Spinal surgery", "L", .10, 1.2, 0.9),
             ("Minor fractures & soft tissue", "E", .16, 0.4, 0.5)],
    "PAED": [("Bronchiolitis", "E", .35, 1.0, 1.2), ("Asthma", "E", .25, 0.8, 1.2),
             ("Gastroenteritis", "E", .25, 0.7, 0.8), ("Paediatric surgery", "L", .15, 1.0, 0.6)],
    "MAT": [("Spontaneous vaginal delivery", "E", .50, 0.8, 0.5), ("Caesarean section", "B", .25, 1.5, 0.8),
            ("Induction of labour", "L", .15, 1.1, 0.5), ("Antenatal complication", "E", .10, 1.0, 1.2)],
    "ONC": [("Chemotherapy complication", "E", .30, 1.0, 1.6), ("Febrile neutropenia", "E", .20, 0.9, 1.5),
            ("Oncology surgery", "L", .30, 1.1, 0.9), ("Palliative care", "E", .20, 1.5, 0.7)],
}

DEATH_P = dict(ICU=0.12, MED=0.035, ONC=0.06, CARD=0.025, ORTH=0.01, SURG=0.005, PAED=0.001, MAT=0.0005)

# ED arrival profile by hour (relative), peaking late morning to early evening
ED_HOUR = np.array([2.4, 1.9, 1.6, 1.4, 1.3, 1.4, 2.0, 3.3, 4.8, 5.8, 6.3, 6.4,
                    6.2, 6.0, 5.9, 5.8, 5.8, 5.7, 5.4, 5.0, 4.5, 3.9, 3.3, 2.8])
ED_HOUR = ED_HOUR / ED_HOUR.sum()
WAIT_HOUR_FACTOR = np.array([0.9, 0.85, 0.8, 0.75, 0.7, 0.7, 0.75, 0.8, 0.9, 1.0, 1.1, 1.15,
                             1.2, 1.25, 1.3, 1.3, 1.35, 1.4, 1.45, 1.45, 1.4, 1.3, 1.15, 1.0])
DOW_EMERG = np.array([1.10, 1.03, 1.00, 0.99, 1.00, 0.94, 0.94])  # Mon..Sun


def season(day: pd.DatetimeIndex, amp: float, flu: float) -> np.ndarray:
    """Winter-peaking seasonality + flu surges centred on mid-Jan and late Dec."""
    doy = day.dayofyear.values
    base = 1 + amp * np.cos(2 * np.pi * (doy - 20) / 365.25)
    ord_days = (day - pd.Timestamp("2025-01-12")).days.values
    surge = np.exp(-0.5 * (ord_days / 14) ** 2)
    ord_days2 = (day - pd.Timestamp("2025-12-22")).days.values
    surge += np.exp(-0.5 * (ord_days2 / 12) ** 2)
    return base + flu * surge


# --------------------------------------------------------------------------------------
# Bed capacity (slowly changing)
# --------------------------------------------------------------------------------------
def build_capacity() -> pd.DataFrame:
    rows = []
    escalation_hospitals = {"SAU", "QET", "KMR", "HBV", "SDN", "PNT"}
    refurb = {"RVG": ("2025-07-01", "2025-08-31"), "WBG": ("2025-06-02", "2025-08-17")}
    new_icu = {"QET", "SDN"}
    for h in HOSPITALS.itertuples():
        tpl = BED_TEMPLATE[h.hospital_type]
        for code, beds in tpl.items():
            if beds == 0:
                continue
            base = max(4, int(round(beds * h.size * BED_SCALE)))
            d = DEPT_ID[code]
            if code == "MED" and h.hospital_code in escalation_hospitals:
                extra = max(4, int(round(base * 0.12)))
                rows += [
                    (h.hospital_id, d, "2024-11-15", "2025-01-05", base, "Baseline establishment"),
                    (h.hospital_id, d, "2025-01-06", "2025-03-30", base + extra, "Winter escalation beds"),
                    (h.hospital_id, d, "2025-03-31", "2025-11-30", base, "Escalation beds closed"),
                    (h.hospital_id, d, "2025-12-01", None, base + extra, "Winter escalation beds"),
                ]
            elif code == "SURG" and h.hospital_code in refurb:
                s, e = refurb[h.hospital_code]
                rows += [
                    (h.hospital_id, d, "2024-11-15", (pd.Timestamp(s) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), base, "Baseline establishment"),
                    (h.hospital_id, d, s, e, int(round(base * 0.7)), "Ward refurbishment"),
                    (h.hospital_id, d, (pd.Timestamp(e) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), None, base, "Ward reopened"),
                ]
            elif code == "ICU" and h.hospital_code in new_icu:
                rows += [
                    (h.hospital_id, d, "2024-11-15", "2025-09-30", base, "Baseline establishment"),
                    (h.hospital_id, d, "2025-10-01", None, base + 4, "Critical care expansion"),
                ]
            else:
                rows.append((h.hospital_id, d, "2024-11-15", None, base, "Baseline establishment"))
    cap = pd.DataFrame(rows, columns=["hospital_id", "department_id", "effective_from",
                                      "effective_to", "staffed_beds", "change_reason"])
    cap.insert(0, "capacity_id", np.arange(1, len(cap) + 1))
    return cap


def daily_beds(cap: pd.DataFrame) -> pd.DataFrame:
    """Expand validity ranges to one row per hospital/department/day."""
    out = []
    for r in cap.itertuples():
        end = pd.Timestamp(r.effective_to) if pd.notna(r.effective_to) else DAYS[-1]
        days = pd.date_range(r.effective_from, end, freq="D")
        out.append(pd.DataFrame({"hospital_id": r.hospital_id, "department_id": r.department_id,
                                 "day": days, "beds": r.staffed_beds}))
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------------------
# Admissions
# --------------------------------------------------------------------------------------
def sample_dx(code: str, elective: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dx = DX[code]
    names = np.array([d[0] for d in dx])
    losm = np.array([d[3] for d in dx])
    rdm = np.array([d[4] for d in dx])
    w_em = np.array([d[2] if d[1] in "EB" else 0 for d in dx], dtype=float)
    w_el = np.array([d[2] if d[1] in "LB" else 0 for d in dx], dtype=float)
    idx = np.where(elective,
                   rng.choice(len(dx), size=len(elective), p=w_el / w_el.sum()),
                   rng.choice(len(dx), size=len(elective), p=w_em / w_em.sum()))
    return names[idx], losm[idx], rdm[idx]


def sample_age(code: str, dx_names: np.ndarray) -> np.ndarray:
    n = len(dx_names)
    if code == "PAED":
        return rng.integers(0, 16, n)
    if code == "MAT":
        return np.clip(rng.normal(31, 5.5, n), 16, 46).astype(int)
    if code == "SURG":
        return np.clip(rng.normal(54, 18, n), 18, 97).astype(int)
    if code == "ORTH":
        age = np.clip(rng.normal(66, 14, n), 18, 97)
        age = np.where(dx_names == "Hip fracture", np.clip(rng.normal(82, 7, n), 55, 102), age)
        age = np.where(dx_names == "Minor fractures & soft tissue", np.clip(rng.normal(42, 18, n), 18, 95), age)
        return age.astype(int)
    return np.clip(rng.normal(68, 15, n), 18, 102).astype(int)


def sample_los(code: str, n: int, mult: np.ndarray) -> np.ndarray:
    p = DEPT_PARAMS[code]
    mu = np.log(p["los"]) - p["sigma"] ** 2 / 2
    return rng.lognormal(mu, p["sigma"], n) * mult


def discharge_times(admit: pd.Series, los_days: np.ndarray) -> pd.Series:
    """Discharge clock time clusters 11:00-17:00; weekend discharges often slip to Monday."""
    raw = admit + pd.to_timedelta(los_days, unit="D")
    ddate = raw.dt.normalize()
    hour = np.clip(rng.normal(14.2, 2.4, len(raw)), 8, 22)
    dis = ddate + pd.to_timedelta(hour * 60, unit="min")
    dow = dis.dt.dayofweek.values
    slip = (dow >= 5) & (rng.random(len(dis)) < 0.30)
    dis = dis + pd.to_timedelta(np.where(slip, 7 - dow, 0), unit="D")
    # too-early discharges (same-day) get a minimum 3-hour stay
    too_early = dis < admit + pd.Timedelta(hours=3)
    dis = dis.where(~too_early, admit + pd.to_timedelta(rng.uniform(3, 10, len(dis)), unit="h"))
    return dis.dt.floor("min")


def disposition(code: str, age: np.ndarray) -> np.ndarray:
    n = len(age)
    u = rng.random(n)
    out = np.full(n, "Home", dtype=object)
    p_death = DEATH_P[code] * np.where(age >= 80, 1.8, 1.0)
    p_transfer = 0.02
    p_ama = 0.015 if code in ("MED", "CARD", "SURG") else 0.004
    p_care = np.where(age >= 75, 0.14, 0.01)
    p_support = np.where(age >= 65, 0.20, 0.03)
    c1 = p_death
    c2 = c1 + p_transfer
    c3 = c2 + p_ama
    c4 = c3 + p_care
    c5 = c4 + p_support
    out[u < c5] = "Home with support"
    out[u < c4] = "Care home / rehab"
    out[u < c3] = "Left against medical advice"
    out[u < c2] = "Transferred to another hospital"
    out[u < c1] = "Died"
    return out


def expected_los_mult(code: str) -> float:
    """Mean LOS multiplier implied by the diagnosis mix, older-patient uplift and weekend slippage."""
    dx = DX[code]
    el = DEPT_PARAMS[code]["elective"]
    w_em = np.array([d[2] if d[1] in "EB" else 0 for d in dx])
    w_el = np.array([d[2] if d[1] in "LB" else 0 for d in dx])
    m = np.array([d[3] for d in dx])
    mix = (1 - el) * (w_em @ m) / w_em.sum() + (el * (w_el @ m) / w_el.sum() if w_el.sum() else 0)
    older = 1.03 if code in ("MED", "CARD", "ONC", "ICU", "ORTH") else 1.0
    return mix * older * 1.03


def base_admissions(beds_day: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for h in HOSPITALS.itertuples():
        for code in INPATIENT:
            d = DEPT_ID[code]
            bd = beds_day[(beds_day.hospital_id == h.hospital_id) & (beds_day.department_id == d)]
            if bd.empty:
                continue
            p = DEPT_PARAMS[code]
            base_beds = bd.beds.iloc[0]
            days = pd.DatetimeIndex(bd.day.values)
            occ_target = min(h.pressure * p["rel_occ"], 0.99)
            demand = occ_target * base_beds * season(days, p["winter"], p["flu"])
            # readmissions are layered on later (~10% of volume, and they skew
            # towards general medicine) so trim the base rate accordingly
            trim = {"MED": 0.78, "CARD": 0.86, "PAED": 0.86}.get(code, 0.93)
            lam = trim * demand / (p["los"] * h.los_mult * expected_los_mult(code))
            el_share = p["elective"]
            dow = days.dayofweek.values
            lam_em = lam * (1 - el_share) * DOW_EMERG[dow]
            el_mod = np.where(days.month == 8, 0.80, 1.0)
            xmas = (days >= "2024-12-22") & (days <= "2025-01-02") | (days >= "2025-12-22")
            el_mod = np.where(xmas, 0.25, el_mod)
            if code == "SURG" and h.hospital_code in ("RVG", "WBG"):
                refurb = (days >= "2025-06-02") & (days <= "2025-08-31")
                el_mod = np.where(refurb, 0.55, el_mod)
            lam_el = np.where(dow < 5, lam * el_share * 7 / 5, 0) * el_mod
            n_em = rng.poisson(lam_em)
            n_el = rng.poisson(lam_el)

            # emergency admit times: ED arrivals + ~5h processing => afternoon/evening peak
            em_day = np.repeat(days.values, n_em)
            em_hour = (rng.choice(24, size=n_em.sum(), p=ED_HOUR) + rng.normal(5, 2, n_em.sum())) % 24
            em_ts = pd.to_datetime(em_day) + pd.to_timedelta(em_hour * 60, unit="min")
            el_day = np.repeat(days.values, n_el)
            el_hour = np.clip(rng.normal(8.5, 1.5, n_el.sum()), 6.5, 14)
            el_ts = pd.to_datetime(el_day) + pd.to_timedelta(el_hour * 60, unit="min")

            admit = pd.Series(np.concatenate([em_ts.values, el_ts.values])).dt.floor("min")
            elective = np.r_[np.zeros(n_em.sum(), bool), np.ones(n_el.sum(), bool)]
            frames.append(pd.DataFrame({"hospital_id": h.hospital_id, "department_id": d, "dept": code,
                                        "admit_ts": admit, "elective": elective}))
    return pd.concat(frames, ignore_index=True)


def enrich(adm: pd.DataFrame, hosp_attr: pd.DataFrame) -> pd.DataFrame:
    """Add diagnosis, age, LOS, discharge time and disposition, department by department."""
    parts = []
    for code, g in adm.groupby("dept", sort=False):
        g = g.copy()
        n = len(g)
        dx, losm, rdm = sample_dx(code, g.elective.values)
        g["dx"] = dx
        g["rd_mult"] = rdm
        age = g["age"].values if "age" in g and g["age"].notna().all() else sample_age(code, dx)
        g["age"] = age
        h_los = hosp_attr.loc[g.hospital_id.values, "los_mult"].values
        los = sample_los(code, n, losm * h_los * np.where(age >= 80, 1.15, 1.0))
        g["discharge_ts"] = discharge_times(g.admit_ts.reset_index(drop=True), los).values
        g["disposition"] = disposition(code, age)
        parts.append(g)
    return pd.concat(parts).sort_index()


def readmission_rounds(adm: pd.DataFrame, hosp_attr: pd.DataFrame, beds_depts: set) -> pd.DataFrame:
    """Generate unplanned returns: 30-day readmissions (chained) and some later returns."""
    by_region = HOSPITALS.groupby("region").hospital_id.apply(list).to_dict()
    region_of = dict(zip(HOSPITALS.hospital_id, HOSPITALS.region))
    all_new = []
    index = adm
    for rnd in range(3):
        eligible = index[~index.disposition.isin(["Died", "Transferred to another hospital"])]
        p = (hosp_attr.loc[eligible.hospital_id.values, "readmit_base"].values
             * eligible.rd_mult.values
             * np.where(eligible.age.values >= 75, 1.25, 1.0)
             * np.where(eligible.disposition.values == "Left against medical advice", 2.2, 1.0)
             * np.where(eligible.disposition.values == "Care home / rehab", 1.2, 1.0)
             * np.where(eligible.discharge_ts.dt.dayofweek.values >= 4, 1.12, 1.0)
             * np.where(eligible.elective.values, 0.55, 1.0))
        hit30 = rng.random(len(eligible)) < p
        # later returns (31-240 days) — not counted as 30-day readmissions
        hit_late = (~hit30) & (rng.random(len(eligible)) < (0.05 if rnd == 0 else 0.0))
        src = pd.concat([eligible[hit30].assign(late=False), eligible[hit_late].assign(late=True)])
        if src.empty:
            break
        gap = np.where(src.late, rng.uniform(31, 240, len(src)),
                       np.minimum(0.4 + rng.gamma(1.1, 8.0, len(src)), 29.9))
        new_admit = (src.discharge_ts + pd.to_timedelta(gap, unit="D")).dt.floor("min")
        new = pd.DataFrame({
            "hospital_id": src.hospital_id.values,
            "department_id": src.department_id.values,
            "dept": src.dept.values,
            "admit_ts": new_admit.values,
            "elective": False,
            "patient_key": src.patient_key.values,
            "age": src.age.values,
        })
        # department of return: mostly same specialty, otherwise general medicine
        to_med = (rng.random(len(new)) < 0.30) & ~new.dept.isin(["PAED", "MAT", "MED"])
        new.loc[to_med, "dept"] = "MED"
        # ~12% present to a different hospital in the same region
        move = rng.random(len(new)) < 0.12
        for i in np.where(move)[0]:
            options = [x for x in by_region[region_of[new.hospital_id.iat[i]]] if x != new.hospital_id.iat[i]]
            new.iat[i, 0] = rng.choice(options)
        # fall back to MED where the receiving hospital lacks the specialty
        new["department_id"] = new.dept.map(DEPT_ID)
        missing = [(h, d) not in beds_depts for h, d in zip(new.hospital_id, new.department_id)]
        new.loc[missing, "dept"] = "MED"
        new["department_id"] = new.dept.map(DEPT_ID)
        new = new[new.admit_ts < EXTRACT_TS]
        new = enrich(new.reset_index(drop=True), hosp_attr)
        all_new.append(new)
        index = new[new.admit_ts < EXTRACT_TS]
    return pd.concat(all_new, ignore_index=True)


def remove_overlaps(adm: pd.DataFrame) -> pd.DataFrame:
    for _ in range(5):
        adm = adm.sort_values(["patient_key", "admit_ts"]).reset_index(drop=True)
        prev_dis = adm.groupby("patient_key").discharge_ts.shift()
        bad = adm.admit_ts <= prev_dis
        if not bad.any():
            break
        adm = adm[~bad]
    return adm.reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Census helpers
# --------------------------------------------------------------------------------------
def midnight_census(adm: pd.DataFrame) -> pd.DataFrame:
    """Occupied beds at 23:59 per hospital/department/day (same logic as SQL query 01)."""
    a = adm.copy()
    a["in_day"] = a.admit_ts.dt.normalize()
    a["out_day"] = a.discharge_ts.fillna(EXTRACT_TS + pd.Timedelta(days=400)).dt.normalize()
    ev = pd.concat([
        a.groupby(["hospital_id", "department_id", "in_day"]).size().rename("n").reset_index().rename(columns={"in_day": "day"}),
        a.groupby(["hospital_id", "department_id", "out_day"]).size().mul(-1).rename("n").reset_index().rename(columns={"out_day": "day"}),
    ])
    ev = ev.groupby(["hospital_id", "department_id", "day"]).n.sum().reset_index()
    grid = pd.MultiIndex.from_product([HOSPITALS.hospital_id, DEPARTMENTS.department_id, DAYS],
                                      names=["hospital_id", "department_id", "day"]).to_frame(index=False)
    grid = grid.merge(ev, how="left").fillna({"n": 0})
    grid["census"] = grid.groupby(["hospital_id", "department_id"]).n.cumsum()
    return grid.drop(columns="n")


# --------------------------------------------------------------------------------------
# Staffing
# --------------------------------------------------------------------------------------
def build_staffing(beds_day: pd.DataFrame) -> pd.DataFrame:
    dept = DEPARTMENTS.set_index("department_id")
    b = beds_day[beds_day.day >= YEAR_START].copy()
    b = b.merge(HOSPITALS[["hospital_id", "vacancy"]], on="hospital_id")
    ratio = dept.loc[b.department_id, "target_patients_per_nurse"].values.astype(float)
    target = dept.loc[b.department_id, "target_occupancy"].values.astype(float)
    # rosters are set against the baseline establishment, so escalation beds are staffed thinly
    base_beds = b.groupby(["hospital_id", "department_id"]).beds.transform("min")
    planned = base_beds * target / ratio
    flu = season(pd.DatetimeIndex(b.day), 0.0, 1.0) - 1
    out = []
    for shift, factor in (("Day", 1.0), ("Night", 0.85)):
        rost = np.maximum(1, np.round(planned * factor)).astype(int)
        vac = b.vacancy.values + np.where((b.hospital_id.values == H_STAFF_LOSS) & (b.day.values >= np.datetime64("2025-07-01")), 0.09, 0)
        p_abs = np.clip(0.045 + vac + 0.05 * flu, 0, 0.5)
        absent = rng.binomial(rost, p_abs)
        agency = rng.binomial(absent, 0.55)
        docs_base = np.where(b.department_id.values == DEPT_ID["ICU"], b.beds / 4, b.beds / (10 if shift == "Day" else 22))
        docs = np.maximum(1, np.round(docs_base) - rng.binomial(2, 0.1, len(b)))
        out.append(pd.DataFrame({
            "hospital_id": b.hospital_id.values, "department_id": b.department_id.values,
            "shift_date": b.day.dt.strftime("%Y-%m-%d").values, "shift_type": shift,
            "rostered_nurses": rost, "nurses_on_duty": rost - absent + agency,
            "agency_nurses": agency, "doctors_on_duty": docs.astype(int),
        }))
    return pd.concat(out, ignore_index=True).sort_values(["hospital_id", "department_id", "shift_date", "shift_type"])


# --------------------------------------------------------------------------------------
# Emergency department
# --------------------------------------------------------------------------------------
def wait_minutes(triage: np.ndarray, hour: np.ndarray, pressure: np.ndarray) -> np.ndarray:
    base = np.array([0, 3, 14, 38, 52, 58])[triage]
    w = base * WAIT_HOUR_FACTOR[hour] * pressure * rng.lognormal(-0.15, 0.55, len(triage))
    return np.where(triage == 1, rng.uniform(0, 4, len(triage)), w)


def build_er(adm: pd.DataFrame, hosp_occ: pd.DataFrame, staffing: pd.DataFrame) -> pd.DataFrame:
    occ = hosp_occ.set_index(["hospital_id", "day"]).occ
    ed_staff = staffing[staffing.department_id == DEPT_ID["ED"]].groupby(["hospital_id", "shift_date"]) \
        .apply(lambda g: g.rostered_nurses.sum() / max(g.nurses_on_duty.sum(), 1)).rename("staff_ratio")
    ed_staff.index = ed_staff.index.set_levels(pd.to_datetime(ed_staff.index.levels[1]), level=1)
    h_eff = HOSPITALS.set_index("hospital_id").ed_eff

    def pressure_for(hid: np.ndarray, day: pd.Series) -> np.ndarray:
        key = pd.MultiIndex.from_arrays([hid, day.dt.normalize()])
        o = occ.reindex(key).fillna(0.85).values
        s = ed_staff.reindex(key).fillna(1.0).values
        eff = h_eff.loc[hid].values
        improve = (hid == H_IMPROVE) & (day.values >= np.datetime64("2025-06-01"))
        eff = eff * np.where(improve, 0.60, 1.0)
        return np.exp(3.2 * (o - 0.85)) * s ** 1.5 * eff, o

    # --- admitted via ED: back-calculate the ED journey from the admission time
    ed_adm = adm[adm.admission_source == "Emergency Department"]
    n = len(ed_adm)
    icu = ed_adm.department_id.values == DEPT_ID["ICU"]
    tri = np.where(icu, rng.choice([1, 2, 3], n, p=[.3, .5, .2]),
                   rng.choice([1, 2, 3, 4, 5], n, p=[.03, .24, .52, .19, .02]))
    approx_arrival = ed_adm.admit_ts - pd.Timedelta(hours=5)
    press, o = pressure_for(ed_adm.hospital_id.values, approx_arrival)
    w = wait_minutes(tri, approx_arrival.dt.hour.values, press)
    assess = rng.lognormal(np.log(np.where(tri <= 2, 70, 115)), 0.45, n)
    board = rng.lognormal(np.log(40), 0.75, n) * np.exp(8.0 * (o - 0.85)) * np.where(icu, 0.6, 1.0)
    admit_ts = ed_adm.admit_ts.reset_index(drop=True)
    decision = (admit_ts - pd.to_timedelta(board, unit="min")).dt.floor("min")
    seen = (decision - pd.to_timedelta(assess, unit="min")).dt.floor("min")
    arrival = (seen - pd.to_timedelta(w, unit="min")).dt.floor("min")
    admitted = pd.DataFrame({
        "patient_id": ed_adm.patient_id.values, "hospital_id": ed_adm.hospital_id.values,
        "arrival_ts": arrival, "triage_category": tri, "provider_seen_ts": seen,
        "decision_to_admit_ts": decision, "departure_ts": admit_ts,
        "er_disposition": "Admitted", "admission_id": ed_adm.admission_id.values,
    })

    # --- not admitted: volume ~2.4x the ED-admitted volume, same seasonality
    daily = admitted.assign(day=admitted.arrival_ts.dt.normalize()).groupby(["hospital_id", "day"]).size()
    frames = []
    for hid in HOSPITALS.hospital_id:
        s = daily.loc[hid].reindex(DAYS, fill_value=0)
        smooth = s.rolling(28, center=True, min_periods=1).mean().values
        dow = DAYS.dayofweek.values
        lam = smooth * 2.4 * np.array([1.14, 1.03, 1.0, 0.98, 0.98, 0.93, 0.94])[dow]
        cnt = rng.poisson(lam)
        day = np.repeat(DAYS.values, cnt)
        hour = rng.choice(24, size=cnt.sum(), p=ED_HOUR)
        arr = pd.Series(pd.to_datetime(day) + pd.to_timedelta(hour * 60 + rng.integers(0, 60, cnt.sum()), unit="min"))
        frames.append(pd.DataFrame({"hospital_id": hid, "arrival_ts": arr, "hour": hour}))
    na = pd.concat(frames, ignore_index=True)
    m = len(na)
    tri = rng.choice([1, 2, 3, 4, 5], m, p=[.002, .06, .34, .45, .148])
    press, _ = pressure_for(na.hospital_id.values, na.arrival_ts)
    w = wait_minutes(tri, na.hour.values, press)
    p_lwbs = np.where(tri >= 3, np.clip(0.008 + 0.06 * np.maximum(0, (w - 60) / 60), 0, 0.45), 0)
    lwbs = rng.random(m) < p_lwbs
    treat = rng.lognormal(np.log(np.where(tri >= 4, 70, 105)), 0.5, m)
    transfer = (~lwbs) & (rng.random(m) < 0.015)
    seen = (na.arrival_ts + pd.to_timedelta(w, unit="min")).dt.floor("min")
    depart = seen + pd.to_timedelta(treat + np.where(transfer, 75, 0), unit="min")
    depart = depart.where(~lwbs, na.arrival_ts + pd.to_timedelta(w * rng.uniform(0.4, 0.95, m), unit="min"))
    not_admitted = pd.DataFrame({
        "patient_id": -1, "hospital_id": na.hospital_id.values, "arrival_ts": na.arrival_ts,
        "triage_category": tri, "provider_seen_ts": seen.where(~lwbs),
        "decision_to_admit_ts": pd.NaT, "departure_ts": depart.dt.floor("min"),
        "er_disposition": np.select([lwbs, transfer], ["Left Without Being Seen", "Transferred"], "Discharged"),
        "admission_id": pd.NA,
    })
    er = pd.concat([admitted, not_admitted], ignore_index=True)
    er = er[(er.arrival_ts >= START) & (er.arrival_ts < EXTRACT_TS)]
    return er.sort_values("arrival_ts").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def fmt(ts: pd.Series) -> pd.Series:
    return ts.dt.strftime("%Y-%m-%d %H:%M").where(ts.notna(), None)


def main() -> None:
    cap = build_capacity()
    beds_day = daily_beds(cap)
    beds_depts = set(zip(cap.hospital_id, cap.department_id))
    hosp_attr = HOSPITALS.set_index("hospital_id")
    hosp_beds = cap.groupby("hospital_id").staffed_beds.max()  # (for licensed beds below)

    adm = base_admissions(beds_day)
    adm["age"] = np.nan
    adm = enrich(adm, hosp_attr)
    adm["patient_key"] = np.arange(len(adm))
    re = readmission_rounds(adm, hosp_attr, beds_depts)
    adm = pd.concat([adm, re], ignore_index=True)
    adm = adm[adm.admit_ts < EXTRACT_TS]
    adm = remove_overlaps(adm)

    # admission type / source
    adm["admission_type"] = np.where(adm.elective, "Elective", "Emergency")
    u = rng.random(len(adm))
    src_em = np.where(u < 0.86, "Emergency Department", np.where(u < 0.96, "GP Referral", "Inter-hospital Transfer"))
    src_em = np.where(adm.dept.values == "MAT", np.where(u < 0.25, "Emergency Department", "Maternity Assessment Unit"), src_em)
    adm["admission_source"] = np.where(adm.elective, "Elective Waiting List", src_em)

    # open stays at extract
    still_in = adm.discharge_ts >= EXTRACT_TS
    adm.loc[still_in, "discharge_ts"] = pd.NaT
    adm.loc[still_in, "disposition"] = None

    adm = adm.sort_values(["admit_ts", "hospital_id", "department_id"]).reset_index(drop=True)
    adm["admission_id"] = np.arange(1, len(adm) + 1)

    # patients (one per patient_key) + ED-only attenders later
    first = adm.sort_values("admit_ts").groupby("patient_key").first()
    pkeys = first.index.values
    pid_map = pd.Series(np.arange(1, len(pkeys) + 1), index=pkeys)
    adm["patient_id"] = pid_map.loc[adm.patient_key].values
    region = dict(zip(HOSPITALS.hospital_id, HOSPITALS.region))
    sex = np.where(first.dept.values == "MAT", "F",
                   np.where(rng.random(len(first)) < np.where(first.dept.values == "CARD", 0.58, 0.49), "M", "F"))
    patients = pd.DataFrame({
        "patient_id": pid_map.values, "sex": sex,
        "birth_year": (first.admit_ts.dt.year.values - first.age.values.astype(int) - rng.integers(0, 2, len(first))),
        "home_region": [region[h] for h in first.hospital_id.values],
    })

    # census -> hospital-level inpatient occupancy used for ED pressure
    census = midnight_census(adm)
    cb = census.merge(beds_day, on=["hospital_id", "department_id", "day"])
    cb = cb[cb.department_id != DEPT_ID["ED"]]
    hosp_occ = cb.groupby(["hospital_id", "day"])[["census", "beds"]].sum()
    hosp_occ["occ"] = hosp_occ.census / hosp_occ.beds
    hosp_occ = hosp_occ.reset_index()

    staffing = build_staffing(beds_day)
    er = build_er(adm, hosp_occ, staffing)

    # ED-only attenders: 45% are known patients from the same hospital, the rest are new
    na = er.patient_id == -1
    n_na = int(na.sum())
    known = rng.random(n_na) < 0.45
    pool = adm.groupby("hospital_id").patient_id.apply(np.array)
    hosp_na = er.loc[na, "hospital_id"].values
    reuse = np.array([rng.choice(pool[h]) for h in hosp_na[known]])
    new_ids = np.arange(patients.patient_id.max() + 1, patients.patient_id.max() + 1 + (~known).sum())
    ids = np.empty(n_na, dtype=np.int64)
    ids[known] = reuse
    ids[~known] = new_ids
    er.loc[na, "patient_id"] = ids
    new_age = np.clip(rng.gamma(2.2, 18, len(new_ids)), 0, 100).astype(int)
    new_pat = pd.DataFrame({
        "patient_id": new_ids, "sex": np.where(rng.random(len(new_ids)) < 0.5, "M", "F"),
        "birth_year": 2025 - new_age,
        "home_region": [region[h] for h in hosp_na[~known]],
    })
    patients = pd.concat([patients, new_pat], ignore_index=True)
    er.insert(0, "er_visit_id", np.arange(1, len(er) + 1))

    # hospitals table
    hospitals = HOSPITALS[["hospital_id", "hospital_code", "hospital_name", "hospital_type", "region", "city"]].copy()
    ip = cap[cap.department_id != DEPT_ID["ED"]].groupby(["hospital_id", "department_id"]).staffed_beds.max() \
        .groupby("hospital_id").sum()
    hospitals["licensed_beds"] = (ip.loc[hospitals.hospital_id].values * 1.08).round().astype(int)
    hospitals["opened_year"] = HOSPITALS.opened_year.values

    # ---------------------------------------------------------------- write SQLite
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA_PATH.read_text())
    con.execute("PRAGMA foreign_keys = ON")

    def insert(table: str, df: pd.DataFrame) -> None:
        df = df.astype(object).where(df.notna(), None)
        cols = ",".join(df.columns)
        ph = ",".join("?" * len(df.columns))
        con.executemany(f"INSERT INTO {table} ({cols}) VALUES ({ph})", df.itertuples(index=False, name=None))

    insert("hospitals", hospitals)
    insert("departments", DEPARTMENTS)
    insert("bed_capacity", cap)
    insert("patients", patients.sort_values("patient_id"))
    adm_out = adm[["admission_id", "patient_id", "hospital_id", "department_id"]].copy()
    adm_out["admit_ts"] = fmt(adm.admit_ts)
    adm_out["discharge_ts"] = fmt(adm.discharge_ts)
    adm_out["admission_type"] = adm.admission_type
    adm_out["admission_source"] = adm.admission_source
    adm_out["primary_diagnosis_group"] = adm.dx
    adm_out["discharge_disposition"] = adm.disposition
    insert("admissions", adm_out)
    er_out = er.copy()
    for c in ("arrival_ts", "provider_seen_ts", "decision_to_admit_ts", "departure_ts"):
        er_out[c] = fmt(pd.to_datetime(er_out[c]))
    er_out["admission_id"] = er_out.admission_id.astype("Int64")
    insert("er_visits", er_out)
    insert("staffing_shifts", staffing)
    con.commit()

    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    assert not fk, f"foreign key violations: {fk[:5]}"
    con.execute("VACUUM")
    con.close()

    # ---------------------------------------------------------------- summary
    y = adm[(adm.admit_ts >= YEAR_START)]
    los = (y.discharge_ts - y.admit_ts).dt.total_seconds() / 86400
    cb25 = cb[cb.day >= YEAR_START]
    print(f"hospitals={len(hospitals)} capacity_rows={len(cap)} patients={len(patients):,}")
    print(f"admissions={len(adm):,} (2025: {len(y):,})  ALOS 2025={los.mean():.2f}d  P90={los.quantile(.9):.1f}d")
    print(f"ER visits={len(er):,}  staffing rows={len(staffing):,}")
    print(f"network inpatient occupancy 2025 = {cb25.census.sum() / cb25.beds.sum():.1%}")
    print((cb25.groupby("hospital_id")[["census", "beds"]].sum().eval("census / beds")).round(3).to_string())
    print(f"DB size: {DB_PATH.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
