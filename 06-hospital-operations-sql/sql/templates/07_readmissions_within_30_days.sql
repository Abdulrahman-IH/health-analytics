-- =============================================================================
-- 07  30-day unplanned readmission rate — by hospital, department and network
-- -----------------------------------------------------------------------------
-- Question  Which hospitals and specialties send patients home who come back
--           as an emergency within 30 days?
-- Method    * LEAD() over each patient's admissions (ordered by admit time,
--             across ALL hospitals) finds the next admission.
--           * Index stays: discharged 1 Jan - 1 Dec 2025 (so every index stay
--             has a full 30-day follow-up before the data extract), excluding
--             deaths and transfers out.
--           * Readmission = next admission is an Emergency admission starting
--             within 30 days of discharge. Elective returns are planned care
--             and are not counted.
--           * Attributed to the discharging hospital; we also show how many
--             readmissions present at a different hospital — invisible in a
--             single-site dataset.
--           * Level rows are stacked with UNION ALL (SQLite has no GROUPING SETS).
-- Grain     hospital | department | network
-- =============================================================================
WITH ordered AS (
    SELECT a.*,
           LEAD(admit_ts)       OVER (PARTITION BY patient_id ORDER BY admit_ts) AS next_admit_ts,
           LEAD(admission_type) OVER (PARTITION BY patient_id ORDER BY admit_ts) AS next_admission_type,
           LEAD(hospital_id)    OVER (PARTITION BY patient_id ORDER BY admit_ts) AS next_hospital_id
    FROM admissions a
),
index_stays AS (
    SELECT hospital_id,
           department_id,
           CASE WHEN next_admission_type = 'Emergency'
                 AND @DAYS(discharge_ts, next_admit_ts) <= 30 THEN 1 ELSE 0 END      AS readmitted_30d,
           CASE WHEN next_admission_type = 'Emergency'
                 AND @DAYS(discharge_ts, next_admit_ts) <= 30
                 AND next_hospital_id <> hospital_id THEN 1 ELSE 0 END               AS readmitted_elsewhere,
           CASE WHEN next_admission_type = 'Emergency'
                 AND @DAYS(discharge_ts, next_admit_ts) <= 7 THEN 1 ELSE 0 END       AS readmitted_7d
    FROM ordered
    WHERE discharge_ts >= '2025-01-01'
      AND discharge_ts <  '2025-12-02'
      AND discharge_disposition NOT IN ('Died', 'Transferred to another hospital')
),
levels AS (
    SELECT 'Hospital' AS level, h.hospital_code AS entity,
           COUNT(*) AS index_stays, SUM(readmitted_30d) AS readmissions_30d,
           SUM(readmitted_7d) AS readmissions_7d, SUM(readmitted_elsewhere) AS readmitted_elsewhere
    FROM index_stays i JOIN hospitals h ON h.hospital_id = i.hospital_id
    GROUP BY h.hospital_code
    UNION ALL
    SELECT 'Department', d.department_code,
           COUNT(*), SUM(readmitted_30d), SUM(readmitted_7d), SUM(readmitted_elsewhere)
    FROM index_stays i JOIN departments d ON d.department_id = i.department_id
    GROUP BY d.department_code
    UNION ALL
    SELECT 'Network', 'ALL',
           COUNT(*), SUM(readmitted_30d), SUM(readmitted_7d), SUM(readmitted_elsewhere)
    FROM index_stays
),
rates AS (
    SELECT l.*,
           1.0 * readmissions_30d / index_stays AS rate_30d
    FROM levels l
)
SELECT level,
       entity,
       index_stays,
       readmissions_30d,
       ROUND(rate_30d, 4)                                              AS readmission_rate_30d,
       ROUND(1.0 * readmissions_7d / index_stays, 4)                   AS readmission_rate_7d,
       ROUND(1.0 * readmitted_elsewhere / NULLIF(readmissions_30d, 0), 4) AS share_readmitted_elsewhere,
       ROUND(rate_30d / MAX(CASE WHEN level = 'Network' THEN rate_30d END) OVER (), 3)
                                                                       AS ratio_to_network,
       CASE WHEN level = 'Network' THEN NULL
            ELSE RANK() OVER (PARTITION BY level ORDER BY rate_30d DESC) END AS rank_within_level
FROM rates
ORDER BY CASE level WHEN 'Network' THEN 0 WHEN 'Hospital' THEN 1 ELSE 2 END,
         readmission_rate_30d DESC;
