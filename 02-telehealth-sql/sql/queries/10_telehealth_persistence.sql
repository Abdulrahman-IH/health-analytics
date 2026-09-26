-- Q10 · Do first-time telehealth users come back?
-- Cohorts by year of first telehealth visit: how many returned for a second
-- virtual visit within 12 months, how long that took, and what share of
-- their later visits stayed virtual.
-- Techniques: ROW_NUMBER() to find the first telehealth visit, LEAD() for
-- the next one, correlated aggregation over later visits, cohort CTEs.

WITH tele AS (
    SELECT patient_id,
           encounter_id,
           start_ts,
           ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY start_ts)    AS tele_visit_no,
           LEAD(start_ts)  OVER (PARTITION BY patient_id ORDER BY start_ts)  AS next_tele_ts
    FROM encounters
    WHERE modality = 'telehealth'
),
first_visit AS (
    SELECT patient_id,
           start_ts                                                        AS first_tele_ts,
           CAST(strftime('%Y', start_ts) AS INTEGER)                       AS cohort_year,
           julianday(next_tele_ts) - julianday(start_ts)                   AS days_to_second
    FROM tele
    WHERE tele_visit_no = 1
      AND start_ts <= '2024-12-31'          -- every cohort gets a full 12 months of follow-up
),
later_visits AS (   -- all scheduled-type visits in the 12 months after the first telehealth visit
    SELECT f.patient_id,
           COUNT(*)                                                        AS later_visits,
           SUM(e.modality = 'telehealth')                                  AS later_telehealth
    FROM first_visit f
    JOIN encounters e
      ON e.patient_id = f.patient_id
     AND e.start_ts   > f.first_tele_ts
     AND julianday(e.start_ts) - julianday(f.first_tele_ts) <= 365
     AND e.encounter_class IN ('ambulatory', 'outpatient', 'wellness', 'virtual')
    GROUP BY f.patient_id
)
SELECT f.cohort_year,
       COUNT(*)                                                            AS first_time_users,
       ROUND(100.0 * SUM(f.days_to_second <= 365) / COUNT(*), 1)          AS pct_repeat_within_12m,
       ROUND(AVG(CASE WHEN f.days_to_second <= 365 THEN f.days_to_second END), 0)
                                                                           AS avg_days_to_second_visit,
       ROUND(100.0 * SUM(l.later_telehealth) / NULLIF(SUM(l.later_visits), 0), 1)
                                                                           AS telehealth_share_of_next_12m_visits_pct,
       ROUND(100.0 * SUM(l.later_visits IS NULL) / COUNT(*), 1)           AS pct_with_no_visit_of_any_kind_next_12m
FROM first_visit f
LEFT JOIN later_visits l USING (patient_id)
GROUP BY f.cohort_year
ORDER BY f.cohort_year;
