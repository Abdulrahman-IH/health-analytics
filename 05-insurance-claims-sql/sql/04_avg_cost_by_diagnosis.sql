-- 04. Claim cost by diagnosis: average & median billed/approved, approval ratio
-- Techniques: CTE, JOIN, ROW_NUMBER()/COUNT() windows to compute a true median in SQLite
-- Business use: cost-of-condition view for care management and benefit design.
WITH approved AS MATERIALIZED (
    SELECT c.diagnosis_code, c.billed_amount, c.approved_amount, c.member_id
    FROM claims c
    WHERE c.claim_status = 'Approved'
),
ranked AS (
    SELECT
        diagnosis_code,
        approved_amount,
        ROW_NUMBER() OVER (PARTITION BY diagnosis_code ORDER BY approved_amount) AS rn,
        COUNT(*)     OVER (PARTITION BY diagnosis_code)                          AS cnt
    FROM approved
),
medians AS MATERIALIZED (
    SELECT diagnosis_code, AVG(approved_amount) AS median_approved
    FROM ranked
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY diagnosis_code
)
SELECT
    d.diagnosis_code,
    d.description,
    d.category,
    COUNT(*)                                          AS approved_claims,
    COUNT(DISTINCT a.member_id)                       AS members,
    ROUND(AVG(a.billed_amount), 0)                    AS avg_billed,
    ROUND(AVG(a.approved_amount), 0)                  AS avg_approved,
    ROUND(m.median_approved, 0)                       AS median_approved,
    ROUND(100.0 * SUM(a.approved_amount) / SUM(a.billed_amount), 1) AS approved_to_billed_pct,
    ROUND(SUM(a.approved_amount), 0)                  AS total_approved,
    ROUND(SUM(a.approved_amount) / COUNT(DISTINCT a.member_id), 0)  AS approved_per_member
FROM approved a
JOIN diagnosis_codes d ON d.diagnosis_code = a.diagnosis_code
JOIN medians m         ON m.diagnosis_code = a.diagnosis_code
GROUP BY d.diagnosis_code
ORDER BY avg_approved DESC;
