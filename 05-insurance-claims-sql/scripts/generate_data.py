"""
Generate a synthetic health insurance claims database (~200,000 claims).

Tables
------
members            - enrolled members (demographics, risk profile)
policies           - annual coverage segments per member (plan type, metal tier, cost sharing)
providers          - rendering providers (specialty, network status, state)
diagnosis_codes    - ICD-10-CM lookup
procedure_codes    - CPT/HCPCS lookup with reference allowed amount and prior-auth flag
rejection_reasons  - denial reason lookup
claims             - claim lines: dx/px codes, billed vs approved, status, dates, rejection reason

Embedded patterns (so the SQL has something real to find)
--------------------------------------------------------
* Seasonality (respiratory winter peaks) and ~6% annual unit-cost trend
* Provider-level coding hygiene differences -> uneven rejection rates
* HMO/EPO out-of-network denials, missing prior auth on high-cost imaging/surgery
* A small cohort of "suspicious" providers: upcoding to 99215, extreme billed markups,
  higher duplicate-submission rates
* Duplicate claims (exact and near-duplicates), most caught (R01) but some paid
* Billed-amount outliers (5-15x typical)
* Adjudication turnaround improving through 2025 (auto-adjudication rollout)

Everything is synthetic. Run from the project folder:  python scripts/generate_data.py
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 2025
rng = np.random.default_rng(SEED)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "claims.db"

N_MEMBERS = 10_000
N_PROVIDERS = 1_200
N_BASE_CLAIMS = 197_500
START = date(2024, 1, 1)
END = date(2025, 12, 31)          # data "as of" date
SERVICE_END = date(2025, 12, 20)

STATES = ["TX", "CA", "FL", "NY", "IL", "GA", "NC", "OH", "AZ", "WA"]
STATE_W = np.array([16, 18, 13, 12, 9, 8, 7, 7, 5, 5], dtype=float)
STATE_W /= STATE_W.sum()

# --------------------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------------------
DIAGNOSES = [
    # code, description, category, chronic, sex restriction, min_age
    ("E11.9", "Type 2 diabetes mellitus without complications", "Endocrine", 1, None, 25),
    ("E78.5", "Hyperlipidemia, unspecified", "Endocrine", 1, None, 30),
    ("I10", "Essential (primary) hypertension", "Circulatory", 1, None, 30),
    ("I25.10", "Atherosclerotic heart disease of native coronary artery", "Circulatory", 1, None, 45),
    ("I48.91", "Unspecified atrial fibrillation", "Circulatory", 1, None, 50),
    ("N18.30", "Chronic kidney disease, stage 3 unspecified", "Renal", 1, None, 45),
    ("J45.909", "Unspecified asthma, uncomplicated", "Respiratory", 1, None, 0),
    ("F32.9", "Major depressive disorder, single episode", "Behavioral Health", 1, None, 14),
    ("F41.1", "Generalized anxiety disorder", "Behavioral Health", 1, None, 14),
    ("M17.11", "Primary osteoarthritis, right knee", "Musculoskeletal", 1, None, 45),
    ("C50.911", "Malignant neoplasm of right female breast", "Oncology", 1, "F", 35),
    ("C34.90", "Malignant neoplasm of bronchus or lung", "Oncology", 1, None, 50),
    ("J06.9", "Acute upper respiratory infection", "Respiratory", 0, None, 0),
    ("J18.9", "Pneumonia, unspecified organism", "Respiratory", 0, None, 0),
    ("M54.50", "Low back pain, unspecified", "Musculoskeletal", 0, None, 18),
    ("S82.201A", "Fracture of shaft of right tibia, initial encounter", "Injury", 0, None, 5),
    ("S06.0X0A", "Concussion without loss of consciousness", "Injury", 0, None, 5),
    ("K21.9", "Gastro-esophageal reflux disease", "Digestive", 0, None, 18),
    ("K80.20", "Calculus of gallbladder without obstruction", "Digestive", 0, None, 25),
    ("O80", "Encounter for full-term uncomplicated delivery", "Maternity", 0, "F", 18),
    ("R07.9", "Chest pain, unspecified", "Symptoms & Signs", 0, None, 18),
    ("N39.0", "Urinary tract infection, site not specified", "Genitourinary", 0, None, 0),
    ("G43.909", "Migraine, unspecified", "Neurological", 0, None, 12),
    ("L03.90", "Cellulitis, unspecified", "Skin", 0, None, 0),
    ("Z00.00", "General adult medical exam without abnormal findings", "Preventive", 0, None, 18),
    ("Z12.31", "Screening mammogram for malignant neoplasm of breast", "Preventive", 0, "F", 40),
]

# code, description, category, reference allowed amount, prior auth required, place of service
PROCEDURES = [
    ("99203", "Office visit, new patient, low complexity", "E&M", 145, 0, "Office"),
    ("99213", "Office visit, established patient, low complexity", "E&M", 105, 0, "Office"),
    ("99214", "Office visit, established patient, moderate complexity", "E&M", 155, 0, "Office"),
    ("99215", "Office visit, established patient, high complexity", "E&M", 215, 0, "Office"),
    ("99396", "Preventive visit, established patient, 40-64", "Preventive", 205, 0, "Office"),
    ("99284", "Emergency dept visit, moderate-high severity", "Emergency", 420, 0, "Emergency Room"),
    ("99285", "Emergency dept visit, high severity", "Emergency", 640, 0, "Emergency Room"),
    ("99223", "Initial hospital inpatient care, high complexity", "Inpatient", 390, 0, "Inpatient Hospital"),
    ("90834", "Psychotherapy, 45 minutes", "Behavioral Health", 115, 0, "Office"),
    ("90837", "Psychotherapy, 60 minutes", "Behavioral Health", 165, 0, "Telehealth"),
    ("97110", "Therapeutic exercise, each 15 minutes", "Rehabilitation", 38, 0, "Office"),
    ("80053", "Comprehensive metabolic panel", "Laboratory", 22, 0, "Independent Lab"),
    ("83036", "Hemoglobin A1c", "Laboratory", 18, 0, "Independent Lab"),
    ("85025", "Complete blood count with differential", "Laboratory", 14, 0, "Independent Lab"),
    ("81001", "Urinalysis with microscopy", "Laboratory", 9, 0, "Independent Lab"),
    ("93000", "Electrocardiogram, complete", "Cardiology Dx", 28, 0, "Office"),
    ("93306", "Echocardiography, transthoracic, complete", "Cardiology Dx", 520, 1, "Outpatient Hospital"),
    ("71046", "Chest X-ray, 2 views", "Imaging", 55, 0, "Imaging Center"),
    ("72148", "MRI lumbar spine without contrast", "Advanced Imaging", 610, 1, "Imaging Center"),
    ("73721", "MRI knee without contrast", "Advanced Imaging", 590, 1, "Imaging Center"),
    ("70450", "CT head without contrast", "Advanced Imaging", 420, 1, "Imaging Center"),
    ("74177", "CT abdomen & pelvis with contrast", "Advanced Imaging", 680, 1, "Imaging Center"),
    ("77067", "Screening mammography, bilateral", "Imaging", 150, 0, "Imaging Center"),
    ("45378", "Colonoscopy, diagnostic", "Procedure", 880, 0, "Outpatient Hospital"),
    ("43239", "Upper GI endoscopy with biopsy", "Procedure", 920, 0, "Outpatient Hospital"),
    ("47562", "Laparoscopic cholecystectomy", "Surgery", 5_400, 1, "Outpatient Hospital"),
    ("27447", "Total knee arthroplasty", "Surgery", 21_500, 1, "Inpatient Hospital"),
    ("27759", "Open treatment of tibial shaft fracture", "Surgery", 4_700, 0, "Inpatient Hospital"),
    ("92928", "Percutaneous coronary stent placement", "Surgery", 11_800, 1, "Inpatient Hospital"),
    ("59400", "Routine obstetric care incl. vaginal delivery", "Maternity", 3_100, 0, "Inpatient Hospital"),
    ("96413", "Chemotherapy infusion, first hour", "Oncology", 830, 1, "Outpatient Hospital"),
    ("J9355", "Injection, trastuzumab, 10 mg", "Specialty Drug", 4_100, 1, "Outpatient Hospital"),
    ("90960", "ESRD-related services, monthly", "Renal", 310, 0, "Office"),
    ("96372", "Therapeutic injection, subcutaneous/IM", "Injection", 28, 0, "Office"),
    ("90471", "Immunization administration", "Preventive", 24, 0, "Office"),
]
PX = {p[0]: p for p in PROCEDURES}

# diagnosis -> (procedures, weights)
DX_PX = {
    "E11.9": (["99213", "99214", "83036", "80053", "99215"], [30, 30, 25, 12, 3]),
    "E78.5": (["99213", "99214", "80053"], [45, 25, 30]),
    "I10": (["99213", "99214", "80053", "93000", "99215"], [40, 30, 12, 15, 3]),
    "I25.10": (["99214", "93000", "93306", "92928", "99215"], [40, 25, 20, 5, 10]),
    "I48.91": (["99214", "93000", "93306", "99215"], [40, 35, 17, 8]),
    "N18.30": (["99214", "80053", "90960", "81001"], [30, 35, 20, 15]),
    "J45.909": (["99213", "99214", "96372", "99284"], [45, 25, 20, 10]),
    "F32.9": (["90834", "90837", "99214"], [40, 40, 20]),
    "F41.1": (["90834", "90837", "99213"], [40, 40, 20]),
    "M17.11": (["99214", "97110", "73721", "27447", "96372"], [30, 40, 12, 4, 14]),
    "C50.911": (["96413", "J9355", "99215", "85025", "74177"], [30, 22, 23, 15, 10]),
    "C34.90": (["96413", "99215", "74177", "71046", "85025"], [35, 25, 15, 10, 15]),
    "J06.9": (["99213", "99203", "99284"], [70, 25, 5]),
    "J18.9": (["99214", "71046", "99284", "99223", "85025"], [25, 30, 20, 10, 15]),
    "M54.50": (["99213", "99214", "97110", "72148"], [30, 20, 38, 12]),
    "S82.201A": (["99285", "71046", "27759", "97110"], [30, 25, 20, 25]),
    "S06.0X0A": (["99284", "99285", "70450"], [45, 20, 35]),
    "K21.9": (["99213", "99214", "43239"], [50, 30, 20]),
    "K80.20": (["99284", "74177", "47562", "99214"], [25, 25, 25, 25]),
    "O80": (["59400", "99223"], [80, 20]),
    "R07.9": (["99284", "99285", "93000", "71046"], [35, 20, 30, 15]),
    "N39.0": (["99213", "81001", "99203"], [45, 40, 15]),
    "G43.909": (["99213", "99214", "70450", "96372"], [40, 30, 10, 20]),
    "L03.90": (["99213", "99203", "96372", "99284"], [45, 25, 20, 10]),
    "Z00.00": (["99396", "80053", "85025", "90471"], [45, 20, 15, 20]),
    "Z12.31": (["77067"], [100]),
}

PX_SPECIALTY = {
    "99203": ["Family Medicine", "Internal Medicine", "Urgent Care"],
    "99213": ["Family Medicine", "Internal Medicine", "Urgent Care", "Endocrinology", "Gastroenterology", "Neurology"],
    "99214": ["Family Medicine", "Internal Medicine", "Cardiology", "Endocrinology", "Nephrology", "Orthopedics", "Gastroenterology", "Neurology", "Behavioral Health"],
    "99215": ["Family Medicine", "Internal Medicine", "Cardiology", "Oncology", "Endocrinology"],
    "99396": ["Family Medicine", "Internal Medicine"],
    "99284": ["Emergency Medicine"],
    "99285": ["Emergency Medicine"],
    "99223": ["Hospital Medicine"],
    "90834": ["Behavioral Health"],
    "90837": ["Behavioral Health"],
    "97110": ["Physical Therapy"],
    "80053": ["Laboratory"],
    "83036": ["Laboratory"],
    "85025": ["Laboratory"],
    "81001": ["Laboratory"],
    "93000": ["Cardiology", "Family Medicine", "Internal Medicine"],
    "93306": ["Cardiology"],
    "71046": ["Radiology"],
    "72148": ["Radiology"],
    "73721": ["Radiology"],
    "70450": ["Radiology"],
    "74177": ["Radiology"],
    "77067": ["Radiology"],
    "45378": ["Gastroenterology"],
    "43239": ["Gastroenterology"],
    "47562": ["General Surgery"],
    "27447": ["Orthopedics"],
    "27759": ["Orthopedics"],
    "92928": ["Cardiology"],
    "59400": ["OB/GYN"],
    "96413": ["Oncology"],
    "J9355": ["Oncology"],
    "90960": ["Nephrology"],
    "96372": ["Family Medicine", "Internal Medicine", "Urgent Care", "Orthopedics"],
    "90471": ["Family Medicine", "Internal Medicine"],
}

SPECIALTY_MIX = {
    "Family Medicine": 190, "Internal Medicine": 150, "Urgent Care": 45, "Emergency Medicine": 60,
    "Hospital Medicine": 35, "Behavioral Health": 110, "Physical Therapy": 80, "Laboratory": 40,
    "Radiology": 70, "Cardiology": 70, "Endocrinology": 35, "Nephrology": 30, "Orthopedics": 65,
    "Gastroenterology": 45, "General Surgery": 35, "OB/GYN": 55, "Oncology": 45, "Neurology": 40,
}
PROVIDER_TYPE = {
    "Emergency Medicine": "Facility", "Hospital Medicine": "Facility", "Laboratory": "Ancillary",
    "Radiology": "Ancillary", "Physical Therapy": "Ancillary",
}

REJECTION_REASONS = [
    ("R01", "Duplicate claim submission", "Payment Integrity", 1),
    ("R02", "Missing or invalid prior authorization", "Utilization Management", 1),
    ("R03", "Service not covered under member's plan", "Benefits", 0),
    ("R04", "Member not eligible on date of service", "Eligibility", 1),
    ("R05", "Out-of-network provider, no OON benefit", "Network", 1),
    ("R06", "Diagnosis/procedure code mismatch or invalid code", "Coding", 1),
    ("R07", "Missing or incomplete claim information", "Administrative", 1),
    ("R08", "Timely filing limit exceeded", "Administrative", 1),
    ("R09", "Not medically necessary", "Clinical Review", 0),
    ("R10", "Billed amount exceeds reasonable & customary review", "Payment Integrity", 0),
]
# avoidable = could have been prevented by a clean front-end submission

FIRST = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth",
         "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Carlos", "Maria",
         "Daniel", "Nancy", "Matthew", "Lisa", "Anthony", "Aisha", "Mark", "Priya", "Omar", "Wei", "Fatima",
         "Luis", "Grace", "Ahmed", "Mei", "Kevin", "Laura", "Hassan", "Sofia", "Ethan"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
        "Patel", "Nguyen", "Kim", "Khan", "Chen", "Ali", "Singh", "Walker", "Young", "Allen"]
ORG_WORDS = ["Riverside", "Summit", "Lakeview", "Pinecrest", "Harbor", "Meadow", "Cedar", "Northgate", "Sunrise",
             "Valley", "Crescent", "Oakwood", "Bayside", "Highland", "Parkside", "Unity", "Horizon", "Evergreen"]


def rand_dates(start: date, end: date, n: int) -> np.ndarray:
    span = (end - start).days
    return np.array([start + timedelta(days=int(d)) for d in rng.integers(0, span + 1, n)])


# --------------------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------------------
def build_members() -> pd.DataFrame:
    ages = np.clip(rng.normal(42, 18, N_MEMBERS), 0, 64).astype(int)
    sex = rng.choice(["F", "M"], N_MEMBERS, p=[0.52, 0.48])
    birth = [date(2025, 1, 1) - timedelta(days=int(a * 365.25 + rng.integers(0, 365))) for a in ages]
    enroll = rand_dates(date(2016, 1, 1), date(2025, 6, 30), N_MEMBERS)
    # 70% enrolled before study window
    early = rng.random(N_MEMBERS) < 0.70
    enroll = np.where(early, rand_dates(date(2016, 1, 1), date(2023, 12, 31), N_MEMBERS), enroll)
    state = rng.choice(STATES, N_MEMBERS, p=STATE_W)
    risk = rng.lognormal(0, 0.85, N_MEMBERS) * (1 + ages / 45)
    mid = [f"M{100000 + i}" for i in range(N_MEMBERS)]
    df = pd.DataFrame({
        "member_id": mid,
        "first_name": rng.choice(FIRST, N_MEMBERS),
        "last_name": rng.choice(LAST, N_MEMBERS),
        "gender": sex,
        "birth_date": birth,
        "state": state,
        "enrollment_date": enroll,
        "risk_score": np.round(risk / np.median(risk), 3),
    })
    return df


def assign_chronic(members: pd.DataFrame) -> dict[str, list[str]]:
    chronic = [d for d in DIAGNOSES if d[3] == 1]
    base_p = {"E11.9": .10, "E78.5": .16, "I10": .22, "I25.10": .06, "I48.91": .04, "N18.30": .04,
              "J45.909": .08, "F32.9": .09, "F41.1": .10, "M17.11": .07, "C50.911": .015, "C34.90": .008}
    out = {}
    ages = (date(2025, 1, 1) - pd.to_datetime(members.birth_date).dt.date).apply(lambda x: x.days / 365.25).values
    for mid, age, sex, risk in zip(members.member_id, ages, members.gender, members.risk_score):
        conds = []
        for code, _, _, _, sx, min_age in chronic:
            if age < min_age or (sx and sx != sex):
                continue
            p = base_p[code] * (0.5 + age / 40) * min(risk, 3) ** 0.6
            if rng.random() < p:
                conds.append(code)
        out[mid] = conds
    return out


# --------------------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------------------
PLAN_DESIGN = {  # plan_type: (share, oon_benefit)
    "PPO": (0.36, 1), "HMO": (0.30, 0), "EPO": (0.14, 0), "HDHP": (0.20, 1),
}
TIERS = {"Bronze": (7000, 9200, 385), "Silver": (4500, 8700, 470), "Gold": (1500, 6500, 575), "Platinum": (500, 3500, 690)}


def build_policies(members: pd.DataFrame) -> pd.DataFrame:
    rows = []
    pid = 500000
    plan_types = list(PLAN_DESIGN)
    plan_p = [PLAN_DESIGN[p][0] for p in plan_types]
    for m in members.itertuples(index=False):
        plan = rng.choice(plan_types, p=plan_p)
        tier = "Bronze" if plan == "HDHP" else rng.choice(list(TIERS), p=[0.18, 0.42, 0.30, 0.10])
        terminated = rng.random() < 0.06
        for year in (2024, 2025):
            start = max(date(year, 1, 1), m.enrollment_date)
            end = date(year, 12, 31)
            if start > end:
                continue
            if year == 2025 and rng.random() < 0.12:  # plan change at renewal
                plan = rng.choice(plan_types, p=plan_p)
                tier = "Bronze" if plan == "HDHP" else rng.choice(list(TIERS), p=[0.18, 0.42, 0.30, 0.10])
            status = "Active"
            if year == 2025 and terminated:
                end = date(2025, int(rng.integers(3, 11)), 28)
                status = "Terminated"
            elif year == 2024:
                status = "Expired"
            ded, oop, prem = TIERS[tier]
            age_factor = 1 + max(0, (2025 - m.birth_date.year) - 21) * 0.02
            rows.append({
                "policy_id": f"P{pid}", "member_id": m.member_id, "plan_type": plan, "metal_tier": tier,
                "coverage_start": start, "coverage_end": end, "annual_deductible": ded,
                "oop_max": oop, "monthly_premium": round(prem * age_factor * (1.06 if year == 2025 else 1), 2),
                "oon_benefit": PLAN_DESIGN[plan][1], "policy_status": status,
            })
            pid += 1
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------------------
def build_providers() -> pd.DataFrame:
    specs = []
    total = sum(SPECIALTY_MIX.values())
    for s, n in SPECIALTY_MIX.items():
        specs += [s] * round(n / total * N_PROVIDERS)
    specs = (specs + ["Family Medicine"] * N_PROVIDERS)[:N_PROVIDERS]
    rng.shuffle(specs)
    rows = []
    for i, s in enumerate(specs):
        ptype = PROVIDER_TYPE.get(s, "Professional")
        if ptype == "Professional" and rng.random() < 0.55:
            name = f"Dr. {rng.choice(FIRST)} {rng.choice(LAST)}"
        else:
            suffix = {"Emergency Medicine": "Medical Center", "Hospital Medicine": "Regional Hospital",
                      "Laboratory": "Diagnostics Lab", "Radiology": "Imaging", "Physical Therapy": "Physical Therapy"}.get(s, f"{s} Associates")
            name = f"{rng.choice(ORG_WORDS)} {suffix}"
        rows.append({
            "provider_id": f"PR{20000 + i}",
            "npi": str(1_000_000_000 + int(rng.integers(0, 899_999_999))),
            "provider_name": name,
            "specialty": s,
            "provider_type": ptype,
            "state": rng.choice(STATES, p=STATE_W),
            "network_status": "In-Network" if rng.random() < 0.86 else "Out-of-Network",
            "contract_start": rand_dates(date(2012, 1, 1), date(2023, 6, 30), 1)[0],
        })
    df = pd.DataFrame(rows)
    # hidden behavioural attributes (not stored)
    df["_volume"] = rng.lognormal(0, 0.7, len(df))
    df["_markup"] = np.clip(rng.normal(1.65, 0.25, len(df)), 1.15, 2.6)
    df["_coding_err"] = np.clip(rng.beta(1.6, 45, len(df)), 0.002, 0.2)
    df["_suspicious"] = False
    eligible = df.index[df.specialty.isin(["Family Medicine", "Internal Medicine", "Cardiology", "Orthopedics",
                                            "Physical Therapy", "Radiology", "Behavioral Health", "Endocrinology"])]
    sus = rng.choice(eligible, 24, replace=False)
    df.loc[sus, "_suspicious"] = True
    df.loc[sus, "_markup"] = rng.uniform(2.8, 4.2, len(sus))
    df.loc[sus, "_volume"] *= 2.4
    df.loc[sus, "_coding_err"] *= 1.8
    return df


# --------------------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------------------
def month_weights() -> tuple[list[date], np.ndarray]:
    days, w = [], []
    d = START
    while d <= SERVICE_END:
        season = {1: 1.18, 2: 1.14, 3: 1.05, 4: 0.97, 5: 0.95, 6: 0.92, 7: 0.88, 8: 0.93, 9: 0.99,
                  10: 1.04, 11: 1.06, 12: 1.10}[d.month]
        growth = 1 + 0.035 * ((d - START).days / 365)
        weekday = 0.22 if d.weekday() == 6 else (0.45 if d.weekday() == 5 else 1.0)
        days.append(d)
        w.append(season * growth * weekday)
        d += timedelta(days=1)
    w = np.array(w)
    return days, w / w.sum()


def build_claims(members, chronic, policies, providers) -> pd.DataFrame:
    days, day_w = month_weights()
    dx_lookup = {d[0]: d for d in DIAGNOSES}
    acute = [d for d in DIAGNOSES if d[3] == 0]

    # provider pools per specialty (weighted by volume, lightly preferring member state)
    pools = {}
    for s, grp in providers.groupby("specialty"):
        pools[s] = (grp.index.values, grp["_volume"].values / grp["_volume"].sum())

    mem = members.set_index("member_id")
    ages = ((pd.Timestamp("2025-01-01") - pd.to_datetime(members.birth_date)).dt.days / 365.25).values
    age_by = dict(zip(members.member_id, ages))
    sex_by = dict(zip(members.member_id, members.gender))

    w = members.risk_score.values * (1 + np.array([len(chronic[m]) for m in members.member_id]) * 0.9)
    w = w / w.sum()
    member_draw = rng.choice(members.member_id.values, N_BASE_CLAIMS, p=w)
    day_draw = rng.choice(len(days), N_BASE_CLAIMS, p=day_w)

    # policy windows per member
    pol_by_member = {k: g.sort_values("coverage_start")[["policy_id", "coverage_start", "coverage_end", "plan_type", "oon_benefit"]].values
                     for k, g in policies.groupby("member_id")}

    prov_state = providers.state.values
    prov_ids = providers.provider_id.values
    prov_sus = providers["_suspicious"].values

    rows = []
    loyalty: dict[tuple[str, str], int] = {}
    for mid, di in zip(member_draw, day_draw):
        svc = days[di]
        pols = pol_by_member[mid]
        # pick the policy active at service date; if none, use nearest (eligibility issue)
        active = [p for p in pols if p[1] <= svc <= p[2]]
        eligibility_gap = False
        if active:
            pol = active[0]
        else:
            # member not covered at date: usually shift date into coverage, sometimes keep (R04)
            if rng.random() < 0.10:
                pol = pols[-1]
                eligibility_gap = True
            else:
                pol = pols[int(rng.integers(0, len(pols)))]
                lo, hi = pol[1], min(pol[2], SERVICE_END)
                if lo > hi:
                    continue
                svc = lo + timedelta(days=int(rng.integers(0, (hi - lo).days + 1)))
        age, sex = age_by[mid], sex_by[mid]
        conds = chronic[mid]
        if conds and rng.random() < 0.58:
            dx = conds[int(rng.integers(0, len(conds)))]
        else:
            while True:
                d = acute[int(rng.integers(0, len(acute)))]
                if age >= d[5] and (d[4] is None or d[4] == sex):
                    # seasonality for respiratory
                    if d[2] == "Respiratory" and svc.month in (5, 6, 7, 8) and rng.random() < 0.6:
                        continue
                    if d[0] == "O80" and rng.random() < 0.7:
                        continue
                    dx = d[0]
                    break
        pxs, pw = DX_PX[dx]
        px = rng.choice(pxs, p=np.array(pw) / sum(pw))
        spec = PX_SPECIALTY[px]
        s = spec[int(rng.integers(0, len(spec)))]
        # members mostly return to the same provider for a given specialty (PCP / specialist loyalty)
        key = (mid, s)
        if key in loyalty and rng.random() < 0.85:
            pi = loyalty[key]
        else:
            idx, pp = pools[s]
            # prefer in-state provider
            for _ in range(3):
                pi = rng.choice(idx, p=pp)
                if prov_state[pi] == mem.at[mid, "state"] or rng.random() < 0.25:
                    break
            loyalty.setdefault(key, pi)
        # upcoding by suspicious providers
        if prov_sus[pi] and px in ("99213", "99214") and rng.random() < 0.6:
            px = "99215"
        rows.append((mid, pol[0], prov_ids[pi], pi, svc, dx, px, pol[3], pol[4], eligibility_gap))

    c = pd.DataFrame(rows, columns=["member_id", "policy_id", "provider_id", "_pi", "service_date", "diagnosis_code",
                                    "procedure_code", "_plan", "_oon_benefit", "_elig_gap"])
    n = len(c)
    prov = providers.iloc[c._pi.values].reset_index(drop=True)
    ref = c.procedure_code.map(lambda p: PX[p][3]).values.astype(float)
    units = np.where(c.procedure_code == "97110", rng.integers(2, 5, n),
                     np.where(c.procedure_code == "J9355", rng.integers(28, 60, n) / 42, 1.0))
    units = np.round(units, 0).clip(1)
    years = ((pd.to_datetime(c.service_date) - pd.Timestamp(START)).dt.days / 365).values
    trend = 1.06 ** years
    oon = (prov.network_status.values == "Out-of-Network")

    allowed_unit = ref * trend * rng.normal(1.0, 0.06, n).clip(0.8, 1.25)
    allowed_unit = np.where(oon, allowed_unit * 0.72, allowed_unit)
    billed = ref * trend * units * prov["_markup"].values * rng.lognormal(0, 0.12, n)
    # outliers
    outlier = rng.random(n) < 0.004
    outlier |= prov["_suspicious"].values & (rng.random(n) < 0.02)
    billed = np.where(outlier, billed * rng.uniform(5, 15, n), billed)
    billed = np.round(billed, 2)
    allowed = np.round(np.minimum(allowed_unit * units, billed), 2)

    # submission lag
    lag = np.round(rng.gamma(1.6, 7, n)).astype(int) + 1
    late = rng.random(n) < 0.012
    lag = np.where(late, rng.integers(185, 330, n), lag)
    service = pd.to_datetime(c.service_date)
    submission = service + pd.to_timedelta(lag, unit="D")

    # ---------------- adjudication outcome ----------------
    reason = np.full(n, None, dtype=object)
    r = rng.random((n, 8))
    pa_required = c.procedure_code.map(lambda p: PX[p][4]).values == 1
    reason = np.where(c._elig_gap.values, "R04", reason)
    reason = np.where((reason == None) & late, "R08", reason)  # noqa: E711
    hmo_like = c._oon_benefit.values == 0
    reason = np.where((reason == None) & oon & hmo_like & (r[:, 0] < 0.82), "R05", reason)  # noqa: E711
    reason = np.where((reason == None) & pa_required & (r[:, 1] < 0.085), "R02", reason)  # noqa: E711
    reason = np.where((reason == None) & (r[:, 2] < prov["_coding_err"].values), "R06", reason)  # noqa: E711
    reason = np.where((reason == None) & (r[:, 3] < 0.028), "R07", reason)  # noqa: E711
    not_cov_p = np.where(np.isin(c.procedure_code.values, ["97110", "90837", "96372"]), 0.035, 0.008)
    reason = np.where((reason == None) & (r[:, 4] < not_cov_p), "R03", reason)  # noqa: E711
    med_nec = np.isin(c.procedure_code.values, ["72148", "73721", "70450", "74177", "93306", "99285", "99215"])
    reason = np.where((reason == None) & med_nec & (r[:, 5] < 0.045), "R09", reason)  # noqa: E711
    reason = np.where((reason == None) & outlier & (r[:, 6] < 0.45), "R10", reason)  # noqa: E711

    status = np.where(reason == None, "Approved", "Rejected")  # noqa: E711

    # turnaround (days from submission to adjudication), improving through 2025
    high_cost = billed > 2500
    manual = high_cost | pa_required | outlier
    tat = np.where(manual, rng.gamma(3.0, 6.0, n), rng.gamma(1.5, 2.6, n))
    tat = np.where(np.isin(reason, ["R01", "R04", "R07", "R08"]), rng.gamma(1.2, 1.8, n), tat)
    tat = np.where(np.isin(reason, ["R09", "R10"]), rng.gamma(4, 7, n), tat)
    months_in = ((submission - pd.Timestamp(START)).dt.days / 30.4).values
    improvement = np.where(months_in > 14, 1 - np.minimum((months_in - 14) * 0.035, 0.32), 1.0)
    tat = np.maximum(np.round(tat * improvement), 0).astype(int)
    adjud = submission + pd.to_timedelta(tat, unit="D")

    # pending: anything whose adjudication would fall after the as-of date, plus a few stuck claims
    as_of = pd.Timestamp(END)
    stuck = (rng.random(n) < 0.004) | (outlier & (rng.random(n) < 0.15))
    pending = (adjud > as_of) | (stuck & (submission > as_of - pd.Timedelta(days=120)))
    recent = (submission > as_of - pd.Timedelta(days=21)) & (rng.random(n) < 0.7)
    pending |= recent
    pending &= submission <= as_of
    status = np.where(pending, "Pending", status)
    reason = np.where(pending, None, reason)

    # drop claims submitted after the as-of date (not yet received)
    keep = (submission <= as_of).values

    approved = np.where(status == "Approved", allowed, 0.0)
    approved = np.where(status == "Pending", np.nan, approved)
    claim_type = c.procedure_code.map(lambda p: "Institutional" if PX[p][5] in ("Inpatient Hospital", "Outpatient Hospital", "Emergency Room") else "Professional")

    out = pd.DataFrame({
        "member_id": c.member_id, "policy_id": c.policy_id, "provider_id": c.provider_id,
        "claim_type": claim_type, "place_of_service": c.procedure_code.map(lambda p: PX[p][5]),
        "service_date": service.dt.date, "submission_date": submission.dt.date,
        "adjudication_date": np.where(status == "Pending", None, adjud.dt.date),
        "diagnosis_code": c.diagnosis_code, "procedure_code": c.procedure_code, "units": units.astype(int),
        "billed_amount": billed, "approved_amount": np.round(approved, 2),
        "claim_status": status, "rejection_reason_code": reason,
        "_suspicious": prov["_suspicious"].values, "_outlier": outlier,
    })[keep].reset_index(drop=True)
    return out


def add_duplicates(claims: pd.DataFrame) -> pd.DataFrame:
    """Re-submit a slice of claims: exact duplicates and near-duplicates (billed amount tweaked)."""
    base = claims[claims.claim_status != "Pending"]
    p = np.where(base._suspicious, 0.12, 0.016)
    pick = base[rng.random(len(base)) < p].copy()
    n = len(pick)
    as_of = pd.Timestamp(END)
    resub = pd.to_datetime(pick.submission_date) + pd.to_timedelta(rng.integers(3, 40, n), unit="D")
    pick["submission_date"] = resub.dt.date
    near = rng.random(n) < 0.3
    pick["billed_amount"] = np.where(near, np.round(pick.billed_amount * rng.uniform(0.97, 1.03, n), 2), pick.billed_amount)
    caught = rng.random(n) < np.where(near, 0.62, 0.86)
    tat = rng.gamma(1.2, 2.0, n).round().astype(int)
    adj = resub + pd.to_timedelta(tat, unit="D")
    pick["claim_status"] = np.where(caught, "Rejected", pick.claim_status)
    pick["rejection_reason_code"] = np.where(caught, "R01", pick.rejection_reason_code)
    pick["approved_amount"] = np.where(caught, 0.0, np.minimum(pick.approved_amount, pick.billed_amount))
    pick["adjudication_date"] = adj.dt.date
    pending = adj > as_of
    pick.loc[pending, ["claim_status", "rejection_reason_code", "approved_amount", "adjudication_date"]] = ["Pending", None, np.nan, None]
    pick = pick[resub <= as_of]
    return pd.concat([claims, pick], ignore_index=True)


def write_db(members, policies, providers, claims):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    schema = (ROOT / "sql" / "00_schema.sql").read_text()
    con.executescript(schema)

    def ins(table, df):
        cols = list(df.columns)
        con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [tuple(None if (isinstance(v, float) and np.isnan(v)) else (v.isoformat() if isinstance(v, date) else v)
                               for v in row) for row in df.itertuples(index=False)])

    ins("diagnosis_codes", pd.DataFrame([(d[0], d[1], d[2], d[3]) for d in DIAGNOSES],
                                        columns=["diagnosis_code", "description", "category", "is_chronic"]))
    ins("procedure_codes", pd.DataFrame([(p[0], p[1], p[2], float(p[3]), p[4]) for p in PROCEDURES],
                                        columns=["procedure_code", "description", "category", "reference_allowed_amount", "requires_prior_auth"]))
    ins("rejection_reasons", pd.DataFrame(REJECTION_REASONS, columns=["reason_code", "description", "category", "is_avoidable"]))
    ins("members", members)
    ins("providers", providers[[c for c in providers.columns if not c.startswith("_")]])
    ins("policies", policies)
    ins("claims", claims)
    con.commit()
    con.execute("ANALYZE")
    con.execute("VACUUM")
    con.close()


def main():
    members = build_members()
    chronic = assign_chronic(members)
    policies = build_policies(members)
    providers = build_providers()
    claims = build_claims(members, chronic, policies, providers)
    claims = add_duplicates(claims)
    claims = claims.sort_values(["submission_date", "service_date", "member_id"], kind="stable").reset_index(drop=True)
    claims.insert(0, "claim_id", [f"CLM{10_000_000 + i}" for i in range(len(claims))])
    claims = claims.drop(columns=["_suspicious", "_outlier"])
    write_db(members, policies, providers, claims)

    print(f"members   {len(members):>8,}")
    print(f"policies  {len(policies):>8,}")
    print(f"providers {len(providers):>8,}")
    print(f"claims    {len(claims):>8,}")
    print(claims.claim_status.value_counts(normalize=True).round(3).to_dict())
    print(f"db -> {DB_PATH}  ({DB_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
