-- Q3 · Telehealth use by chronic condition (2021-2025)
-- For every tracked chronic-condition cohort: visits after diagnosis,
-- telehealth share, share of patients who ever used telehealth, and a rank.
-- Techniques: view-based cohort CTE, date-conditioned JOIN, CROSS JOIN to a
-- one-row benchmark, DENSE_RANK().

WITH cohort AS (
    SELECT condition_group, patient_id, first_onset
    FROM v_patient_chronic
),
visits AS (
    SELECT c.condition_group, e.patient_id, e.encounter_id, e.modality
    FROM cohort c
    JOIN encounters e
      ON e.patient_id = c.patient_id
     AND e.start_date >= c.first_onset                 -- only visits after the diagnosis
    WHERE e.start_date BETWEEN '2021-01-01' AND '2025-12-31'
),
agg AS (
    SELECT condition_group,
           COUNT(DISTINCT patient_id)                                     AS patients,
           COUNT(*)                                                       AS visits,
           SUM(modality = 'telehealth')                                   AS telehealth_visits,
           COUNT(DISTINCT CASE WHEN modality = 'telehealth'
                               THEN patient_id END)                       AS telehealth_users
    FROM visits
    GROUP BY condition_group
),
benchmark AS (
    SELECT ROUND(100.0 * SUM(modality = 'telehealth') / COUNT(*), 1)    AS overall_share_pct
    FROM encounters
    WHERE start_date BETWEEN '2021-01-01' AND '2025-12-31'
)
SELECT a.condition_group,
       a.patients,
       a.visits,
       a.telehealth_visits,
       ROUND(100.0 * a.telehealth_visits / a.visits, 1)                  AS telehealth_share_pct,
       b.overall_share_pct,
       ROUND(100.0 * a.telehealth_users / a.patients, 1)                 AS pct_patients_using_telehealth,
       ROUND(1.0 * a.visits / a.patients, 1)                             AS visits_per_patient,
       DENSE_RANK() OVER (ORDER BY 1.0 * a.telehealth_visits / a.visits DESC) AS rank_by_share
FROM agg a
CROSS JOIN benchmark b
WHERE a.patients >= 30
ORDER BY telehealth_share_pct DESC;
