-- Dialect: SQLite 3.25+  (generated from sql/templates/06_er_wait_by_hour_and_triage.sql by scripts/render_sql.py)
-- =============================================================================
-- 06  ED waits by arrival hour and triage category
-- -----------------------------------------------------------------------------
-- Question  When in the day does the ED fall behind, and are the sickest
--           patients protected when it does?
-- Method    * Network-wide 2025 attendances bucketed by arrival hour x triage
--             category (1 = resuscitation ... 5 = non-urgent).
--           * SUM() OVER (PARTITION BY triage) gives each hour's share of that
--             category's daily arrivals (demand profile).
--           * RANK() OVER (PARTITION BY triage ORDER BY avg wait) flags the
--             worst hours per category — the rota-planning signal.
--           * Arrivals are compared with the average door-to-provider wait so
--             the demand/capacity mismatch shows up hour by hour.
-- Grain     arrival hour (0-23) x triage category (1-5)
-- =============================================================================
WITH visits AS (
    SELECT CAST(strftime('%H', arrival_ts) AS INTEGER)                                       AS arrival_hour,
           triage_category,
           er_disposition,
           (strftime('%s', provider_seen_ts) - strftime('%s', arrival_ts)) / 60.0                  AS door_to_provider_min,
           (strftime('%s', departure_ts) - strftime('%s', arrival_ts)) / 60.0                      AS total_ed_min
    FROM er_visits
    WHERE arrival_ts >= '2025-01-01'
      AND arrival_ts <  '2026-01-01'
),
cells AS (
    SELECT arrival_hour,
           triage_category,
           COUNT(*)                                                             AS attendances,
           AVG(door_to_provider_min)                                            AS avg_door_to_provider,
           1.0 * SUM(CASE WHEN door_to_provider_min > 60 THEN 1 ELSE 0 END)
               / COUNT(door_to_provider_min)                                    AS share_wait_over_60,
           1.0 * SUM(CASE WHEN total_ed_min <= 240 THEN 1 ELSE 0 END) / COUNT(*)  AS within_4h_rate,
           1.0 * SUM(CASE WHEN er_disposition = 'Left Without Being Seen' THEN 1 ELSE 0 END)
               / COUNT(*)                                                       AS lwbs_rate,
           1.0 * SUM(CASE WHEN er_disposition = 'Admitted' THEN 1 ELSE 0 END) / COUNT(*) AS admission_rate
    FROM visits
    GROUP BY arrival_hour, triage_category
)
SELECT arrival_hour,
       triage_category,
       attendances,
       ROUND(1.0 * attendances / 365, 2)                                        AS avg_daily_arrivals,
       ROUND(1.0 * attendances / SUM(attendances) OVER (PARTITION BY triage_category), 4)
                                                                                AS share_of_triage_daily_demand,
       ROUND(avg_door_to_provider, 1)                                           AS avg_door_to_provider_min,
       ROUND(share_wait_over_60, 4)                                             AS share_wait_over_60_min,
       ROUND(within_4h_rate, 4)                                                 AS within_4h_rate,
       ROUND(lwbs_rate, 4)                                                      AS lwbs_rate,
       ROUND(admission_rate, 4)                                                 AS admission_rate,
       RANK() OVER (PARTITION BY triage_category ORDER BY avg_door_to_provider DESC) AS worst_hour_rank
FROM cells
ORDER BY triage_category, arrival_hour;
