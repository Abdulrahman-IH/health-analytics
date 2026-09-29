-- =============================================================================
-- 08  What drives 30-day readmission? — rate and relative risk by factor
-- -----------------------------------------------------------------------------
-- Question  Which patient groups and discharge circumstances carry the most
--           readmission risk, so transitional-care resources can be targeted?
-- Method    Same index-stay and readmission definitions as query 07. Each
--           factor (diagnosis group, discharge destination, age band, LOS
--           band, discharge day) is profiled from one base CTE via UNION ALL.
--           Relative risk = factor-level rate / overall rate, where the
--           overall rate is computed once with window aggregates over all
--           index stays. Levels with < 150 index stays are suppressed.
-- Grain     factor x level
-- =============================================================================
WITH ordered AS (
    SELECT a.*,
           LEAD(admit_ts)       OVER (PARTITION BY patient_id ORDER BY admit_ts) AS next_admit_ts,
           LEAD(admission_type) OVER (PARTITION BY patient_id ORDER BY admit_ts) AS next_admission_type
    FROM admissions a
),
index_stays AS (
    SELECT o.primary_diagnosis_group,
           o.discharge_disposition,
           CASE WHEN 2025 - p.birth_year < 18 THEN '0-17'
                WHEN 2025 - p.birth_year < 45 THEN '18-44'
                WHEN 2025 - p.birth_year < 65 THEN '45-64'
                WHEN 2025 - p.birth_year < 75 THEN '65-74'
                WHEN 2025 - p.birth_year < 85 THEN '75-84'
                ELSE '85+' END                                                    AS age_band,
           CASE WHEN @DAYS(o.admit_ts, o.discharge_ts) < 1  THEN '1: <1 day'
                WHEN @DAYS(o.admit_ts, o.discharge_ts) < 3  THEN '2: 1-2 days'
                WHEN @DAYS(o.admit_ts, o.discharge_ts) < 7  THEN '3: 3-6 days'
                WHEN @DAYS(o.admit_ts, o.discharge_ts) < 21 THEN '4: 7-20 days'
                ELSE '5: 21+ days' END                                            AS los_band,
           CASE WHEN @DOW(o.discharge_ts) IN (5, 6, 0) THEN 'Fri-Sun' ELSE 'Mon-Thu' END AS discharge_day,
           o.admission_type,
           CASE WHEN o.next_admission_type = 'Emergency'
                 AND @DAYS(o.discharge_ts, o.next_admit_ts) <= 30 THEN 1 ELSE 0 END AS readmitted_30d
    FROM ordered o
    JOIN patients p ON p.patient_id = o.patient_id
    WHERE o.discharge_ts >= '2025-01-01'
      AND o.discharge_ts <  '2025-12-02'
      AND o.discharge_disposition NOT IN ('Died', 'Transferred to another hospital')
),
profiled AS (
    SELECT 'Diagnosis group' AS factor, primary_diagnosis_group AS level_value,
           COUNT(*) AS index_stays, SUM(readmitted_30d) AS readmissions
    FROM index_stays GROUP BY primary_diagnosis_group
    UNION ALL
    SELECT 'Discharge destination', discharge_disposition, COUNT(*), SUM(readmitted_30d)
    FROM index_stays GROUP BY discharge_disposition
    UNION ALL
    SELECT 'Age band', age_band, COUNT(*), SUM(readmitted_30d)
    FROM index_stays GROUP BY age_band
    UNION ALL
    SELECT 'Length of stay', los_band, COUNT(*), SUM(readmitted_30d)
    FROM index_stays GROUP BY los_band
    UNION ALL
    SELECT 'Discharge day', discharge_day, COUNT(*), SUM(readmitted_30d)
    FROM index_stays GROUP BY discharge_day
    UNION ALL
    SELECT 'Admission type', admission_type, COUNT(*), SUM(readmitted_30d)
    FROM index_stays GROUP BY admission_type
),
with_overall AS (
    SELECT p.*,
           1.0 * readmissions / index_stays                                  AS rate,
           -- each factor partitions the full population, so any factor's totals
           -- give the overall rate
           1.0 * SUM(readmissions) OVER (PARTITION BY factor)
               / SUM(index_stays)  OVER (PARTITION BY factor)                AS overall_rate,
           1.0 * readmissions / SUM(readmissions) OVER (PARTITION BY factor) AS share_of_readmissions
    FROM profiled p
)
SELECT factor,
       level_value,
       index_stays,
       readmissions,
       ROUND(rate, 4)                                                        AS readmission_rate_30d,
       ROUND(rate / overall_rate, 2)                                         AS relative_risk,
       ROUND(share_of_readmissions, 4)                                       AS share_of_readmissions,
       RANK() OVER (PARTITION BY factor ORDER BY rate DESC)                  AS risk_rank_in_factor
FROM with_overall
WHERE index_stays >= 150
ORDER BY factor, readmission_rate_30d DESC;
