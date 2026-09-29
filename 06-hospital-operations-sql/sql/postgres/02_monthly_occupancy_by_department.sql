-- Dialect: PostgreSQL 13+  (generated from sql/templates/02_monthly_occupancy_by_department.sql by scripts/render_sql.py)
-- =============================================================================
-- 02  Monthly bed occupancy by department — network view with pressure days
-- -----------------------------------------------------------------------------
-- Question  Which specialties run hottest, in which months, and how often do
--           individual wards tip over the 95% "no slack" line?
-- Method    Reuses the movement-based midnight census from query 01, then:
--           * occupancy = SUM(occupied bed-days) / SUM(staffed bed-days)
--             (bed-day weighting, so a 60-bed ward outweighs a 6-bed one)
--           * share of ward-days at >=85% and >=95%
--           * RANK() of departments within each month
--           * LAG() for the month-on-month change in occupancy (percentage points)
-- Grain     inpatient department x month (2025)
-- =============================================================================
WITH RECURSIVE calendar (census_date) AS (
    SELECT DATE '2025-01-01'
    UNION ALL
    SELECT (census_date + 1) FROM calendar WHERE census_date < DATE '2025-12-31'
),
stays AS (
    SELECT hospital_id, department_id,
           CAST(admit_ts AS DATE) AS in_date, CAST(discharge_ts AS DATE) AS out_date
    FROM admissions
),
movements AS (
    SELECT hospital_id, department_id, DATE '2025-01-01' AS move_date, 1 AS delta
    FROM stays
    WHERE in_date < DATE '2025-01-01' AND (out_date IS NULL OR out_date >= DATE '2025-01-01')
    UNION ALL
    SELECT hospital_id, department_id, in_date, 1 FROM stays
    WHERE in_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31'
    UNION ALL
    SELECT hospital_id, department_id, out_date, -1 FROM stays
    WHERE out_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31'
),
daily_net AS (
    SELECT hospital_id, department_id, move_date, SUM(delta) AS net_change
    FROM movements
    GROUP BY hospital_id, department_id, move_date
),
census AS (
    SELECT b.hospital_id, b.department_id, c.census_date, b.staffed_beds,
           SUM(COALESCE(n.net_change, 0)) OVER (
               PARTITION BY b.hospital_id, b.department_id
               ORDER BY c.census_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS occupied_beds
    FROM calendar c
    JOIN bed_capacity b
      ON c.census_date >= b.effective_from
     AND (b.effective_to IS NULL OR c.census_date <= b.effective_to)
    JOIN departments d ON d.department_id = b.department_id AND d.is_inpatient = TRUE
    LEFT JOIN daily_net n
      ON n.hospital_id = b.hospital_id AND n.department_id = b.department_id
     AND n.move_date = c.census_date
),
monthly AS (
    SELECT department_id,
           to_char(census_date, 'YYYY-MM')                                              AS month,
           SUM(staffed_beds)                                                AS staffed_bed_days,
           SUM(occupied_beds)                                               AS occupied_bed_days,
           1.0 * SUM(occupied_beds) / SUM(staffed_beds)                     AS occupancy_rate,
           MAX(1.0 * occupied_beds / staffed_beds)                          AS peak_ward_occupancy,
           1.0 * SUM(CASE WHEN occupied_beds >= 0.85 * staffed_beds THEN 1 ELSE 0 END) / COUNT(*) AS share_days_ge_85,
           1.0 * SUM(CASE WHEN occupied_beds >= 0.95 * staffed_beds THEN 1 ELSE 0 END) / COUNT(*) AS share_days_ge_95
    FROM census
    GROUP BY department_id, to_char(census_date, 'YYYY-MM')
)
SELECT m.month,
       d.department_code,
       d.department_name,
       m.staffed_bed_days,
       m.occupied_bed_days,
       ROUND(m.occupancy_rate, 4)                                   AS occupancy_rate,
       ROUND(m.occupancy_rate - d.target_occupancy, 4)              AS gap_to_target,
       ROUND(m.peak_ward_occupancy, 4)                              AS peak_ward_occupancy,
       ROUND(m.share_days_ge_85, 4)                                 AS share_ward_days_ge_85,
       ROUND(m.share_days_ge_95, 4)                                 AS share_ward_days_ge_95,
       RANK() OVER (PARTITION BY m.month ORDER BY m.occupancy_rate DESC) AS rank_in_month,
       ROUND(100 * (m.occupancy_rate
             - LAG(m.occupancy_rate) OVER (PARTITION BY m.department_id ORDER BY m.month)), 2)
                                                                    AS mom_change_pp
FROM monthly m
JOIN departments d ON d.department_id = m.department_id
ORDER BY m.month, rank_in_month;
