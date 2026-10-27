-- First observed purchase, not proven first-ever acquisition.
-- Use December 2010 as lookback; activity stops before incomplete December 2011.
-- Missing CustomerID excluded only from this customer-level metric.
WITH activity AS (
 SELECT DISTINCT customer_id, substr(invoice_date,1,7) AS month,
   CAST(strftime('%Y',invoice_date) AS INTEGER)*12 +
   CAST(strftime('%m',invoice_date) AS INTEGER) AS month_id
 FROM transactions
 WHERE quantity>0 AND customer_id IS NOT NULL AND invoice_date < '2011-12-01'
), first_seen AS (
 SELECT customer_id,MIN(month) AS cohort, MIN(month_id) AS first_month_id
 FROM activity GROUP BY customer_id
), sizes AS (
 SELECT cohort,COUNT(*) AS cohort_size,MIN(first_month_id) AS first_month_id
 FROM first_seen GROUP BY cohort
), periods(k) AS (VALUES(0),(1),(2),(3),(4),(5)), active AS (
 SELECT f.cohort,a.month_id-f.first_month_id AS age,COUNT(*) AS active_customers
 FROM activity a JOIN first_seen f USING(customer_id)
 GROUP BY 1,2
)
SELECT s.cohort,p.k AS age,s.cohort_size,
 CASE WHEN s.first_month_id+p.k <= 2011*12+11 THEN COALESCE(a.active_customers,0) END AS active_customers,
 CASE WHEN s.first_month_id+p.k <= 2011*12+11
      THEN 1.0*COALESCE(a.active_customers,0)/s.cohort_size END AS retention
FROM sizes s CROSS JOIN periods p
LEFT JOIN active a ON a.cohort=s.cohort AND a.age=p.k
ORDER BY s.cohort,p.k;
