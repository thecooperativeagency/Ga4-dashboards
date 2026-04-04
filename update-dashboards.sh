#!/bin/bash
# ============================================================
# GA4 Dashboard Auto-Update Script
# Runs every Monday morning via cron
# Pulls fresh data from GA4 and updates all 3 dashboards
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/tmp/ga4-dashboard-update.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$DATE] Starting GA4 dashboard update..." | tee -a "$LOG_FILE"

# ── CONFIG ────────────────────────────────────────────────────
# Client ID loaded from gog config
CLIENT_ID=$(cat ~/.config/gogcli/config.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('client_id',''))" 2>/dev/null || echo "")
if [ -z "$CLIENT_ID" ]; then CLIENT_ID=$(security find-generic-password -a "gogcli-client-id" -s "gogcli" -w 2>/dev/null || echo ""); fi
# Client secret loaded from gog config
CLIENT_SECRET=$(cat ~/.config/gogcli/config.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('client_secret',''))" 2>/dev/null || echo "")
if [ -z "$CLIENT_SECRET" ]; then CLIENT_SECRET=$(security find-generic-password -a "gogcli-client-secret" -s "gogcli" -w 2>/dev/null || echo ""); fi

BH_BMW_PROPERTY="334199347"
AUDI_BR_PROPERTY="381984706"
BMW_JACKSON_PROPERTY="255835161"

BH_BMW_EMAIL="bhbmwecommerce@gmail.com"
AUDI_BR_EMAIL="bhbmwecommerce@gmail.com"
BMW_JACKSON_EMAIL="bmwofjackson@thecoopbrla.com"

# ── FUNCTIONS ─────────────────────────────────────────────────

get_access_token() {
    local EMAIL="$1"
    local REFRESH_JSON=$(security find-generic-password -a "token:default:${EMAIL}" -s "gogcli" -w 2>/dev/null)
    local REFRESH_TOKEN=$(echo "$REFRESH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])")
    curl -s -X POST "https://oauth2.googleapis.com/token" \
        -d "client_id=${CLIENT_ID}" \
        -d "client_secret=${CLIENT_SECRET}" \
        -d "refresh_token=${REFRESH_TOKEN}" \
        -d "grant_type=refresh_token" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
}

get_totals() {
    local TOKEN="$1"
    local PROPERTY="$2"
    local START="$3"
    local END="$4"
    curl -s -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY}:runReport" \
        -d "{\"dateRanges\":[{\"startDate\":\"${START}\",\"endDate\":\"${END}\"}],\"metrics\":[{\"name\":\"sessions\"},{\"name\":\"totalUsers\"},{\"name\":\"newUsers\"},{\"name\":\"screenPageViews\"}],\"dimensions\":[{\"name\":\"date\"}]}" | \
    python3 -c "
import sys,json
data=json.load(sys.stdin)
rows=data.get('rows',[])
s=sum(int(r['metricValues'][0]['value']) for r in rows)
u=sum(int(r['metricValues'][1]['value']) for r in rows)
n=sum(int(r['metricValues'][2]['value']) for r in rows)
p=sum(int(r['metricValues'][3]['value']) for r in rows)
pps=round(p/s,2) if s>0 else 0
print(f'{s},{u},{n},{p},{pps}')
"
}

get_sources() {
    local TOKEN="$1"
    local PROPERTY="$2"
    local START="$3"
    local END="$4"
    curl -s -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY}:runReport" \
        -d "{\"dateRanges\":[{\"startDate\":\"${START}\",\"endDate\":\"${END}\"}],\"dimensions\":[{\"name\":\"sessionSource\"},{\"name\":\"sessionMedium\"}],\"metrics\":[{\"name\":\"sessions\"},{\"name\":\"totalUsers\"}],\"orderBys\":[{\"metric\":{\"metricName\":\"sessions\"},\"desc\":true}],\"limit\":20}"
}

get_devices() {
    local TOKEN="$1"
    local PROPERTY="$2"
    local START="$3"
    local END="$4"
    curl -s -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY}:runReport" \
        -d "{\"dateRanges\":[{\"startDate\":\"${START}\",\"endDate\":\"${END}\"}],\"dimensions\":[{\"name\":\"deviceCategory\"}],\"metrics\":[{\"name\":\"sessions\"}],\"orderBys\":[{\"metric\":{\"metricName\":\"sessions\"},\"desc\":true}]}"
}

get_daily() {
    local TOKEN="$1"
    local PROPERTY="$2"
    local START="$3"
    local END="$4"
    curl -s -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY}:runReport" \
        -d "{\"dateRanges\":[{\"startDate\":\"${START}\",\"endDate\":\"${END}\"}],\"metrics\":[{\"name\":\"sessions\"}],\"dimensions\":[{\"name\":\"date\"}]}"
}

# ── DATE RANGES ────────────────────────────────────────────────
TODAY=$(date '+%Y-%m-%d')
LAST30_START=$(date -v-30d '+%Y-%m-%d')
LAST60_START=$(date -v-60d '+%Y-%m-%d')
Q1_2026_START="2026-01-01"
Q1_2026_END="2026-03-31"
Q1_PREV_START="2024-01-01"
Q1_PREV_END="2024-03-31"

echo "[$DATE] Fetching access tokens..." | tee -a "$LOG_FILE"
TOKEN_BH=$(get_access_token "$BH_BMW_EMAIL")
TOKEN_JACKSON=$(get_access_token "$BMW_JACKSON_EMAIL")

echo "[$DATE] Pulling data for all 3 stores..." | tee -a "$LOG_FILE"

# ── PULL ALL DATA ─────────────────────────────────────────────
BH_Q1=$(get_totals "$TOKEN_BH" "$BH_BMW_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
BH_PREV=$(get_totals "$TOKEN_BH" "$BH_BMW_PROPERTY" "$Q1_PREV_START" "$Q1_PREV_END")
BH_30=$(get_totals "$TOKEN_BH" "$BH_BMW_PROPERTY" "$LAST30_START" "$TODAY")
BH_60=$(get_totals "$TOKEN_BH" "$BH_BMW_PROPERTY" "$LAST60_START" "$TODAY")
BH_SOURCES=$(get_sources "$TOKEN_BH" "$BH_BMW_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
BH_DEVICES=$(get_devices "$TOKEN_BH" "$BH_BMW_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")

AUDI_Q1=$(get_totals "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
AUDI_PREV=$(get_totals "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$Q1_PREV_START" "$Q1_PREV_END")
AUDI_30=$(get_totals "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$LAST30_START" "$TODAY")
AUDI_60=$(get_totals "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$LAST60_START" "$TODAY")
AUDI_SOURCES=$(get_sources "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
AUDI_DEVICES=$(get_devices "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")

JACKSON_Q1=$(get_totals "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
JACKSON_PREV=$(get_totals "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$Q1_PREV_START" "$Q1_PREV_END")
JACKSON_30=$(get_totals "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$LAST30_START" "$TODAY")
JACKSON_60=$(get_totals "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$LAST60_START" "$TODAY")
JACKSON_SOURCES=$(get_sources "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
JACKSON_DEVICES=$(get_devices "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")

echo "[$DATE] Data pulled. Generating updated dashboards..." | tee -a "$LOG_FILE"

# ── GENERATE UPDATED DATA JS ───────────────────────────────────
python3 << PYEOF
import json, subprocess, sys, os

def parse_totals(csv):
    parts = csv.strip().split(',')
    return {
        'sessions': int(parts[0]),
        'users': int(parts[1]),
        'newUsers': int(parts[2]),
        'pageviews': int(parts[3]),
        'pagesPerSession': float(parts[4])
    }

def parse_sources(json_str):
    data = json.loads(json_str)
    sources = []
    for r in data.get('rows', []):
        sources.append({
            'source': r['dimensionValues'][0]['value'],
            'medium': r['dimensionValues'][1]['value'],
            'sessions': int(r['metricValues'][0]['value']),
            'users': int(r['metricValues'][1]['value'])
        })
    return sources

def parse_mobile_pct(json_str):
    data = json.loads(json_str)
    rows = data.get('rows', [])
    total = sum(int(r['metricValues'][0]['value']) for r in rows)
    for r in rows:
        if r['dimensionValues'][0]['value'] == 'mobile':
            return round(int(r['metricValues'][0]['value']) / total * 100, 1)
    return 0

# Parse all data
bh_q1 = parse_totals("""${BH_Q1}""")
bh_prev = parse_totals("""${BH_PREV}""")
bh_30 = parse_totals("""${BH_30}""")
bh_60 = parse_totals("""${BH_60}""")
bh_sources = parse_sources("""${BH_SOURCES}""")
bh_mobile = parse_mobile_pct("""${BH_DEVICES}""")

audi_q1 = parse_totals("""${AUDI_Q1}""")
audi_prev = parse_totals("""${AUDI_PREV}""")
audi_30 = parse_totals("""${AUDI_30}""")
audi_60 = parse_totals("""${AUDI_60}""")
audi_sources = parse_sources("""${AUDI_SOURCES}""")
audi_mobile = parse_mobile_pct("""${AUDI_DEVICES}""")

jackson_q1 = parse_totals("""${JACKSON_Q1}""")
jackson_prev = parse_totals("""${JACKSON_PREV}""")
jackson_30 = parse_totals("""${JACKSON_30}""")
jackson_60 = parse_totals("""${JACKSON_60}""")
jackson_sources = parse_sources("""${JACKSON_SOURCES}""")
jackson_mobile = parse_mobile_pct("""${JACKSON_DEVICES}""")

# Write data file
data = {
    'updated': '${TODAY}',
    'brian_harris_bmw': {
        'q1_2026': bh_q1, 'q1_prev': bh_prev,
        'last30': bh_30, 'last60': bh_60,
        'sources': bh_sources, 'mobile_pct': bh_mobile
    },
    'audi_baton_rouge': {
        'q1_2026': audi_q1, 'q1_prev': audi_prev,
        'last30': audi_30, 'last60': audi_60,
        'sources': audi_sources, 'mobile_pct': audi_mobile
    },
    'bmw_jackson': {
        'q1_2026': jackson_q1, 'q1_prev': jackson_prev,
        'last30': jackson_30, 'last60': jackson_60,
        'sources': jackson_sources, 'mobile_pct': jackson_mobile
    }
}

with open('ga4-data.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"Data written to ga4-data.json")
print(f"BH BMW Q1: {bh_q1['sessions']:,} sessions | Mobile: {bh_mobile}%")
print(f"Audi BR Q1: {audi_q1['sessions']:,} sessions | Mobile: {audi_mobile}%")
print(f"BMW Jackson Q1: {jackson_q1['sessions']:,} sessions | Mobile: {jackson_mobile}%")
PYEOF

echo "[$DATE] Committing and pushing to GitHub..." | tee -a "$LOG_FILE"

cd "$SCRIPT_DIR"
git add ga4-data.json
git add brian-harris-bmw-dashboard.html bmw-jackson-dashboard.html audi-baton-rouge-dashboard.html
git diff --staged --quiet || git commit -m "Auto-update: GA4 data refresh $(date '+%Y-%m-%d')"
git push origin main

echo "[$DATE] Dashboard update complete!" | tee -a "$LOG_FILE"
