-- Dialect: SQLite 3.25+  (generated from sql/templates/09_capacity_bottlenecks.sql by scripts/render_sql.py)
-- =============================================================================
-- 09  Capacity bottlenecks — sustained critical occupancy and ED exit block
-- -----------------------------------------------------------------------------
-- Question  Which wards are *persistently* full (not just busy on a bad day),
--           and is that congestion backing up into the emergency department?
-- Method    * Midnight census as in query 01.
--           * Gaps-and-islands: consecutive days at >= 95% occupancy share the
--             same (day number - ROW_NUMBER()) key, so GROUP BY that key turns
--             runs of critical days into episodes with a start, end and length.
--           * ED exit block = boarding time from decision-to-admit to leaving
--             the ED, for patients admitted to that same department; share of
--             boarders waiting > 4h and > 12h ("trolley waits").
--           * Bottleneck score = critical-day share x (1 + share boarding > 4h);
--             DENSE_RANK() orders the network's worst pinch points.
-- Grain     hospital x inpatient department (2025)
-- =============================================================================
WITH RECURSIVE calendar (census_date) AS (
    SELECT '2025-01-01'
    UNION ALL
    SELECT date(census_date, '+1 day') FROM calendar WHERE census_date < '2025-12-31'
),
stays AS (
    SELECT hospital_id, department_id,
           date(admit_ts) AS in_date, date(discharge_ts) AS out_date
    FROM admissions
),
movements AS (
    SELECT hospital_id, department_id, '2025-01-01' AS move_date, 1 AS delta
    FROM stays
    WHERE in_date < '2025-01-01' AND (out_date IS NULL OR out_date >= '2025-01-01')
    UNION ALL
    SELECT hospital_id, department_id, in_date, 1 FROM stays
    WHERE in_date BETWEEN '2025-01-01' AND '2025-12-31'
    UNION ALL
    SELECT hospital_id, department_id, out_date, -1 FROM stays
    WHERE out_date BETWEEN '2025-01-01' AND '2025-12-31'
),
daily_net AS (
    SELECT hospital_id, department_id, move_date, SUM(delta) AS net_change
    FROM movements GROUP BY hospital_id, department_id, move_date
),
census AS (
    SELECT b.hospital_id, b.department_id, c.census_date, b.staffed_beds,
           SUM(COALESCE(n.net_change, 0)) OVER (
               PARTITION BY b.hospital_id, b.department_id ORDER BY c.census_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS occupied_beds
    FROM calendar c
    JOIN bed_capacity b
      ON c.census_date >= b.effective_from
     AND (b.effective_to IS NULL OR c.census_date <= b.effective_to)
    JOIN departments d ON d.department_id = b.department_id AND d.is_inpatient = TRUE
    LEFT JOIN daily_net n
      ON n.hospital_id = b.hospital_id AND n.department_id = b.department_id
     AND n.move_date = c.census_date
),
critical_days AS (
    SELECT hospital_id, department_id, census_date,
           CAST(julianday(census_date) AS INTEGER)
             - ROW_NUMBER() OVER (PARTITION BY hospital_id, department_id ORDER BY census_date) AS island_key
    FROM census
    WHERE occupied_beds >= 0.95 * staffed_beds
),
episodes AS (
    SELECT hospital_id, department_id, island_key,
           MIN(census_date) AS episode_start,
           MAX(census_date) AS episode_end,
           COUNT(*)         AS episode_days
    FROM critical_days
    GROUP BY hospital_id, department_id, island_key
),
longest AS (
    SELECT hospital_id, department_id, episode_start, episode_end, episode_days,
           ROW_NUMBER() OVER (PARTITION BY hospital_id, department_id
                              ORDER BY episode_days DESC, episode_start) AS rn
    FROM episodes
),
ward_summary AS (
    SELECT c.hospital_id, c.department_id,
           COUNT(*)                                                             AS days,
           1.0 * SUM(c.occupied_beds) / SUM(c.staffed_beds)                     AS occupancy_rate,
           SUM(CASE WHEN c.occupied_beds >= 0.95 * c.staffed_beds THEN 1 ELSE 0 END) AS critical_days,
           SUM(CASE WHEN c.occupied_beds >  c.staffed_beds THEN 1 ELSE 0 END)   AS over_capacity_days
    FROM census c
    GROUP BY c.hospital_id, c.department_id
),
episode_counts AS (
    SELECT hospital_id, department_id,
           COUNT(*)                                                  AS critical_episodes,
           SUM(CASE WHEN episode_days >= 7 THEN 1 ELSE 0 END)        AS episodes_7plus_days
    FROM episodes
    GROUP BY hospital_id, department_id
),
boarding AS (
    SELECT a.hospital_id, a.department_id,
           COUNT(*)                                                             AS ed_admissions,
           AVG((strftime('%s', e.departure_ts) - strftime('%s', e.decision_to_admit_ts)) / 60.0)                AS avg_boarding_min,
           1.0 * SUM(CASE WHEN (strftime('%s', e.departure_ts) - strftime('%s', e.decision_to_admit_ts)) / 60.0 > 240 THEN 1 ELSE 0 END)
               / COUNT(*)                                                       AS share_boarding_over_4h,
           SUM(CASE WHEN (strftime('%s', e.departure_ts) - strftime('%s', e.decision_to_admit_ts)) / 60.0 > 720 THEN 1 ELSE 0 END)
                                                                                AS trolley_waits_over_12h
    FROM er_visits e
    JOIN admissions a ON a.admission_id = e.admission_id
    WHERE e.er_disposition = 'Admitted'
      AND e.arrival_ts >= '2025-01-01' AND e.arrival_ts < '2026-01-01'
    GROUP BY a.hospital_id, a.department_id
),
scored AS (
    SELECT w.*,
           COALESCE(ec.critical_episodes, 0)   AS critical_episodes,
           COALESCE(ec.episodes_7plus_days, 0) AS episodes_7plus_days,
           l.episode_start AS longest_run_start,
           l.episode_end   AS longest_run_end,
           COALESCE(l.episode_days, 0)         AS longest_run_days,
           COALESCE(b.ed_admissions, 0)        AS ed_admissions,
           b.avg_boarding_min,
           COALESCE(b.share_boarding_over_4h, 0) AS share_boarding_over_4h,
           COALESCE(b.trolley_waits_over_12h, 0) AS trolley_waits_over_12h,
           (1.0 * w.critical_days / w.days) * (1 + COALESCE(b.share_boarding_over_4h, 0)) AS bottleneck_score
    FROM ward_summary w
    LEFT JOIN episode_counts ec ON ec.hospital_id = w.hospital_id AND ec.department_id = w.department_id
    LEFT JOIN longest l ON l.hospital_id = w.hospital_id AND l.department_id = w.department_id AND l.rn = 1
    LEFT JOIN boarding b ON b.hospital_id = w.hospital_id AND b.department_id = w.department_id
)
SELECT DENSE_RANK() OVER (ORDER BY s.bottleneck_score DESC) AS bottleneck_rank,
       h.hospital_code,
       d.department_code,
       ROUND(s.occupancy_rate, 4)            AS occupancy_rate,
       s.critical_days,
       s.over_capacity_days,
       s.critical_episodes,
       s.episodes_7plus_days,
       s.longest_run_days,
       s.longest_run_start,
       s.longest_run_end,
       s.ed_admissions,
       ROUND(s.avg_boarding_min, 1)          AS avg_boarding_min,
       ROUND(s.share_boarding_over_4h, 4)    AS share_boarding_over_4h,
       s.trolley_waits_over_12h,
       ROUND(s.bottleneck_score, 4)          AS bottleneck_score
FROM scored s
JOIN hospitals   h ON h.hospital_id   = s.hospital_id
JOIN departments d ON d.department_id = s.department_id
ORDER BY bottleneck_rank, h.hospital_code, d.department_code;
