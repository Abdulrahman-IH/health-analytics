"""
Synthetic population-health dataset generator (Synthea-style).

Produces ~50,000 synthetic adult patients with demographics, geography,
chronic conditions (diabetes, hypertension, obesity + two secondary
conditions), USPSTF-aligned preventive screening records, monthly wearable
vitals, and app-engagement event logs.

The output deliberately contains realistic data-quality defects (duplicates,
inconsistent casing, implausible values, out-of-window timestamps) so that the
downstream cleaning notebook has real work to do.  Nothing here is derived
from real patient data.

Usage:
    python src/generate_synthetic_data.py --n-patients 50000 --seed 42 \
        --out data/raw
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Reference configuration
# --------------------------------------------------------------------------- #
SNAPSHOT_DATE = pd.Timestamp("2025-12-31")
PERIOD_START = pd.Timestamp("2025-01-01")

REGIONS = {
    "Northeast": {"weight": 0.17, "states": ["NY", "PA", "NJ", "MA", "CT"]},
    "Midwest": {"weight": 0.21, "states": ["IL", "OH", "MI", "MN", "WI"]},
    "South": {"weight": 0.38, "states": ["TX", "FL", "GA", "NC", "TN"]},
    "West": {"weight": 0.24, "states": ["CA", "WA", "AZ", "CO", "OR"]},
}
STATE_NAMES = {
    "NY": "New York", "PA": "Pennsylvania", "NJ": "New Jersey", "MA": "Massachusetts",
    "CT": "Connecticut", "IL": "Illinois", "OH": "Ohio", "MI": "Michigan",
    "MN": "Minnesota", "WI": "Wisconsin", "TX": "Texas", "FL": "Florida",
    "GA": "Georgia", "NC": "North Carolina", "TN": "Tennessee", "CA": "California",
    "WA": "Washington", "AZ": "Arizona", "CO": "Colorado", "OR": "Oregon",
}

# SNOMED-CT codes as used by Synthea's condition modules
CONDITIONS = {
    "diabetes": {"code": "44054006", "name": "Type 2 diabetes mellitus"},
    "hypertension": {"code": "59621000", "name": "Essential hypertension"},
    "obesity": {"code": "414916001", "name": "Obesity (BMI 30+)"},
    "hyperlipidemia": {"code": "55822004", "name": "Hyperlipidemia"},
    "asthma": {"code": "195967001", "name": "Asthma"},
}

# Preventive screenings with (simplified) USPSTF / HEDIS eligibility rules
SCREENINGS = [
    # code, name, sex, min_age, max_age, interval_months, condition_required
    ("AWV", "Annual wellness visit", "Any", 18, 120, 12, None),
    ("BP", "Blood pressure screening", "Any", 18, 120, 12, None),
    ("FLU", "Influenza vaccination", "Any", 18, 120, 12, None),
    ("LIPID", "Lipid panel", "Any", 40, 75, 60, None),
    ("A1C_SCREEN", "Diabetes screening (A1c / glucose)", "Any", 35, 70, 36, None),
    ("CRC", "Colorectal cancer screening", "Any", 45, 75, 120, None),
    ("MAMMO", "Breast cancer screening (mammography)", "F", 40, 74, 24, None),
    ("CERVICAL", "Cervical cancer screening", "F", 21, 65, 36, None),
    ("A1C_DM", "HbA1c test (diabetes management)", "Any", 18, 120, 6, "diabetes"),
    ("EYE_DM", "Diabetic retinal eye exam", "Any", 18, 120, 12, "diabetes"),
]

EVENT_TYPES = {
    # type: (probability weight, category)
    "login": (0.52, "Access"),
    "appointment_booking": (0.09, "Care navigation"),
    "medication_reminder_sent": (0.14, "Medication adherence"),
    "medication_reminder_acknowledged": (0.10, "Medication adherence"),
    "screening_reminder_viewed": (0.08, "Preventive care"),
    "message_to_care_team": (0.04, "Care navigation"),
    "wearable_sync": (0.03, "Wearable"),
}


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


# --------------------------------------------------------------------------- #
# Patients
# --------------------------------------------------------------------------- #
def make_patients(n: int, rng: np.random.Generator) -> pd.DataFrame:
    patient_id = np.array([f"P{idx:07d}" for idx in range(1, n + 1)])

    # Age: adult population skewed toward 30-70
    age = np.clip(rng.gamma(shape=4.2, scale=7.2, size=n) + 18, 18, 95).round().astype(int)
    birth_date = SNAPSHOT_DATE - pd.to_timedelta(age * 365.25 + rng.integers(0, 365, n), unit="D")

    sex = rng.choice(["F", "M"], size=n, p=[0.515, 0.485])

    race = rng.choice(
        ["White", "Black or African American", "Hispanic or Latino", "Asian", "Other / Multiracial"],
        size=n, p=[0.58, 0.13, 0.18, 0.07, 0.04],
    )

    region_names = list(REGIONS)
    region = rng.choice(region_names, size=n, p=[REGIONS[r]["weight"] for r in region_names])
    state = np.array([rng.choice(REGIONS[r]["states"]) for r in region])

    urban_p = {"Northeast": [0.55, 0.35, 0.10], "Midwest": [0.38, 0.37, 0.25],
               "South": [0.36, 0.38, 0.26], "West": [0.48, 0.36, 0.16]}
    urbanicity = np.array([rng.choice(["Urban", "Suburban", "Rural"], p=urban_p[r]) for r in region])

    # Area Deprivation Index decile (1 = least deprived, 10 = most deprived)
    adi_base = np.where(urbanicity == "Rural", 6.3, np.where(urbanicity == "Suburban", 4.6, 5.4))
    adi_base = adi_base + np.where(region == "South", 0.6, 0) - np.where(region == "Northeast", 0.4, 0)
    adi = np.clip(np.round(rng.normal(adi_base, 2.2)), 1, 10).astype(int)

    # Insurance
    insurance = np.empty(n, dtype=object)
    for i in range(n):
        if age[i] >= 65:
            insurance[i] = rng.choice(["Medicare", "Medicare Advantage", "Commercial"], p=[0.55, 0.37, 0.08])
        else:
            p_medicaid = 0.10 + 0.03 * (adi[i] - 5)
            p_unins = 0.05 + 0.012 * (adi[i] - 5)
            p_medicaid, p_unins = max(p_medicaid, 0.02), max(p_unins, 0.01)
            p_comm = 1 - p_medicaid - p_unins
            insurance[i] = rng.choice(["Commercial", "Medicaid", "Uninsured"], p=[p_comm, p_medicaid, p_unins])

    smoking = np.empty(n, dtype=object)
    p_current = np.clip(0.11 + 0.012 * (adi - 5) - 0.0015 * (age - 45), 0.03, 0.30)
    p_former = np.clip(0.18 + 0.004 * (age - 45), 0.08, 0.40)
    u = rng.random(n)
    smoking[:] = "Never"
    smoking[u < p_current] = "Current"
    smoking[(u >= p_current) & (u < p_current + p_former)] = "Former"

    # BMI: regional + deprivation + age effects
    bmi_mu = 27.6 + 0.045 * (age - 45) - 0.0009 * (age - 45) ** 2 + 0.28 * (adi - 5)
    bmi_mu += np.where(region == "South", 0.9, np.where(region == "West", -0.7, 0.1))
    bmi_mu += np.where(race == "Asian", -2.2, 0) + np.where(race == "Black or African American", 1.1, 0)
    bmi = np.clip(rng.normal(bmi_mu, 5.6), 16.5, 62).round(1)

    height_cm = np.where(sex == "M", rng.normal(176, 7, n), rng.normal(162.5, 6.5, n)).round(1)
    weight_kg = (bmi * (height_cm / 100) ** 2).round(1)

    # Digital enrollment
    enroll_logit = 0.9 - 0.035 * (age - 45) - 0.08 * (adi - 5)
    enroll_logit += np.where(urbanicity == "Rural", -0.35, np.where(urbanicity == "Urban", 0.15, 0))
    enroll_logit += np.where(insurance == "Uninsured", -0.5, np.where(insurance == "Medicare Advantage", 0.25, 0))
    app_enrolled = rng.random(n) < sigmoid(enroll_logit)

    enroll_days = rng.integers(0, 730, n)  # enrolled between Jan-2024 and Dec-2025
    enrollment_date = np.where(
        app_enrolled,
        (pd.Timestamp("2024-01-01") + pd.to_timedelta(enroll_days, unit="D")).strftime("%Y-%m-%d"),
        None,
    )

    wearable_logit = -0.9 + 1.9 * app_enrolled - 0.03 * (age - 45) - 0.06 * (adi - 5)
    wearable_user = rng.random(n) < sigmoid(wearable_logit)

    primary_care_assigned = rng.random(n) < np.clip(0.82 - 0.03 * (adi - 5) - 0.12 * (insurance == "Uninsured"), 0.3, 0.97)

    patients = pd.DataFrame({
        "patient_id": patient_id,
        "birth_date": birth_date.strftime("%Y-%m-%d"),
        "age": age,
        "sex": sex,
        "race_ethnicity": race,
        "region": region,
        "state": state,
        "urbanicity": urbanicity,
        "adi_decile": adi,
        "insurance_type": insurance,
        "smoking_status": smoking,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "bmi": bmi,
        "has_primary_care_provider": primary_care_assigned.astype(int),
        "app_enrolled": app_enrolled.astype(int),
        "app_enrollment_date": enrollment_date,
        "wearable_user": wearable_user.astype(int),
    })
    return patients


# --------------------------------------------------------------------------- #
# Chronic conditions
# --------------------------------------------------------------------------- #
def make_conditions(p: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(p)
    age, bmi, adi = p.age.values, p.bmi.values, p.adi_decile.values
    black = (p.race_ethnicity == "Black or African American").values
    hisp = (p.race_ethnicity == "Hispanic or Latino").values
    asian = (p.race_ethnicity == "Asian").values
    smoker = (p.smoking_status == "Current").values
    south = (p.region == "South").values

    obesity = bmi >= 30

    htn_logit = -1.85 + 0.07 * (age - 45) + 0.11 * (bmi - 27) + 0.06 * (adi - 5) + 0.55 * black + 0.25 * smoker + 0.15 * south
    hypertension = rng.random(n) < sigmoid(htn_logit)

    dm_logit = -3.25 + 0.05 * (age - 45) + 0.13 * (bmi - 27) + 0.07 * (adi - 5) + 0.45 * black + 0.5 * hisp + 0.35 * asian + 0.6 * hypertension + 0.15 * south
    diabetes = rng.random(n) < sigmoid(dm_logit)

    hl_logit = -1.7 + 0.055 * (age - 45) + 0.05 * (bmi - 27) + 0.7 * diabetes + 0.5 * hypertension
    hyperlipidemia = rng.random(n) < sigmoid(hl_logit)

    asthma_logit = -2.7 + 0.03 * (bmi - 27) + 0.35 * smoker + 0.05 * (adi - 5) - 0.01 * (age - 45)
    asthma = rng.random(n) < sigmoid(asthma_logit)

    rows = []

    def onset(mask, mean_years_ago):
        yrs = np.clip(rng.exponential(mean_years_ago, mask.sum()), 0.1, 40)
        return (SNAPSHOT_DATE - pd.to_timedelta(yrs * 365.25, unit="D")).strftime("%Y-%m-%d")

    # Hypertension with systolic / diastolic reading
    m = hypertension
    sbp = np.clip(rng.normal(139 + 0.9 * (adi[m] - 5) - 4 * p.app_enrolled.values[m], 15), 105, 210).round()
    dbp = np.clip(sbp * 0.62 + rng.normal(0, 6, m.sum()), 60, 125).round()
    rows.append(pd.DataFrame({
        "patient_id": p.patient_id.values[m], "condition_key": "hypertension",
        "condition_code": CONDITIONS["hypertension"]["code"], "condition_name": CONDITIONS["hypertension"]["name"],
        "onset_date": onset(m, 7), "measure_name": "systolic_bp_mmhg", "measure_value": sbp,
        "secondary_measure_name": "diastolic_bp_mmhg", "secondary_measure_value": dbp,
        "on_medication": (rng.random(m.sum()) < 0.72).astype(int),
    }))

    # Diabetes with HbA1c
    m = diabetes
    a1c = np.clip(rng.normal(7.6 + 0.12 * (adi[m] - 5) - 0.35 * p.app_enrolled.values[m], 1.3), 5.4, 14.5).round(1)
    rows.append(pd.DataFrame({
        "patient_id": p.patient_id.values[m], "condition_key": "diabetes",
        "condition_code": CONDITIONS["diabetes"]["code"], "condition_name": CONDITIONS["diabetes"]["name"],
        "onset_date": onset(m, 6), "measure_name": "hba1c_pct", "measure_value": a1c,
        "secondary_measure_name": None, "secondary_measure_value": np.nan,
        "on_medication": (rng.random(m.sum()) < 0.8).astype(int),
    }))

    # Obesity with BMI
    m = obesity
    rows.append(pd.DataFrame({
        "patient_id": p.patient_id.values[m], "condition_key": "obesity",
        "condition_code": CONDITIONS["obesity"]["code"], "condition_name": CONDITIONS["obesity"]["name"],
        "onset_date": onset(m, 5), "measure_name": "bmi", "measure_value": bmi[m],
        "secondary_measure_name": None, "secondary_measure_value": np.nan,
        "on_medication": (rng.random(m.sum()) < 0.12).astype(int),
    }))

    # Hyperlipidemia with LDL
    m = hyperlipidemia
    ldl = np.clip(rng.normal(138, 28, m.sum()), 70, 260).round()
    rows.append(pd.DataFrame({
        "patient_id": p.patient_id.values[m], "condition_key": "hyperlipidemia",
        "condition_code": CONDITIONS["hyperlipidemia"]["code"], "condition_name": CONDITIONS["hyperlipidemia"]["name"],
        "onset_date": onset(m, 6), "measure_name": "ldl_mg_dl", "measure_value": ldl,
        "secondary_measure_name": None, "secondary_measure_value": np.nan,
        "on_medication": (rng.random(m.sum()) < 0.6).astype(int),
    }))

    # Asthma (no measure)
    m = asthma
    rows.append(pd.DataFrame({
        "patient_id": p.patient_id.values[m], "condition_key": "asthma",
        "condition_code": CONDITIONS["asthma"]["code"], "condition_name": CONDITIONS["asthma"]["name"],
        "onset_date": onset(m, 15), "measure_name": None, "measure_value": np.nan,
        "secondary_measure_name": None, "secondary_measure_value": np.nan,
        "on_medication": (rng.random(m.sum()) < 0.65).astype(int),
    }))

    conditions = pd.concat(rows, ignore_index=True)
    conditions.insert(0, "condition_record_id", [f"C{idx:07d}" for idx in range(1, len(conditions) + 1)])
    return conditions


# --------------------------------------------------------------------------- #
# Preventive screenings
# --------------------------------------------------------------------------- #
def make_screenings(p: pd.DataFrame, conditions: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    diabetic_ids = set(conditions.loc[conditions.condition_key == "diabetes", "patient_id"])
    is_diabetic = p.patient_id.isin(diabetic_ids).values

    age, sex, adi = p.age.values, p.sex.values, p.adi_decile.values
    enrolled = p.app_enrolled.values.astype(bool)
    pcp = p.has_primary_care_provider.values.astype(bool)
    unins = (p.insurance_type == "Uninsured").values
    medicaid = (p.insurance_type == "Medicaid").values
    rural = (p.urbanicity == "Rural").values
    region = p.region.values

    frames = []
    for code, name, req_sex, min_age, max_age, interval, req_cond in SCREENINGS:
        eligible = (age >= min_age) & (age <= max_age)
        if req_sex != "Any":
            eligible &= sex == req_sex
        if req_cond == "diabetes":
            eligible &= is_diabetic
        idx = np.where(eligible)[0]
        k = len(idx)
        if k == 0:
            continue

        base = {"AWV": 0.46, "BP": 0.72, "FLU": 0.36, "LIPID": 0.55, "A1C_SCREEN": 0.42,
                "CRC": 0.50, "MAMMO": 0.60, "CERVICAL": 0.57, "A1C_DM": 0.66, "EYE_DM": 0.40}[code]
        logit = np.log(base / (1 - base))
        logit = logit + 0.55 * enrolled[idx] + 0.6 * pcp[idx] - 0.9 * unins[idx] - 0.25 * medicaid[idx]
        logit = logit - 0.07 * (adi[idx] - 5) - 0.25 * rural[idx]
        logit = logit + np.where(region[idx] == "Northeast", 0.2, np.where(region[idx] == "South", -0.15, 0))
        logit = logit + 0.004 * (age[idx] - 55)
        completed = rng.random(k) < sigmoid(logit)

        # Completed within interval -> last date within [snapshot - interval, snapshot]
        window_days = interval * 30.4
        days_ago = np.where(
            completed,
            rng.uniform(0, window_days, k),
            np.where(rng.random(k) < 0.55, rng.uniform(window_days, window_days * 2.5, k), np.nan),
        )
        last_date = SNAPSHOT_DATE - pd.to_timedelta(np.nan_to_num(days_ago, nan=0), unit="D")
        last_date = pd.Series(last_date).where(~np.isnan(days_ago), pd.NaT)
        next_due = last_date + pd.to_timedelta(window_days, unit="D")

        frames.append(pd.DataFrame({
            "patient_id": p.patient_id.values[idx],
            "screening_code": code,
            "screening_name": name,
            "is_eligible": 1,
            "is_completed": completed.astype(int),
            "last_completed_date": last_date.dt.strftime("%Y-%m-%d").values,
            "next_due_date": next_due.dt.strftime("%Y-%m-%d").values,
            "recommended_interval_months": interval,
            "reminder_sent": (rng.random(k) < (0.75 * enrolled[idx] + 0.15)).astype(int),
        }))

    screenings = pd.concat(frames, ignore_index=True)
    screenings.insert(0, "screening_record_id", [f"S{idx:07d}" for idx in range(1, len(screenings) + 1)])
    return screenings


# --------------------------------------------------------------------------- #
# Wearable vitals (monthly aggregates)
# --------------------------------------------------------------------------- #
def make_wearables(p: pd.DataFrame, conditions: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    users = p[p.wearable_user == 1].reset_index(drop=True)
    n = len(users)
    def flag(cond: str) -> np.ndarray:
        ids = set(conditions.loc[conditions.condition_key == cond, "patient_id"])
        return users.patient_id.isin(ids).values.astype(float)

    age, bmi = users.age.values.astype(float), users.bmi.values.astype(float)
    htn, dm = flag("hypertension"), flag("diabetes")
    enrolled = users.app_enrolled.values.astype(float)

    # Patient-level baselines
    steps_base = 7400 - 45 * (age - 45) - 170 * (bmi - 27) + 600 * enrolled - 250 * htn - 400 * dm + rng.normal(0, 1500, n)
    steps_base = np.clip(steps_base, 1200, 16000)
    sleep_base = np.clip(rng.normal(7.0 - 0.02 * (bmi - 27) - 0.01 * (age - 45), 0.75), 4.2, 9.8)
    hr_base = np.clip(rng.normal(66 + 0.35 * (bmi - 27) + 3.5 * htn + 2 * dm - 0.06 * (age - 45), 7), 48, 100)
    device = rng.choice(["Apple Watch", "Fitbit", "Garmin", "Samsung Galaxy Watch", "Oura Ring"], n, p=[0.42, 0.24, 0.13, 0.15, 0.06])

    # Churn: some users stop syncing part-way through the year
    active_until_month = np.where(rng.random(n) < 0.83, 12, rng.integers(2, 12, n))

    months = pd.period_range("2025-01", "2025-12", freq="M")
    seasonal = np.array([-900, -750, -250, 250, 550, 700, 650, 500, 250, 0, -450, -800])

    frames = []
    for mi, month in enumerate(months):
        active = active_until_month >= (mi + 1)
        k = active.sum()
        steps = steps_base[active] + seasonal[mi] + rng.normal(0, 700, k)
        frames.append(pd.DataFrame({
            "patient_id": users.patient_id.values[active],
            "month": str(month),
            "device_type": device[active],
            "avg_daily_steps": np.clip(steps, 300, 30000).round(),
            "avg_sleep_hours": np.clip(sleep_base[active] + rng.normal(0, 0.3, k), 3.5, 11).round(2),
            "avg_resting_hr": np.clip(hr_base[active] + rng.normal(0, 1.8, k), 42, 115).round(1),
            "active_days": np.clip(rng.binomial(month.days_in_month, 0.78 + 0.1 * (enrolled[active] - 0.5)), 1, month.days_in_month),
            "days_with_10k_steps": None,  # filled below
        }))
    w = pd.concat(frames, ignore_index=True)
    frac_10k = np.clip((w.avg_daily_steps - 6000) / 9000, 0, 1)
    w["days_with_10k_steps"] = np.minimum(w.active_days, rng.binomial(w.active_days, frac_10k))
    w.insert(0, "wearable_record_id", [f"W{idx:07d}" for idx in range(1, len(w) + 1)])
    return w


# --------------------------------------------------------------------------- #
# App engagement events
# --------------------------------------------------------------------------- #
def make_events(p: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    enrolled = p[p.app_enrolled == 1].reset_index(drop=True)
    n = len(enrolled)
    enroll_dt = pd.to_datetime(enrolled.app_enrollment_date)

    # Heavy-tailed activity level: many light users, a few power users
    rate = rng.gamma(shape=1.15, scale=7.5, size=n)  # expected events in the year
    rate *= np.clip(1 - 0.012 * (enrolled.age.values - 45), 0.45, 1.6)
    rate *= np.where(enrolled.wearable_user.values == 1, 1.35, 1.0)
    # About 18% of enrolled users never come back after signup
    dormant = rng.random(n) < 0.18
    counts = np.where(dormant, rng.integers(0, 2, n), rng.poisson(rate))
    counts = np.minimum(counts, 120)

    total = int(counts.sum())
    pid = np.repeat(enrolled.patient_id.values, counts)
    start = np.maximum(np.repeat(enroll_dt.values, counts), np.datetime64(PERIOD_START))
    span_days = (np.datetime64(SNAPSHOT_DATE) - start).astype("timedelta64[D]").astype(int) + 1
    offset_days = (rng.random(total) * span_days).astype(int)
    seconds = rng.integers(6 * 3600, 23 * 3600, total)
    ts = start + offset_days.astype("timedelta64[D]") + seconds.astype("timedelta64[s]")

    types = np.array(list(EVENT_TYPES))
    probs = np.array([EVENT_TYPES[t][0] for t in types])
    event_type = rng.choice(types, size=total, p=probs)
    channel_p = np.where(np.repeat(enrolled.age.values, counts) >= 60, 0.32, 0.12)
    channel = np.where(rng.random(total) < channel_p, "Web",
                       np.where(rng.random(total) < 0.56, "iOS", "Android"))
    session_minutes = np.clip(rng.lognormal(1.2, 0.7, total), 0.2, 90).round(1)

    events = pd.DataFrame({
        "event_id": [f"E{idx:08d}" for idx in range(1, total + 1)],
        "patient_id": pid,
        "event_timestamp": pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": event_type,
        "event_category": [EVENT_TYPES[t][1] for t in event_type],
        "channel": channel,
        "session_minutes": session_minutes,
    })
    return events.sort_values("event_timestamp").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Deliberate data-quality defects
# --------------------------------------------------------------------------- #
def inject_defects(patients, conditions, screenings, wearables, events, rng):
    log = {}

    # Patients: duplicates, casing / whitespace, missing BMI, implausible values, state name variants
    dup = patients.sample(320, random_state=1)
    patients = pd.concat([patients, dup], ignore_index=True)
    log["duplicate_patient_rows"] = len(dup)

    i = rng.choice(len(patients), 900, replace=False)
    patients.loc[i, "region"] = patients.loc[i, "region"].str.upper()
    j = rng.choice(len(patients), 700, replace=False)
    patients.loc[j, "region"] = " " + patients.loc[j, "region"].str.lower() + " "
    k = rng.choice(len(patients), 1200, replace=False)
    patients.loc[k, "sex"] = patients.loc[k, "sex"].map({"F": "female", "M": "male"})
    log["inconsistent_casing_rows"] = len(i) + len(j) + len(k)

    s = rng.choice(len(patients), 1500, replace=False)
    patients.loc[s, "state"] = patients.loc[s, "state"].map(STATE_NAMES)
    log["state_full_name_rows"] = len(s)

    miss = rng.choice(len(patients), 1400, replace=False)
    patients.loc[miss, "bmi"] = np.nan
    log["missing_bmi_rows"] = len(miss)
    bad = rng.choice(len(patients), 90, replace=False)
    patients.loc[bad, "bmi"] = rng.choice([7.2, 8.9, 95.0, 112.4, 0.0], len(bad))
    log["implausible_bmi_rows"] = len(bad)

    ages = rng.choice(len(patients), 45, replace=False)
    patients.loc[ages, "birth_date"] = (SNAPSHOT_DATE + pd.to_timedelta(rng.integers(30, 800, len(ages)), unit="D")).strftime("%Y-%m-%d")
    log["future_birth_date_rows"] = len(ages)
    patients = patients.sample(frac=1, random_state=7).reset_index(drop=True)

    # Wearables: impossible values + duplicate rows
    w_idx = rng.choice(len(wearables), 1100, replace=False)
    wearables.loc[w_idx[:400], "avg_daily_steps"] = -1 * wearables.loc[w_idx[:400], "avg_daily_steps"]
    wearables.loc[w_idx[400:650], "avg_daily_steps"] = rng.integers(60000, 250000, 250)
    wearables.loc[w_idx[650:850], "avg_sleep_hours"] = rng.uniform(19, 26, 200).round(2)
    wearables.loc[w_idx[850:], "avg_resting_hr"] = 0
    log["implausible_wearable_rows"] = len(w_idx)
    wearables = pd.concat([wearables, wearables.sample(500, random_state=3)], ignore_index=True)
    log["duplicate_wearable_rows"] = 500

    # Events: duplicate ids, timestamps after snapshot, orphan patient ids
    events = pd.concat([events, events.sample(1500, random_state=5)], ignore_index=True)
    log["duplicate_event_rows"] = 1500
    e_idx = rng.choice(len(events), 600, replace=False)
    events.loc[e_idx, "event_timestamp"] = (SNAPSHOT_DATE + pd.to_timedelta(rng.integers(1, 120, 600), unit="D")).strftime("%Y-%m-%d %H:%M:%S")
    log["future_event_rows"] = 600
    o_idx = rng.choice(len(events), 250, replace=False)
    events.loc[o_idx, "patient_id"] = "P9999999"
    log["orphan_event_rows"] = 250
    events.loc[rng.choice(len(events), 400, replace=False), "channel"] = "ios"
    events.loc[rng.choice(len(events), 300, replace=False), "channel"] = "ANDROID"
    log["inconsistent_channel_rows"] = 700

    # Screenings: completed date in the future, is_completed but no date
    sc_idx = rng.choice(np.where(screenings.is_completed == 1)[0], 350, replace=False)
    screenings.loc[sc_idx[:200], "last_completed_date"] = (SNAPSHOT_DATE + pd.to_timedelta(rng.integers(5, 200, 200), unit="D")).strftime("%Y-%m-%d")
    screenings.loc[sc_idx[200:], "last_completed_date"] = None
    log["inconsistent_screening_rows"] = 350

    # Conditions: duplicate records
    conditions = pd.concat([conditions, conditions.sample(400, random_state=9)], ignore_index=True)
    log["duplicate_condition_rows"] = 400

    return patients, conditions, screenings, wearables, events, log


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-patients", type=int, default=50_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("data/raw"))
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.n_patients:,} synthetic patients (seed={args.seed}) ...")
    patients = make_patients(args.n_patients, rng)
    conditions = make_conditions(patients, rng)
    screenings = make_screenings(patients, conditions, rng)
    wearables = make_wearables(patients, conditions, rng)
    events = make_events(patients, rng)

    patients, conditions, screenings, wearables, events, log = inject_defects(
        patients, conditions, screenings, wearables, events, rng
    )

    tables = {
        "patients": patients,
        "conditions": conditions,
        "screenings": screenings,
        "wearable_monthly": wearables,
        "engagement_events": events,
    }
    for name, df in tables.items():
        path = args.out / f"{name}.csv.gz"
        df.to_csv(path, index=False, compression="gzip")
        print(f"  wrote {path}  ({len(df):,} rows, {df.shape[1]} cols)")

    meta = {
        "generator": "03-population-health-powerbi/src/generate_synthetic_data.py",
        "seed": args.seed,
        "n_patients_requested": args.n_patients,
        "snapshot_date": SNAPSHOT_DATE.strftime("%Y-%m-%d"),
        "period_start": PERIOD_START.strftime("%Y-%m-%d"),
        "row_counts": {k: int(len(v)) for k, v in tables.items()},
        "injected_defects": log,
    }
    (args.out / "generation_metadata.json").write_text(json.dumps(meta, indent=2))
    print("Injected defects:", json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
