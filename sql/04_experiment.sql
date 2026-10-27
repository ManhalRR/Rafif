-- One row per randomized participant. Intention-to-treat denominator.
SELECT variant, COUNT(*) AS users, SUM(converted) AS conversions,
       AVG(converted) AS conversion_rate,
       SUM(revenue_kopecks)/100.0 AS revenue_rub,
       AVG(revenue_kopecks)/100.0 AS revenue_per_user_rub
FROM experiment GROUP BY variant ORDER BY variant;
