"""Validate the public data/interface contract, not a substitute for browser QA."""
from pathlib import Path
import csv
import json
import math
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parent

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.paths = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ('href', 'src'):
            if attrs.get(key): self.paths.append(attrs[key])

def main():
    checks = []
    def check(name, condition):
        if not condition: raise AssertionError(name)
        checks.append(name)
    def load(path): return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))
    d, f, v = load('results/dashboard.json'), load('results/forecast.json'), load('results/validation.json')
    check('24 unique ordered complete months', len(d['meta']['months']) == 24 and d['meta']['months'] == sorted(set(d['meta']['months'])))
    check('Accepted/reporting/source scopes ordered', d['meta']['reporting_rows'] <= d['meta']['accepted_rows'] <= d['meta']['source_rows'])
    check('No failed core checks', d['checks']['failed'] == 0 and v['failed'] == 0)
    for key in ('gross_pence','cancel_pence','net_pence','orders'):
        check('Month/country/total contract '+key, sum(r[key] for r in d['monthly']) == sum(r[key] for r in d['country_month']) == d['totals'][key])
    for key in ('gross_pence','cancel_pence','net_pence'):
        check('Product/total monetary contract '+key, sum(r[key] for r in d['products']) == d['totals'][key])
    check('All product codes unique', len({p['stock_code'] for p in d['products']}) == len(d['products']))
    check('ABC labels valid', all(p['abc'] in 'ABC' and len(p['abc']) == 1 for p in d['products']))
    check('Future cohort cells kept as null', any(c['retention'] is None for c in d['cohorts']))
    check('24 cohort bases', len([c for c in d['cohorts'] if c['age'] == 0]) == 24)
    check('Forecast excludes partial December actual', f['forecast_month'] == '2011-12' and all(r['month'] < f['forecast_month'] for r in f['history']))
    check('Backtest has six future steps', len(f['backtest']) == 6 and all(r['train_through'] < r['month'] for r in f['backtest']))
    check('Three model outputs', len(f['models']) == 3 and f['recommended_id'] in {m['id'] for m in f['models']})
    def finite(node):
        if isinstance(node, float): return math.isfinite(node)
        if isinstance(node, dict): return all(finite(value) for value in node.values())
        if isinstance(node, list): return all(finite(value) for value in node)
        return True
    check('No NaN/Infinity in published payload', finite(d) and finite(f))
    allowed = {'monthly.csv','country_month.csv','products.csv','cohorts.csv','quality_monthly.csv','forecast_backtest.csv'}
    for path in (ROOT/'results').glob('*.csv'):
        check('Aggregate CSV allowlist '+path.name, path.name in allowed)
        with path.open(encoding='utf-8-sig', newline='') as file:
            fields = csv.DictReader(file).fieldnames or []
        check('No customer/invoice IDs in public CSV '+path.name, not ({x.lower() for x in fields} & {'customer_id','customerid','invoice','invoice_no','invoiceno','order_key','source_row_id'}))
    parser=Links(); parser.feed((ROOT/'index.html').read_text(encoding='utf-8'))
    local=[x.split('#')[0].split('?')[0] for x in parser.paths if not (':' in x or x.startswith('#') or x.startswith('../'))]
    check('All internal document/assets exist', all((ROOT/x).is_file() for x in local if x))
    check('Frontend assets present', all((ROOT/p).is_file() for p in ('app.js','style.css','README.md')))
    print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False,indent=2))

if __name__ == '__main__': main()
