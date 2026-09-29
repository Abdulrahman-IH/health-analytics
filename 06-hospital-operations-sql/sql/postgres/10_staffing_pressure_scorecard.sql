-- Dialect: PostgreSQL 13+  (generated from sql/templates/10_staffing_pressure_scorecard.sql by scripts/render_sql.py)
-- =============================================================================
-- 10  Nurse staffing vs demand, rolled into a hospital operations scorecard
-- -----------------------------------------------------------------------------
-- Question  Are wards staffed for the patients actually in the beds, and how
--           does each hospital compare across flow, ED and quality measures?
-- Method    * Night-shift patients-per-nurse = midnight census / nurses on duty
--             (the census *is* the night-shift caseload). A shift breaches when
--             it exceeds the department's safe-staffing ratio.
--           * Absence rate = rostered nurses not covered by the substantive
--             team; agency share = agency nurses / nurses on duty.
--           * Scorecard KPIs (occupancy, ALOS, ED 4-hour rate, 30-day
--             readmission, staffing breaches) are each RANK()ed across the 15
--             hospitals; the mean rank gives an overall position and NTILE(3)
--             splits the network into performance tiers.
-- Grain     hospital (2025)
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
night_shifts AS (
    SELECT c.hospital_id,
           c.occupied_beds,
           c.staffed_beds,
           s.rostered_nurses,
           s.nurses_on_duty,
           s.agency_nurses,
           1.0 * c.occupied_beds / NULLIF(s.nurses_on_duty, 0) AS patients_per_nurse,   -- NULL if nobody on shift
           d.target_patients_per_nurse
    FROM census c
    JOIN staffing_shifts s
      ON s.hospital_id = c.hospital_id AND s.department_id = c.department_id
     AND s.shift_date = c.census_date AND s.shift_type = 'Night'
    JOIN departments d ON d.department_id = c.department_id
),
staffing AS (
    SELECT hospital_id,
           1.0 * SUM(occupied_beds) / SUM(staffed_beds)                          AS occupancy_rate,
           1.0 * SUM(occupied_beds) / SUM(nurses_on_duty)                        AS avg_patients_per_nurse,
           1.0 * SUM(CASE WHEN patients_per_nurse > target_patients_per_nurse
                          OR (nurses_on_duty = 0 AND occupied_beds > 0) THEN 1 ELSE 0 END)
               / COUNT(*)                                                        AS share_shifts_breaching_ratio,
           1.0 - 1.0 * SUM(nurses_on_duty - agency_nurses) / SUM(rostered_nurses) AS absence_rate,
           1.0 * SUM(agency_nurses) / SUM(nurses_on_duty)                        AS agency_share
    FROM night_shifts
    GROUP BY hospital_id
),
los AS (
    SELECT hospital_id, AVG((EXTRACT(EPOCH FROM (discharge_ts - admit_ts)) / 86400.0)) AS alos_days
    FROM admissions
    WHERE discharge_ts >= '2025-01-01' AND discharge_ts < '2026-01-01'
    GROUP BY hospital_id
),
ed AS (
    SELECT hospital_id,
           1.0 * SUM(CASE WHEN EXTRACT(EPOCH FROM (departure_ts - arrival_ts)) / 60.0 <= 240 THEN 1 ELSE 0 END) / COUNT(*) AS ed_within_4h
    FROM er_visits
    WHERE arrival_ts >= '2025-01-01' AND arrival_ts < '2026-01-01'
    GROUP BY hospital_id
),
readmit AS (
    SELECT hospital_id,
           1.0 * SUM(CASE WHEN next_type = 'Emergency'
                           AND (EXTRACT(EPOCH FROM (next_admit - discharge_ts)) / 86400.0) <= 30 THEN 1 ELSE 0 END) / COUNT(*) AS readmission_rate_30d
    FROM (
        SELECT hospital_id, discharge_ts, discharge_disposition,
               LEAD(admit_ts)       OVER (PARTITION BY patient_id ORDER BY admit_ts) AS next_admit,
               LEAD(admission_type) OVER (PARTITION BY patient_id ORDER BY admit_ts) AS next_type
        FROM admissions
    ) x
    WHERE discharge_ts >= '2025-01-01' AND discharge_ts < '2025-12-02'
      AND discharge_disposition NOT IN ('Died', 'Transferred to another hospital')
    GROUP BY hospital_id
),
kpis AS (
    SELECT s.*, l.alos_days, e.ed_within_4h, r.readmission_rate_30d,
           -- rank 1 = best on each measure
           RANK() OVER (ORDER BY s.occupancy_rate)                 AS rk_occupancy,
           RANK() OVER (ORDER BY l.alos_days)                      AS rk_alos,
           RANK() OVER (ORDER BY e.ed_within_4h DESC)              AS rk_ed,
           RANK() OVER (ORDER BY r.readmission_rate_30d)           AS rk_readmit,
           RANK() OVER (ORDER BY s.share_shifts_breaching_ratio)   AS rk_staffing
    FROM staffing s
    JOIN los     l ON l.hospital_id = s.hospital_id
    JOIN ed      e ON e.hospital_id = s.hospital_id
    JOIN readmit r ON r.hospital_id = s.hospital_id
),
scored AS (
    SELECT k.*,
           (rk_occupancy + rk_alos + rk_ed + rk_readmit + rk_staffing) / 5.0 AS mean_rank
    FROM kpis k
)
SELECT RANK() OVER (ORDER BY sc.mean_rank)                   AS overall_rank,
       CASE NTILE(3) OVER (ORDER BY sc.mean_rank)
            WHEN 1 THEN 'Top third' WHEN 2 THEN 'Middle third' ELSE 'Bottom third' END AS tier,
       h.hospital_code,
       h.hospital_name,
       h.hospital_type,
       ROUND(sc.occupancy_rate, 4)                AS occupancy_rate,
       ROUND(sc.alos_days, 2)                     AS alos_days,
       ROUND(sc.ed_within_4h, 4)                  AS ed_within_4h,
       ROUND(sc.readmission_rate_30d, 4)          AS readmission_rate_30d,
       ROUND(sc.avg_patients_per_nurse, 2)        AS night_patients_per_nurse,
       ROUND(sc.share_shifts_breaching_ratio, 4)  AS share_night_shifts_breaching_ratio,
       ROUND(sc.absence_rate, 4)                  AS nurse_absence_rate,
       ROUND(sc.agency_share, 4)                  AS agency_share,
       ROUND(sc.mean_rank, 2)                     AS mean_rank
FROM scored sc
JOIN hospitals h ON h.hospital_id = sc.hospital_id
ORDER BY overall_rank, h.hospital_code;
