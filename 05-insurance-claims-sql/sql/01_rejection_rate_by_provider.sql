-- 01. Rejection rate by provider, benchmarked against specialty peers
-- Techniques: CTE, JOIN, window AVG/RANK partitioned by specialty
-- Business use: provider relations / provider education targeting. Pending claims excluded.
WITH provider_stats AS (
    SELECT
        p.provider_id,
        p.provider_name,
        p.specialty,
        p.network_status,
        COUNT(*)                                                     AS adjudicated_claims,
        SUM(CASE WHEN c.claim_status = 'Rejected' THEN 1 ELSE 0 END) AS rejected_claims,
        SUM(CASE WHEN c.claim_status = 'Rejected' THEN c.billed_amount ELSE 0 END) AS rejected_billed
    FROM claims c
    JOIN providers p ON p.provider_id = c.provider_id
    WHERE c.claim_status <> 'Pending'
    GROUP BY p.provider_id
    HAVING COUNT(*) >= 150                       -- credibility threshold
),
benchmarked AS (
    SELECT
        *,
        ROUND(100.0 * rejected_claims / adjudicated_claims, 2)                          AS rejection_rate_pct,
        ROUND(100.0 * SUM(rejected_claims) OVER (PARTITION BY specialty)
                    / SUM(adjudicated_claims) OVER (PARTITION BY specialty), 2)          AS specialty_rate_pct,
        RANK() OVER (PARTITION BY specialty
                     ORDER BY 1.0 * rejected_claims / adjudicated_claims DESC)          AS rank_in_specialty
    FROM provider_stats
)
SELECT
    provider_id,
    provider_name,
    specialty,
    network_status,
    adjudicated_claims,
    rejected_claims,
    rejection_rate_pct,
    specialty_rate_pct,
    ROUND(rejection_rate_pct - specialty_rate_pct, 2) AS pts_above_specialty,
    rank_in_specialty,
    ROUND(rejected_billed, 0)                         AS rejected_billed
FROM benchmarked
ORDER BY pts_above_specialty DESC
LIMIT 25;
