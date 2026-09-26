-- Q9 · Patient engagement by age group and condition (2023-2025)
-- Engagement is measured per patient as (a) visits per year, (b) the
-- appointment completion rate (completed / (completed + no-show)) and
-- (c) telehealth share. Patients are then placed into engagement quartiles
-- with NTILE() and the mix is reported for every age group x condition cell.
-- Techniques: multi-CTE patient-level features, JOINs across four tables,
-- NTILE() OVER (ORDER BY), conditional aggregation.

WITH cohort AS (
    SELECT pc.patient_id, pc.condition_group, p.age_group
    FROM v_patient_chronic pc
    JOIN patients p USING (patient_id)
    WHERE pc.condition_group IN ('Hypertension', 'Type 2 diabetes', 'Heart disease',
                                 'Asthma', 'Behavioural health')
      AND pc.first_onset <= '2022-12-31'
),
visit_stats AS (
    SELECT patient_id,
           COUNT(*)                          AS visits,
           SUM(modality = 'telehealth')      AS telehealth_visits
    FROM encounters
    WHERE start_date BETWEEN '2023-01-01' AND '2025-12-31'
      AND encounter_class IN ('ambulatory', 'outpatient', 'wellness', 'virtual')
    GROUP BY patient_id
),
appt_stats AS (
    SELECT patient_id,
           SUM(status = 'completed')         AS completed,
           SUM(status = 'no_show')           AS no_shows
    FROM appointments
    WHERE scheduled_date BETWEEN '2023-01-01' AND '2025-12-31'
    GROUP BY patient_id
),
patient_level AS (
    SELECT c.patient_id,
           c.condition_group,
           c.age_group,
           COALESCE(v.visits, 0) / 3.0                                   AS visits_per_year,
           COALESCE(1.0 * v.telehealth_visits / NULLIF(v.visits, 0), 0)  AS telehealth_share,
           1.0 * a.completed / NULLIF(a.completed + a.no_shows, 0)       AS completion_rate
    FROM cohort c
    LEFT JOIN visit_stats v USING (patient_id)
    LEFT JOIN appt_stats  a USING (patient_id)
),
quartiles AS (        -- quartile of visit frequency across the whole chronic cohort
    SELECT *,
           NTILE(4) OVER (ORDER BY visits_per_year) AS engagement_quartile
    FROM (SELECT DISTINCT patient_id, visits_per_year FROM patient_level)
)
SELECT pl.age_group,
       pl.condition_group,
       COUNT(*)                                                          AS patients,
       ROUND(AVG(pl.visits_per_year), 1)                                 AS visits_per_patient_year,
       ROUND(100.0 * AVG(pl.completion_rate), 1)                         AS appointment_completion_pct,
       ROUND(100.0 * AVG(pl.telehealth_share), 1)                        AS telehealth_share_pct,
       ROUND(100.0 * SUM(q.engagement_quartile = 4) / COUNT(*), 1)       AS pct_in_top_engagement_quartile,
       ROUND(100.0 * SUM(q.engagement_quartile = 1) / COUNT(*), 1)       AS pct_in_bottom_engagement_quartile
FROM patient_level pl
JOIN quartiles q USING (patient_id)
GROUP BY pl.age_group, pl.condition_group
HAVING COUNT(*) >= 10
ORDER BY pl.condition_group, pl.age_group;
