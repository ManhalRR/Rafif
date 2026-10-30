WITH RECURSIVE ages(age) AS (SELECT 0 UNION ALL SELECT age+1 FROM ages WHERE age<11),
 purchases AS (
 SELECT DISTINCT f.customer_id,d.month,d.month_index
 FROM fact_transactions f JOIN dim_date d USING(date_id)
 WHERE d.full_date>=:start AND d.full_date<:end AND f.is_sale=1 AND f.customer_id IS NOT NULL
 ), first_month AS (
 SELECT customer_id,MIN(month_index) AS cohort_index FROM purchases GROUP BY customer_id
 ), cohort_sizes AS (
 SELECT p.month AS cohort,f.cohort_index,COUNT(*) AS size
 FROM first_month f JOIN purchases p ON p.customer_id=f.customer_id AND p.month_index=f.cohort_index
 GROUP BY p.month,f.cohort_index
 ), active AS (
 SELECT f.cohort_index,p.month_index-f.cohort_index AS age,COUNT(*) AS active_customers
 FROM purchases p JOIN first_month f USING(customer_id)
 WHERE p.month_index-f.cohort_index BETWEEN 0 AND 11
 GROUP BY f.cohort_index,p.month_index-f.cohort_index
 )
SELECT c.cohort,c.size,a.age,
 CASE WHEN c.cohort_index+a.age>:last_month_index THEN NULL ELSE COALESCE(x.active_customers,0) END AS active_customers,
 CASE WHEN c.cohort_index+a.age>:last_month_index THEN NULL ELSE COALESCE(x.active_customers,0)*1.0/c.size END AS retention
FROM cohort_sizes c CROSS JOIN ages a LEFT JOIN active x ON x.cohort_index=c.cohort_index AND x.age=a.age
ORDER BY c.cohort,a.age;
