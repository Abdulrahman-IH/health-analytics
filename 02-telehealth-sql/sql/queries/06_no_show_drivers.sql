-- Q6 · What drives no-shows: lead time, weekday and visit category, by modality
-- One long table of "driver / level" rows with in-person and telehealth
-- no-show rates side by side and the gap between them.
-- Techniques: CTE with derived bands, UNION ALL, conditional aggregation,
-- RANK() OVER (PARTITION BY driver).

WITH appts AS (
    SELECT a.status,
           a.modality,
           a.visit_category,
           CASE WHEN a.lead_days <= 3  THEN '0-3 days'
                WHEN a.lead_days <= 14 THEN '4-14 days'
                WHEN a.lead_days <= 30 THEN '15-30 days'
                ELSE                        '31+ days' END                  AS lead_band,
           CASE strftime('%w', a.scheduled_date)
                WHEN '1' THEN 'Mon' WHEN '2' THEN 'Tue' WHEN '3' THEN 'Wed'
                WHEN '4' THEN 'Thu' WHEN '5' THEN 'Fri' ELSE 'Weekend' END   AS weekday
    FROM appointments a
    WHERE a.scheduled_date BETWEEN '2021-01-01' AND '2025-12-31'
),
long AS (
    SELECT 'Booking lead time' AS driver, lead_band      AS level, modality, status FROM appts
    UNION ALL
    SELECT 'Weekday',                     weekday        AS level, modality, status FROM appts
    UNION ALL
    SELECT 'Visit category',              visit_category AS level, modality, status FROM appts
),
agg AS (
    SELECT driver,
           level,
           SUM(modality = 'in_person')                                  AS booked_in_person,
           SUM(modality = 'in_person'  AND status = 'no_show')          AS no_show_in_person,
           SUM(modality = 'telehealth')                                 AS booked_telehealth,
           SUM(modality = 'telehealth' AND status = 'no_show')          AS no_show_telehealth
    FROM long
    GROUP BY driver, level
)
SELECT driver,
       level,
       booked_in_person,
       ROUND(100.0 * no_show_in_person  / booked_in_person, 1)         AS no_show_rate_in_person_pct,
       booked_telehealth,
       ROUND(100.0 * no_show_telehealth / booked_telehealth, 1)        AS no_show_rate_telehealth_pct,
       ROUND(100.0 * no_show_in_person  / booked_in_person
             - 100.0 * no_show_telehealth / booked_telehealth, 1)       AS telehealth_advantage_pts,
       RANK() OVER (PARTITION BY driver
                    ORDER BY 1.0 * (no_show_in_person + no_show_telehealth)
                               / (booked_in_person + booked_telehealth) DESC) AS risk_rank_within_driver
FROM agg
WHERE booked_telehealth >= 50
ORDER BY driver, risk_rank_within_driver;
