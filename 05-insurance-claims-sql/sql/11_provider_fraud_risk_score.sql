-- 11. Provider fraud-signal scorecard (composite risk score)
-- Signals, each compared with specialty peers via PERCENT_RANK():
--   (a) billed-to-reference markup  (b) high-complexity E&M (99215) share -> upcoding
--   (c) duplicate-submission rate   (d) billed-amount outlier rate  (e) claims per member
-- Techniques: multiple CTEs, JOINs, PERCENT_RANK() OVER (PARTITION BY specialty), weighted score
-- Business use: prioritise the Special Investigations Unit (SIU) caseload.
WITH dup_flags AS (
    SELECT claim_id,
           ROW_NUMBER() OVER (PARTITION BY member_id, provider_id, service_date, procedure_code
                              ORDER BY submission_date, claim_id) > 1 AS is_dup
    FROM claims
),
proc_median AS (
    SELECT procedure_code, AVG(billed_amount) AS median_billed
    FROM (SELECT procedure_code, billed_amount,
                 ROW_NUMBER() OVER (PARTITION BY procedure_code ORDER BY billed_amount) AS rn,
                 COUNT(*)     OVER (PARTITION BY procedure_code)                        AS cnt
          FROM claims)
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY procedure_code
),
provider_signals AS (
    SELECT
        p.provider_id, p.provider_name, p.specialty, p.network_status,
        COUNT(*)                                                               AS claims,
        COUNT(DISTINCT c.member_id)                                            AS members,
        SUM(c.billed_amount) / SUM(pc.reference_allowed_amount * c.units)      AS markup_ratio,
        1.0 * SUM(c.procedure_code = '99215')
            / NULLIF(SUM(c.procedure_code IN ('99213','99214','99215')), 0)    AS em_high_share,
        AVG(d.is_dup)                                                          AS dup_rate,
        AVG(c.billed_amount >= 4 * pm.median_billed)                           AS outlier_rate,
        1.0 * COUNT(*) / COUNT(DISTINCT c.member_id)                           AS claims_per_member,
        SUM(COALESCE(c.approved_amount, 0))                                    AS approved_paid
    FROM claims c
    JOIN providers p        ON p.provider_id = c.provider_id
    JOIN procedure_codes pc ON pc.procedure_code = c.procedure_code
    JOIN proc_median pm     ON pm.procedure_code = c.procedure_code
    JOIN dup_flags d        ON d.claim_id = c.claim_id
    GROUP BY p.provider_id
    HAVING COUNT(*) >= 50
),
scored AS (
    SELECT *,
        PERCENT_RANK() OVER (PARTITION BY specialty ORDER BY markup_ratio)                  AS pr_markup,
        PERCENT_RANK() OVER (PARTITION BY specialty ORDER BY COALESCE(em_high_share, 0))    AS pr_upcode,
        PERCENT_RANK() OVER (PARTITION BY specialty ORDER BY dup_rate)                      AS pr_dup,
        PERCENT_RANK() OVER (PARTITION BY specialty ORDER BY outlier_rate)                  AS pr_outlier,
        PERCENT_RANK() OVER (PARTITION BY specialty ORDER BY claims_per_member)             AS pr_intensity
    FROM provider_signals
)
SELECT
    provider_id, provider_name, specialty, network_status, claims, members,
    ROUND(markup_ratio, 2)                    AS markup_ratio,
    ROUND(100 * em_high_share, 1)             AS pct_99215,
    ROUND(100 * dup_rate, 2)                  AS dup_rate_pct,
    ROUND(100 * outlier_rate, 2)              AS outlier_rate_pct,
    ROUND(claims_per_member, 2)               AS claims_per_member,
    ROUND(approved_paid, 0)                   AS approved_paid,
    ROUND(100 * (0.30 * pr_markup + 0.20 * pr_upcode + 0.25 * pr_dup
               + 0.15 * pr_outlier + 0.10 * pr_intensity), 1) AS risk_score,
    (pr_markup >= 0.95) + (pr_upcode >= 0.95 AND em_high_share IS NOT NULL)
      + (pr_dup >= 0.95) + (pr_outlier >= 0.95)                   AS red_flags
FROM scored
ORDER BY risk_score DESC
LIMIT 30;
