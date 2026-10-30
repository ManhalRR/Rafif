SELECT d.month,c.country,
 SUM(CASE WHEN f.is_sale=1 THEN f.amount_pence ELSE 0 END) AS gross_pence,
 -SUM(CASE WHEN f.is_cancel=1 THEN f.amount_pence ELSE 0 END) AS cancel_pence,
 SUM(f.amount_pence) AS net_pence,
 COUNT(DISTINCT CASE WHEN f.is_sale=1 THEN f.order_key END) AS orders
FROM fact_transactions f JOIN dim_date d USING(date_id) JOIN dim_country c USING(country_id)
WHERE d.full_date>=:start AND d.full_date<:end
GROUP BY d.month,c.country ORDER BY d.month,c.country;
