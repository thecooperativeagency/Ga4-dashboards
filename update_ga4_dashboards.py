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


def ga4_daily(email: str, property_id: str, start: str, end: str):
    raw = subprocess.check_output(['bash', str(GA4_QUERY), email, 'report', property_id, start, end], text=True)
    payload = json.loads(raw)
    labels, sessions = [], []
    for row in payload.get('rows', []):
        date_str = row['dimensionValues'][0]['value']
        labels.append(f"{date_str[4:6]}/{date_str[6:8]}")
        sessions.append(int(row['metricValues'][0]['value']))
    return {'labels': labels, 'sessions': sessions}


def build_dataset(label: str, totals: dict, daily: dict):
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


def patch_dashboard(path: Path, datasets: dict, sources: list, mobile_pct: float):
    html = path.read_text()
    data_js = '{\n' + ',\n'.join(f"    {k}: {js_obj(v)}" for k, v in datasets.items()) + '\n}'
    sources_js = js_obj(sources)
    html = re.sub(r"const DATA\s*=\s*\{[\s\S]*?\};\s*\n\s*const SOURCES\s*=\s*\[[\s\S]*?\];", f"const DATA = {data_js};\n\nconst SOURCES = {sources_js};", html, count=1)
    html = re.sub(r"Mobile Traffic',\s*val:\s*'[^']+',\s*raw:\s*[0-9.]+", f"Mobile Traffic',val:'{mobile_pct}%',raw:{mobile_pct}", html)
    html = re.sub(r"Mobile Traffic',\s* val: '\s*[^']+',\s* raw: [0-9.]+", f"Mobile Traffic', val: '{mobile_pct}%', raw: {mobile_pct}", html)
    path.write_text(html)


def main():
    bh_q1 = parse_totals(os.environ['BH_Q1'])
    bh_prev = parse_totals(os.environ['BH_PREV'])
    bh_30 = parse_totals(os.environ['BH_30'])
    bh_60 = parse_totals(os.environ['BH_60'])
    bh_sources = parse_sources(os.environ['BH_SOURCES'])
    bh_mobile = parse_mobile_pct(os.environ['BH_DEVICES'])

    audi_q1 = parse_totals(os.environ['AUDI_Q1'])
    audi_prev = parse_totals(os.environ['AUDI_PREV'])
    audi_30 = parse_totals(os.environ['AUDI_30'])
    audi_60 = parse_totals(os.environ['AUDI_60'])
    audi_sources = parse_sources(os.environ['AUDI_SOURCES'])
    audi_mobile = parse_mobile_pct(os.environ['AUDI_DEVICES'])

    jackson_q1 = parse_totals(os.environ['JACKSON_Q1'])
    jackson_prev = parse_totals(os.environ['JACKSON_PREV'])
    jackson_30 = parse_totals(os.environ['JACKSON_30'])
    jackson_60 = parse_totals(os.environ['JACKSON_60'])
    jackson_sources = parse_sources(os.environ['JACKSON_SOURCES'])
    jackson_mobile = parse_mobile_pct(os.environ['JACKSON_DEVICES'])

    data = {
        'updated': os.environ['TODAY'],
        'brian_harris_bmw': {'q1_2026': bh_q1, 'q1_prev': bh_prev, 'last30': bh_30, 'last60': bh_60, 'sources': bh_sources, 'mobile_pct': bh_mobile},
        'audi_baton_rouge': {'q1_2026': audi_q1, 'q1_prev': audi_prev, 'last30': audi_30, 'last60': audi_60, 'sources': audi_sources, 'mobile_pct': audi_mobile},
        'bmw_jackson': {'q1_2026': jackson_q1, 'q1_prev': jackson_prev, 'last30': jackson_30, 'last60': jackson_60, 'sources': jackson_sources, 'mobile_pct': jackson_mobile},
    }
    (DASH_DIR / 'ga4-data.json').write_text(json.dumps(data, indent=2))

    store_defs = [
        {
            'file': 'brian-harris-bmw-dashboard.html',
            'email': os.environ['BH_BMW_EMAIL'],
            'property': os.environ['BH_BMW_PROPERTY'],
            'mobile': bh_mobile,
            'sources': bh_sources,
            'datasets': {
                'q1_2026': build_dataset('Last 90 Days', bh_q1, ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '90daysAgo', 'today')),
                'yoy90': build_dataset('Same 90 Days Last Year', bh_prev, ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '455daysAgo', '366daysAgo')),
                'prev90': build_dataset('Previous 90 Days', bh_prev, ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '180daysAgo', '91daysAgo')),
                'last30': build_dataset('Last 30 Days', bh_30, ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '30daysAgo', 'today')),
                'prev30': build_dataset('Previous 30 Days', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BH_BMW_EMAIL'], 'report', os.environ['BH_BMW_PROPERTY'], '60daysAgo', '31daysAgo'], text=True) and os.environ['BH_PREV']), ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '60daysAgo', '31daysAgo')),
                'yoy30': build_dataset('Same 30 Days Last Year', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BH_BMW_EMAIL'], 'report', os.environ['BH_BMW_PROPERTY'], '395daysAgo', '366daysAgo'], text=True) and os.environ['BH_PREV']), ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '395daysAgo', '366daysAgo')),
                'last60': build_dataset('Last 60 Days', bh_60, ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '60daysAgo', 'today')),
                'prev60': build_dataset('Previous 60 Days', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BH_BMW_EMAIL'], 'report', os.environ['BH_BMW_PROPERTY'], '120daysAgo', '61daysAgo'], text=True) and os.environ['BH_PREV']), ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '120daysAgo', '61daysAgo')),
                'yoy60': build_dataset('Same 60 Days Last Year', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BH_BMW_EMAIL'], 'report', os.environ['BH_BMW_PROPERTY'], '425daysAgo', '366daysAgo'], text=True) and os.environ['BH_PREV']), ga4_daily(os.environ['BH_BMW_EMAIL'], os.environ['BH_BMW_PROPERTY'], '425daysAgo', '366daysAgo')),
            }
        },
        {
            'file': 'audi-baton-rouge-dashboard.html',
            'email': os.environ['AUDI_BR_EMAIL'],
            'property': os.environ['AUDI_BR_PROPERTY'],
            'mobile': audi_mobile,
            'sources': audi_sources,
            'datasets': {
                'q1_2026': build_dataset('Last 90 Days', audi_q1, ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '90daysAgo', 'today')),
                'yoy90': build_dataset('Same 90 Days Last Year', audi_prev, ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '455daysAgo', '366daysAgo')),
                'prev90': build_dataset('Previous 90 Days', audi_prev, ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '180daysAgo', '91daysAgo')),
                'last30': build_dataset('Last 30 Days', audi_30, ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '30daysAgo', 'today')),
                'prev30': build_dataset('Previous 30 Days', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['AUDI_BR_EMAIL'], 'report', os.environ['AUDI_BR_PROPERTY'], '60daysAgo', '31daysAgo'], text=True) and os.environ['AUDI_PREV']), ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '60daysAgo', '31daysAgo')),
                'yoy30': build_dataset('Same 30 Days Last Year', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['AUDI_BR_EMAIL'], 'report', os.environ['AUDI_BR_PROPERTY'], '395daysAgo', '366daysAgo'], text=True) and os.environ['AUDI_PREV']), ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '395daysAgo', '366daysAgo')),
                'last60': build_dataset('Last 60 Days', audi_60, ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '60daysAgo', 'today')),
                'prev60': build_dataset('Previous 60 Days', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['AUDI_BR_EMAIL'], 'report', os.environ['AUDI_BR_PROPERTY'], '120daysAgo', '61daysAgo'], text=True) and os.environ['AUDI_PREV']), ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '120daysAgo', '61daysAgo')),
                'yoy60': build_dataset('Same 60 Days Last Year', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['AUDI_BR_EMAIL'], 'report', os.environ['AUDI_BR_PROPERTY'], '425daysAgo', '366daysAgo'], text=True) and os.environ['AUDI_PREV']), ga4_daily(os.environ['AUDI_BR_EMAIL'], os.environ['AUDI_BR_PROPERTY'], '425daysAgo', '366daysAgo')),
            }
        },
        {
            'file': 'bmw-jackson-dashboard.html',
            'email': os.environ['BMW_JACKSON_EMAIL'],
            'property': os.environ['BMW_JACKSON_PROPERTY'],
            'mobile': jackson_mobile,
            'sources': jackson_sources,
            'datasets': {
                'q1_2026': build_dataset('Last 90 Days', jackson_q1, ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '90daysAgo', 'today')),
                'yoy90': build_dataset('Same 90 Days Last Year', jackson_prev, ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '455daysAgo', '366daysAgo')),
                'prev90': build_dataset('Previous 90 Days', jackson_prev, ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '180daysAgo', '91daysAgo')),
                'last30': build_dataset('Last 30 Days', jackson_30, ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '30daysAgo', 'today')),
                'prev30': build_dataset('Previous 30 Days', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BMW_JACKSON_EMAIL'], 'report', os.environ['BMW_JACKSON_PROPERTY'], '60daysAgo', '31daysAgo'], text=True) and os.environ['JACKSON_PREV']), ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '60daysAgo', '31daysAgo')),
                'yoy30': build_dataset('Same 30 Days Last Year', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BMW_JACKSON_EMAIL'], 'report', os.environ['BMW_JACKSON_PROPERTY'], '395daysAgo', '366daysAgo'], text=True) and os.environ['JACKSON_PREV']), ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '395daysAgo', '366daysAgo')),
                'last60': build_dataset('Last 60 Days', jackson_60, ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '60daysAgo', 'today')),
                'prev60': build_dataset('Previous 60 Days', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BMW_JACKSON_EMAIL'], 'report', os.environ['BMW_JACKSON_PROPERTY'], '120daysAgo', '61daysAgo'], text=True) and os.environ['JACKSON_PREV']), ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '120daysAgo', '61daysAgo')),
                'yoy60': build_dataset('Same 60 Days Last Year', parse_totals(subprocess.check_output(['bash', str(GA4_QUERY), os.environ['BMW_JACKSON_EMAIL'], 'report', os.environ['BMW_JACKSON_PROPERTY'], '425daysAgo', '366daysAgo'], text=True) and os.environ['JACKSON_PREV']), ga4_daily(os.environ['BMW_JACKSON_EMAIL'], os.environ['BMW_JACKSON_PROPERTY'], '425daysAgo', '366daysAgo')),
            }
        }
    ]

    for store in store_defs:
        patch_dashboard(DASH_DIR / store['file'], store['datasets'], store['sources'], store['mobile'])

    print('Data written to ga4-data.json and dashboard HTML files')
    print(f"BH BMW Q1: {bh_q1['sessions']:,} sessions | Mobile: {bh_mobile}%")
    print(f"Audi BR Q1: {audi_q1['sessions']:,} sessions | Mobile: {audi_mobile}%")
    print(f"BMW Jackson Q1: {jackson_q1['sessions']:,} sessions | Mobile: {jackson_mobile}%")


if __name__ == '__main__':
    main()
