-- 03. Rejection rate by specialty x reason, with each specialty's top denial driver
-- Techniques: CTEs, conditional aggregation (pivot), ROW_NUMBER() to pick the top reason
-- Business use: tailor provider-education campaigns (e.g. prior-auth for Radiology, coding for PT).
WITH base AS (
    SELECT p.specialty, c.claim_status, c.rejection_reason_code
    FROM claims c
    JOIN providers p ON p.provider_id = c.provider_id
    WHERE c.claim_status <> 'Pending'
),
by_reason AS (
    SELECT specialty, rejection_reason_code, COUNT(*) AS n
    FROM base
    WHERE claim_status = 'Rejected'
    GROUP BY specialty, rejection_reason_code
),
top_reason AS (
    SELECT specialty, rejection_reason_code, n,
           ROW_NUMBER() OVER (PARTITION BY specialty ORDER BY n DESC) AS rn
    FROM by_reason
)
SELECT
    b.specialty,
    COUNT(*)                                                                         AS adjudicated,
    ROUND(100.0 * AVG(b.claim_status = 'Rejected'), 2)                               AS rejection_rate_pct,
    ROUND(100.0 * AVG(b.rejection_reason_code = 'R02'), 2)                           AS prior_auth_pct,
    ROUND(100.0 * AVG(b.rejection_reason_code = 'R05'), 2)                           AS out_of_network_pct,
    ROUND(100.0 * AVG(b.rejection_reason_code = 'R06'), 2)                           AS coding_pct,
    ROUND(100.0 * AVG(b.rejection_reason_code = 'R01'), 2)                           AS duplicate_pct,
    ROUND(100.0 * AVG(b.rejection_reason_code IN ('R04','R07','R08')), 2)            AS admin_eligibility_pct,
    ROUND(100.0 * AVG(b.rejection_reason_code IN ('R03','R09','R10')), 2)            AS clinical_policy_pct,
    t.rejection_reason_code || ' - ' || rr.description                               AS top_rejection_reason
FROM base b
JOIN top_reason t        ON t.specialty = b.specialty AND t.rn = 1
JOIN rejection_reasons rr ON rr.reason_code = t.rejection_reason_code
GROUP BY b.specialty
ORDER BY rejection_rate_pct DESC;
