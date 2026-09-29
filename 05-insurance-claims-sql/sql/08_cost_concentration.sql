-- 08. Cost concentration (Pareto): share of spend by member spend decile
-- Techniques: CTEs, NTILE(10), running SUM() OVER for cumulative share
-- Business use: quantify how concentrated risk is ("top 10% of members drive X% of cost").
WITH member_spend AS (
    SELECT member_id, SUM(approved_amount) AS spend
    FROM claims
    WHERE claim_status = 'Approved'
    GROUP BY member_id
),
deciles AS (
    SELECT member_id, spend, NTILE(10) OVER (ORDER BY spend DESC) AS decile
    FROM member_spend
),
agg AS (
    SELECT decile, COUNT(*) AS members, SUM(spend) AS spend, MIN(spend) AS min_spend, MAX(spend) AS max_spend
    FROM deciles
    GROUP BY decile
)
SELECT
    decile,
    members,
    ROUND(min_spend, 0)                                                          AS min_member_spend,
    ROUND(max_spend, 0)                                                          AS max_member_spend,
    ROUND(spend / members, 0)                                                    AS avg_member_spend,
    ROUND(100.0 * spend / SUM(spend) OVER (), 1)                                 AS pct_of_spend,
    ROUND(100.0 * SUM(spend) OVER (ORDER BY decile) / SUM(spend) OVER (), 1)     AS cumulative_pct_of_spend
FROM agg
ORDER BY decile;
