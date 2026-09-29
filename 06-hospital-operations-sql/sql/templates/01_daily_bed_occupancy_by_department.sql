-- =============================================================================
-- 01  Daily bed occupancy by hospital and department (midnight census)
-- -----------------------------------------------------------------------------
-- Question  How full is every inpatient ward, every day of 2025, measured
--           against the beds that were actually staffed on that day?
-- Method    * Midnight census = patients admitted on/before day D and not yet
--             discharged by the end of day D.
--           * Rather than joining every day to every stay (days x stays), each
--             stay contributes +1 on its admission date and -1 on its discharge
--             date; a running SUM() OVER (ORDER BY date) turns those movements
--             into the census. Stays already open on 1 Jan enter as an opening
--             balance.
--           * Staffed beds come from the slowly-changing bed_capacity table,
--             so winter escalation beds and ward closures are respected.
--           * A 7-day rolling average smooths weekday/weekend noise.
-- Grain     hospital x inpatient department x day (2025)
-- =============================================================================
WITH RECURSIVE calendar (census_date) AS (
    SELECT @LIT(2025-01-01)
    UNION ALL
    SELECT @ADD_DAYS(census_date, 1) FROM calendar WHERE census_date < @LIT(2025-12-31)
),
stays AS (
    SELECT hospital_id,
           department_id,
           @DATE(admit_ts)     AS in_date,
           @DATE(discharge_ts) AS out_date          -- NULL = still in a bed at extract
    FROM admissions
),
movements AS (
    -- opening balance: patients already in a bed when the year starts
    SELECT hospital_id, department_id, @LIT(2025-01-01) AS move_date, 1 AS delta
    FROM stays
    WHERE in_date < @LIT(2025-01-01)
      AND (out_date IS NULL OR out_date >= @LIT(2025-01-01))
    UNION ALL
    SELECT hospital_id, department_id, in_date, 1
    FROM stays
    WHERE in_date BETWEEN @LIT(2025-01-01) AND @LIT(2025-12-31)
    UNION ALL
    SELECT hospital_id, department_id, out_date, -1
    FROM stays
    WHERE out_date BETWEEN @LIT(2025-01-01) AND @LIT(2025-12-31)
),
daily_net AS (
    SELECT hospital_id, department_id, move_date, SUM(delta) AS net_change
    FROM movements
    GROUP BY hospital_id, department_id, move_date
),
capacity_by_day AS (
    -- one row per ward per day with the staffed beds valid on that date
    SELECT c.census_date, b.hospital_id, b.department_id, b.staffed_beds
    FROM calendar c
    JOIN bed_capacity b
      ON c.census_date >= b.effective_from
     AND (b.effective_to IS NULL OR c.census_date <= b.effective_to)
    JOIN departments d
      ON d.department_id = b.department_id
    WHERE d.is_inpatient = TRUE
),
census AS (
    SELECT cb.hospital_id,
           cb.department_id,
           cb.census_date,
           cb.staffed_beds,
           SUM(COALESCE(n.net_change, 0)) OVER (
               PARTITION BY cb.hospital_id, cb.department_id
               ORDER BY cb.census_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS occupied_beds
    FROM capacity_by_day cb
    LEFT JOIN daily_net n
      ON n.hospital_id   = cb.hospital_id
     AND n.department_id = cb.department_id
     AND n.move_date     = cb.census_date
),
occupancy AS (
    SELECT *,
           1.0 * occupied_beds / staffed_beds AS occupancy_rate
    FROM census
)
SELECT h.hospital_code,
       d.department_code,
       o.census_date,
       o.staffed_beds,
       o.occupied_beds,
       ROUND(o.occupancy_rate, 4) AS occupancy_rate,
       ROUND(AVG(o.occupancy_rate) OVER (
           PARTITION BY o.hospital_id, o.department_id
           ORDER BY o.census_date
           ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
       ), 4) AS occupancy_7d_avg,
       CASE WHEN o.occupancy_rate >= 0.95 THEN 'Critical (>=95%)'
            WHEN o.occupancy_rate >= 0.85 THEN 'High (85-95%)'
            ELSE 'Normal (<85%)'
       END AS occupancy_band
FROM occupancy o
JOIN hospitals   h ON h.hospital_id   = o.hospital_id
JOIN departments d ON d.department_id = o.department_id
ORDER BY h.hospital_code, d.department_code, o.census_date;
