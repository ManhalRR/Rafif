"""Small specified edge cases; no UCI download required."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run import normalize,warehouse,marts,pence

def source(rows):
    names=['Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country']
    d=pd.DataFrame(rows,columns=names)
    d['source_row_id']=['fixture:'+str(i+2) for i in range(len(d))]
    return d

def sale(invoice='1',stock='50001',qty=1,date='2009-12-01',price=10,customer=1,country='UK'):
    return (invoice,stock,'Product '+stock,qty,date,price,customer,country)

def sql_fixture(rows):
    d,_=normalize(source(rows))
    conn=warehouse(d,':memory:')
    try:return marts(conn)
    finally:conn.close()

class EngineTests(unittest.TestCase):
    def test_decimal_half_even_applies_to_line_not_unit(self):
        self.assertEqual(pence(1,.005),0)
        self.assertEqual(pence(1,.015),2)
        self.assertEqual(pence(-1,.015),-2)
        self.assertEqual(pence(3,.005),2)
        self.assertEqual(pence(100,.1),1000)

    def test_malformed_rows_have_exclusive_reasons(self):
        rows=[sale(),sale('C2',qty=1),sale('3',qty=-1),sale('4',price=0),sale('5',qty=0),
              sale('6',date='not-a-date'),sale(None),sale('8',qty=1.5)]
        d,reasons=normalize(source(rows))
        self.assertEqual(len(d),1)
        self.assertEqual(reasons.tolist(),['accepted','sign_prefix_mismatch','sign_prefix_mismatch','nonpositive_or_invalid_price','invalid_or_zero_quantity','invalid_datetime','missing_invoice','invalid_or_zero_quantity'])

    def test_missing_customer_kept_in_money_not_cohorts(self):
        f=sql_fixture([sale(),sale('2',price=20,customer=None)])
        self.assertEqual(int(f['monthly'].net_pence.sum()),3000)
        self.assertEqual(int(f['cohorts'][f['cohorts'].age.eq(0)]['size'].sum()),1)
        self.assertEqual(int(f['quality_monthly'].missing_customer_rows.sum()),1)

    def test_cancellation_only_month_keeps_negative_net_and_zero_orders(self):
        f=sql_fixture([sale(),sale('C2',qty=-1,date='2010-01-02',price=3)])
        jan=f['monthly'].set_index('month').loc['2010-01']
        self.assertEqual(jan.to_dict(),{'gross_pence':0,'cancel_pence':300,'net_pence':-300,'orders':0})

    def test_duplicate_rows_retained_but_order_is_unique(self):
        f=sql_fixture([sale(),sale()])
        self.assertEqual(int(f['monthly'].net_pence.sum()),2000)
        self.assertEqual(int(f['monthly'].orders.sum()),1)

    def test_period_boundaries_exclude_partial_december(self):
        f=sql_fixture([sale('0',date='2009-11-30 23:59:59'),sale('1',date='2009-12-01 00:00:00'),
                       sale('2',date='2011-11-30 23:59:59'),sale('3',date='2011-12-01 00:00:00')])
        self.assertEqual(f['monthly'].month.tolist(),['2009-12','2011-11'])
        self.assertEqual(int(f['monthly'].orders.sum()),2)

    def test_cohort_future_null_differs_from_observed_zero(self):
        f=sql_fixture([sale(),sale('2',date='2011-11-15',customer=2)])['cohorts'].set_index(['cohort','age'])
        self.assertEqual(f.loc[('2009-12',1),'active_customers'],0)
        self.assertTrue(pd.isna(f.loc[('2011-11',1),'active_customers']))
        self.assertEqual(f.loc[('2011-11',0),'retention'],1)

    def test_abc_thresholds_and_equal_gross_tie_order(self):
        f=sql_fixture([sale('1','50002',price=40),sale('2','50001',price=40),sale('3','50003',price=15),sale('4','50004',price=5)])['products']
        self.assertEqual(f.stock_code.tolist(),['50001','50002','50003','50004'])
        self.assertEqual(f.abc.tolist(),['A','A','B','C'])
        self.assertAlmostEqual(f.gross_share.sum(),1)

    def test_same_invoice_in_two_countries_or_months_not_collapsed(self):
        f=sql_fixture([sale('1',country='UK'),sale('1',country='Germany'),sale('1',date='2010-01-01',country='UK')])
        self.assertEqual(int(f['monthly'].orders.sum()),3)
        self.assertEqual(int(f['country_month'].orders.sum()),3)

    def test_cancellation_only_product_universe_has_undefined_gross_share(self):
        f=sql_fixture([sale('C1',qty=-1)])['products']
        self.assertEqual(f.abc.tolist(),['C'])
        self.assertTrue(pd.isna(f.iloc[0].gross_share))

    def test_product_and_country_reconcile_money_with_cancellations(self):
        f=sql_fixture([sale('1','50001',price=12.345),sale('2','POST',price=3,country='Germany'),sale('C3','50001',qty=-1,price=2)])
        for name in ['monthly','country_month','products']:
            self.assertEqual(int(f[name].net_pence.sum()),1334)
            self.assertEqual(int(f[name].gross_pence.sum())-int(f[name].cancel_pence.sum()),1334)
        self.assertEqual(f['products'].set_index('stock_code').loc['POST','code_category'],'service_or_nonstandard_code')

if __name__=='__main__':unittest.main()
