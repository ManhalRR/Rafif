-- SQLite 3.25+. Positive sales and cancellations are defined during normalization.
-- All amounts are integer pence, rounded once per source line.
WITH monthly AS (
  SELECT substr(invoice_date,1,7) AS month,
         COUNT(DISTINCT CASE WHEN quantity > 0 THEN invoice_no END) AS orders,
         SUM(CASE WHEN quantity > 0 THEN amount_pence ELSE 0 END) AS gross_pence,
         -SUM(CASE WHEN quantity < 0 THEN amount_pence ELSE 0 END) AS cancellations_pence,
         SUM(amount_pence) AS net_pence
  FROM transactions
  WHERE invoice_date >= '2011-01-01' AND invoice_date < '2011-12-01'
  GROUP BY 1
)
SELECT *,
       ROUND(100.0*(net_pence-LAG(net_pence) OVER(ORDER BY month)) /
         NULLIF(LAG(net_pence) OVER(ORDER BY month),0),2) AS mom_pct,
       SUM(net_pence) OVER(ORDER BY month ROWS UNBOUNDED PRECEDING) AS cumulative_net_pence
FROM monthly ORDER BY month;
