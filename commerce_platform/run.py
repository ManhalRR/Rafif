"""Commerce warehouse: UCI Online Retail II -> SQLite -> aggregate marts.

python run.py [--input data/online_retail_II.xlsx]
python run.py --tests-only
Raw transactions and customer IDs remain in the local data directory.
"""
from pathlib import Path
from decimal import Decimal, ROUND_HALF_EVEN
from datetime import datetime, timezone
import argparse
import hashlib
import json
import sqlite3
import sys
import unittest
import urllib.request
import zipfile
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
START='2009-12-01'; END='2011-12-01'; CUT='2010-12-01'
MONTHS=pd.period_range(START,periods=24,freq='M').astype(str).tolist()
SOURCE_URL='https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip'
XLSX_SHA='bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980'
ZIP_SHA='572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb'
COLS=['Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country']
PARAMS={'start':START,'end':END,'last_month_index':2011*12+10}

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def records(frame):
    return json.loads(frame.to_json(orient='records',force_ascii=False,double_precision=15))

def pence(quantity,price):
    return int((Decimal(str(int(quantity)))*Decimal(str(price))*100).quantize(Decimal('1'),rounding=ROUND_HALF_EVEN))

def download_source(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    archive=path.parent/'online_retail_ii.zip'
    if not archive.exists():
        temporary=archive.with_suffix('.download')
        urllib.request.urlretrieve(SOURCE_URL,temporary)
        if digest(temporary)!=ZIP_SHA:raise ValueError('Downloaded ZIP SHA-256 differs from pinned source')
        temporary.replace(archive)
    if digest(archive)!=ZIP_SHA:raise ValueError('ZIP SHA-256 mismatch')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Source ZIP CRC failed')
        path.write_bytes(z.read('online_retail_II.xlsx'))

def read_source(path):
    if digest(path)!=XLSX_SHA:raise ValueError('XLSX SHA-256 mismatch; do not substitute a modified workbook')
    sheets=pd.read_excel(path,sheet_name=None,engine='openpyxl')
    if list(sheets)!=['Year 2009-2010','Year 2010-2011']:raise ValueError('Unexpected sheets')
    frames=[]; sheet_audit=[]
    for sheet,d in sheets.items():
        if list(d.columns)!=COLS:raise ValueError('Unexpected source schema')
        x=d.copy();x['source_sheet']=sheet;x['source_row_id']=[sheet+':'+str(i) for i in range(2,len(x)+2)]
        frames.append(x)
        sheet_audit.append({'sheet':sheet,'rows':len(x),'first_date':str(x.InvoiceDate.min()),'last_date':str(x.InvoiceDate.max()),'exact_duplicates':int(x.duplicated(COLS).sum())})
    raw=pd.concat(frames,ignore_index=True)
    if len(raw)!=1067371:raise ValueError('Unexpected source row count')
    first,last=frames
    overlap_a=first[first.InvoiceDate.ge(CUT)]
    overlap_b=last[last.InvoiceDate.le(overlap_a.InvoiceDate.max())]
    ha=pd.util.hash_pandas_object(overlap_a[COLS],index=False).value_counts().sort_index()
    hb=pd.util.hash_pandas_object(overlap_b[COLS],index=False).value_counts().sort_index()
    # Hash equality is accompanied by source SHA and invoice counts; no fuzzy matching.
    equal=ha.equals(hb)
    if not equal:raise ValueError('Overlap multisets differ; source ownership needs investigation')
    keep=((raw.source_sheet.eq('Year 2009-2010')&raw.InvoiceDate.lt(CUT))|
          (raw.source_sheet.eq('Year 2010-2011')&raw.InvoiceDate.ge(CUT)))
    selected=raw.loc[keep].copy()
    audit={'sheets':sheet_audit,'first_overlap_rows':len(overlap_a),'second_overlap_rows':len(overlap_b),
        'overlap_invoice_count':int(overlap_a.Invoice.nunique()),'overlap_multisets_equal':equal,
        'overlap_rows_excluded':int((~keep).sum()),'combined_exact_duplicates':int(raw.duplicated(COLS).sum()),
        'selected_exact_duplicates':int(selected.duplicated(COLS).sum()),'selected_rows':len(selected)}
    return raw,selected,audit

def normalize(raw):
    d=raw.copy()
    d['invoice_date']=pd.to_datetime(d.InvoiceDate,errors='coerce',format='mixed')
    q=pd.to_numeric(d.Quantity,errors='coerce');price=pd.to_numeric(d.Price,errors='coerce')
    invoice=d.Invoice.astype('string').str.strip()
    reasons=pd.Series('accepted',index=d.index,dtype='str')
    conditions=[('invalid_datetime',d.invoice_date.isna()),
        ('invalid_or_zero_quantity',~np.isfinite(q)|q.isna()|q.eq(0)|q.mod(1).ne(0)),
        ('nonpositive_or_invalid_price',~np.isfinite(price)|price.isna()|price.le(0)),
        ('missing_invoice',invoice.isna()|invoice.eq(''))]
    cancellation=invoice.str.upper().str.startswith('C').fillna(False)
    conditions.append(('sign_prefix_mismatch',~((q.gt(0)&~cancellation)|(q.lt(0)&cancellation))))
    for label,mask in conditions:reasons.loc[reasons.eq('accepted')&mask]=label
    accepted=reasons.eq('accepted')
    d=d.loc[accepted].copy();q=q.loc[accepted].astype('int64');price=price.loc[accepted]
    d['invoice_no']=invoice.loc[accepted];d['quantity']=q
    d['unit_price_text']=price.map(str)
    d['amount_pence']=np.fromiter((pence(x,y) for x,y in zip(q,price)),dtype='int64',count=len(d))
    d['is_sale']=q.gt(0).astype('int64');d['is_cancel']=q.lt(0).astype('int64')
    customer=pd.to_numeric(d['Customer ID'],errors='coerce')
    valid_customer=customer.notna()&np.isfinite(customer)&customer.gt(0)&customer.mod(1).eq(0)
    d['customer_id']=customer.where(valid_customer).astype('Int64')
    d['country']=d.Country.astype('string').str.strip().fillna('Unknown')
    d.loc[d.country.eq(''),'country']='Unknown'
    d['stock_code']=d.StockCode.astype('string').str.strip().fillna('UNKNOWN_STOCK_CODE')
    d.loc[d.stock_code.eq(''),'stock_code']='UNKNOWN_STOCK_CODE'
    d['description']=d.Description.astype('string').str.strip().fillna('Description unavailable')
    d.loc[d.description.eq(''),'description']='Description unavailable'
    d['month']=d.invoice_date.dt.strftime('%Y-%m')
    # JSON tuple is unambiguous even if country/invoice text contains separators.
    d['order_key']=[json.dumps([str(i),str(c),str(m)],ensure_ascii=False,separators=(',',':')) for i,c,m in zip(d.invoice_no,d.country,d.month)]
    return d,reasons

def warehouse(d,path):
    conn=sqlite3.connect(path)
    conn.executescript((ROOT/'sql/00_schema.sql').read_text(encoding='utf-8'))
    dates=pd.DataFrame({'full_date':pd.date_range(d.invoice_date.min().normalize(),d.invoice_date.max().normalize(),freq='D')})
    dates['date_id']=dates.full_date.dt.strftime('%Y%m%d').astype(int)
    dates['month']=dates.full_date.dt.strftime('%Y-%m');dates['year']=dates.full_date.dt.year
    dates['month_number']=dates.full_date.dt.month;dates['month_index']=dates.year*12+dates.month_number-1
    dates['full_date']=dates.full_date.dt.strftime('%Y-%m-%d')
    dates.to_sql('dim_date',conn,if_exists='append',index=False)
    countries=pd.DataFrame({'country':sorted(d.country.unique())});countries['country_id']=np.arange(1,len(countries)+1)
    countries.to_sql('dim_country',conn,if_exists='append',index=False)
    labels=d.groupby(['stock_code','description'],dropna=False).size().rename('n').reset_index().sort_values(['stock_code','n','description'],ascending=[True,False,True]).drop_duplicates('stock_code')
    products=labels[['stock_code','description']].copy();products['product_id']=np.arange(1,len(products)+1)
    products['code_category']=np.where(products.stock_code.str.match(r'^\d{5}[A-Za-z]*$'),'standard_stock_pattern','service_or_nonstandard_code')
    products.to_sql('dim_product',conn,if_exists='append',index=False)
    f=d[['source_row_id','invoice_no','order_key','customer_id','quantity','unit_price_text','amount_pence','is_sale','is_cancel']].copy()
    f['date_id']=d.invoice_date.dt.strftime('%Y%m%d').astype(int)
    f['invoice_timestamp']=d.invoice_date.dt.strftime('%Y-%m-%d %H:%M:%S')
    f['country_id']=d.country.map(countries.set_index('country').country_id)
    f['product_id']=d.stock_code.map(products.set_index('stock_code').product_id)
    f.to_sql('fact_transactions',conn,if_exists='append',index=False,chunksize=10000)
    conn.executescript('CREATE INDEX idx_fact_date_country ON fact_transactions(date_id,country_id); CREATE INDEX idx_fact_product ON fact_transactions(product_id); CREATE INDEX idx_fact_customer_date ON fact_transactions(customer_id,date_id);')
    return conn

def marts(conn):
    frames={}
    for name,file in [('monthly','10_monthly.sql'),('country_month','20_country_month.sql'),('products','30_products.sql'),('cohorts','40_cohorts.sql'),('quality_monthly','50_quality_monthly.sql')]:
        frames[name]=pd.read_sql_query((ROOT/'sql'/file).read_text(encoding='utf-8'),conn,params=PARAMS)
        frames[name].to_sql('mart_'+name,conn,if_exists='replace',index=False)
    return frames

def validate(d,raw,selected,audit,frames,conn):
    checks=[]
    def check(label,value):
        if not bool(value):raise AssertionError(label)
        checks.append({'check':label,'passed':True})
    reporting=d[d.invoice_date.ge(START)&d.invoice_date.lt(END)]
    positive=reporting[reporting.is_sale.eq(1)]
    totals={'gross_pence':int(positive.amount_pence.sum()),'cancel_pence':-int(reporting.loc[reporting.is_cancel.eq(1),'amount_pence'].sum()),
        'net_pence':int(reporting.amount_pence.sum()),'orders':int(positive.order_key.nunique()),
        'known_customers':int(positive.customer_id.nunique()),'products':int(reporting.stock_code.nunique())}
    monthly=frames['monthly'];country=frames['country_month'];products=frames['products'];cohorts=frames['cohorts']
    check('Source workbook row count',len(raw)==1067371)
    check('Overlap row multisets identical',audit['overlap_multisets_equal'])
    check('Source ownership is complete after explicit overlap exclusion',len(selected)+audit['overlap_rows_excluded']==len(raw))
    check('Source row provenance unique',d.source_row_id.is_unique)
    check('SQLite foreign key validation',not conn.execute('PRAGMA foreign_key_check').fetchall())
    check('SQLite integrity check',conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
    check('Exactly 24 complete reporting months',monthly.month.tolist()==MONTHS)
    check('Gross less cancellations equals net',totals['gross_pence']-totals['cancel_pence']==totals['net_pence'])
    for key in ['gross_pence','cancel_pence','net_pence','orders']:
        check('Monthly '+key+' reconciles to independent transaction aggregation',int(monthly[key].sum())==totals[key])
    independent=reporting.groupby('month').agg(net_pence=('amount_pence','sum'))
    independent['gross_pence']=positive.groupby('month').amount_pence.sum()
    independent['cancel_pence']=-reporting[reporting.is_cancel.eq(1)].groupby('month').amount_pence.sum()
    independent['orders']=positive.groupby('month').order_key.nunique()
    independent=independent.fillna(0).astype('int64').reset_index()
    for key in ['gross_pence','cancel_pence','net_pence','orders']:
        check('Independent pandas vs SQL monthly '+key,monthly[key].tolist()==independent[key].tolist())
    check('Country-month monetary aggregates match pandas',country.set_index(['month','country']).net_pence.sort_index().equals(reporting.groupby(['month','country']).amount_pence.sum().rename('net_pence').sort_index()))
    check('Composite order belongs to exactly one country and month',positive.groupby('order_key').agg(countries=('country','nunique'),months=('month','nunique')).eq(1).all().all())
    check('Country-month orders add to total',int(country.orders.sum())==totals['orders'])
    for key in ['gross_pence','cancel_pence','net_pence']:
        check('Product '+key+' reconciles',int(products[key].sum())==totals[key])
    check('Product net matches independent pandas aggregation',products.set_index('stock_code').net_pence.sort_index().equals(reporting.groupby('stock_code').amount_pence.sum().rename('net_pence').sort_index()))
    check('ABC shares sum to 1',abs(products.gross_share.sum()-1)<1e-12)
    check('ABC deterministic gross/code sorting',products.stock_code.tolist()==products.sort_values(['gross_pence','stock_code'],ascending=[False,True]).stock_code.tolist())
    purchases=positive[positive.customer_id.notna()][['customer_id','month']].drop_duplicates()
    first=purchases.groupby('customer_id').month.min()
    check('Cohort sizes reconcile to unique known buyers',int(cohorts[cohorts.age.eq(0)]['size'].sum())==totals['known_customers'])
    check('All M0 cells equal cohort size',cohorts.loc[cohorts.age.eq(0),'retention'].eq(1).all())
    independent_cohorts={}
    for cohort,ids in first.groupby(first):
        ids=set(ids.index);base=pd.Period(cohort,freq='M')
        for age in range(12):
            month=str(base+age)
            independent_cohorts[(cohort,age)]=None if month>MONTHS[-1] else int(purchases[purchases.month.eq(month)].customer_id.isin(ids).sum())
    check('All cohort cells reconcile independently including future NULL',all((pd.isna(r.active_customers) and independent_cohorts[(r.cohort,r.age)] is None) or r.active_customers==independent_cohorts[(r.cohort,r.age)] for r in cohorts.itertuples()))
    check('Observed cohort rates within unit interval',cohorts.retention.dropna().between(0,1).all())
    check('Quality monthly counts reconcile',int(frames['quality_monthly'].rows.sum())==len(reporting))
    check('Quality missing customer counts reconcile',int(frames['quality_monthly'].missing_customer_rows.sum())==int(reporting.customer_id.isna().sum()))
    invoice_audit=positive.groupby('invoice_no').agg(countries=('country','nunique'),months=('month','nunique'))
    return totals,checks,reporting,{'invoices_spanning_countries':int(invoice_audit.countries.gt(1).sum()),'invoices_spanning_months':int(invoice_audit.months.gt(1).sum()),'plain_invoice_orders':int(positive.invoice_no.nunique()),'composite_orders':totals['orders']}

def run_tests():
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_engine.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise AssertionError('Engine fixture tests failed')
    return result.testsRun

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'data/online_retail_II.xlsx')
    parser.add_argument('--tests-only',action='store_true')
    args=parser.parse_args()
    if args.tests_only:run_tests();return
    if not args.input.exists():
        if '--input' in sys.argv:parser.error('Specified input does not exist')
        download_source(args.input)
    print('Reading verified UCI workbook...',flush=True)
    raw,selected,audit=read_source(args.input)
    print('Normalizing ownership-selected rows...',flush=True)
    d,reasons=normalize(selected)
    (ROOT/'data').mkdir(exist_ok=True);out=ROOT/'results';out.mkdir(exist_ok=True)
    temp=ROOT/'data/warehouse.build.sqlite'
    if temp.exists():temp.unlink()
    print('Building SQLite dimensions/fact and SQL marts...',flush=True)
    conn=warehouse(d,temp)
    try:
        frames=marts(conn)
        totals,checks,reporting,order_audit=validate(d,raw,selected,audit,frames,conn)
        fixtures=run_tests()
        conn.commit()
    finally:conn.close()
    temp.replace(ROOT/'data/warehouse.sqlite')
    duplicate_flags=selected.duplicated(COLS)
    dup_ids=set(selected.loc[duplicate_flags,'source_row_id'])
    duplicate_pence=int(reporting.loc[reporting.source_row_id.isin(dup_ids),'amount_pence'].sum())
    rules=[{'rule':'overlap_superseded_by_second_sheet','rows':audit['overlap_rows_excluded']}]+[{'rule':str(k),'rows':int(v)} for k,v in reasons.value_counts().items()]
    quality={'rules':rules,'missing_customer_rows':int(raw['Customer ID'].isna().sum()),'missing_customer_share':float(raw['Customer ID'].isna().mean()),
        'exact_duplicate_rows':audit['selected_exact_duplicates'],'duplicate_net_sensitivity_pence':duplicate_pence,
        'monthly':records(frames['quality_monthly']),'ownership_audit':audit,'order_key_audit':order_audit,
        'reporting_missing_customer_rows':int(reporting.customer_id.isna().sum()),'excluded_row_policy':'rules are mutually exclusive; accepted rule is retained source rows',
        'duplicate_scope':'date-ownership-selected source before quality filtering; raw combined duplicates also reported in ownership audit'}
    country=frames['country_month'].groupby('country').net_pence.sum().sort_values(ascending=False)
    a=frames['products'][frames['products'].abc.eq('A')]
    insights=[{'title':'Концентрация географии','value':str(country.index[0]),'interpretation':f'На крупнейшую страну приходится {country.iloc[0]/totals["net_pence"]:.1%} оборота после отмен за 24 месяца.','action':'Сравнивать основной рынок и остальные страны отдельно; общий тренд не переносить на каждую страну.'},
      {'title':'Концентрация ассортимента','value':f'{len(a)} кодов A','interpretation':f'Класс A формирует {a.gross_share.sum():.1%} положительного оборота. Включены сервисные и нестандартные коды.','action':'Перед ассортиментными решениями отделить услуги и дополнить данные себестоимостью и остатками; прибыль и дефицит не установлены.'},
      {'title':'Перекрытие исходных листов','value':f'{audit["overlap_rows_excluded"]} строк','interpretation':'Период 1–9 декабря 2010 присутствует на обоих листах. Проверено совпадение мультимножеств строк; каждый календарный период имеет одного владельца.','action':'Не объединять ежегодные выгрузки без проверки перекрытия; хранить происхождение каждой строки.'}]
    dashboard={'meta':{'source_rows':len(raw),'accepted_rows':len(d),'excluded_rows':len(raw)-len(d),'reporting_rows':len(reporting),
      'source_sha256':XLSX_SHA,'source_zip_sha256':ZIP_SHA,'period_start':START,'period_end':'2011-11-30','currency':'GBP','source_url':'https://doi.org/10.24432/C5CG6D','months':MONTHS,'countries':sorted(frames['country_month'].country.unique().tolist()),'money_policy':'Decimal line amount rounded half-even to integer pence','source_ownership_cutoff':CUT},
      'totals':totals,'monthly':records(frames['monthly']),'country_month':records(frames['country_month']),'products':records(frames['products']),'cohorts':records(frames['cohorts']),
      'quality':quality,'checks':{'passed':len(checks)+fixtures,'failed':0,'reconciliations':len(checks),'fixture_tests':fixtures},'insights':insights}
    for name,frame in frames.items():frame.to_csv(out/(name+'.csv'),index=False,encoding='utf-8')
    write_json(out/'dashboard.json',dashboard)
    write_json(out/'quality.json',quality)
    write_json(out/'validation.json',{'performed_at_utc':datetime.now(timezone.utc).isoformat(),'source_sha256':XLSX_SHA,'source_zip_sha256':ZIP_SHA,'warehouse_sha256':digest(ROOT/'data/warehouse.sqlite'),
      'passed':len(checks)+fixtures,'failed':0,'reconciliation_checks':checks,'fixture_tests_passed':fixtures,'fixture_file':'tests/test_engine.py',
      'runtime':{'python':sys.version.split()[0],'pandas':pd.__version__,'numpy':np.__version__,'sqlite':sqlite3.sqlite_version}})
    print(json.dumps({'totals':totals,'checks':dashboard['checks'],'source_ownership':audit,'order_audit':order_audit},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
