#!/bin/bash
# Build + publish ABR Google Ads monthly brief.
# Conversion definition lives in build_abr_google_ads_monthly.py — do not edit HTML by hand.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 scripts/build_abr_google_ads_monthly.py
STAMP="$(python3 -c 'from datetime import date; print(date.today().strftime("%b %-d, %Y"))')"
git add abr-google-ads-monthly.html data/abr-google-ads-monthly.json assets/abr-header.jpg scripts/build_abr_google_ads_monthly.py
if git diff --cached --quiet; then
  echo "No changes to publish"
else
  git commit -m "Refresh ABR Google Ads monthly brief (${STAMP})."
  git push origin main
fi
URL="https://thecooperativeagency.github.io/Ga4-dashboards/abr-google-ads-monthly.html"
for i in 1 2 3 4 5 6 7 8; do
  curl -fsS -o /tmp/abr-ads-monthly-live.html "${URL}?cb=${i}$(date +%s)" || true
  if grep -q "Generated ${STAMP}" /tmp/abr-ads-monthly-live.html && grep -q "site CTA conversions" /tmp/abr-ads-monthly-live.html; then
    echo "LIVE ${URL}"
    exit 0
  fi
  sleep 8
done
echo "Published but Pages body not flipped yet. Raw should have Generated ${STAMP}."
exit 0
