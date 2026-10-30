WITH product_totals AS (
 SELECT p.stock_code,p.description,p.code_category,
  SUM(CASE WHEN f.is_sale=1 THEN f.amount_pence ELSE 0 END) AS gross_pence,
  -SUM(CASE WHEN f.is_cancel=1 THEN f.amount_pence ELSE 0 END) AS cancel_pence,
  SUM(f.amount_pence) AS net_pence,SUM(f.quantity) AS quantity,
  COUNT(DISTINCT CASE WHEN f.is_sale=1 THEN f.order_key END) AS orders
 FROM fact_transactions f JOIN dim_date d USING(date_id) JOIN dim_product p USING(product_id)
 WHERE d.full_date>=:start AND d.full_date<:end
 GROUP BY p.stock_code,p.description,p.code_category
), ranked AS (
 SELECT *,SUM(gross_pence) OVER() AS all_gross,
  COALESCE(SUM(gross_pence) OVER(ORDER BY gross_pence DESC,stock_code ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS prior_gross
 FROM product_totals
)
SELECT stock_code,description,code_category,gross_pence,cancel_pence,net_pence,quantity,orders,
 CASE WHEN gross_pence<=0 THEN 'C'
      WHEN prior_gross*1.0/all_gross<0.80 THEN 'A'
      WHEN prior_gross*1.0/all_gross<0.95 THEN 'B' ELSE 'C' END AS abc,
 CASE WHEN all_gross>0 THEN gross_pence*1.0/all_gross ELSE NULL END AS gross_share
FROM ranked ORDER BY gross_pence DESC,stock_code;
