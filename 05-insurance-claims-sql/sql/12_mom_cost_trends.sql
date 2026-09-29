-- 12. Month-over-month cost trends (incurred basis, by service month)
-- Techniques: CTEs, LAG() for MoM, LAG(12) for YoY, rolling 3-month AVG window, PMPM using
--             monthly member-months from policies
-- Business use: medical cost trend monitoring, PMPM tracking, reserve/IBNR sanity checks.
WITH RECURSIVE months(m) AS (
    SELECT DATE('2024-01-01')
    UNION ALL
    SELECT DATE(m, '+1 month') FROM months WHERE m < DATE('2025-10-01')
),
member_months AS (
    SELECT strftime('%Y-%m', mo.m) AS month, COUNT(DISTINCT p.member_id) AS members
    FROM months mo
    JOIN policies p
      ON p.coverage_start <= DATE(mo.m, '+1 month', '-1 day')
     AND p.coverage_end   >= mo.m
    GROUP BY 1
),
cost AS (
    SELECT
        strftime('%Y-%m', service_date)                                        AS month,
        COUNT(*)                                                               AS claims,
        SUM(billed_amount)                                                     AS billed,
        SUM(CASE WHEN claim_status = 'Approved' THEN approved_amount END)      AS approved
    FROM claims
    WHERE service_date < '2025-11-01'             -- allow ~60 days of claims run-out (Nov-Dec 2025 still maturing)
    GROUP BY 1
)
SELECT
    c.month,
    c.claims,
    ROUND(c.billed, 0)                                                              AS billed,
    ROUND(c.approved, 0)                                                            AS approved,
    mm.members                                                                      AS member_months,
    ROUND(c.approved / mm.members, 2)                                               AS approved_pmpm,
    ROUND(100.0 * (c.approved / LAG(c.approved) OVER (ORDER BY c.month) - 1), 1)    AS mom_change_pct,
    ROUND(100.0 * (c.approved / mm.members)
               / (LAG(c.approved, 12) OVER (ORDER BY c.month) / LAG(mm.members, 12) OVER (ORDER BY c.month)) - 100, 1)
                                                                                    AS yoy_pmpm_change_pct,
    ROUND(AVG(c.approved) OVER (ORDER BY c.month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 0) AS rolling_3m_approved
FROM cost c
JOIN member_months mm ON mm.month = c.month
ORDER BY c.month;
