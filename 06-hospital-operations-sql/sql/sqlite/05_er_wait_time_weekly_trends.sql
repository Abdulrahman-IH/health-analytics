-- Dialect: SQLite 3.25+  (generated from sql/templates/05_er_wait_time_weekly_trends.sql by scripts/render_sql.py)
-- =============================================================================
-- 05  Emergency department wait-time trends — weekly, by hospital
-- -----------------------------------------------------------------------------
-- Question  Are ED waits getting better or worse, and where?
-- Method    * Door-to-provider = arrival -> first clinician assessment.
--           * Total time in ED = arrival -> departure; the 4-hour standard is
--             the share of attendances completed within 240 minutes.
--           * P90 door-to-provider via ROW_NUMBER()/COUNT() within each
--             hospital-week (portable nearest-rank percentile).
--           * AVG() OVER a 4-week window smooths the trend; LAG() gives the
--             week-on-week change; FIRST_VALUE() anchors each hospital to its
--             first full week so the year-to-date change is explicit.
-- Grain     hospital x ISO week (full weeks 6 Jan - 28 Dec 2025)
-- =============================================================================
WITH visits AS (
    SELECT hospital_id,
           date(arrival_ts, '-6 days', 'weekday 1')                                        AS week_start,
           er_disposition,
           (strftime('%s', provider_seen_ts) - strftime('%s', arrival_ts)) / 60.0                   AS door_to_provider_min,
           (strftime('%s', departure_ts) - strftime('%s', arrival_ts)) / 60.0                       AS total_ed_min
    FROM er_visits
    WHERE arrival_ts >= '2025-01-06'
      AND arrival_ts <  '2025-12-29'
),
ranked AS (
    SELECT v.*,
           ROW_NUMBER() OVER (PARTITION BY hospital_id, week_start
                              ORDER BY CASE WHEN door_to_provider_min IS NULL THEN 1 ELSE 0 END,  -- NULLs last in both engines
                                       door_to_provider_min)                   AS rn,
           COUNT(door_to_provider_min) OVER (PARTITION BY hospital_id, week_start)               AS n_seen
    FROM visits v
),
weekly AS (
    SELECT hospital_id,
           week_start,
           COUNT(*)                                                            AS attendances,
           AVG(door_to_provider_min)                                           AS avg_door_to_provider,
           MIN(CASE WHEN door_to_provider_min IS NOT NULL
                     AND 1.0 * rn / n_seen >= 0.9 THEN door_to_provider_min END) AS p90_door_to_provider,
           1.0 * SUM(CASE WHEN total_ed_min <= 240 THEN 1 ELSE 0 END) / COUNT(*) AS within_4h_rate,
           1.0 * SUM(CASE WHEN er_disposition = 'Left Without Being Seen' THEN 1 ELSE 0 END) / COUNT(*) AS lwbs_rate
    FROM ranked
    GROUP BY hospital_id, week_start
),
trended AS (
    SELECT w.*,
           AVG(avg_door_to_provider) OVER (
               PARTITION BY hospital_id ORDER BY week_start
               ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)                       AS avg_wait_4wk_ma,
           AVG(within_4h_rate) OVER (
               PARTITION BY hospital_id ORDER BY week_start
               ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)                       AS within_4h_4wk_ma,
           avg_door_to_provider
             - LAG(avg_door_to_provider) OVER (PARTITION BY hospital_id ORDER BY week_start) AS wow_change_min,
           FIRST_VALUE(avg_door_to_provider) OVER (
               PARTITION BY hospital_id ORDER BY week_start
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)               AS first_week_wait
    FROM weekly w
)
SELECT h.hospital_code,
       t.week_start,
       t.attendances,
       ROUND(t.avg_door_to_provider, 1)                AS avg_door_to_provider_min,
       ROUND(t.p90_door_to_provider, 1)                AS p90_door_to_provider_min,
       ROUND(t.avg_wait_4wk_ma, 1)                     AS avg_wait_4wk_moving_avg,
       ROUND(t.wow_change_min, 1)                      AS week_on_week_change_min,
       ROUND(t.avg_door_to_provider - t.first_week_wait, 1) AS change_vs_first_week_min,
       ROUND(t.within_4h_rate, 4)                      AS within_4h_rate,
       ROUND(t.within_4h_4wk_ma, 4)                    AS within_4h_4wk_moving_avg,
       ROUND(t.lwbs_rate, 4)                           AS lwbs_rate
FROM trended t
JOIN hospitals h ON h.hospital_id = t.hospital_id
ORDER BY h.hospital_code, t.week_start;
