-- SQLite. Parameters are exclusive interval boundaries.
-- Features contain no information on/after :snapshot.
WITH buyers AS (
  SELECT customer_id,
         CAST(julianday(:snapshot) - julianday(date(MAX(invoice_date))) AS INTEGER) AS recency_days,
         COUNT(DISTINCT invoice_no) AS frequency
  FROM transactions
  WHERE customer_id IS NOT NULL AND amount_pence > 0
    AND invoice_date >= :history_start AND invoice_date < :snapshot
  GROUP BY customer_id
), monetary AS (
  SELECT customer_id, SUM(amount_pence) AS monetary_pence
  FROM transactions
  WHERE customer_id IS NOT NULL
    AND invoice_date >= :history_start AND invoice_date < :snapshot
  GROUP BY customer_id
), holdout AS (
  SELECT customer_id,
         COUNT(DISTINCT CASE WHEN amount_pence > 0 THEN invoice_no END) AS future_orders,
         SUM(CASE WHEN amount_pence > 0 THEN amount_pence ELSE 0 END) AS future_gross_pence,
         -SUM(CASE WHEN amount_pence < 0 THEN amount_pence ELSE 0 END) AS future_cancel_pence,
         SUM(amount_pence) AS future_net_pence
  FROM transactions
  WHERE customer_id IS NOT NULL
    AND invoice_date >= :snapshot AND invoice_date < :holdout_end
  GROUP BY customer_id
), features AS (
  SELECT b.*, m.monetary_pence,
    CASE WHEN b.recency_days <= 30 AND b.frequency >= 5 AND m.monetary_pence >= 100000 THEN 'loyal_high_value'
         WHEN b.recency_days > 90 AND b.frequency >= 3 THEN 'at_risk_repeat'
         WHEN b.recency_days <= 30 AND b.frequency = 1 THEN 'recent_single'
         WHEN b.recency_days <= 60 AND b.frequency >= 2 THEN 'active_repeat'
         ELSE 'other_buyers' END AS segment
  FROM buyers b JOIN monetary m USING(customer_id)
)
SELECT f.*, COALESCE(h.future_orders, 0) AS future_orders,
       COALESCE(h.future_gross_pence, 0) AS future_gross_pence,
       COALESCE(h.future_cancel_pence, 0) AS future_cancel_pence,
       COALESCE(h.future_net_pence, 0) AS future_net_pence
FROM features f LEFT JOIN holdout h USING(customer_id)
ORDER BY customer_id;
