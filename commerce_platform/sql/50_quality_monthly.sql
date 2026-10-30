SELECT d.month,COUNT(*) AS rows,SUM(CASE WHEN f.customer_id IS NULL THEN 1 ELSE 0 END) AS missing_customer_rows
FROM fact_transactions f JOIN dim_date d USING(date_id)
WHERE d.full_date>=:start AND d.full_date<:end
GROUP BY d.month ORDER BY d.month;
