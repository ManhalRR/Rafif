"""Customer analytics on UCI Online Retail. No customer-level exports are produced.

python run.py --input "../data/Online Retail.xlsx"
SQL features and all outputs are regenerated; the source is never modified.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sqlite3
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SHA256 = '43465a06f2ccf7c8b5bd2892bc7defb52f97487934fe93b16ae4c3936424676d'
PARAMS = dict(history_start='2010-12-01', snapshot='2011-10-01', holdout_end='2011-12-01')
LABELS = {
    'loyal_high_value': 'Ценные регулярные',
    'active_repeat': 'Активные повторные',
    'recent_single': 'Недавняя единственная покупка',
    'at_risk_repeat': 'Повторные с паузой >90 дней',
    'other_buyers': 'Остальные покупатели',
}
checks = []


def check(name, condition):
    if not bool(condition):
        raise AssertionError(name)
    checks.append({'check': name, 'passed': True})


def prepare(raw):
    d = raw.rename(columns={'InvoiceNo': 'invoice_no', 'InvoiceDate': 'invoice_date',
                            'Quantity': 'quantity', 'UnitPrice': 'unit_price',
                            'CustomerID': 'customer_id'}).copy()
    d['invoice_no'] = d.invoice_no.astype(str).str.strip()
    d['invoice_date'] = pd.to_datetime(d.invoice_date, errors='coerce')
    cancel = d.invoice_no.str.upper().str.startswith('C')
    valid = (d.invoice_date.notna() & d.unit_price.gt(0) &
             ((d.quantity.gt(0) & ~cancel) | (d.quantity.lt(0) & cancel)))
    d = d.loc[valid].copy()
    d['amount_pence'] = np.rint(d.quantity * d.unit_price * 100).astype('int64')
    d['customer_id'] = d.customer_id.astype('Int64')
    return d


def features_sql(d):
    db = d[['invoice_no', 'invoice_date', 'customer_id', 'amount_pence']].copy()
    db['invoice_date'] = db.invoice_date.dt.strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect(':memory:') as conn:
        db.to_sql('transactions', conn, index=False)
        conn.execute('CREATE INDEX idx_customer_date ON transactions(customer_id, invoice_date)')
        return pd.read_sql_query((ROOT/'segmentation.sql').read_text(encoding='utf-8'), conn, params=PARAMS)


def assign_segment(r, f, m):
    if r <= 30 and f >= 5 and m >= 100000:
        return 'loyal_high_value'
    if r > 90 and f >= 3:
        return 'at_risk_repeat'
    if r <= 30 and f == 1:
        return 'recent_single'
    if r <= 60 and f >= 2:
        return 'active_repeat'
    return 'other_buyers'


def features_pandas(d):
    history = d[d.customer_id.notna() & d.invoice_date.ge(PARAMS['history_start']) &
                d.invoice_date.lt(PARAMS['snapshot'])]
    pos = history[history.amount_pence.gt(0)]
    f = pos.groupby('customer_id').agg(last_date=('invoice_date', 'max'), frequency=('invoice_no', 'nunique'))
    f['recency_days'] = (pd.Timestamp(PARAMS['snapshot']) - f.last_date.dt.normalize()).dt.days
    f['monetary_pence'] = history.groupby('customer_id').amount_pence.sum()
    f['segment'] = [assign_segment(r, n, m) for r, n, m in zip(f.recency_days, f.frequency, f.monetary_pence)]
    future = d[d.customer_id.notna() & d.invoice_date.ge(PARAMS['snapshot']) & d.invoice_date.lt(PARAMS['holdout_end'])]
    f['future_orders'] = future[future.amount_pence.gt(0)].groupby('customer_id').invoice_no.nunique()
    f['future_gross_pence'] = future[future.amount_pence.gt(0)].groupby('customer_id').amount_pence.sum()
    f['future_cancel_pence'] = -future[future.amount_pence.lt(0)].groupby('customer_id').amount_pence.sum()
    f['future_net_pence'] = future.groupby('customer_id').amount_pence.sum()
    f = f.drop(columns='last_date').fillna(0).reset_index().sort_values('customer_id')
    return f


def wilson(x, n):
    if n <= 0 or not 0 <= x <= n:
        raise ValueError('Wilson interval requires n > 0 and 0 <= x <= n')
    z = 1.959963984540054
    p = x/n
    a = 1 + z*z/n
    c = (p + z*z/(2*n))/a
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/a
    # Exact endpoints avoid floating-point underflow at 0/n and n/n.
    return [0.0 if x == 0 else max(0.0,c-h), 1.0 if x == n else min(1.0,c+h)]


def aggregate(f):
    rows = []
    for key in LABELS:
        g = f[f.segment.eq(key)]
        n = len(g)
        if not n:
            continue
        returning = int(g.future_orders.gt(0).sum())
        ci = wilson(returning, n)
        rows.append(dict(segment=key, label=LABELS[key], customers=n, share=n/len(f),
                         returning=returning, return_rate=returning/n, ci_low=ci[0], ci_high=ci[1],
                         history_net_gbp=int(g.monetary_pence.sum())/100,
                         future_orders=int(g.future_orders.sum()),
                         future_gross_gbp=int(g.future_gross_pence.sum())/100,
                         future_cancellations_gbp=int(g.future_cancel_pence.sum())/100,
                         future_net_gbp=int(g.future_net_pence.sum())/100,
                         future_net_per_customer_gbp=int(g.future_net_pence.sum())/100/n,
                         median_recency_days=float(g.recency_days.median()),
                         median_orders=float(g.frequency.median())))
    return rows


def fixture_tests():
    rows = [
        ('1', '2011-09-01 12:00:00', 1, 100, 1),
        ('2', '2011-09-30 23:59:59', 1, 200, 1),
        ('3', '2011-10-01 00:00:00', 1, 300, 1),
        ('C4', '2011-11-01', -1, 50, 1),
        ('5', '2011-12-01', 1, 9999, 1),
        ('6', '2011-09-30', 1, 20, 2),
        ('C7', '2011-11-01', -1, 50, 2),
        ('8', '2011-10-01', 1, 10, 3),
        ('C9', '2011-09-01', -1, 20, 4),
        ('10', '2011-09-20', 1, 10, None),
        ('11', '2011-09-20', 1, 0, 5),
        ('C12', '2011-09-20', 1, 10, 6),
        ('13', '2011-09-20', 1, 15, 7),
    ]
    raw = pd.DataFrame(rows, columns=['InvoiceNo', 'InvoiceDate', 'Quantity', 'UnitPrice', 'CustomerID'])
    # pandas mixed strings are explicitly normalized to avoid fixture parser ambiguity.
    raw['InvoiceDate'] = pd.to_datetime(raw.InvoiceDate, format='mixed')
    cleaned = prepare(raw)
    f = features_sql(cleaned).set_index('customer_id')
    p = features_pandas(cleaned).set_index('customer_id')
    check('Fixture: SQL/pandas agree on mixed edge cases', all(f[c].tolist() == p[c].tolist() for c in f.columns))
    check('Fixture: future-only and cancellation-only clients excluded', set(f.index) == {1, 2, 7})
    check('Fixture: R/F use only dates before snapshot', int(f.loc[1, 'frequency']) == 2 and int(f.loc[1, 'recency_days']) == 1)
    check('Fixture: October 1 included, December 1 excluded', int(f.loc[1, 'future_orders']) == 1)
    check('Fixture: signed cancellations reduce net without creating a purchase', int(f.loc[1, 'future_net_pence']) == 25000 and int(f.loc[2, 'future_orders']) == 0 and int(f.loc[2, 'future_net_pence']) == -5000)
    check('Fixture: no later activity gives zero purchases, not a missing customer', int(f.loc[7, 'future_orders']) == 0 and int(f.loc[7, 'future_net_pence']) == 0)
    for r, n, m, expected in [(30,5,100000,'loyal_high_value'), (31,5,100000,'active_repeat'),
        (30,5,99999,'active_repeat'), (90,3,100000,'other_buyers'), (91,3,100000,'at_risk_repeat'),
        (30,1,100,'recent_single'), (31,1,100,'other_buyers'), (60,2,100,'active_repeat'),
        (61,2,100,'other_buyers')]:
        check(f'Fixture: segment boundary R={r}, F={n}, M={m}', assign_segment(r,n,m) == expected)
    for x in [0,10]:
        lo, hi = wilson(x,10)
        check(f'Fixture: Wilson interval handles {x}/10', -1e-12 <= lo <= x/10 <= hi <= 1+1e-12)


def json_save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def build_report(summary, segments, out):
    from report import render
    (out.parent/'index.html').write_text(render(summary, segments), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT.parent/'data'/'Online Retail.xlsx')
    parser.add_argument('--output', type=Path, default=ROOT/'results')
    parser.add_argument('--tests-only', action='store_true', help='Run small edge-case fixtures without loading XLSX')
    args = parser.parse_args()
    if args.tests_only:
        fixture_tests()
        print(json.dumps({'passed':len(checks), 'checks':checks}, ensure_ascii=False, indent=2))
        return
    if not args.input.exists():
        parser.error('Source missing. Download UCI Online Retail.xlsx; see README.md. No substitute data are generated.')
    sha = hashlib.sha256(args.input.read_bytes()).hexdigest()
    check('Exact documented UCI source SHA-256', sha == SHA256)
    raw = pd.read_excel(args.input, engine='openpyxl')
    d = prepare(raw)
    check('Source row count', len(raw) == 541909)
    f = features_sql(d)
    p = features_pandas(d)
    check('Unique customer unit', f.customer_id.is_unique)
    check('One and only one rule-based segment per customer', f.segment.isin(LABELS).all())
    check('Recency strictly positive at snapshot', f.recency_days.ge(1).all())
    check('SQL/pandas customer universe', f.customer_id.tolist() == p.customer_id.tolist())
    for col in ['recency_days','frequency','monetary_pence','future_orders','future_gross_pence','future_cancel_pence','future_net_pence','segment']:
        check(f'Independent SQL/pandas reconciliation: {col}', f[col].tolist() == p[col].tolist())
    past = d[d.invoice_date.lt(PARAMS['snapshot'])]
    past_f = features_sql(past)
    feature_cols = ['customer_id','recency_days','frequency','monetary_pence','segment']
    check('Leakage test: removing all holdout rows leaves features unchanged', f[feature_cols].equals(past_f[feature_cols]))
    future = d[d.invoice_date.ge(PARAMS['snapshot']) & d.invoice_date.lt(PARAMS['holdout_end'])]
    existing = future[future.customer_id.isin(f.customer_id)]
    check('Existing-customer holdout net reconciles to transactions', int(f.future_net_pence.sum()) == int(existing.amount_pence.sum()))
    check('Holdout gross less cancellations equals net per client', (f.future_gross_pence-f.future_cancel_pence).eq(f.future_net_pence).all())
    check('History orders each belong to one customer', past[past.customer_id.notna() & past.amount_pence.gt(0)].groupby('invoice_no').customer_id.nunique().max() == 1)
    segments = aggregate(f)
    check('Segment sizes reconcile to customer universe', sum(s['customers'] for s in segments) == len(f))
    check('Segment returning clients reconcile', sum(s['returning'] for s in segments) == int(f.future_orders.gt(0).sum()))
    check('Segment future net reconciles', round(sum(s['future_net_gbp'] for s in segments)*100) == int(f.future_net_pence.sum()))
    # Sensitivity analysis, not automatic deduplication: source has no unique line ID.
    dedup_f = features_sql(prepare(raw.drop_duplicates()))
    dedup_compare = f[['customer_id','segment']].merge(dedup_f[['customer_id','segment']], on='customer_id', suffixes=('_retained','_dedup'))
    check('Duplicate sensitivity preserves client universe', len(dedup_compare) == len(f))
    fixture_tests()
    positive_future = future[future.amount_pence.gt(0)]
    known_future = future[future.customer_id.notna()]
    omitted_known = known_future[~known_future.customer_id.isin(f.customer_id)]
    unknown = future[future.customer_id.isna()]
    check('Coverage bridge reconciles all holdout net', int(existing.amount_pence.sum()+omitted_known.amount_pence.sum()+unknown.amount_pence.sum()) == int(future.amount_pence.sum()))
    summary = {
        'project':'Customer Analytics / CRM segmentation', 'source':'UCI Online Retail',
        'source_sha256':sha, 'dates':PARAMS,
        'source_rows':len(raw), 'accepted_rows':len(d), 'excluded_rows':len(raw)-len(d),
        'exact_duplicate_rows_retained':int(raw.duplicated().sum()),
        'customers':len(f), 'returning_customers':int(f.future_orders.gt(0).sum()),
        'return_rate':float(f.future_orders.gt(0).mean()),
        'history_net_gbp':int(f.monetary_pence.sum())/100,
        'holdout_existing_net_gbp':int(existing.amount_pence.sum())/100,
        'holdout_other_known_net_gbp':int(omitted_known.amount_pence.sum())/100,
        'holdout_unknown_net_gbp':int(unknown.amount_pence.sum())/100,
        'holdout_all_net_gbp':int(future.amount_pence.sum())/100,
        'holdout_missing_id_positive_sales_share':float(positive_future.loc[positive_future.customer_id.isna(),'amount_pence'].sum()/positive_future.amount_pence.sum()),
        'dedup_sensitivity':{'customers_with_changed_segment':int(dedup_compare.segment_retained.ne(dedup_compare.segment_dedup).sum()),
            'existing_holdout_net_delta_gbp':int(f.future_net_pence.sum()-dedup_f.future_net_pence.sum())/100},
        'checks_passed':len(checks),
        'runtime':{'python':sys.version.split()[0], 'pandas':pd.__version__, 'numpy':np.__version__, 'sqlite':sqlite3.sqlite_version},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    json_save(args.output/'summary.json', summary)
    json_save(args.output/'segments.json', segments)
    json_save(args.output/'validation.json', {'passed':len(checks), 'failed':0, 'checks':checks})
    pd.DataFrame(segments).to_csv(args.output/'segments.csv', index=False, encoding='utf-8-sig')
    build_report(summary, segments, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
