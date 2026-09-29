-- 10. Billed-amount outlier detection by procedure code
-- A claim is an outlier when |z| > 3 relative to its procedure code's distribution AND it bills
-- >= 3x the procedure's median. z-test is done without SQRT for portability: (x-mean)^2 > 9*variance.
-- Techniques: window AVG over partition for mean/variance, median via ROW_NUMBER, CTEs, JOINs
-- Business use: pre-payment review queue for billing anomalies (unbundling, unit inflation, typos).
WITH stats AS (
    SELECT
        c.claim_id, c.provider_id, c.member_id, c.procedure_code, c.service_date,
        c.billed_amount, c.approved_amount, c.claim_status, c.rejection_reason_code,
        AVG(c.billed_amount) OVER (PARTITION BY c.procedure_code)                          AS mean_billed,
        AVG(c.billed_amount * c.billed_amount) OVER (PARTITION BY c.procedure_code)
          - AVG(c.billed_amount) OVER (PARTITION BY c.procedure_code)
          * AVG(c.billed_amount) OVER (PARTITION BY c.procedure_code)                      AS var_billed,
        ROW_NUMBER() OVER (PARTITION BY c.procedure_code ORDER BY c.billed_amount)         AS rn,
        COUNT(*)     OVER (PARTITION BY c.procedure_code)                                  AS cnt
    FROM claims c
),
medians AS (
    SELECT procedure_code, AVG(billed_amount) AS median_billed
    FROM stats
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY procedure_code
),
flagged AS (
    SELECT s.*, m.median_billed,
           s.billed_amount / m.median_billed AS x_median
    FROM stats s
    JOIN medians m ON m.procedure_code = s.procedure_code
    WHERE (s.billed_amount - s.mean_billed) * (s.billed_amount - s.mean_billed) > 9 * s.var_billed
      AND s.billed_amount >= 3 * m.median_billed
)
SELECT
    f.claim_id,
    f.procedure_code,
    pc.description                     AS procedure_description,
    f.provider_id,
    p.provider_name,
    p.specialty,
    f.service_date,
    ROUND(f.median_billed, 2)          AS procedure_median_billed,
    f.billed_amount,
    ROUND(f.x_median, 1)               AS times_median,
    f.claim_status,
    f.rejection_reason_code,
    f.approved_amount
FROM flagged f
JOIN procedure_codes pc ON pc.procedure_code = f.procedure_code
JOIN providers p        ON p.provider_id = f.provider_id
ORDER BY f.billed_amount - f.median_billed DESC;
