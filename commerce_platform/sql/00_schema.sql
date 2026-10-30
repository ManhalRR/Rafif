PRAGMA foreign_keys=ON;
CREATE TABLE dim_date(date_id INTEGER PRIMARY KEY, full_date TEXT NOT NULL UNIQUE,
 month TEXT NOT NULL, month_index INTEGER NOT NULL, year INTEGER NOT NULL, month_number INTEGER NOT NULL);
CREATE TABLE dim_country(country_id INTEGER PRIMARY KEY, country TEXT NOT NULL UNIQUE);
CREATE TABLE dim_product(product_id INTEGER PRIMARY KEY, stock_code TEXT NOT NULL UNIQUE,
 description TEXT NOT NULL, code_category TEXT NOT NULL);
CREATE TABLE fact_transactions(source_row_id TEXT PRIMARY KEY, date_id INTEGER NOT NULL REFERENCES dim_date,
 country_id INTEGER NOT NULL REFERENCES dim_country, product_id INTEGER NOT NULL REFERENCES dim_product,
 invoice_no TEXT NOT NULL, order_key TEXT NOT NULL, invoice_timestamp TEXT NOT NULL,
 customer_id INTEGER, quantity INTEGER NOT NULL, unit_price_text TEXT NOT NULL,
 amount_pence INTEGER NOT NULL, is_sale INTEGER NOT NULL, is_cancel INTEGER NOT NULL);
