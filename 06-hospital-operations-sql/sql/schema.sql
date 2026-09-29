-- =============================================================================
-- Hospital Operations & Bed Utilisation — relational schema
-- -----------------------------------------------------------------------------
-- Written in PostgreSQL DDL that SQLite also accepts unchanged:
--   * PostgreSQL: native DATE / TIMESTAMP / BOOLEAN / NUMERIC types.
--   * SQLite: the same declarations map to type affinities; timestamps are
--     stored as ISO-8601 text ('YYYY-MM-DD HH:MM') and booleans as 0/1.
-- Surrogate keys are supplied by the loader (no SERIAL / AUTOINCREMENT) so the
-- same ids exist in both engines.
--
-- Grain summary
--   hospitals        1 row per hospital                         (15)
--   departments      1 row per clinical department              (9)
--   bed_capacity     1 row per hospital x department x validity window
--                    (slowly changing: winter escalation, refurbishment, ...)
--   patients         1 row per patient
--   admissions       1 row per inpatient department spell
--   er_visits        1 row per emergency department attendance
--   staffing_shifts  1 row per hospital x department x date x shift
-- =============================================================================

DROP TABLE IF EXISTS staffing_shifts;
DROP TABLE IF EXISTS er_visits;
DROP TABLE IF EXISTS admissions;
DROP TABLE IF EXISTS patients;
DROP TABLE IF EXISTS bed_capacity;
DROP TABLE IF EXISTS departments;
DROP TABLE IF EXISTS hospitals;

CREATE TABLE hospitals (
    hospital_id     SMALLINT     PRIMARY KEY,
    hospital_code   VARCHAR(6)   NOT NULL UNIQUE,
    hospital_name   VARCHAR(80)  NOT NULL,
    hospital_type   VARCHAR(20)  NOT NULL
        CHECK (hospital_type IN ('Teaching', 'Regional General', 'Community')),
    region          VARCHAR(20)  NOT NULL,
    city            VARCHAR(40)  NOT NULL,
    licensed_beds   INTEGER      NOT NULL CHECK (licensed_beds > 0),
    opened_year     SMALLINT
);

CREATE TABLE departments (
    department_id        SMALLINT     PRIMARY KEY,
    department_code      VARCHAR(6)   NOT NULL UNIQUE,
    department_name      VARCHAR(40)  NOT NULL,
    service_line         VARCHAR(30)  NOT NULL,
    is_inpatient         BOOLEAN      NOT NULL,       -- ED is the only non-inpatient unit
    target_occupancy     NUMERIC(4,3) NOT NULL,       -- planning target, e.g. 0.850
    target_patients_per_nurse NUMERIC(4,1) NOT NULL   -- safe-staffing ratio (patients : 1 RN)
);

-- Staffed beds (ED: treatment bays) valid over a closed date range.
-- effective_to IS NULL means "current". Ranges never overlap per hospital/department.
CREATE TABLE bed_capacity (
    capacity_id     INTEGER      PRIMARY KEY,
    hospital_id     SMALLINT     NOT NULL REFERENCES hospitals (hospital_id),
    department_id   SMALLINT     NOT NULL REFERENCES departments (department_id),
    effective_from  DATE         NOT NULL,
    effective_to    DATE,
    staffed_beds    INTEGER      NOT NULL CHECK (staffed_beds >= 0),
    change_reason   VARCHAR(40)  NOT NULL,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE patients (
    patient_id      INTEGER      PRIMARY KEY,
    sex             CHAR(1)      NOT NULL CHECK (sex IN ('F', 'M')),
    birth_year      SMALLINT     NOT NULL,
    home_region     VARCHAR(20)  NOT NULL
);

CREATE TABLE admissions (
    admission_id          INTEGER      PRIMARY KEY,
    patient_id            INTEGER      NOT NULL REFERENCES patients (patient_id),
    hospital_id           SMALLINT     NOT NULL REFERENCES hospitals (hospital_id),
    department_id         SMALLINT     NOT NULL REFERENCES departments (department_id),
    admit_ts              TIMESTAMP    NOT NULL,
    discharge_ts          TIMESTAMP,                  -- NULL = still in a bed at data extract
    admission_type        VARCHAR(10)  NOT NULL
        CHECK (admission_type IN ('Emergency', 'Elective')),
    admission_source      VARCHAR(40)  NOT NULL,
    primary_diagnosis_group VARCHAR(40) NOT NULL,
    discharge_disposition VARCHAR(40),                -- NULL while still admitted
    CHECK (discharge_ts IS NULL OR discharge_ts > admit_ts)
);

CREATE TABLE er_visits (
    er_visit_id           INTEGER      PRIMARY KEY,
    patient_id            INTEGER      NOT NULL REFERENCES patients (patient_id),
    hospital_id           SMALLINT     NOT NULL REFERENCES hospitals (hospital_id),
    arrival_ts            TIMESTAMP    NOT NULL,
    triage_category       SMALLINT     NOT NULL CHECK (triage_category BETWEEN 1 AND 5),
    provider_seen_ts      TIMESTAMP,                  -- NULL when the patient left without being seen
    decision_to_admit_ts  TIMESTAMP,                  -- populated for admitted patients only
    departure_ts          TIMESTAMP    NOT NULL,
    er_disposition        VARCHAR(30)  NOT NULL
        CHECK (er_disposition IN ('Admitted', 'Discharged', 'Transferred', 'Left Without Being Seen')),
    admission_id          INTEGER      REFERENCES admissions (admission_id),
    CHECK (departure_ts >= arrival_ts)
);

CREATE TABLE staffing_shifts (
    hospital_id       SMALLINT  NOT NULL REFERENCES hospitals (hospital_id),
    department_id     SMALLINT  NOT NULL REFERENCES departments (department_id),
    shift_date        DATE      NOT NULL,
    shift_type        VARCHAR(5) NOT NULL CHECK (shift_type IN ('Day', 'Night')),
    rostered_nurses   SMALLINT  NOT NULL,
    nurses_on_duty    SMALLINT  NOT NULL,             -- includes agency / bank cover
    agency_nurses     SMALLINT  NOT NULL,
    doctors_on_duty   SMALLINT  NOT NULL,
    PRIMARY KEY (hospital_id, department_id, shift_date, shift_type)
);

-- Indexes: capacity range lookups and the patient timeline used for readmissions.
-- The census / ED queries aggregate whole tables, so they scan rather than seek;
-- add (hospital_id, admit_ts) / (hospital_id, arrival_ts) indexes for point lookups
-- in a production warehouse.
CREATE INDEX ix_capacity_hosp_dept   ON bed_capacity (hospital_id, department_id, effective_from);
CREATE INDEX ix_adm_patient_admit    ON admissions (patient_id, admit_ts);
CREATE INDEX ix_er_admission         ON er_visits (admission_id);
