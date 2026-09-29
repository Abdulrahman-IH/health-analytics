-- 06. Monthly turnaround trend, SLA compliance, and aged pending inventory
-- Techniques: CTEs, strftime month buckets, LAG() for MoM change, UNION of trend + backlog snapshot
-- Business use: track the auto-adjudication rollout and flag aging pended claims.
WITH monthly AS (
    SELECT
        strftime('%Y-%m', submission_date)                                         AS month,
        COUNT(*)                                                                    AS decided_claims,
        AVG(julianday(adjudication_date) - julianday(submission_date))             AS avg_days,
        AVG(julianday(adjudication_date) - julianday(submission_date) <= 15)       AS within_15d,
        AVG(julianday(adjudication_date) - julianday(submission_date) <= 30)       AS within_30d
    FROM claims
    WHERE claim_status IN ('Approved', 'Rejected')
      AND submission_date < '2025-12-01'          -- exclude the incomplete final month
    GROUP BY 1
)
SELECT
    month,
    decided_claims,
    ROUND(avg_days, 2)                                        AS avg_turnaround_days,
    ROUND(avg_days - LAG(avg_days) OVER (ORDER BY month), 2)  AS mom_change_days,
    ROUND(AVG(avg_days) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS rolling_3m_days,
    ROUND(100 * within_15d, 1)                                AS pct_within_15d,
    ROUND(100 * within_30d, 1)                                AS pct_within_30d
FROM monthly
ORDER BY month;

-- Companion snapshot: pending inventory by age bucket as of 2025-12-31
-- SELECT
--     CASE WHEN age <= 15 THEN '0-15 days' WHEN age <= 30 THEN '16-30 days'
--          WHEN age <= 60 THEN '31-60 days' ELSE '60+ days' END AS age_bucket,
--     COUNT(*) AS pending_claims, ROUND(SUM(billed_amount)) AS pending_billed
-- FROM (SELECT billed_amount, julianday('2025-12-31') - julianday(submission_date) AS age
--       FROM claims WHERE claim_status = 'Pending')
-- GROUP BY 1 ORDER BY MIN(age);
