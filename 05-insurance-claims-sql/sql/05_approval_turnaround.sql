-- 05. Adjudication turnaround time (submission -> decision) by claim type and outcome
-- Techniques: julianday date math, CTE, window-based percentiles (median / P90) via ROW_NUMBER
-- Business use: payer efficiency & prompt-pay compliance (many states require 30-45 day payment).
WITH tat AS (
    SELECT
        c.claim_type,
        c.claim_status,
        CASE WHEN pc.requires_prior_auth = 1 OR c.billed_amount > 2500
             THEN 'Manual review path' ELSE 'Auto-adjudication path' END   AS review_path,
        julianday(c.adjudication_date) - julianday(c.submission_date)       AS days
    FROM claims c
    JOIN procedure_codes pc ON pc.procedure_code = c.procedure_code
    WHERE c.claim_status IN ('Approved', 'Rejected')
),
ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY claim_type, claim_status, review_path ORDER BY days) AS rn,
           COUNT(*)     OVER (PARTITION BY claim_type, claim_status, review_path)               AS cnt
    FROM tat
)
SELECT
    claim_type,
    review_path,
    claim_status,
    cnt                                                            AS claims,
    ROUND(AVG(days), 1)                                            AS avg_days,
    MAX(CASE WHEN rn = (cnt + 1) / 2          THEN days END)       AS median_days,
    MAX(CASE WHEN rn = CAST(0.9 * cnt AS INT) THEN days END)       AS p90_days,
    ROUND(100.0 * AVG(days <= 15), 1)                              AS pct_within_15d,
    ROUND(100.0 * AVG(days <= 30), 1)                              AS pct_within_30d
FROM ranked
GROUP BY claim_type, review_path, claim_status
ORDER BY claim_type, review_path, claim_status;
