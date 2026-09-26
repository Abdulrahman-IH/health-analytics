-- ---------------------------------------------------------------------------
-- Telehealth & Patient Engagement Analysis · SQLite schema
--
-- Source: Synthea synthetic EHR export (CSV), Massachusetts, 1,500 living
-- patients, study window 2019-01-01 to 2025-12-31 (seven full years). Direct identifiers that
-- Synthea generates (names, SSN, street address) are dropped at load time
-- even though they are synthetic, so the database is safe to share.
--
-- Tables
--   patients       one row per patient, with age and age band at the
--                  reference date
--   organizations  care sites
--   providers      clinicians, with speciality
--   payers         insurance products
--   encounters     one row per visit; encounter_class = 'virtual' is a
--                  telehealth visit, everything else is in person
--   conditions     problem-list entries with onset / resolution dates
--   medications    prescriptions with dispense counts
--   appointments   scheduling layer derived from encounters, adding
--                  no-show and cancellation rows (see build_database.py)
-- ---------------------------------------------------------------------------

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS medications;
DROP TABLE IF EXISTS conditions;
DROP TABLE IF EXISTS encounters;
DROP TABLE IF EXISTS providers;
DROP TABLE IF EXISTS organizations;
DROP TABLE IF EXISTS payers;
DROP TABLE IF EXISTS patients;

CREATE TABLE patients (
    patient_id      INTEGER PRIMARY KEY,
    source_id       TEXT NOT NULL UNIQUE,      -- Synthea UUID, kept for traceability
    birth_date      DATE NOT NULL,
    death_date      DATE,
    gender          TEXT NOT NULL CHECK (gender IN ('M', 'F')),
    race            TEXT,
    ethnicity       TEXT,
    marital_status  TEXT,
    city            TEXT,
    state           TEXT,
    county          TEXT,
    zip             TEXT,
    income          INTEGER,
    age_years       INTEGER NOT NULL,          -- age at reference date 2025-12-31
    age_group       TEXT NOT NULL CHECK (age_group IN ('0-17', '18-34', '35-49', '50-64', '65+'))
);

CREATE TABLE organizations (
    organization_id INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    city            TEXT,
    state           TEXT,
    zip             TEXT
);

CREATE TABLE providers (
    provider_id     INTEGER PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations (organization_id),
    gender          TEXT,
    speciality      TEXT,
    city            TEXT,
    state           TEXT
);

CREATE TABLE payers (
    payer_id        INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    ownership       TEXT
);

CREATE TABLE encounters (
    encounter_id        INTEGER PRIMARY KEY,
    patient_id          INTEGER NOT NULL REFERENCES patients (patient_id),
    organization_id     INTEGER REFERENCES organizations (organization_id),
    provider_id         INTEGER REFERENCES providers (provider_id),
    payer_id            INTEGER REFERENCES payers (payer_id),
    start_ts            DATETIME NOT NULL,
    stop_ts             DATETIME,
    start_date          DATE NOT NULL,          -- date part of start_ts, for joins
    encounter_class     TEXT NOT NULL,          -- ambulatory | wellness | outpatient | urgentcare | emergency | inpatient | virtual | ...
    modality            TEXT NOT NULL CHECK (modality IN ('telehealth', 'in_person')),
    encounter_code      TEXT,
    encounter_type      TEXT,                   -- SNOMED description of the visit type
    reason_code         TEXT,
    reason_description  TEXT,
    base_cost           REAL,
    total_claim_cost    REAL,
    payer_coverage      REAL
);

CREATE TABLE conditions (
    condition_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patients (patient_id),
    encounter_id    INTEGER REFERENCES encounters (encounter_id),
    onset_date      DATE NOT NULL,
    resolved_date   DATE,
    code_system     TEXT,
    code            TEXT NOT NULL,
    description     TEXT NOT NULL,
    condition_group TEXT                         -- analyst-assigned chronic-condition bucket, NULL if not tracked
);

CREATE TABLE medications (
    medication_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          INTEGER NOT NULL REFERENCES patients (patient_id),
    encounter_id        INTEGER REFERENCES encounters (encounter_id),
    payer_id            INTEGER REFERENCES payers (payer_id),
    start_date          DATE NOT NULL,
    stop_date           DATE,
    code                TEXT NOT NULL,
    description         TEXT NOT NULL,
    dispenses           INTEGER,
    base_cost           REAL,
    total_cost          REAL,
    reason_code         TEXT,
    reason_description  TEXT
);

-- Scheduling layer. Every completed appointment maps to one encounter.
-- No-show and cancelled appointments have no encounter and are generated
-- by a documented, seeded model in build_database.py.
CREATE TABLE appointments (
    appointment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patients (patient_id),
    encounter_id    INTEGER REFERENCES encounters (encounter_id),   -- NULL unless status = 'completed'
    provider_id     INTEGER REFERENCES providers (provider_id),
    scheduled_date  DATE NOT NULL,          -- date the visit was booked for
    booked_date     DATE NOT NULL,          -- date the booking was made
    lead_days       INTEGER NOT NULL,       -- scheduled_date - booked_date
    modality        TEXT NOT NULL CHECK (modality IN ('telehealth', 'in_person')),
    visit_category  TEXT NOT NULL,          -- wellness | ambulatory | outpatient | urgentcare | virtual ...
    status          TEXT NOT NULL CHECK (status IN ('completed', 'no_show', 'cancelled'))
);

CREATE INDEX idx_enc_patient_start ON encounters (patient_id, start_ts);
CREATE INDEX idx_cond_patient     ON conditions (patient_id, onset_date);
CREATE INDEX idx_med_patient      ON medications (patient_id, start_date);
CREATE INDEX idx_appt_patient     ON appointments (patient_id, scheduled_date);

-- Convenience views -----------------------------------------------------------

-- One row per patient per tracked chronic condition (earliest onset).
CREATE VIEW v_patient_chronic AS
SELECT patient_id,
       condition_group,
       MIN(onset_date) AS first_onset
FROM conditions
WHERE condition_group IS NOT NULL
GROUP BY patient_id, condition_group;

-- Encounters with patient demographics attached.
CREATE VIEW v_encounter_demo AS
SELECT e.*,
       p.gender,
       p.age_years,
       p.age_group,
       CAST(strftime('%Y', e.start_ts) AS INTEGER) AS visit_year,
       strftime('%Y-%m', e.start_ts)               AS visit_month
FROM encounters e
JOIN patients p ON p.patient_id = e.patient_id;
