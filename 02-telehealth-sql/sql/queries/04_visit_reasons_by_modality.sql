-- Q4 · What telehealth is used for: top visit reasons by modality (2021-2025)
-- The documented reason for the visit where Synthea records one, otherwise
-- the visit type. Top 8 per modality with share of that modality's volume.
-- Techniques: CTE, COALESCE, SUM() OVER (PARTITION BY), ROW_NUMBER() top-N.

WITH reasons AS (
    SELECT modality,
           COALESCE(reason_description, encounter_type)                  AS reason,
           COUNT(*)                                                       AS visits
    FROM encounters
    WHERE start_date BETWEEN '2021-01-01' AND '2025-12-31'
    GROUP BY modality, reason
),
ranked AS (
    SELECT modality,
           reason,
           visits,
           ROUND(100.0 * visits / SUM(visits) OVER (PARTITION BY modality), 1) AS pct_of_modality,
           ROW_NUMBER() OVER (PARTITION BY modality ORDER BY visits DESC)      AS rn
    FROM reasons
)
SELECT modality,
       rn                                                                AS rank_in_modality,
       reason,
       visits,
       pct_of_modality
FROM ranked
WHERE rn <= 8
ORDER BY modality, rn;
