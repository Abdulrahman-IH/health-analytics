-- Dialect: PostgreSQL 13+  (generated from sql/templates/03_length_of_stay_avg_p90.sql by scripts/render_sql.py)
-- =============================================================================
-- 03  Length of stay — average, median and P90 by hospital and department
-- -----------------------------------------------------------------------------
-- Question  Where do stays run long against the network benchmark for the
--           same specialty, and how many bed-days does that cost?
-- Method    * LOS measured on 2025 discharges, in fractional days.
--           * Percentiles are computed portably with window functions
--             (nearest-rank: the first stay whose ROW_NUMBER()/COUNT() >= p),
--             so the same SQL runs on SQLite, which has no PERCENTILE_CONT.
--           * The benchmark is the network-wide figure for the department;
--             excess bed-days = (hospital ALOS - benchmark ALOS) x discharges.
--             A positive number is capacity that could be released by matching
--             peer performance (before case-mix adjustment).
-- Grain     hospital x inpatient department, plus a network row per department
-- =============================================================================
WITH stays AS (
    SELECT a.hospital_id,
           a.department_id,
           (EXTRACT(EPOCH FROM (a.discharge_ts - a.admit_ts)) / 86400.0) AS los_days
    FROM admissions a
    WHERE a.discharge_ts >= '2025-01-01'
      AND a.discharge_ts <  '2026-01-01'
),
ranked AS (
    SELECT hospital_id,
           department_id,
           los_days,
           ROW_NUMBER() OVER (PARTITION BY hospital_id, department_id ORDER BY los_days) AS rn_hosp,
           COUNT(*)     OVER (PARTITION BY hospital_id, department_id)                   AS n_hosp,
           ROW_NUMBER() OVER (PARTITION BY department_id ORDER BY los_days)              AS rn_net,
           COUNT(*)     OVER (PARTITION BY department_id)                                AS n_net
    FROM stays
),
hospital_los AS (
    SELECT hospital_id,
           department_id,
           COUNT(*)                                                         AS discharges,
           AVG(los_days)                                                    AS alos,
           MIN(CASE WHEN 1.0 * rn_hosp / n_hosp >= 0.5 THEN los_days END)   AS median_los,
           MIN(CASE WHEN 1.0 * rn_hosp / n_hosp >= 0.9 THEN los_days END)   AS p90_los
    FROM ranked
    GROUP BY hospital_id, department_id
),
network_los AS (
    SELECT department_id,
           COUNT(*)                                                         AS discharges,
           AVG(los_days)                                                    AS alos,
           MIN(CASE WHEN 1.0 * rn_net / n_net >= 0.5 THEN los_days END)     AS median_los,
           MIN(CASE WHEN 1.0 * rn_net / n_net >= 0.9 THEN los_days END)     AS p90_los
    FROM ranked
    GROUP BY department_id
),
combined AS (
    SELECT h.hospital_code                                AS hospital,
           d.department_code,
           hl.discharges,
           hl.alos, hl.median_los, hl.p90_los,
           nl.alos                                        AS network_alos,
           nl.p90_los                                     AS network_p90_los,
           (hl.alos - nl.alos) * hl.discharges            AS excess_bed_days,
           RANK() OVER (PARTITION BY hl.department_id ORDER BY hl.alos DESC) AS alos_rank_in_dept
    FROM hospital_los hl
    JOIN network_los nl ON nl.department_id = hl.department_id
    JOIN hospitals   h  ON h.hospital_id    = hl.hospital_id
    JOIN departments d  ON d.department_id  = hl.department_id
    UNION ALL
    SELECT 'NETWORK', d.department_code, nl.discharges,
           nl.alos, nl.median_los, nl.p90_los, nl.alos, nl.p90_los, 0, NULL
    FROM network_los nl
    JOIN departments d ON d.department_id = nl.department_id
)
SELECT hospital,
       department_code,
       discharges,
       ROUND(alos, 2)                  AS alos_days,
       ROUND(median_los, 2)            AS median_los_days,
       ROUND(p90_los, 2)               AS p90_los_days,
       ROUND(p90_los / alos, 2)        AS p90_to_mean_ratio,     -- tail heaviness
       ROUND(network_alos, 2)          AS network_alos_days,
       ROUND(network_p90_los, 2)       AS network_p90_los_days,
       ROUND(excess_bed_days, 0)       AS excess_bed_days,
       alos_rank_in_dept
FROM combined
ORDER BY department_code, CASE WHEN hospital = 'NETWORK' THEN 0 ELSE 1 END, alos DESC, hospital;
