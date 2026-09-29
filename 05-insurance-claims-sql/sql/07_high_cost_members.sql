-- 07. High-cost members: top 1% by approved spend, their conditions and plan
-- Techniques: CTEs, NTILE(100) percentile bucketing, window SUM for share of total, GROUP_CONCAT
-- Business use: case/disease-management referrals and stop-loss (reinsurance) exposure.
WITH member_spend AS (
    SELECT
        c.member_id,
        COUNT(*)                   AS approved_claims,
        SUM(c.approved_amount)     AS approved_spend,
        COUNT(DISTINCT c.provider_id) AS distinct_providers
    FROM claims c
    WHERE c.claim_status = 'Approved'
    GROUP BY c.member_id
),
pctl AS (
    SELECT *,
           NTILE(100) OVER (ORDER BY approved_spend DESC)             AS spend_percentile,
           100.0 * approved_spend / SUM(approved_spend) OVER ()       AS pct_of_total_spend
    FROM member_spend
),
conditions AS (
    SELECT c.member_id,
           GROUP_CONCAT(DISTINCT d.category)                          AS chronic_categories,
           COUNT(DISTINCT d.diagnosis_code)                           AS chronic_dx_count
    FROM claims c
    JOIN diagnosis_codes d ON d.diagnosis_code = c.diagnosis_code AND d.is_chronic = 1
    GROUP BY c.member_id
),
latest_policy AS (
    SELECT member_id, plan_type, metal_tier,
           ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY coverage_start DESC) AS rn
    FROM policies
)
SELECT
    p.member_id,
    CAST((julianday('2025-12-31') - julianday(m.birth_date)) / 365.25 AS INT) AS age,
    m.gender,
    m.state,
    lp.plan_type,
    lp.metal_tier,
    p.approved_claims,
    p.distinct_providers,
    ROUND(p.approved_spend, 0)           AS approved_spend,
    ROUND(p.pct_of_total_spend, 3)       AS pct_of_total_spend,
    COALESCE(cd.chronic_dx_count, 0)     AS chronic_dx_count,
    cd.chronic_categories
FROM pctl p
JOIN members m        ON m.member_id = p.member_id
JOIN latest_policy lp ON lp.member_id = p.member_id AND lp.rn = 1
LEFT JOIN conditions cd ON cd.member_id = p.member_id
WHERE p.spend_percentile = 1
ORDER BY p.approved_spend DESC
LIMIT 50;
