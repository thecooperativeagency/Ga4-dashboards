#!/bin/bash
# ============================================================
# GA4 Dashboard Auto-Update Script
# Runs every Monday morning via cron
# Pulls fresh data from GA4 and updates all 3 dashboards
# ============================================================

set -euo pipefail

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
    local REFRESH_JSON
    REFRESH_JSON=$(security find-generic-password -a "token:analytics:${EMAIL}" -s "gogcli" -w 2>/dev/null || true)
    if [ -z "$REFRESH_JSON" ]; then
        REFRESH_JSON=$(security find-generic-password -a "token:default:${EMAIL}" -s "gogcli" -w 2>/dev/null || true)
    fi
    if [ -z "$REFRESH_JSON" ]; then
        echo "Missing refresh token for ${EMAIL}" >&2
        return 1
    fi
    local REFRESH_TOKEN
    REFRESH_TOKEN=$(echo "$REFRESH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])")
    curl -s -X POST "https://oauth2.googleapis.com/token" \
        -d "client_id=${CLIENT_ID}" \
        -d "client_secret=${CLIENT_SECRET}" \
        -d "refresh_token=${REFRESH_TOKEN}" \
        -d "grant_type=refresh_token" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data['access_token']) if 'access_token' in data else (_ for _ in ()).throw(SystemExit(data))"
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
BH_SOURCES=$(get_sources "$TOKEN_BH" "$BH_BMW_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
BH_DEVICES=$(get_devices "$TOKEN_BH" "$BH_BMW_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")

AUDI_SOURCES=$(get_sources "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
AUDI_DEVICES=$(get_devices "$TOKEN_BH" "$AUDI_BR_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")

JACKSON_SOURCES=$(get_sources "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")
JACKSON_DEVICES=$(get_devices "$TOKEN_JACKSON" "$BMW_JACKSON_PROPERTY" "$Q1_2026_START" "$Q1_2026_END")

echo "[$DATE] Data pulled. Generating updated dashboards..." | tee -a "$LOG_FILE"

# ── GENERATE UPDATED DATA JS ───────────────────────────────────
BH_SOURCES="$BH_SOURCES" BH_DEVICES="$BH_DEVICES" \
AUDI_SOURCES="$AUDI_SOURCES" AUDI_DEVICES="$AUDI_DEVICES" \
JACKSON_SOURCES="$JACKSON_SOURCES" JACKSON_DEVICES="$JACKSON_DEVICES" \
TODAY="$TODAY" BH_BMW_EMAIL="$BH_BMW_EMAIL" AUDI_BR_EMAIL="$AUDI_BR_EMAIL" BMW_JACKSON_EMAIL="$BMW_JACKSON_EMAIL" BH_BMW_PROPERTY="$BH_BMW_PROPERTY" AUDI_BR_PROPERTY="$AUDI_BR_PROPERTY" BMW_JACKSON_PROPERTY="$BMW_JACKSON_PROPERTY" \
python3 /Users/lucfaucheux/.openclaw/workspace/ga4-dashboards/update_ga4_dashboards.py

echo "[$DATE] Checking yesterday's session thresholds..." | tee -a "$LOG_FILE"

ALERT_THRESHOLD=100
ALERTS=""

# Get yesterday's sessions for threshold check
YESTERDAY=$(date -v-1d '+%Y-%m-%d')

for STORE in "Brian Harris BMW|$BH_BMW_EMAIL|$BH_BMW_PROPERTY" "Audi Baton Rouge|$AUDI_BR_EMAIL|$AUDI_BR_PROPERTY" "BMW of Jackson|$BMW_JACKSON_EMAIL|$BMW_JACKSON_PROPERTY"; do
    IFS='|' read -r NAME EMAIL PROPERTY <<< "$STORE"
    TOKEN=$(get_access_token "$EMAIL")
    
    YESTERDAY_DATA=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY}:runReport" \
        -d "{\"dateRanges\":[{\"startDate\":\"yesterday\",\"endDate\":\"yesterday\"}],\"metrics\":[{\"name\":\"sessions\"}]}" | \
        python3 -c "import sys,json; data=json.load(sys.stdin); rows=data.get('rows',[]); print(int(rows[0]['metricValues'][0]['value']) if rows else 0)")
    
    if [ "$YESTERDAY_DATA" -lt "$ALERT_THRESHOLD" ]; then
        ALERTS="${ALERTS}⚠️ ${NAME}: ${YESTERDAY_DATA} sessions (threshold: ${ALERT_THRESHOLD})\n"
    fi
    
    # Add yesterday's sessions to the data object
    echo "${NAME} yesterday: ${YESTERDAY_DATA} sessions" | tee -a "$LOG_FILE"
done

# Telegram alert if any property is below threshold
if [ -n "$ALERTS" ]; then
    echo "[$DATE] ALERT: Properties below threshold detected" | tee -a "$LOG_FILE"
    TELEGRAM_BOT_TOKEN=$(grep TELEGRAM_BOT_TOKEN ~/.openclaw/workspace/kalshi-weather/.env 2>/dev/null | cut -d= -f2)
    TELEGRAM_CHAT_ID=$(grep TELEGRAM_CHAT_ID ~/.openclaw/workspace/kalshi-weather/.env 2>/dev/null | cut -d= -f2)
    
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "parse_mode=Markdown" \
            -d "text=🚨 *GA4 Session Alert* 🚨%0A%0AYesterday's sessions dropped below threshold:%0A%0A${ALERTS}%0A📊 Dashboards updated: https://thecooperativeagency.github.io/Ga4-dashboards/" > /dev/null
        echo "[$DATE] Telegram alert sent" | tee -a "$LOG_FILE"
    fi
else
    echo "[$DATE] All properties above threshold. No alerts." | tee -a "$LOG_FILE"
fi

echo "[$DATE] Committing and pushing to GitHub..." | tee -a "$LOG_FILE"

cd "$SCRIPT_DIR"
git add ga4-data.json
git add brian-harris-bmw-dashboard.html bmw-jackson-dashboard.html audi-baton-rouge-dashboard.html
if git diff --staged --quiet; then
    echo "[$DATE] No dashboard changes to commit." | tee -a "$LOG_FILE"
else
    git commit -m "Auto-update: GA4 data refresh $(date '+%Y-%m-%d')"
    git push origin main
fi

echo "[$DATE] Dashboard update complete!" | tee -a "$LOG_FILE"
