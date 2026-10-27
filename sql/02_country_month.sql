SELECT substr(invoice_date,1,7) AS month, country,
       COUNT(DISTINCT CASE WHEN quantity>0 THEN invoice_no END) AS orders,
       SUM(CASE WHEN quantity>0 THEN amount_pence ELSE 0 END) AS gross_pence,
       -SUM(CASE WHEN quantity<0 THEN amount_pence ELSE 0 END) AS cancellations_pence,
       SUM(amount_pence) AS net_pence
FROM transactions
WHERE invoice_date >= '2011-01-01' AND invoice_date < '2011-12-01'
GROUP BY 1,2 ORDER BY 1,2;
