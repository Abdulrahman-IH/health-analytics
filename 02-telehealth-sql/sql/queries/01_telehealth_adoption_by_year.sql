-- Q1 · Telehealth adoption over time
-- Yearly visit volume, telehealth share and its year-on-year change (LAG),
-- new telehealth users per year and the cumulative user base (running SUM).
-- Techniques: CTEs, LEFT JOIN, LAG(), SUM() OVER (ORDER BY).

WITH yearly AS (
    SELECT visit_year,
           COUNT(*)                                                       AS visits,
           SUM(modality = 'telehealth')                                   AS telehealth_visits,
           COUNT(DISTINCT patient_id)                                     AS patients_seen,
           COUNT(DISTINCT CASE WHEN modality = 'telehealth'
                               THEN patient_id END)                       AS telehealth_patients
    FROM v_encounter_demo
    GROUP BY visit_year
),
first_use AS (                      -- year of each patient's first telehealth visit
    SELECT patient_id, MIN(visit_year) AS first_tele_year
    FROM v_encounter_demo
    WHERE modality = 'telehealth'
    GROUP BY patient_id
),
new_users AS (
    SELECT first_tele_year AS visit_year, COUNT(*) AS new_telehealth_users
    FROM first_use
    GROUP BY first_tele_year
)
SELECT y.visit_year,
       y.visits,
       y.telehealth_visits,
       ROUND(100.0 * y.telehealth_visits / y.visits, 1)                  AS telehealth_share_pct,
       ROUND(100.0 * y.telehealth_visits / y.visits
             - LAG(100.0 * y.telehealth_visits / y.visits)
                   OVER (ORDER BY y.visit_year), 1)                       AS share_change_pts,
       y.telehealth_patients,
       ROUND(100.0 * y.telehealth_patients / y.patients_seen, 1)         AS pct_active_patients_using_telehealth,
       COALESCE(n.new_telehealth_users, 0)                                AS new_telehealth_users,
       SUM(COALESCE(n.new_telehealth_users, 0))
           OVER (ORDER BY y.visit_year)                                   AS cumulative_telehealth_users
FROM yearly y
LEFT JOIN new_users n USING (visit_year)
ORDER BY y.visit_year;
