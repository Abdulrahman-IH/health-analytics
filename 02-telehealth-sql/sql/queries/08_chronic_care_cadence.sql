-- Q8 · Follow-up cadence in chronic disease management (2023-2025)
-- Patients with an established chronic condition should be seen at least
-- every six months. Patients are classed by whether they used telehealth in
-- the *prior* period (2021-2022), so exposure precedes the outcome, and the
-- two groups are compared on 2023-2025 visit frequency, the gap between
-- visits and the share who never let a gap exceed six months.
-- Techniques: cohort CTE from a view, LAG() to compute gaps between
-- consecutive visits, LEFT JOINs to keep patients with no visits at all.

WITH cohort AS (
    SELECT patient_id, condition_group
    FROM v_patient_chronic
    WHERE condition_group IN ('Hypertension', 'Type 2 diabetes', 'Heart disease',
                              'Asthma', 'Chronic kidney disease', 'Behavioural health')
      AND first_onset <= '2022-12-31'                -- established before the window
),
prior_use AS (       -- exposure: any telehealth visit in 2021-2022
    SELECT DISTINCT patient_id
    FROM encounters
    WHERE modality = 'telehealth'
      AND start_date BETWEEN '2021-01-01' AND '2022-12-31'
),
visits AS (
    SELECT c.condition_group,
           e.patient_id,
           e.start_ts,
           LAG(e.start_ts) OVER (PARTITION BY c.condition_group, e.patient_id
                                 ORDER BY e.start_ts)                    AS prev_ts
    FROM cohort c
    JOIN encounters e ON e.patient_id = c.patient_id
    WHERE e.encounter_class IN ('ambulatory', 'outpatient', 'wellness', 'virtual')
      AND e.start_date BETWEEN '2023-01-01' AND '2025-12-31'
),
per_patient AS (
    SELECT condition_group,
           patient_id,
           COUNT(*)                                                      AS visits,
           MAX(julianday(start_ts) - julianday(prev_ts))                 AS longest_gap_days,
           AVG(julianday(start_ts) - julianday(prev_ts))                 AS mean_gap_days
    FROM visits
    GROUP BY condition_group, patient_id
),
classified AS (
    SELECT c.condition_group,
           c.patient_id,
           COALESCE(v.visits, 0)                                         AS visits,
           v.longest_gap_days,
           v.mean_gap_days,
           CASE WHEN u.patient_id IS NOT NULL
                THEN 'prior telehealth user' ELSE 'in-person only' END   AS user_type,
           -- on cadence = at least 6 visits in 3 years and never more than ~6 months between visits
           CASE WHEN COALESCE(v.visits, 0) >= 6 AND v.longest_gap_days <= 200 THEN 1 ELSE 0 END AS on_cadence
    FROM cohort c
    LEFT JOIN per_patient v USING (condition_group, patient_id)
    LEFT JOIN prior_use   u USING (patient_id)
)
SELECT condition_group,
       user_type,
       COUNT(*)                                                          AS patients,
       ROUND(AVG(visits) / 3.0, 1)                                       AS visits_per_patient_year,
       ROUND(AVG(mean_gap_days), 0)                                      AS avg_gap_between_visits_days,
       ROUND(100.0 * SUM(visits = 0) / COUNT(*), 1)                     AS pct_with_no_visits,
       ROUND(100.0 * SUM(on_cadence) / COUNT(*), 1)                     AS pct_on_6_month_cadence
FROM classified
GROUP BY condition_group, user_type
ORDER BY condition_group, user_type;
