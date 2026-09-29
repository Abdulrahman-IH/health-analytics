-- 09. Duplicate-claim detection (fraud / payment-integrity signal)
-- Definition: same member + provider + service date + procedure code, submitted more than once.
--   exact duplicate = identical billed amount; near duplicate = billed within +/-5%.
-- Techniques: window COUNT/ROW_NUMBER/FIRST_VALUE partitioned by the duplicate key, CTEs
-- Business use: quantify dollars paid on duplicates that slipped past front-end edits (recoverable).
WITH keyed AS (
    SELECT
        c.*,
        COUNT(*)     OVER w                                   AS copies,
        ROW_NUMBER() OVER (PARTITION BY member_id, provider_id, service_date, procedure_code
                           ORDER BY submission_date, claim_id) AS seq,
        FIRST_VALUE(billed_amount) OVER (PARTITION BY member_id, provider_id, service_date, procedure_code
                           ORDER BY submission_date, claim_id) AS original_billed,
        FIRST_VALUE(claim_id) OVER (PARTITION BY member_id, provider_id, service_date, procedure_code
                           ORDER BY submission_date, claim_id) AS original_claim_id
    FROM claims c
    WINDOW w AS (PARTITION BY member_id, provider_id, service_date, procedure_code)
),
dups AS (
    SELECT
        k.*,
        CASE WHEN billed_amount = original_billed THEN 'Exact duplicate'
             WHEN ABS(billed_amount - original_billed) <= 0.05 * original_billed THEN 'Near duplicate'
             ELSE 'Same-day repeat service' END AS dup_type
    FROM keyed k
    WHERE copies > 1 AND seq > 1
)
SELECT
    dup_type,
    COUNT(*)                                                           AS duplicate_claims,
    SUM(claim_status = 'Rejected' AND rejection_reason_code = 'R01')   AS caught_by_edits,
    SUM(claim_status = 'Approved')                                     AS paid_duplicates,
    SUM(claim_status = 'Pending')                                      AS pending_duplicates,
    ROUND(100.0 * SUM(claim_status = 'Approved') / COUNT(*), 1)        AS leakage_rate_pct,
    ROUND(SUM(CASE WHEN claim_status = 'Approved' THEN approved_amount ELSE 0 END), 0) AS dollars_paid_on_duplicates,
    COUNT(DISTINCT provider_id)                                        AS providers_involved
FROM dups
GROUP BY dup_type
ORDER BY duplicate_claims DESC;
