-- 02. Rejection reasons: volume, share of denials, dollars, avoidability
-- Techniques: LEFT JOIN, aggregation, window SUM() OVER () for share-of-total, running cumulative share
-- Business use: which denial categories drive rework and abrasion, and how much is preventable.
WITH reason_totals AS (
    SELECT
        r.reason_code,
        r.description,
        r.category,
        r.is_avoidable,
        COUNT(c.claim_id)              AS rejected_claims,
        COALESCE(SUM(c.billed_amount),0) AS rejected_billed
    FROM rejection_reasons r
    LEFT JOIN claims c
           ON c.rejection_reason_code = r.reason_code
          AND c.claim_status = 'Rejected'
    GROUP BY r.reason_code
)
SELECT
    reason_code,
    description,
    category,
    CASE is_avoidable WHEN 1 THEN 'Avoidable' ELSE 'Clinical/Policy' END AS avoidability,
    rejected_claims,
    ROUND(100.0 * rejected_claims / SUM(rejected_claims) OVER (), 2)     AS pct_of_rejections,
    ROUND(100.0 * SUM(rejected_claims) OVER (ORDER BY rejected_claims DESC
                                             ROWS UNBOUNDED PRECEDING)
                / SUM(rejected_claims) OVER (), 1)                         AS cumulative_pct,
    ROUND(rejected_billed, 0)                                              AS rejected_billed,
    ROUND(rejected_billed / NULLIF(rejected_claims, 0), 0)                 AS avg_billed_per_denial
FROM reason_totals
ORDER BY rejected_claims DESC;
