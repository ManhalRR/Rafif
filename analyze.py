"""Reproducible retail analytics and A/B experiment analysis.

Run: python analyze.py
Dependencies: pandas, numpy, openpyxl. SQL is SQLite, included in Python.
The actual UCI source is fetched only when the workbook is missing.
"""
from pathlib import Path
import hashlib, json, math, sqlite3, zipfile, urllib.request
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; OUT=ROOT/'results'
DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
SOURCE='https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip'
SOURCE_SHA256='43465a06f2ccf7c8b5bd2892bc7defb52f97487934fe93b16ae4c3936424676d'
START='2011-01-01'; END='2011-12-01'
checks=[]

def check(name, condition):
    if not bool(condition): raise AssertionError(name)
    checks.append({'check':name,'passed':True})

def dump(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def query(conn,name):
    return pd.read_sql_query((ROOT/'sql'/name).read_text(encoding='utf-8'),conn)

def wilson(x,n):
    z=1.959963984540054; p=x/n; den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return center-half,center+half

def main():
    src=DATA/'Online Retail.xlsx'
    if not src.exists():
        urllib.request.urlretrieve(SOURCE,DATA/'online_retail.zip')
        with zipfile.ZipFile(DATA/'online_retail.zip') as z:
            src.write_bytes(z.read(next(n for n in z.namelist() if n.endswith('.xlsx'))))
    check('UCI source checksum matches the documented workbook',
          hashlib.sha256(src.read_bytes()).hexdigest()==SOURCE_SHA256)
    raw=pd.read_excel(src,engine='openpyxl')
    duplicate=raw.duplicated(keep='first')
    df=raw.rename(columns={'InvoiceNo':'invoice_no','StockCode':'stock_code','Description':'description',
        'Quantity':'quantity','InvoiceDate':'invoice_date','UnitPrice':'unit_price','CustomerID':'customer_id','Country':'country'}).copy()
    df['invoice_no']=df.invoice_no.astype(str)
    df['invoice_date']=pd.to_datetime(df.invoice_date,errors='coerce')
    cancellation=df.invoice_no.str.upper().str.startswith('C')
    eligible=df.invoice_date.notna() & df.unit_price.gt(0) & ((df.quantity.gt(0)&~cancellation)|(df.quantity.lt(0)&cancellation))
    df['amount_pence']=np.rint(df.quantity*df.unit_price*100).astype('int64')
    df['exact_duplicate_flag']=duplicate
    clean=df.loc[eligible].copy()
    scope=clean[(clean.invoice_date>=START)&(clean.invoice_date<END)].copy()
    check('UCI workbook has expected 541909 source rows',len(raw)==541909)
    check('Accepted sales are positive and cancellations negative',((clean.quantity>0)==~clean.invoice_no.str.upper().str.startswith('C')).all())
    check('Each sales invoice belongs to a single country',scope[scope.quantity>0].groupby('invoice_no').country.nunique().max()==1)
    conn=sqlite3.connect(DATA/'portfolio.sqlite')
    db=clean.copy();db['invoice_date']=db.invoice_date.dt.strftime('%Y-%m-%d %H:%M:%S')
    db['customer_id']=db.customer_id.astype('Int64').astype(object).where(db.customer_id.notna(),None)
    db.to_sql('transactions',conn,index=False,if_exists='replace',chunksize=10000)
    conn.execute('CREATE INDEX IF NOT EXISTS tx_date ON transactions(invoice_date)')
    conn.execute('CREATE INDEX IF NOT EXISTS tx_customer ON transactions(customer_id,invoice_date)')
    monthly=query(conn,'01_monthly_sales.sql')
    country_month=query(conn,'02_country_month.sql')
    cohorts=query(conn,'03_cohort_retention.sql')
    check('11 complete reporting months',len(monthly)==11)
    check('SQL/Pandas monetary reconciliation',int(monthly.net_pence.sum())==int(scope.amount_pence.sum()))
    check('Gross less cancellations equals net',((monthly.gross_pence-monthly.cancellations_pence)==monthly.net_pence).all())
    check('Country aggregation reconciles to total',int(country_month.net_pence.sum())==int(monthly.net_pence.sum()))
    check('Cohort retention bounded from zero to one',cohorts.retention.dropna().between(0,1).all())
    check('Month zero retention equals one',cohorts.loc[cohorts.age==0,'retention'].eq(1).all())
    check('November M1 is censored, not zero',cohorts[(cohorts.cohort=='2011-11')&(cohorts.age==1)].retention.isna().all())
    # Independent set-based validation of SQL M1 retention.
    known=clean[(clean.quantity>0)&clean.customer_id.notna()&(clean.invoice_date<END)].copy()
    known['month']=known.invoice_date.dt.to_period('M')
    first=known.groupby('customer_id').month.min()
    for row in cohorts[(cohorts.age==1)&cohorts.retention.notna()].itertuples():
        period=pd.Period(row.cohort,'M'); base=set(first[first==period].index)
        following=set(known.loc[known.month==period+1,'customer_id'])
        check('Independent M1 cohort '+row.cohort,len(base&following)==int(row.active_customers))
    gross=int(monthly.gross_pence.sum()); cancel=int(monthly.cancellations_pence.sum()); net=gross-cancel
    country=country_month.groupby('country',as_index=False)[['orders','gross_pence','cancellations_pence','net_pence']].sum().sort_values('net_pence',ascending=False)
    m1=cohorts[(cohorts.age==1)&cohorts.cohort.ge('2011-01')&cohorts.retention.notna()]
    totals={'period':'January-November 2011','orders':int(monthly.orders.sum()),'gross_gbp':gross/100,
      'cancellations_gbp':cancel/100,'net_gbp':net/100,'cancellation_value_ratio':cancel/gross,
      'uk_net_share':float(country.loc[country.country=='United Kingdom','net_pence'].iloc[0]/net),
      'm1_weighted_retention':float(m1.active_customers.sum()/m1.cohort_size.sum()),
      'm1_cohorts':'January-October 2011; first observed purchase',
      'peak_month':str(monthly.loc[monthly.net_pence.idxmax(),'month']),
      'peak_net_gbp':int(monthly.net_pence.max())/100}
    quality={'source_rows':len(raw),'accepted_rows_all_dates':len(clean),'reporting_rows':len(scope),
      'excluded_rows':int((~eligible).sum()),'missing_customer_id_source':int(raw.CustomerID.isna().sum()),
      'missing_customer_id_share_source':float(raw.CustomerID.isna().mean()),
      'exact_duplicate_rows':int(duplicate.sum()),'exact_duplicates_policy':'Retained: no reliable source line identifier; equality alone does not prove an error.',
      'duplicate_sensitivity_net_gbp':float(scope.loc[scope.exact_duplicate_flag,'amount_pence'].sum()/100),
      'missing_customer_id_sales_share':float(scope.loc[(scope.quantity>0)&scope.customer_id.isna(),'amount_pence'].sum()/gross),
      'no_positive_price_rows':int(df.unit_price.le(0).sum()),'workbook_sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
    monthly.to_csv(OUT/'retail_monthly.csv',index=False)
    country_month.to_csv(OUT/'retail_country_month.csv',index=False)
    cohorts.to_csv(OUT/'retail_cohorts.csv',index=False)
    country.to_csv(OUT/'retail_countries.csv',index=False)
    dump('retail_summary.json',{'totals':totals,'quality':quality})

    # Synthetic randomized experiment. The seed and generator are fixed, not selected by p-value.
    rng=np.random.default_rng(20261027); n=24000
    variant=rng.choice(['A','B'],size=n,p=[.5,.5]); device=rng.choice(['mobile','desktop'],size=n,p=[.65,.35])
    probabilities=np.where(device=='mobile',.10,.13)+np.where(variant=='B',.015,0)
    converted=rng.binomial(1,probabilities)
    revenue=np.rint(converted*rng.lognormal(mean=8.5,sigma=.65,size=n)*100).astype('int64')
    assigned=pd.Timestamp('2026-08-01')+pd.to_timedelta(rng.integers(0,28,size=n),unit='D')
    conversion_date=assigned+pd.to_timedelta(rng.integers(0,7,size=n),unit='D')
    experiment=pd.DataFrame({'user_id':np.arange(1,n+1),'variant':variant,'device':device,
      'assigned_date':assigned.strftime('%Y-%m-%d'),'converted':converted,'revenue_kopecks':revenue,
      'conversion_date':np.where(converted==1,conversion_date.strftime('%Y-%m-%d'),None)})
    experiment.to_csv(DATA/'synthetic_ab.csv',index=False)
    experiment.to_sql('experiment',conn,if_exists='replace',index=False)
    groups=query(conn,'04_experiment.sql')
    check('Experiment has unique randomized participants',experiment.user_id.is_unique and len(experiment)==24000)
    check('No revenue for non-converters',experiment.loc[experiment.converted==0,'revenue_kopecks'].eq(0).all())
    check('Complete observation window',pd.to_datetime(experiment.assigned_date).max()+pd.Timedelta(days=7)<pd.Timestamp('2026-09-05'))
    check('SQL/Pandas experiment counts match',int(groups.conversions.sum())==int(experiment.converted.sum()))
    a,b=groups.iloc[0],groups.iloc[1]; na,nb=int(a.users),int(b.users); xa,xb=int(a.conversions),int(b.conversions)
    pa,pb=xa/na,xb/nb; delta=pb-pa
    pooled=(xa+xb)/(na+nb); se=math.sqrt(pooled*(1-pooled)*(1/na+1/nb)); z=delta/se
    pvalue=math.erfc(abs(z)/math.sqrt(2))
    la,ua=wilson(xa,na);lb,ub=wilson(xb,nb)
    ci=[delta-math.sqrt((pb-lb)**2+(ua-pa)**2),delta+math.sqrt((ub-pb)**2+(pa-la)**2)]
    chi=((na-n/2)**2+(nb-n/2)**2)/(n/2);srm_p=math.erfc(math.sqrt(chi/2))
    check('Conversion confidence interval contains point estimate',ci[0]<=delta<=ci[1])
    check('Nonnegative p-values bounded by one',0<=pvalue<=1 and 0<=srm_p<=1)
    rpa=experiment.loc[experiment.variant=='A','revenue_kopecks'].to_numpy()/100
    rpb=experiment.loc[experiment.variant=='B','revenue_kopecks'].to_numpy()/100
    rpu_delta=float(rpb.mean()-rpa.mean());rpu_se=math.sqrt(rpa.var(ddof=1)/na+rpb.var(ddof=1)/nb)
    ab={'synthetic':True,'seed':20261027,'primary_metric':'7-day conversion, intention-to-treat',
      'analysis_cutoff':'2026-09-05','groups':groups.to_dict(orient='records'),'delta':delta,'relative_lift':delta/pa,
      'difference_ci95_newcombe':ci,'p_value_two_sided':pvalue,'srm_p_value':srm_p,
      'rpu_delta_rub':rpu_delta,'rpu_ci95_normal':[rpu_delta-1.95996398454*rpu_se,rpu_delta+1.95996398454*rpu_se],
      'decision':'B improves conversion in this simulation' if ci[0]>0 else 'No clear conversion improvement in this simulation',
      'limitations':'Synthetic data. Fixed-horizon analysis, no repeated peeking. No company impact or deployment claim. RPU is exploratory.'}
    groups.to_csv(OUT/'ab_groups.csv',index=False)
    dump('ab_summary.json',ab)
    dump('validation.json',{'checks':checks,'total_passed':len(checks)})
    payload={'retail':{'totals':totals,'quality':quality,'monthly':monthly.to_dict(orient='records'),
       'country_month':country_month.to_dict(orient='records'),'countries':country.to_dict(orient='records'),
       'cohorts':json.loads(cohorts.to_json(orient='records'))},'ab':ab}
    # Pandas uses NaN for the first MoM value; JSON null is explicit.
    payload['retail']['monthly']=json.loads(monthly.to_json(orient='records'))
    dump('dashboard_data.json',payload)
    conn.close()
    print(json.dumps({'retail':totals,'quality':quality,'ab':ab,'checks':len(checks)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
