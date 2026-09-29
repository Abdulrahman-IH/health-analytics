-- Health Insurance Claims & Fraud Signals - SQLite schema
PRAGMA foreign_keys = ON;

CREATE TABLE members (
    member_id        TEXT PRIMARY KEY,
    first_name       TEXT NOT NULL,
    last_name        TEXT NOT NULL,
    gender           TEXT CHECK (gender IN ('F','M')),
    birth_date       DATE NOT NULL,
    state            TEXT NOT NULL,
    enrollment_date  DATE NOT NULL,
    risk_score       REAL            -- relative prospective risk (1.0 = median member)
);

CREATE TABLE policies (
    policy_id         TEXT PRIMARY KEY,
    member_id         TEXT NOT NULL REFERENCES members(member_id),
    plan_type         TEXT CHECK (plan_type IN ('PPO','HMO','EPO','HDHP')),
    metal_tier        TEXT CHECK (metal_tier IN ('Bronze','Silver','Gold','Platinum')),
    coverage_start    DATE NOT NULL,
    coverage_end      DATE NOT NULL,
    annual_deductible REAL,
    oop_max           REAL,
    monthly_premium   REAL,
    oon_benefit       INTEGER CHECK (oon_benefit IN (0,1)),   -- 1 = plan pays out-of-network
    policy_status     TEXT CHECK (policy_status IN ('Active','Expired','Terminated'))
);

CREATE TABLE providers (
    provider_id     TEXT PRIMARY KEY,
    npi             TEXT UNIQUE NOT NULL,
    provider_name   TEXT NOT NULL,
    specialty       TEXT NOT NULL,
    provider_type   TEXT CHECK (provider_type IN ('Professional','Facility','Ancillary')),
    state           TEXT NOT NULL,
    network_status  TEXT CHECK (network_status IN ('In-Network','Out-of-Network')),
    contract_start  DATE
);

CREATE TABLE diagnosis_codes (
    diagnosis_code  TEXT PRIMARY KEY,   -- ICD-10-CM
    description     TEXT NOT NULL,
    category        TEXT NOT NULL,
    is_chronic      INTEGER CHECK (is_chronic IN (0,1))
);

CREATE TABLE procedure_codes (
    procedure_code            TEXT PRIMARY KEY,   -- CPT / HCPCS
    description               TEXT NOT NULL,
    category                  TEXT NOT NULL,
    reference_allowed_amount  REAL NOT NULL,      -- 2024 fee-schedule reference per unit
    requires_prior_auth       INTEGER CHECK (requires_prior_auth IN (0,1))
);

CREATE TABLE rejection_reasons (
    reason_code  TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    category     TEXT NOT NULL,
    is_avoidable INTEGER CHECK (is_avoidable IN (0,1))   -- preventable with a clean front-end submission
);

CREATE TABLE claims (
    claim_id               TEXT PRIMARY KEY,
    member_id              TEXT NOT NULL REFERENCES members(member_id),
    policy_id              TEXT NOT NULL REFERENCES policies(policy_id),
    provider_id            TEXT NOT NULL REFERENCES providers(provider_id),
    claim_type             TEXT CHECK (claim_type IN ('Professional','Institutional')),
    place_of_service       TEXT,
    service_date           DATE NOT NULL,
    submission_date        DATE NOT NULL,
    adjudication_date      DATE,                 -- NULL while pending
    diagnosis_code         TEXT NOT NULL REFERENCES diagnosis_codes(diagnosis_code),
    procedure_code         TEXT NOT NULL REFERENCES procedure_codes(procedure_code),
    units                  INTEGER NOT NULL DEFAULT 1,
    billed_amount          REAL NOT NULL,
    approved_amount        REAL,                 -- 0 when rejected, NULL while pending
    claim_status           TEXT CHECK (claim_status IN ('Approved','Rejected','Pending')),
    rejection_reason_code  TEXT REFERENCES rejection_reasons(reason_code)
);

CREATE INDEX idx_claims_provider  ON claims(provider_id);
CREATE INDEX idx_claims_service   ON claims(service_date);
-- leading member_id column also serves member-level lookups
CREATE INDEX idx_claims_dup_key   ON claims(member_id, provider_id, service_date, procedure_code);
CREATE INDEX idx_policies_member  ON policies(member_id);
