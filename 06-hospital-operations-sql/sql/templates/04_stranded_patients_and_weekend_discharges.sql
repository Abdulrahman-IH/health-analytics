-- =============================================================================
-- 04  Long-stay ("stranded") patients and the weekend discharge gap
-- -----------------------------------------------------------------------------
-- Question  How much bed capacity is locked up in long stays, and does
--           discharge activity collapse at weekends (then spike on Monday)?
-- Method    * Stranded = LOS >= 7 days, super-stranded = LOS >= 21 days
--             (NHS England definitions). We report their share of discharges
--             and, more importantly, their share of occupied bed-days.
--           * Weekend discharge ratio = average Sat/Sun daily discharges divided
--             by average Mon-Fri daily discharges (1.0 = seven-day service).
--           * Monday surge = Monday discharges / average Tue-Fri discharges.
--           * PERCENT_RANK() places each hospital in the network distribution.
-- Grain     hospital (2025 discharges)
-- =============================================================================
WITH stays AS (
    SELECT hospital_id,
           @DAYS(admit_ts, discharge_ts)     AS los_days,
           @DOW(discharge_ts)                AS discharge_dow       -- 0 = Sunday
    FROM admissions
    WHERE discharge_ts >= '2025-01-01'
      AND discharge_ts <  '2026-01-01'
),
by_hospital AS (
    SELECT hospital_id,
           COUNT(*)                                                         AS discharges,
           SUM(los_days)                                                    AS bed_days,
           SUM(CASE WHEN los_days >= 7  THEN 1 ELSE 0 END)                  AS stranded,
           SUM(CASE WHEN los_days >= 21 THEN 1 ELSE 0 END)                  AS super_stranded,
           SUM(CASE WHEN los_days >= 7  THEN los_days ELSE 0 END)           AS stranded_bed_days,
           SUM(CASE WHEN los_days >= 21 THEN los_days ELSE 0 END)           AS super_stranded_bed_days,
           -- 2025 has 104 weekend days, 261 weekdays and 52 Mondays / 209 Tue-Fri days
           SUM(CASE WHEN discharge_dow IN (0, 6) THEN 1 ELSE 0 END) / 104.0   AS weekend_daily,
           SUM(CASE WHEN discharge_dow BETWEEN 1 AND 5 THEN 1 ELSE 0 END) / 261.0 AS weekday_daily,
           SUM(CASE WHEN discharge_dow = 1 THEN 1 ELSE 0 END) / 52.0          AS monday_daily,
           SUM(CASE WHEN discharge_dow BETWEEN 2 AND 5 THEN 1 ELSE 0 END) / 209.0 AS tue_fri_daily
    FROM stays
    GROUP BY hospital_id
),
metrics AS (
    SELECT hospital_id,
           discharges,
           1.0 * stranded / discharges                     AS stranded_share,
           1.0 * super_stranded / discharges               AS super_stranded_share,
           stranded_bed_days / bed_days                    AS stranded_bed_day_share,
           super_stranded_bed_days / bed_days              AS super_stranded_bed_day_share,
           weekend_daily / weekday_daily                   AS weekend_discharge_ratio,
           monday_daily / tue_fri_daily                    AS monday_surge_ratio
    FROM by_hospital
)
SELECT h.hospital_code,
       h.hospital_type,
       m.discharges,
       ROUND(m.stranded_share, 4)                 AS stranded_share,
       ROUND(m.super_stranded_share, 4)           AS super_stranded_share,
       ROUND(m.stranded_bed_day_share, 4)         AS stranded_bed_day_share,
       ROUND(m.super_stranded_bed_day_share, 4)   AS super_stranded_bed_day_share,
       ROUND(m.weekend_discharge_ratio, 3)        AS weekend_discharge_ratio,
       ROUND(m.monday_surge_ratio, 3)             AS monday_surge_ratio,
       ROUND(CAST(PERCENT_RANK() OVER (ORDER BY m.stranded_bed_day_share) AS NUMERIC), 3)        AS stranded_pct_rank,
       ROUND(CAST(PERCENT_RANK() OVER (ORDER BY m.weekend_discharge_ratio DESC) AS NUMERIC), 3) AS weekend_gap_pct_rank
FROM metrics m
JOIN hospitals h ON h.hospital_id = m.hospital_id
ORDER BY m.stranded_bed_day_share DESC;
