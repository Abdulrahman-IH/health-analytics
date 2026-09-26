-- Q7 · Follow-up adherence after an emergency or inpatient discharge
-- Transitions-of-care measure: share of discharges with an ambulatory,
-- outpatient, wellness or virtual visit within 7 / 14 / 30 days, and how
-- often that first follow-up was delivered by telehealth.
-- Techniques: CTE, self-join on the encounters table, ROW_NUMBER() to pick
-- the first follow-up per discharge, LEFT JOIN to keep non-followed-up cases.

WITH acute AS (
    SELECT encounter_id                       AS index_id,
           patient_id,
           encounter_class                    AS index_class,
           COALESCE(stop_ts, start_ts)        AS discharge_ts
    FROM encounters
    WHERE encounter_class IN ('emergency', 'inpatient')
      AND start_date BETWEEN '2019-01-01' AND '2025-11-30'   -- leave a full 30-day window
),
candidates AS (
    SELECT a.index_id,
           f.modality                                                  AS followup_modality,
           julianday(f.start_ts) - julianday(a.discharge_ts)           AS days_to_followup,
           ROW_NUMBER() OVER (PARTITION BY a.index_id ORDER BY f.start_ts) AS rn
    FROM acute a
    JOIN encounters f
      ON f.patient_id = a.patient_id
     AND f.start_ts   > a.discharge_ts
     AND f.encounter_class IN ('ambulatory', 'outpatient', 'wellness', 'virtual')
),
first_followup AS (
    SELECT index_id, followup_modality, days_to_followup
    FROM candidates
    WHERE rn = 1
),
joined AS (
    SELECT a.index_id,
           a.index_class,
           p.age_group,
           ff.followup_modality,
           ff.days_to_followup
    FROM acute a
    JOIN patients p USING (patient_id)
    LEFT JOIN first_followup ff USING (index_id)
)
SELECT index_class,
       age_group,
       COUNT(*)                                                          AS discharges,
       ROUND(100.0 * SUM(days_to_followup <= 7)  / COUNT(*), 1)          AS followup_7d_pct,
       ROUND(100.0 * SUM(days_to_followup <= 14) / COUNT(*), 1)          AS followup_14d_pct,
       ROUND(100.0 * SUM(days_to_followup <= 30) / COUNT(*), 1)          AS followup_30d_pct,
       ROUND(AVG(CASE WHEN days_to_followup <= 30 THEN days_to_followup END), 1)
                                                                         AS avg_days_to_followup,
       ROUND(100.0 * SUM(days_to_followup <= 30 AND followup_modality = 'telehealth')
                   / NULLIF(SUM(days_to_followup <= 30), 0), 1)          AS telehealth_share_of_30d_followups_pct
FROM joined
GROUP BY index_class, age_group
HAVING COUNT(*) >= 20
ORDER BY index_class, age_group;
