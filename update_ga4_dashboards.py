#!/usr/bin/env python3
import json
import os
import re
import subprocess
from pathlib import Path

WORKSPACE = Path('/Users/lucfaucheux/.openclaw/workspace')
DASH_DIR = WORKSPACE / 'ga4-dashboards'
GA4_QUERY = WORKSPACE / 'ga4-query.sh'


def parse_totals(csv: str):
    parts = csv.strip().split(',')
    return {
        'sessions': int(parts[0]),
        'users': int(parts[1]),
        'newUsers': int(parts[2]),
        'pageviews': int(parts[3]),
        'pagesPerSession': float(parts[4]),
    }


def parse_sources(json_str: str):
    data = json.loads(json_str)
    return [
        {
            'source': r['dimensionValues'][0]['value'],
            'medium': r['dimensionValues'][1]['value'],
            'sessions': int(r['metricValues'][0]['value']),
            'users': int(r['metricValues'][1]['value']),
        }
        for r in data.get('rows', [])
    ]


def parse_mobile_pct(json_str: str):
    data = json.loads(json_str)
    rows = data.get('rows', [])
    total = sum(int(r['metricValues'][0]['value']) for r in rows)
    if not total:
        return 0.0
    for r in rows:
        if r['dimensionValues'][0]['value'] == 'mobile':
            return round(int(r['metricValues'][0]['value']) / total * 100, 1)
    return 0.0


def run_report(email: str, property_id: str, start: str, end: str):
    raw = subprocess.check_output(['bash', str(GA4_QUERY), email, 'report', property_id, start, end], text=True)
    return json.loads(raw)


def totals_from_report(report: dict):
    totals = {'sessions': 0, 'users': 0, 'newUsers': 0, 'pageviews': 0}
    for row in report.get('rows', []):
        totals['sessions'] += int(row['metricValues'][0]['value'])
        totals['users'] += int(row['metricValues'][1]['value'])
        totals['newUsers'] += int(row['metricValues'][2]['value'])
        totals['pageviews'] += int(row['metricValues'][3]['value'])
    totals['pagesPerSession'] = round(totals['pageviews'] / totals['sessions'], 2) if totals['sessions'] else 0.0
    return totals


def daily_from_report(report: dict):
    pairs = []
    for row in report.get('rows', []):
        date_str = row['dimensionValues'][0]['value']
        pairs.append((date_str, int(row['metricValues'][0]['value'])))
    pairs.sort(key=lambda x: x[0])
    labels = [f"{date_str[4:6]}/{date_str[6:8]}" for date_str, _ in pairs]
    sessions = [value for _, value in pairs]
    return {'labels': labels, 'sessions': sessions}


def fetch_period(email: str, property_id: str, start: str, end: str, label: str):
    report = run_report(email, property_id, start, end)
    totals = totals_from_report(report)
    daily = daily_from_report(report)
    return {
        'label': label,
        'sessions': totals['sessions'],
        'users': totals['users'],
        'newUsers': totals['newUsers'],
        'pageviews': totals['pageviews'],
        'pagesPerSession': totals['pagesPerSession'],
        'daily': daily,
    }


def js_obj(value):
    return json.dumps(value, separators=(',', ':'))


def patch_dashboard(path: Path, datasets: dict, sources: list, mobile_pct: float, updated_label: str):
    html = path.read_text()
    data_js = '{\n' + ',\n'.join(f"    {k}: {js_obj(v)}" for k, v in datasets.items()) + '\n}'
    sources_js = js_obj(sources)
    html = re.sub(r"const DATA\s*=\s*\{[\s\S]*?\};\s*\n\s*const SOURCES\s*=\s*\[[\s\S]*?\];", f"const DATA = {data_js};\n\nconst SOURCES = {sources_js};", html, count=1)
    html = re.sub(r"Mobile Traffic',\s*val:\s*'[^']+',\s*raw:\s*[0-9.]+", f"Mobile Traffic',val:'{mobile_pct}%',raw:{mobile_pct}", html)
    html = re.sub(r"Mobile Traffic',\s* val: '\s*[^']+',\s* raw: [0-9.]+", f"Mobile Traffic', val: '{mobile_pct}%', raw: {mobile_pct}", html)
    # Keep visible refresh stamps current on every refresh (header badge + footer).
    html = re.sub(
        r'(id="dataUpdated">Updated on )(?:[A-Za-z]+ \d{1,2}, \d{4}|[A-Za-z]+ \d{4})',
        rf'\1{updated_label}',
        html,
        count=1,
    )
    html = re.sub(
        r'(footer-right[\s\S]{0,400}?Updated\s+)(?:[A-Za-z]+ \d{1,2}, \d{4}|[A-Za-z]+ \d{4})',
        rf'\1{updated_label}',
        html,
        count=1,
    )
    # Fallback: any remaining plain "Updated MONTH ..." stamps in footers.
    html = re.sub(
        r'(Updated\s+)(?:[A-Za-z]+ \d{1,2}, \d{4}|[A-Za-z]+ \d{4})',
        rf'\1{updated_label}',
        html,
    )
    path.write_text(html)


def build_store(email: str, property_id: str):
    return {
        'q1_2026': fetch_period(email, property_id, '90daysAgo', 'today', 'Last 90 Days'),
        'prev90': fetch_period(email, property_id, '180daysAgo', '91daysAgo', 'Previous 90 Days'),
        'yoy90': fetch_period(email, property_id, '455daysAgo', '366daysAgo', 'Same 90 Days Last Year'),
        'last60': fetch_period(email, property_id, '60daysAgo', 'today', 'Last 60 Days'),
        'prev60': fetch_period(email, property_id, '120daysAgo', '61daysAgo', 'Previous 60 Days'),
        'yoy60': fetch_period(email, property_id, '425daysAgo', '366daysAgo', 'Same 60 Days Last Year'),
        'last30': fetch_period(email, property_id, '30daysAgo', 'today', 'Last 30 Days'),
        'prev30': fetch_period(email, property_id, '60daysAgo', '31daysAgo', 'Previous 30 Days'),
        'yoy30': fetch_period(email, property_id, '395daysAgo', '366daysAgo', 'Same 30 Days Last Year'),
    }


def main():
    bh_sources = parse_sources(os.environ['BH_SOURCES'])
    bh_mobile = parse_mobile_pct(os.environ['BH_DEVICES'])
    audi_sources = parse_sources(os.environ['AUDI_SOURCES'])
    audi_mobile = parse_mobile_pct(os.environ['AUDI_DEVICES'])
    jackson_sources = parse_sources(os.environ['JACKSON_SOURCES'])
    jackson_mobile = parse_mobile_pct(os.environ['JACKSON_DEVICES'])

    bh_data = build_store(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'])
    audi_data = build_store(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'])
    jackson_data = build_store(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'])

    from datetime import datetime

    today = os.environ['TODAY']
    updated_label = datetime.strptime(today, '%Y-%m-%d').strftime('%B %-d, %Y')

    cache = {
        'updated': today,
        'brian_harris_bmw': {
            'q1_2026': {k: bh_data['q1_2026'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'q1_prev': {k: bh_data['yoy90'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'last30': {k: bh_data['last30'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'last60': {k: bh_data['last60'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'sources': bh_sources,
            'mobile_pct': bh_mobile,
        },
        'audi_baton_rouge': {
            'q1_2026': {k: audi_data['q1_2026'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'q1_prev': {k: audi_data['yoy90'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'last30': {k: audi_data['last30'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'last60': {k: audi_data['last60'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'sources': audi_sources,
            'mobile_pct': audi_mobile,
        },
        'bmw_jackson': {
            'q1_2026': {k: jackson_data['q1_2026'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'q1_prev': {k: jackson_data['yoy90'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'last30': {k: jackson_data['last30'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'last60': {k: jackson_data['last60'][k] for k in ('sessions', 'users', 'newUsers', 'pageviews', 'pagesPerSession')},
            'sources': jackson_sources,
            'mobile_pct': jackson_mobile,
        },
    }
    (DASH_DIR / 'ga4-data.json').write_text(json.dumps(cache, indent=2))

    patch_dashboard(DASH_DIR / 'brian-harris-bmw-dashboard.html', bh_data, bh_sources, bh_mobile, updated_label)
    patch_dashboard(DASH_DIR / 'audi-baton-rouge-dashboard.html', audi_data, audi_sources, audi_mobile, updated_label)
    patch_dashboard(DASH_DIR / 'bmw-jackson-dashboard.html', jackson_data, jackson_sources, jackson_mobile, updated_label)

    print('Data written to ga4-data.json and dashboard HTML files')
    print(f"BH BMW last30 vs prev30: {bh_data['last30']['sessions']:,} vs {bh_data['prev30']['sessions']:,}")
    print(f"Audi BR last30 vs prev30: {audi_data['last30']['sessions']:,} vs {audi_data['prev30']['sessions']:,}")
    print(f"BMW Jackson last30 vs prev30: {jackson_data['last30']['sessions']:,} vs {jackson_data['prev30']['sessions']:,}")


if __name__ == '__main__':
    main()
