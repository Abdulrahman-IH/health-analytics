-- Q5 · No-show and cancellation rates by modality and age group (2021-2025)
-- Each segment is compared with its modality total, its age-group total and
-- the overall rate, all computed in the same pass with window functions.
-- Techniques: JOIN, CTE, conditional aggregation, SUM() OVER (PARTITION BY).

WITH appts AS (
    SELECT a.status, a.modality, p.age_group
    FROM appointments a
    JOIN patients p USING (patient_id)
    WHERE a.scheduled_date BETWEEN '2021-01-01' AND '2025-12-31'
),
seg AS (
    SELECT age_group,
           modality,
           COUNT(*)                     AS booked,
           SUM(status = 'completed')    AS completed,
           SUM(status = 'no_show')      AS no_shows,
           SUM(status = 'cancelled')    AS cancelled
    FROM appts
    GROUP BY age_group, modality
)
SELECT age_group,
       modality,
       booked,
       completed,
       no_shows,
       cancelled,
       ROUND(100.0 * no_shows  / booked, 1)                                        AS no_show_rate_pct,
       ROUND(100.0 * cancelled / booked, 1)                                        AS cancel_rate_pct,
       ROUND(100.0 * SUM(no_shows) OVER (PARTITION BY modality)
                   / SUM(booked)   OVER (PARTITION BY modality), 1)                AS modality_no_show_rate_pct,
       ROUND(100.0 * SUM(no_shows) OVER (PARTITION BY age_group)
                   / SUM(booked)   OVER (PARTITION BY age_group), 1)               AS age_group_no_show_rate_pct,
       ROUND(100.0 * no_shows / booked
             - 100.0 * SUM(no_shows) OVER () / SUM(booked) OVER (), 1)             AS diff_vs_overall_pts
FROM seg
ORDER BY age_group, modality;
