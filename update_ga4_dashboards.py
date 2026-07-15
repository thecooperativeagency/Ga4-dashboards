#!/usr/bin/env python3
"""Pull real GA4 metrics and patch dealership dashboards. No estimates."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

WORKSPACE = Path('/Users/lucfaucheux/.openclaw/workspace')
DASH_DIR = WORKSPACE / 'ga4-dashboards'
GA4_QUERY = WORKSPACE / 'ga4-query.sh'
TOKEN_CACHE: dict[str, str] = {}


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


def parse_mobile_pct(json_str: str) -> float:
    data = json.loads(json_str)
    rows = data.get('rows', [])
    total = sum(int(r['metricValues'][0]['value']) for r in rows)
    if not total:
        return 0.0
    for r in rows:
        if r['dimensionValues'][0]['value'] == 'mobile':
            return round(int(r['metricValues'][0]['value']) / total * 100, 1)
    return 0.0


def _client_creds():
    cfg = Path.home() / '.config/gogcli/config.json'
    if cfg.exists():
        data = json.loads(cfg.read_text())
        return data['client_id'], data['client_secret']
    client_id = subprocess.check_output(
        ['security', 'find-generic-password', '-a', 'gogcli-client-id', '-s', 'gogcli', '-w'],
        text=True,
    ).strip()
    client_secret = subprocess.check_output(
        ['security', 'find-generic-password', '-a', 'gogcli-client-secret', '-s', 'gogcli', '-w'],
        text=True,
    ).strip()
    return client_id, client_secret


def get_access_token(email: str) -> str:
    if email in TOKEN_CACHE:
        return TOKEN_CACHE[email]
    refresh_json = ''
    for account in (f'token:analytics:{email}', f'token:default:{email}'):
        try:
            refresh_json = subprocess.check_output(
                ['security', 'find-generic-password', '-a', account, '-s', 'gogcli', '-w'],
                text=True,
            ).strip()
            if refresh_json:
                break
        except subprocess.CalledProcessError:
            continue
    if not refresh_json:
        raise RuntimeError(f'Missing refresh token for {email}')
    refresh_token = json.loads(refresh_json)['refresh_token']
    client_id, client_secret = _client_creds()
    body = (
        f'client_id={client_id}&client_secret={client_secret}'
        f'&refresh_token={refresh_token}&grant_type=refresh_token'
    ).encode()
    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    token = payload['access_token']
    TOKEN_CACHE[email] = token
    return token


def run_report_api(email: str, property_id: str, body: dict) -> dict:
    token = get_access_token(email)
    req = urllib.request.Request(
        f'https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport',
        data=json.dumps(body).encode(),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def run_report(email: str, property_id: str, start: str, end: str):
    raw = subprocess.check_output(
        ['bash', str(GA4_QUERY), email, 'report', property_id, start, end],
        text=True,
    )
    return json.loads(raw)


def totals_from_report(report: dict):
    totals = {'sessions': 0, 'users': 0, 'newUsers': 0, 'pageviews': 0}
    for row in report.get('rows', []):
        totals['sessions'] += int(row['metricValues'][0]['value'])
        totals['users'] += int(row['metricValues'][1]['value'])
        totals['newUsers'] += int(row['metricValues'][2]['value'])
        totals['pageviews'] += int(row['metricValues'][3]['value'])
    totals['pagesPerSession'] = (
        round(totals['pageviews'] / totals['sessions'], 2) if totals['sessions'] else 0.0
    )
    return totals


def daily_from_report(report: dict):
    pairs = []
    for row in report.get('rows', []):
        date_str = row['dimensionValues'][0]['value']
        pairs.append((date_str, int(row['metricValues'][0]['value'])))
    pairs.sort(key=lambda x: x[0])
    labels = [f'{date_str[4:6]}/{date_str[6:8]}' for date_str, _ in pairs]
    sessions = [value for _, value in pairs]
    return {'labels': labels, 'sessions': sessions}


def fetch_engagement(email: str, property_id: str, start: str, end: str) -> dict:
    report = run_report_api(
        email,
        property_id,
        {
            'dateRanges': [{'startDate': start, 'endDate': end}],
            'metrics': [
                {'name': 'sessions'},
                {'name': 'bounceRate'},
                {'name': 'averageSessionDuration'},
                {'name': 'engagementRate'},
                {'name': 'screenPageViewsPerSession'},
            ],
        },
    )
    if not report.get('rows'):
        return {
            'bounceRate': 0.0,
            'avgSessionDuration': 0.0,
            'engagementRate': 0.0,
            'pagesPerSessionApi': 0.0,
        }
    mv = report['rows'][0]['metricValues']
    return {
        'bounceRate': round(float(mv[1]['value']) * 100, 1),  # GA4 returns 0-1 ratio
        'avgSessionDuration': round(float(mv[2]['value']), 1),  # seconds
        'engagementRate': round(float(mv[3]['value']) * 100, 1),
        'pagesPerSessionApi': round(float(mv[4]['value']), 2),
    }


def fetch_mobile_pct(email: str, property_id: str, start: str, end: str) -> float:
    report = run_report_api(
        email,
        property_id,
        {
            'dateRanges': [{'startDate': start, 'endDate': end}],
            'dimensions': [{'name': 'deviceCategory'}],
            'metrics': [{'name': 'sessions'}],
        },
    )
    rows = report.get('rows', [])
    total = sum(int(r['metricValues'][0]['value']) for r in rows)
    if not total:
        return 0.0
    for r in rows:
        if r['dimensionValues'][0]['value'] == 'mobile':
            return round(int(r['metricValues'][0]['value']) / total * 100, 1)
    return 0.0


def fetch_high_bounce_pages(email: str, property_id: str, start: str, end: str, limit: int = 12):
    report = run_report_api(
        email,
        property_id,
        {
            'dateRanges': [{'startDate': start, 'endDate': end}],
            'dimensions': [{'name': 'pagePath'}],
            'metrics': [
                {'name': 'sessions'},
                {'name': 'bounceRate'},
                {'name': 'averageSessionDuration'},
            ],
            'metricFilter': {
                'filter': {
                    'fieldName': 'sessions',
                    'numericFilter': {
                        'operation': 'GREATER_THAN_OR_EQUAL',
                        'value': {'int64Value': '20'},
                    },
                }
            },
            'orderBys': [{'metric': {'metricName': 'bounceRate'}, 'desc': True}],
            'limit': limit,
        },
    )
    out = []
    for r in report.get('rows', []):
        sessions = int(r['metricValues'][0]['value'])
        bounce = round(float(r['metricValues'][1]['value']) * 100, 1)
        duration = round(float(r['metricValues'][2]['value']), 1)
        out.append(
            {
                'pagePath': r['dimensionValues'][0]['value'],
                'sessions': sessions,
                'bounceRate': bounce,
                'avgSessionDuration': duration,
            }
        )
    return out



def fetch_campaigns(email: str, property_id: str, start: str, end: str, limit: int = 50):
    report = run_report_api(
        email,
        property_id,
        {
            'dateRanges': [{'startDate': start, 'endDate': end}],
            'dimensions': [
                {'name': 'sessionCampaignName'},
                {'name': 'sessionSource'},
                {'name': 'sessionMedium'},
            ],
            'metrics': [
                {'name': 'sessions'},
                {'name': 'totalUsers'},
                {'name': 'bounceRate'},
                {'name': 'averageSessionDuration'},
            ],
            'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
            'limit': limit,
        },
    )
    out = []
    for r in report.get('rows', []):
        campaign = r['dimensionValues'][0]['value']
        source = r['dimensionValues'][1]['value']
        medium = r['dimensionValues'][2]['value']
        sessions = int(r['metricValues'][0]['value'])
        users = int(r['metricValues'][1]['value'])
        bounce = round(float(r['metricValues'][2]['value']) * 100, 1)
        duration = round(float(r['metricValues'][3]['value']), 1)
        src_l, med_l, camp_l = source.lower(), medium.lower(), campaign.lower()
        paid = (
            med_l in {'cpc', 'ppc', 'paid', 'paid_social', 'display'}
            or src_l in {'fb', 'ig', 'facebook', 'instagram', 'meta'}
            or 'paid search' in camp_l
            or 'paid social' in camp_l
        )
        if not paid:
            continue
        out.append(
            {
                'campaign': campaign,
                'source': source,
                'medium': medium,
                'channel': f'{source} / {medium}',
                'sessions': sessions,
                'users': users,
                'bounceRate': bounce,
                'avgSessionDuration': duration,
            }
        )
    out.sort(key=lambda row: row['sessions'], reverse=True)
    return out[:25]


def fetch_hostnames(email: str, property_id: str, start: str, end: str, limit: int = 15):
    report = run_report_api(
        email,
        property_id,
        {
            'dateRanges': [{'startDate': start, 'endDate': end}],
            'dimensions': [{'name': 'hostName'}],
            'metrics': [{'name': 'sessions'}, {'name': 'totalUsers'}],
            'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
            'limit': limit,
        },
    )
    rows = []
    total = 0
    for r in report.get('rows', []):
        sessions = int(r['metricValues'][0]['value'])
        total += sessions
        rows.append(
            {
                'hostname': r['dimensionValues'][0]['value'],
                'sessions': sessions,
                'users': int(r['metricValues'][1]['value']),
            }
        )
    for row in rows:
        row['share'] = round((row['sessions'] / total * 100), 1) if total else 0.0
    return {'total': total, 'rows': rows}


def fetch_top_pages(email: str, property_id: str, start: str, end: str, limit: int = 15):
    report = run_report_api(
        email,
        property_id,
        {
            'dateRanges': [{'startDate': start, 'endDate': end}],
            'dimensions': [{'name': 'pagePath'}],
            'metrics': [
                {'name': 'sessions'},
                {'name': 'averageSessionDuration'},
                {'name': 'bounceRate'},
                {'name': 'screenPageViews'},
            ],
            'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
            'limit': limit,
        },
    )
    out = []
    for r in report.get('rows', []):
        out.append(
            {
                'pagePath': r['dimensionValues'][0]['value'],
                'sessions': int(r['metricValues'][0]['value']),
                'avgSessionDuration': round(float(r['metricValues'][1]['value']), 1),
                'bounceRate': round(float(r['metricValues'][2]['value']) * 100, 1),
                'pageviews': int(r['metricValues'][3]['value']),
            }
        )
    return out


def fetch_weekly_sessions(email: str, property_id: str, start: str, end: str):
    report = run_report_api(
        email,
        property_id,
        {
            'dateRanges': [{'startDate': start, 'endDate': end}],
            'dimensions': [{'name': 'yearWeek'}],
            'metrics': [{'name': 'sessions'}],
            'orderBys': [{'dimension': {'dimensionName': 'yearWeek'}}],
            'limit': 60,
        },
    )
    labels = []
    sessions = []
    for r in report.get('rows', []):
        yw = r['dimensionValues'][0]['value']  # e.g. 202628
        labels.append(yw)
        sessions.append(int(r['metricValues'][0]['value']))
    return {'labels': labels, 'sessions': sessions}


def fetch_panels(email: str, property_id: str):
    return {
        'campaigns': fetch_campaigns(email, property_id, '30daysAgo', 'today'),
        'hostnames': fetch_hostnames(email, property_id, '90daysAgo', 'today'),
        'top_pages': fetch_top_pages(email, property_id, '90daysAgo', 'today', limit=12),
        'top_pages_30': fetch_top_pages(email, property_id, '30daysAgo', 'today', limit=12),
        'weekly_current': fetch_weekly_sessions(email, property_id, '365daysAgo', 'today'),
        'weekly_prior': fetch_weekly_sessions(email, property_id, '730daysAgo', '366daysAgo'),
    }


def fetch_period(email: str, property_id: str, start: str, end: str, label: str):
    report = run_report(email, property_id, start, end)
    totals = totals_from_report(report)
    daily = daily_from_report(report)
    engagement = fetch_engagement(email, property_id, start, end)
    mobile = fetch_mobile_pct(email, property_id, start, end)
    # Prefer API pps when available; keep derived as fallback consistency check.
    pages_per_session = engagement['pagesPerSessionApi'] or totals['pagesPerSession']
    return {
        'label': label,
        'sessions': totals['sessions'],
        'users': totals['users'],
        'newUsers': totals['newUsers'],
        'pageviews': totals['pageviews'],
        'pagesPerSession': pages_per_session,
        'bounceRate': engagement['bounceRate'],
        'avgSessionDuration': engagement['avgSessionDuration'],
        'engagementRate': engagement['engagementRate'],
        'mobilePct': mobile,
        'daily': daily,
    }


def js_obj(value):
    return json.dumps(value, separators=(',', ':'))



def upsert_const(html: str, name: str, value_js: str, after: str = 'SOURCES') -> str:
    pattern = rf'const {name}\s*=\s*[\s\S]*?;'
    if re.search(pattern, html):
        return re.sub(pattern, f'const {name} = {value_js};', html, count=1)
    anchor = rf'(const {after}\s*=\s*[\s\S]*?;)'
    if re.search(anchor, html):
        return re.sub(anchor, rf'\1\n\nconst {name} = {value_js};', html, count=1)
    # fallback after DATA
    return re.sub(
        r'(const DATA\s*=\s*\{[\s\S]*?\};)',
        rf'\1\n\nconst {name} = {value_js};',
        html,
        count=1,
    )


def patch_dashboard(
    path: Path,
    datasets: dict,
    sources: list,
    high_bounce: list,
    panels: dict,
    updated_label: str,
):
    html = path.read_text()
    data_js = '{\n' + ',\n'.join(f'    {k}: {js_obj(v)}' for k, v in datasets.items()) + '\n}'
    sources_js = js_obj(sources)
    high_bounce_js = js_obj(high_bounce)
    campaigns_js = js_obj(panels['campaigns'])
    hostnames_js = js_obj(panels['hostnames'])
    top_pages_js = js_obj(panels['top_pages'])
    top_pages_30_js = js_obj(panels['top_pages_30'])
    weekly_js = js_obj(
        {
            'current': panels['weekly_current'],
            'prior': panels['weekly_prior'],
        }
    )

    html = re.sub(
        r'const DATA\s*=\s*\{[\s\S]*?\};\s*\n\s*const SOURCES\s*=\s*\[[\s\S]*?\];',
        f'const DATA = {data_js};\n\nconst SOURCES = {sources_js};',
        html,
        count=1,
    )
    html = upsert_const(html, 'HIGH_BOUNCE', high_bounce_js, after='SOURCES')
    html = upsert_const(html, 'CAMPAIGNS', campaigns_js, after='HIGH_BOUNCE')
    html = upsert_const(html, 'HOSTNAMES', hostnames_js, after='CAMPAIGNS')
    html = upsert_const(html, 'TOP_PAGES', top_pages_js, after='HOSTNAMES')
    html = upsert_const(html, 'TOP_PAGES_30', top_pages_30_js, after='TOP_PAGES')
    html = upsert_const(html, 'WEEKLY', weekly_js, after='TOP_PAGES_30')

    html = re.sub(
        r'(id="dataUpdated">Updated on )(?:[A-Za-z]+ \d{1,2}, \d{4}|[A-Za-z]+ \d{4})',
        rf'\1{updated_label}',
        html,
        count=1,
    )
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


def period_summary(period: dict):
    keys = (
        'sessions',
        'users',
        'newUsers',
        'pageviews',
        'pagesPerSession',
        'bounceRate',
        'avgSessionDuration',
        'engagementRate',
        'mobilePct',
    )
    return {k: period[k] for k in keys}


def main():
    bh_sources = parse_sources(os.environ['BH_SOURCES'])
    audi_sources = parse_sources(os.environ['AUDI_SOURCES'])
    jackson_sources = parse_sources(os.environ['JACKSON_SOURCES'])

    bh_email = os.environ['BH_BMW_EMAIL']
    audi_email = os.environ['AUDI_BR_EMAIL']
    jackson_email = os.environ['BMW_JACKSON_EMAIL']
    bh_prop = os.environ['BH_BMW_PROPERTY']
    audi_prop = os.environ['AUDI_BR_PROPERTY']
    jackson_prop = os.environ['BMW_JACKSON_PROPERTY']

    bh_data = build_store(bh_email, bh_prop)
    audi_data = build_store(audi_email, audi_prop)
    jackson_data = build_store(jackson_email, jackson_prop)

    bh_high = fetch_high_bounce_pages(bh_email, bh_prop, '30daysAgo', 'today')
    audi_high = fetch_high_bounce_pages(audi_email, audi_prop, '30daysAgo', 'today')
    jackson_high = fetch_high_bounce_pages(jackson_email, jackson_prop, '30daysAgo', 'today')

    bh_panels = fetch_panels(bh_email, bh_prop)
    audi_panels = fetch_panels(audi_email, audi_prop)
    jackson_panels = fetch_panels(jackson_email, jackson_prop)

    today = os.environ['TODAY']
    updated_label = datetime.strptime(today, '%Y-%m-%d').strftime('%B %-d, %Y')

    cache = {
        'updated': today,
        'brian_harris_bmw': {
            'q1_2026': period_summary(bh_data['q1_2026']),
            'q1_prev': period_summary(bh_data['yoy90']),
            'last30': period_summary(bh_data['last30']),
            'last60': period_summary(bh_data['last60']),
            'sources': bh_sources,
            'mobile_pct': bh_data['q1_2026']['mobilePct'],
            'high_bounce': bh_high,
            'panels': bh_panels,
        },
        'audi_baton_rouge': {
            'q1_2026': period_summary(audi_data['q1_2026']),
            'q1_prev': period_summary(audi_data['yoy90']),
            'last30': period_summary(audi_data['last30']),
            'last60': period_summary(audi_data['last60']),
            'sources': audi_sources,
            'mobile_pct': audi_data['q1_2026']['mobilePct'],
            'high_bounce': audi_high,
            'panels': audi_panels,
        },
        'bmw_jackson': {
            'q1_2026': period_summary(jackson_data['q1_2026']),
            'q1_prev': period_summary(jackson_data['yoy90']),
            'last30': period_summary(jackson_data['last30']),
            'last60': period_summary(jackson_data['last60']),
            'sources': jackson_sources,
            'mobile_pct': jackson_data['q1_2026']['mobilePct'],
            'high_bounce': jackson_high,
            'panels': jackson_panels,
        },
    }
    (DASH_DIR / 'ga4-data.json').write_text(json.dumps(cache, indent=2))

    patch_dashboard(DASH_DIR / 'brian-harris-bmw-dashboard.html', bh_data, bh_sources, bh_high, bh_panels, updated_label)
    patch_dashboard(DASH_DIR / 'audi-baton-rouge-dashboard.html', audi_data, audi_sources, audi_high, audi_panels, updated_label)
    patch_dashboard(DASH_DIR / 'bmw-jackson-dashboard.html', jackson_data, jackson_sources, jackson_high, jackson_panels, updated_label)

    print('Data written to ga4-data.json and dashboard HTML files')
    for label, data, panels in (
        ('BH BMW', bh_data, bh_panels),
        ('Audi BR', audi_data, audi_panels),
        ('BMW Jackson', jackson_data, jackson_panels),
    ):
        cur = data['last30']
        print(
            f"{label} last30: sessions={cur['sessions']:,} bounce={cur['bounceRate']}% "
            f"campaigns={len(panels['campaigns'])} top_pages={len(panels['top_pages'])} "
            f"hosts={len(panels['hostnames']['rows'])}"
        )


if __name__ == '__main__':
    main()
