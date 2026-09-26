-- Q2 · Telehealth adoption by age group (steady state, 2021-2025)
-- Share of visits delivered virtually and share of patients who used
-- telehealth at least once, each compared with the population average.
-- Techniques: CTE, JOIN via view, SUM() OVER () for totals, RANK().

WITH steady AS (
    SELECT patient_id, age_group, modality
    FROM v_encounter_demo
    WHERE visit_year BETWEEN 2021 AND 2025
),
by_age AS (
    SELECT age_group,
           COUNT(DISTINCT patient_id)                                     AS patients,
           COUNT(*)                                                       AS visits,
           SUM(modality = 'telehealth')                                   AS telehealth_visits,
           COUNT(DISTINCT CASE WHEN modality = 'telehealth'
                               THEN patient_id END)                       AS telehealth_users
    FROM steady
    GROUP BY age_group
)
SELECT age_group,
       patients,
       visits,
       telehealth_visits,
       ROUND(100.0 * telehealth_visits / visits, 1)                      AS telehealth_share_pct,
       ROUND(100.0 * telehealth_users / patients, 1)                     AS pct_patients_using_telehealth,
       ROUND(100.0 * SUM(telehealth_visits) OVER ()
                   / SUM(visits) OVER (), 1)                              AS overall_share_pct,
       ROUND(100.0 * telehealth_visits / visits
             - 100.0 * SUM(telehealth_visits) OVER ()
                     / SUM(visits) OVER (), 1)                            AS diff_vs_overall_pts,
       RANK() OVER (ORDER BY 1.0 * telehealth_visits / visits DESC)      AS adoption_rank
FROM by_age
ORDER BY age_group;
