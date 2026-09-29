"""
Synthetic data generator for Project 7: Medication Adherence & Digital Reminder Impact.

Creates five linked tables for 20,000 patients with chronic conditions:

    data/patients.csv.gz         one row per patient (demographics, clinical, social factors)
    data/app_enrollment.csv.gz   one row per patient enrolled in the reminder app
    data/prescriptions.csv.gz    one row per chronic maintenance prescription
    data/refills.csv.gz          one row per pharmacy fill (claims-style)
    data/reminder_logs.csv.gz    one row per refill reminder sent by the app

Design notes
------------
* Measurement year is calendar 2025. Prescriptions start (first fill) between
  1 Jan and 31 Mar 2025, so every Rx has 9-12 months of follow-up.
* Enrolment in the reminder app is NOT random: younger, digitally literate
  smartphone owners with more conditions opt in more often. The notebook has
  to deal with this confounding (propensity weighting) instead of reading the
  raw difference as the causal effect.
* Each refill is simulated sequentially. A patient-level latent adherence
  propensity drives the chance of refilling on time. For app users, a refill
  reminder is sent 3 days before the due date; if the patient engages with it,
  the chance of an on-time refill rises. Engagement fades with "reminder
  fatigue" over the year, and a follow-up nudge goes out if the refill is
  3+ days overdue.
* Everything is seeded, so the data are reproducible.

Run:  python generate_data.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
N_PATIENTS = 20_000
YEAR_START = pd.Timestamp("2025-01-01")
YEAR_END = pd.Timestamp("2025-12-31")
OUT = Path(__file__).parent / "data"

rng = np.random.default_rng(SEED)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# --------------------------------------------------------------------------
# 1. Patients
# --------------------------------------------------------------------------
n = N_PATIENTS
patient_id = np.array([f"P{i:05d}" for i in range(1, n + 1)])

age = np.clip(rng.normal(61, 13, n), 25, 92).round().astype(int)
sex = rng.choice(["Female", "Male"], n, p=[0.53, 0.47])
region = rng.choice(["North", "South", "East", "West", "Central"], n,
                    p=[0.22, 0.24, 0.18, 0.20, 0.16])
urban = rng.choice(["Urban", "Suburban", "Rural"], n, p=[0.45, 0.35, 0.20])
insurance = rng.choice(["Commercial", "Medicare", "Medicaid", "Self-pay"], n,
                       p=[0.40, 0.38, 0.17, 0.05])
insurance = np.where((age >= 65) & (rng.random(n) < 0.85), "Medicare", insurance)

# Chronic conditions (correlated through a shared cardiometabolic factor)
cm = rng.normal(0, 1, n) + (age - 60) / 20
has_htn = rng.random(n) < sigmoid(0.2 + 0.9 * cm)
has_dm = rng.random(n) < sigmoid(-0.9 + 0.7 * cm)
has_hld = rng.random(n) < sigmoid(-0.3 + 0.8 * cm)
has_copd = rng.random(n) < sigmoid(-2.4 + 0.4 * cm)
has_hf = rng.random(n) < sigmoid(-3.0 + 0.8 * cm)
cond = np.column_stack([has_htn, has_dm, has_hld, has_copd, has_hf])
# every patient in the cohort has >=1 chronic condition on maintenance therapy
none = cond.sum(1) == 0
cond[none, rng.integers(0, 3, none.sum())] = True
has_htn, has_dm, has_hld, has_copd, has_hf = cond.T
n_conditions = cond.sum(1)

depression = rng.random(n) < sigmoid(-1.8 + 0.25 * n_conditions)
prior_hosp = rng.poisson(0.15 + 0.18 * n_conditions + 0.4 * has_hf)
smartphone = rng.random(n) < sigmoid(3.2 - 0.055 * (age - 40))
digital_literacy = np.clip(
    rng.normal(6.5 - 0.06 * (age - 55) + 1.2 * smartphone, 1.6), 0, 10).round(1)

copay_base = {"Commercial": 18, "Medicare": 12, "Medicaid": 3, "Self-pay": 45}
monthly_copay = np.array([copay_base[i] for i in insurance]) * rng.lognormal(0, 0.45, n)
monthly_copay = (monthly_copay * (0.6 + 0.25 * n_conditions)).round(2)

patients = pd.DataFrame({
    "patient_id": patient_id, "age": age, "sex": sex, "region": region,
    "urbanicity": urban, "insurance_type": insurance,
    "hypertension": has_htn.astype(int), "type2_diabetes": has_dm.astype(int),
    "hyperlipidemia": has_hld.astype(int), "copd": has_copd.astype(int),
    "heart_failure": has_hf.astype(int), "n_chronic_conditions": n_conditions,
    "depression_dx": depression.astype(int), "prior_year_hospitalizations": prior_hosp,
    "smartphone_owner": smartphone.astype(int), "digital_literacy_score": digital_literacy,
    "monthly_copay_usd": monthly_copay,
})

# --------------------------------------------------------------------------
# 2. App enrolment (confounded opt-in)
# --------------------------------------------------------------------------
enrol_logit = (-2.75 + 0.35 * (digital_literacy - 6) - 0.022 * (age - 60)
               + 1.6 * smartphone + 0.18 * n_conditions
               + 0.25 * (urban == "Urban") - 0.3 * (insurance == "Self-pay"))
enrolled = rng.random(n) < sigmoid(enrol_logit)
enrolled &= smartphone | (rng.random(n) < 0.25)          # SMS-only users possible

enr_idx = np.where(enrolled)[0]
enr_channel = np.where(smartphone[enr_idx],
                       rng.choice(["Push", "SMS"], len(enr_idx), p=[0.78, 0.22]), "SMS")
enr_date = YEAR_START - pd.to_timedelta(rng.integers(0, 180, len(enr_idx)), unit="D")
enr_time_pref = rng.choice(["Morning", "Midday", "Evening"], len(enr_idx), p=[0.5, 0.15, 0.35])
dose_rem = rng.random(len(enr_idx)) < 0.72
caregiver = rng.random(len(enr_idx)) < np.where(age[enr_idx] >= 70, 0.3, 0.08)

app_enrollment = pd.DataFrame({
    "patient_id": patient_id[enr_idx],
    "enrollment_date": enr_date.date,
    "reminder_channel": enr_channel,
    "preferred_reminder_time": enr_time_pref,
    "refill_reminders_on": 1,
    "daily_dose_reminders_on": dose_rem.astype(int),
    "caregiver_alerts_on": caregiver.astype(int),
})

# Latent traits (never exported)
# adherence propensity: log-odds of an on-time refill without any reminder
propensity = (0.75 + 0.006 * (age - 60) + 0.14 * (digital_literacy - 6) - 0.55 * depression
              - 0.022 * (monthly_copay - 15) - 0.12 * np.maximum(n_conditions - 2, 0)
              - 0.35 * (insurance == "Medicaid") - 0.45 * (insurance == "Self-pay")
              - 0.15 * prior_hosp + rng.normal(0, 0.85, n))
# engagement propensity (only meaningful for enrolled)
engage = sigmoid(0.4 + 0.25 * (digital_literacy - 6) + rng.normal(0, 1.0, n))
engage_boost = np.zeros(n)
engage_boost[enr_idx] = np.where(enr_channel == "Push", 0.0, -0.6) + 0.55 * dose_rem + 0.5 * caregiver
engage = sigmoid(np.log(engage / (1 - engage)) + engage_boost)

# --------------------------------------------------------------------------
# 3. Prescriptions
# --------------------------------------------------------------------------
drug_map = {
    "hypertension": [("ACE inhibitor", 0.4), ("ARB", 0.3), ("Calcium channel blocker", 0.3)],
    "type2_diabetes": [("Metformin", 0.65), ("SGLT2 inhibitor", 0.2), ("DPP-4 inhibitor", 0.15)],
    "hyperlipidemia": [("Statin", 1.0)],
    "copd": [("LAMA/LABA inhaler", 1.0)],
    "heart_failure": [("Beta blocker", 1.0)],
}
cond_names = list(drug_map)
drug_effect = {"Statin": -0.25, "LAMA/LABA inhaler": -0.35, "Metformin": -0.1,
               "SGLT2 inhibitor": 0.05, "DPP-4 inhibitor": 0.0, "ACE inhibitor": 0.0,
               "ARB": 0.05, "Calcium channel blocker": 0.0, "Beta blocker": 0.1}

rx_rows = []
for i in range(n):
    for c_i, c in enumerate(cond_names):
        if cond[i, c_i]:
            names, probs = zip(*drug_map[c])
            rx_rows.append((i, c, rng.choice(names, p=probs)))
rx = pd.DataFrame(rx_rows, columns=["p_idx", "condition", "drug_class"])
rx["rx_id"] = [f"RX{k:06d}" for k in range(1, len(rx) + 1)]
rx["patient_id"] = patient_id[rx.p_idx]
rx["start_date"] = YEAR_START + pd.to_timedelta(rng.integers(0, 90, len(rx)), unit="D")
mail_order = rng.random(n) < sigmoid(-1.3 + 0.03 * (age - 60) + 0.4 * (insurance == "Commercial"))
rx["pharmacy_type"] = np.where(mail_order[rx.p_idx], "Mail order", "Retail")
rx["days_supply"] = np.where(rx.pharmacy_type == "Mail order", 90,
                             np.where(rng.random(len(rx)) < 0.2, 90, 30))
rx["prescriber_specialty"] = rng.choice(
    ["Primary care", "Cardiology", "Endocrinology", "Pulmonology"], len(rx),
    p=[0.7, 0.12, 0.1, 0.08])

# --------------------------------------------------------------------------
# 4. Refill + reminder simulation
# --------------------------------------------------------------------------
fills, logs = [], []
reminder_effect = 1.15   # log-odds lift on on-time refill when patient engages
followup_effect = 0.55   # extra lift from an engaged overdue follow-up nudge
end = YEAR_END
enrolled_set = set(enr_idx)
chan_of = dict(zip(enr_idx, enr_channel))
time_pref_hour = {"Morning": 8, "Midday": 12, "Evening": 19}
pref_of = dict(zip(enr_idx, enr_time_pref))

log_k = 0
for r in rx.itertuples(index=False):
    i = r.p_idx
    is_enr = i in enrolled_set
    base = propensity[i] + drug_effect[r.drug_class] + (0.35 if r.days_supply == 90 else 0)
    fill_date = r.start_date
    k = 0
    while fill_date <= end:
        fills.append((r.rx_id, patients.patient_id.iat[i], fill_date, r.days_supply,
                      r.days_supply * (2 if r.drug_class == "Metformin" else 1),
                      r.pharmacy_type))
        due = fill_date + pd.Timedelta(days=int(r.days_supply))
        if due > end:
            break
        k += 1
        month = (due - YEAR_START).days / 30.4
        logit = base - 0.05 * k                      # adherence decays over time
        engaged = False
        if is_enr:
            fatigue = sigmoid(np.log(engage[i] / (1 - engage[i])) - 0.07 * month)
            send = due - pd.Timedelta(days=3)
            u = rng.random()
            if u < fatigue * 0.55:
                action = "Refill requested"; engaged = True
            elif u < fatigue:
                action = "Opened"; engaged = rng.random() < 0.75
            elif u < fatigue + (1 - fatigue) * 0.25:
                action = "Snoozed"
            elif u < fatigue + (1 - fatigue) * 0.5:
                action = "Dismissed"
            else:
                action = "Ignored"
            hour = time_pref_hour[pref_of[i]]
            ts = send + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 30)))
            resp = (round(float(rng.lognormal(3.2, 1.1)), 1)
                    if action in ("Refill requested", "Opened", "Snoozed", "Dismissed") else np.nan)
            log_k += 1
            logs.append((f"L{log_k:07d}", patients.patient_id.iat[i], r.rx_id, ts,
                         "Refill due (3-day)", chan_of[i], action, resp))
            if engaged:
                logit += reminder_effect
        on_time = rng.random() < sigmoid(logit)
        if on_time:
            gap = int(rng.integers(-6, 5))
        else:
            gap = int(rng.exponential(22)) + 5
            # overdue nudge for app users
            if is_enr and gap >= 3:
                nudge_day = due + pd.Timedelta(days=3)
                u = rng.random()
                fatigue = sigmoid(np.log(engage[i] / (1 - engage[i])) - 0.07 * month)
                act2 = ("Refill requested" if u < fatigue * 0.45 else
                        "Opened" if u < fatigue * 0.8 else
                        "Dismissed" if u < fatigue * 0.8 + 0.1 else "Ignored")
                log_k += 1
                hour = time_pref_hour[pref_of[i]]
                logs.append((f"L{log_k:07d}", patients.patient_id.iat[i], r.rx_id,
                             nudge_day + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 30))),
                             "Overdue follow-up", chan_of[i], act2,
                             round(float(rng.lognormal(3.4, 1.1)), 1) if act2 != "Ignored" else np.nan))
                if act2 == "Refill requested" and rng.random() < sigmoid(followup_effect):
                    gap = int(rng.integers(3, 8))
        # discontinuation (treatment stops, no more fills)
        p_stop = sigmoid(-3.6 - 0.45 * base + (0.5 if gap > 30 else 0) - (0.4 if engaged else 0))
        if rng.random() < p_stop:
            break
        fill_date = due + pd.Timedelta(days=gap)

refills = pd.DataFrame(fills, columns=["rx_id", "patient_id", "fill_date", "days_supply",
                                       "quantity", "pharmacy_type"])
refills = refills.sort_values(["patient_id", "rx_id", "fill_date"]).reset_index(drop=True)
refills.insert(0, "fill_id", [f"F{k:07d}" for k in range(1, len(refills) + 1)])
refills["fill_date"] = refills.fill_date.dt.date

reminder_logs = pd.DataFrame(logs, columns=["log_id", "patient_id", "rx_id", "sent_at",
                                            "reminder_type", "channel", "action",
                                            "response_minutes"])

prescriptions = rx[["rx_id", "patient_id", "condition", "drug_class", "start_date",
                    "days_supply", "pharmacy_type", "prescriber_specialty"]].copy()
prescriptions = prescriptions.rename(columns={"days_supply": "standard_days_supply"})
prescriptions["start_date"] = prescriptions.start_date.dt.date

# --------------------------------------------------------------------------
# 5. Save
# --------------------------------------------------------------------------
OUT.mkdir(exist_ok=True)
tables = {"patients": patients, "app_enrollment": app_enrollment,
          "prescriptions": prescriptions, "refills": refills,
          "reminder_logs": reminder_logs}
for name, df in tables.items():
    df.to_csv(OUT / f"{name}.csv.gz", index=False, compression="gzip")
    print(f"{name:16s} {len(df):>8,d} rows  {df.shape[1]} cols")
