#!/usr/bin/env python3
"""Build ABR Google Ads monthly ops brief.

Conversion definition is locked here — do not change per run:
  site CTA conversions = click_main_cta
                       + click_phone_number
                       + start_check_availability_form
                       + complete_quick_qualify_form

Ads "Calls from ads" stay a separate column. SRP/VDP pageviews are not conversions.
Window: 1st of current month through yesterday, vs the same day-span last month.
"""
from __future__ import annotations

import calendar
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import update_ga4_dashboards as ga4  # noqa: E402

EMAIL = "bhbmwecommerce@gmail.com"
PROPERTY = "381984706"
CID = "3995837733"
PIPEBOARD = "https://google-ads.mcp.pipeboard.co/"

SITE_CTA_EVENTS = (
    "click_main_cta",
    "click_phone_number",
    "start_check_availability_form",
    "complete_quick_qualify_form",
)
CTA_LABELS = {
    "click_main_cta": "Main CTA",
    "click_phone_number": "Phone tap",
    "start_check_availability_form": "Start check-availability",
    "complete_quick_qualify_form": "Finish qualify form",
}

DATA_PATH = ROOT / "data" / "abr-google-ads-monthly.json"
HTML_PATH = ROOT / "abr-google-ads-monthly.html"


def windows(today: date | None = None) -> tuple[date, date, date, date]:
    today = today or date.today()
    end = today - timedelta(days=1)
    start = end.replace(day=1)
    span = (end - start).days
    if start.month == 1:
        prior_start = date(start.year - 1, 12, 1)
    else:
        prior_start = date(start.year, start.month - 1, 1)
    last_prior = calendar.monthrange(prior_start.year, prior_start.month)[1]
    prior_end = prior_start + timedelta(days=span)
    if prior_end.day > last_prior or prior_end.month != prior_start.month:
        prior_end = date(prior_start.year, prior_start.month, last_prior)
    return start, end, prior_start, prior_end


def fmt_range(a: date, b: date) -> str:
    def md(d: date) -> str:
        return f"{d.strftime('%b')} {d.day}"

    if a.year == b.year:
        return f"{md(a)}–{b.day}, {b.year}"
    return f"{md(a)}, {a.year} – {md(b)}, {b.year}"


def pipeboard_token() -> str:
    for p in (Path.home() / ".hermes/profiles/semi/.env", Path.home() / ".hermes/.env"):
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            s = line.strip()
            if s.startswith("PIPEBOARD_API_KEY=") or s.startswith("PIPEBOARD_API_TOKEN="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("PIPEBOARD_API_KEY missing")


def rpc(token: str, name: str, args: dict) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": name, "arguments": args}, "id": 1}
    ).encode()
    req = urllib.request.Request(
        PIPEBOARD,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = json.loads(resp.read().decode())
    result = raw.get("result", raw)
    if isinstance(result, dict) and result.get("isError"):
        raise SystemExit(f"pipeboard error {name}: {result}")
    if isinstance(result, dict) and "content" in result:
        text = result["content"][0]["text"]
        return json.loads(text)
    return result


def gaql(token: str, query: str) -> list[dict]:
    obj = rpc(token, "execute_google_ads_gaql_query", {"customer_id": CID, "query": query})
    return obj.get("results") or []


def micros(v) -> float:
    return float(v or 0) / 1_000_000


def role(name: str) -> str:
    n = (name or "").lower()
    if "conquest" in n:
        return "Conquest"
    if "sales offers" in n:
        return "Sales Offers"
    if "service offers" in n:
        return "Service Offers"
    if n.startswith("service") or "| service" in n:
        return "Service"
    if "brand" in n:
        return "Brand"
    if "location" in n or "near me" in n:
        return "Locations"
    if any(
        m in n
        for m in (
            "q3",
            "q5",
            "q7",
            "q8",
            "q6",
            "a3",
            "a4",
            "a5",
            "a6",
            "s3",
            "s5",
            "inventory",
            "sedan",
            "suv",
            "secondary",
        )
    ):
        return "Model"
    return "Other"


def short_name(name: str) -> str:
    return (
        (name or "")
        .replace(" | Paid Search", "")
        .replace("New Inventory - ", "")
        .strip()
    )


def campaign_key(name: str) -> str:
    return short_name(name).lower()


def is_search(ch) -> bool:
    return str(ch or "").upper() in ("SEARCH", "2", "")


def ads_window(token: str, start: date, end: date) -> tuple[list[dict], dict]:
    q = f"""
    SELECT campaign.name, campaign.status, campaign.advertising_channel_type,
           metrics.cost_micros, metrics.clicks, metrics.impressions, metrics.conversions,
           metrics.average_cpc
    FROM campaign
    WHERE segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
      AND campaign.status IN ('ENABLED','PAUSED')
    """
    by: dict[str, dict] = {}
    for r in gaql(token, q):
        c = r.get("campaign") or {}
        m = r.get("metrics") or {}
        ch = c.get("advertisingChannelType") or c.get("advertising_channel_type") or ""
        if str(ch).upper() not in ("SEARCH", "2", ""):
            continue
        name = c.get("name") or ""
        rec = by.setdefault(
            name,
            {
                "name": name,
                "short": short_name(name),
                "status": c.get("status") or "",
                "role": role(name),
                "spend": 0.0,
                "clicks": 0,
                "impr": 0,
                "ads_conv": 0.0,
                "cpc": 0.0,
                "calls": 0.0,
                "site_cta": 0,
                "cta": {k: 0 for k in SITE_CTA_EVENTS},
            },
        )
        rec["spend"] += micros(m.get("costMicros") or m.get("cost_micros"))
        rec["clicks"] += int(m.get("clicks") or 0)
        rec["impr"] += int(m.get("impressions") or 0)
        rec["ads_conv"] += float(m.get("conversions") or 0)

    q2 = f"""
    SELECT campaign.name, segments.conversion_action_name, metrics.conversions
    FROM campaign
    WHERE segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
      AND metrics.conversions > 0
    """
    for r in gaql(token, q2):
        name = (r.get("campaign") or {}).get("name") or ""
        action = (r.get("segments") or {}).get("conversionActionName") or ""
        val = float((r.get("metrics") or {}).get("conversions") or 0)
        if name in by and "call" in action.lower():
            by[name]["calls"] += val

    camps = []
    for rec in by.values():
        rec["spend"] = round(rec["spend"], 2)
        rec["ads_conv"] = round(rec["ads_conv"], 2)
        rec["calls"] = round(rec["calls"], 2)
        rec["cpc"] = round(rec["spend"] / rec["clicks"], 2) if rec["clicks"] else 0
        camps.append(rec)
    camps.sort(key=lambda x: -x["spend"])
    totals = {
        "spend": round(sum(c["spend"] for c in camps), 2),
        "clicks": sum(c["clicks"] for c in camps),
        "impr": sum(c["impr"] for c in camps),
        "ads_conv": round(sum(c["ads_conv"] for c in camps), 2),
        "calls": round(sum(c["calls"] for c in camps), 2),
        "cpc": 0.0,
        "site_cta": 0,
        "cta": {k: 0 for k in SITE_CTA_EVENTS},
    }
    totals["cpc"] = round(totals["spend"] / totals["clicks"], 2) if totals["clicks"] else 0
    return camps, totals


def sem_filter() -> dict:
    return {
        "andGroup": {
            "expressions": [
                {
                    "filter": {
                        "fieldName": "sessionSourceMedium",
                        "stringFilter": {"matchType": "EXACT", "value": "google / cpc"},
                    }
                },
                {
                    "filter": {
                        "fieldName": "sessionCampaignName",
                        "stringFilter": {"matchType": "CONTAINS", "value": "Paid Search"},
                    }
                },
            ]
        }
    }


def ga4_ctas(start: date, end: date) -> tuple[dict[str, dict], dict]:
    or_events = {
        "orGroup": {
            "expressions": [
                {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "EXACT", "value": n}}}
                for n in SITE_CTA_EVENTS
            ]
        }
    }
    filt = {
        "andGroup": {
            "expressions": list(sem_filter()["andGroup"]["expressions"]) + [or_events]
        }
    }
    raw = ga4.run_report_api(
        EMAIL,
        PROPERTY,
        {
            "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": "sessionCampaignName"}, {"name": "eventName"}],
            "metrics": [{"name": "eventCount"}],
            "dimensionFilter": filt,
            "limit": 250,
        },
    )
    by_camp: dict[str, dict] = defaultdict(lambda: {k: 0 for k in SITE_CTA_EVENTS})
    totals = {k: 0 for k in SITE_CTA_EVENTS}
    for r in raw.get("rows") or []:
        camp = r["dimensionValues"][0]["value"]
        ev = r["dimensionValues"][1]["value"]
        n = int(float(r["metricValues"][0]["value"]))
        if ev not in SITE_CTA_EVENTS:
            continue
        by_camp[camp][ev] += n
        totals[ev] += n
    return by_camp, totals


def attach_ctas(camps: list[dict], totals: dict, by_camp: dict, event_totals: dict) -> None:
    index = {campaign_key(c["name"]): c for c in camps}
    for camp_name, events in by_camp.items():
        rec = index.get(campaign_key(camp_name))
        if not rec:
            continue
        rec["cta"] = {k: int(events.get(k, 0)) for k in SITE_CTA_EVENTS}
        rec["site_cta"] = sum(rec["cta"].values())
    totals["cta"] = {k: int(event_totals.get(k, 0)) for k in SITE_CTA_EVENTS}
    totals["site_cta"] = sum(totals["cta"].values())


def pct(curr, prior) -> str:
    if prior in (0, None) and curr in (0, None):
        return "flat"
    if not prior:
        return "new"
    change = (curr - prior) / prior * 100
    if abs(change) < 0.5:
        return "flat"
    sign = "+" if change > 0 else ""
    return f"{sign}{change:.1f}%"


def money(n) -> str:
    return f"${n:,.0f}" if float(n) >= 100 else f"${n:,.2f}"


def num(n) -> str:
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}"
    return f"{int(n):,}"


def one_move(camps: list[dict], totals: dict) -> str:
    brand = next((c for c in camps if c["role"] == "Brand"), None)
    offers = [c for c in camps if c["role"] in ("Sales Offers", "Conquest") and c["spend"] > 0]
    offer_cta = sum(c["site_cta"] for c in offers)
    offer_spend = sum(c["spend"] for c in offers)
    if brand and brand["clicks"] and brand["cpc"] <= 1:
        return (
            f"Raise Brand. It spent {money(brand['spend'])} at ${brand['cpc']:.2f} CPC, "
            f"{brand['calls']:.0f} ad calls and {brand['site_cta']} site CTAs. "
            f"Judge Offers on site CTAs ({offer_cta} on {money(offer_spend)}), not Ads call zeros."
        )
    return "Judge search on site CTAs (main CTA, phone tap, check-availability, qualify), not Ads call conversions alone."


def render(data: dict) -> str:
    c, p = data["totals"]["curr"], data["totals"]["prior"]
    stamp = date.fromisoformat(data["generated"]).strftime("%b %-d, %Y")
    rows = []
    for camp in data["campaigns"]:
        pill = "on" if camp["status"] == "ENABLED" else "off"
        label = "On" if camp["status"] == "ENABLED" else "Paused"
        rows.append(
            f"""            <tr>
              <td>{camp['short']}</td>
              <td class="role">{camp['role']}</td>
              <td><span class="pill {pill}">{label}</span></td>
              <td class="num">{money(camp['spend']) if camp['spend'] else '$0'}</td>
              <td class="num">{num(camp['clicks'])}</td>
              <td class="num">{'$'+format(camp['cpc'],'.2f') if camp['clicks'] else '—'}</td>
              <td class="num">{num(camp['site_cta'])}</td>
              <td class="num">{num(camp['calls'])}</td>
            </tr>"""
        )
    rows.append(
        f"""            <tr class="total-row">
              <td>Search total</td>
              <td></td>
              <td></td>
              <td class="num">{money(c['spend'])}</td>
              <td class="num">{num(c['clicks'])}</td>
              <td class="num">${c['cpc']:.2f}</td>
              <td class="num">{num(c['site_cta'])}</td>
              <td class="num">{num(c['calls'])}</td>
            </tr>"""
    )
    cta_bits = " · ".join(f"{CTA_LABELS[k]} {c['cta'][k]}" for k in SITE_CTA_EVENTS)
    cls = lambda key: "up" if key.startswith("+") else ("flat" if key in ("flat", "new") else "down")
    spend_d, click_d, cta_d, call_d = pct(c["spend"], p["spend"]), pct(c["clicks"], p["clicks"]), pct(c["site_cta"], p["site_cta"]), pct(c["calls"], p["calls"])
    cpc_d = pct(c["cpc"], p["cpc"])

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<meta name="robots" content="noindex, nofollow"/>
<title>Google Ads Monthly — Audi Baton Rouge</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
:root {{
  --accent:#BB0A21; --ink:#0a0a0a; --muted:#6b6b6b; --line:#e0e0e0; --bg:#f3f3f3; --card:#FFFFFF;
  --stat:#fff; --why:#f8fafc; --why-ink:#243041; --row:#f0f2f5; --foot:#ececec;
  --good:#0f7b3a; --bad:#b42318; --radius:0px;
  --font:"Inter","Helvetica Neue",Helvetica,Arial,sans-serif;
}}
html[data-theme="dark"] {{
  --ink:#f3f3f3; --muted:#9a9a9a; --line:#2a2a2a; --bg:#111111; --card:#1a1a1a;
  --stat:#161616; --why:#161616; --why-ink:#d4d4d4; --row:#222; --foot:#1f1f1f;
  --good:#3dbe73; --bad:#f07167;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:var(--font); background:var(--bg); color:var(--ink); line-height:1.45; -webkit-font-smoothing:antialiased; }}
.top.has-photo {{
  position:relative; color:#fff; overflow:hidden;
  background-color:#0a0a0a; background-position:center; background-size:cover; background-repeat:no-repeat;
  border-bottom:4px solid var(--accent); padding:40px 16px 34px;
}}
.top.has-photo::before {{
  content:""; position:absolute; inset:0; z-index:0;
  background:linear-gradient(105deg, rgba(0,0,0,.82) 0%, rgba(0,0,0,.55) 48%, rgba(187,10,33,.28) 100%);
}}
.top.has-photo > .wrap {{ position:relative; z-index:1; }}
.top.has-photo .brand {{ color:rgba(255,255,255,.78); }}
.top.has-photo h1 {{ color:#fff; text-shadow:0 1px 10px rgba(0,0,0,.35); }}
.top.has-photo .sub {{ color:rgba(255,255,255,.9); }}
.wrap {{ max-width:920px; margin:0 auto; padding:18px 16px 48px; }}
.brand {{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.14em; font-weight:600; }}
h1 {{ font-size:28px; margin-top:6px; letter-spacing:-.04em; font-weight:700; }}
.sub {{ color:var(--muted); font-size:14px; margin-top:4px; }}
.meta {{ font-size:13px; color:var(--muted); margin:0 0 14px; }}
.theme-row {{ display:flex; justify-content:flex-end; margin:0 0 12px; }}
.theme-btn {{
  border:1px solid #c5c9d3; background:#fff; color:#111; border-radius:999px;
  padding:8px 14px; font:inherit; font-size:12.5px; font-weight:750; cursor:pointer;
}}
html[data-theme="dark"] .theme-btn {{ background:#1a1a1a; color:#f3f3f3; border-color:#3a3a3a; }}
.theme-btn:hover {{ border-color:var(--accent); color:var(--accent); }}
.verdict {{ background:#0a0a0a; color:#fff; border-radius:0; padding:18px; margin-bottom:14px; border-top:3px solid var(--accent); }}
.verdict .lbl {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; opacity:.7; }}
.verdict .txt {{ font-size:18px; font-weight:750; margin-top:8px; line-height:1.35; }}
.verdict .when {{ font-size:13px; opacity:.8; margin-top:10px; }}
.block {{ background:var(--card); border:1px solid var(--line); padding:18px; margin-bottom:14px; }}
.block h2 {{ font-size:18px; font-weight:800; margin-bottom:4px; letter-spacing:-.02em; }}
.when {{ font-size:13px; color:var(--muted); margin-bottom:10px; }}
.why {{ background:var(--why); border:1px solid var(--line); padding:12px; margin:0 0 14px; font-size:13px; color:var(--why-ink); }}
.why strong {{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin-bottom:4px; }}
.stat-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:12px 0; }}
.stat {{ background:var(--stat); border:1px solid var(--line); padding:12px; }}
.stat .k {{ font-size:10px; text-transform:uppercase; letter-spacing:.1em; color:var(--muted); font-weight:700; }}
.stat .v {{ font-size:22px; font-weight:850; margin-top:4px; letter-spacing:-.03em; font-variant-numeric:tabular-nums; }}
.stat .s {{ font-size:12px; color:var(--muted); margin-top:4px; }}
.up {{ color:var(--good); font-weight:700; }}
.down {{ color:var(--bad); font-weight:700; }}
.flat {{ color:var(--muted); }}
.table-scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; min-width:720px; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.1em; color:var(--muted); border-bottom:1px solid var(--line); padding:8px 6px; font-weight:600; }}
td {{ padding:10px 6px; border-bottom:1px solid var(--row); vertical-align:top; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
tr.total-row td {{ background:var(--foot); font-weight:800; border-top:2px solid var(--line); }}
.pill {{ display:inline-block; font-size:10px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; padding:2px 7px; }}
.pill.on {{ background:#eaf8ef; color:#0f7a3a; border:1px solid #b7e4c7; }}
.pill.off {{ background:#ececec; color:#666; border:1px solid #d0d0d0; }}
html[data-theme="dark"] .pill.on {{ background:#16301f; color:#3dbe73; border-color:#245c38; }}
html[data-theme="dark"] .pill.off {{ background:#2a2a2a; color:#999; border-color:#3a3a3a; }}
.role {{ color:var(--muted); font-size:12px; }}
.foot {{ font-size:12px; color:var(--muted); line-height:1.55; padding:6px 2px 0; }}
footer {{ text-align:center; color:var(--muted); font-size:11px; padding:18px; letter-spacing:.06em; text-transform:uppercase; }}
footer a {{ color:var(--accent); text-decoration:none; }}
@media (max-width:720px) {{
  html, body {{ overflow-x:hidden; }}
  .wrap {{ padding:14px 12px 40px; }}
  h1 {{ font-size:22px; }}
  .stat-grid {{ grid-template-columns:1fr; }}
  .table-scroll {{ margin-left:-12px; margin-right:-12px; padding-left:12px; padding-right:12px; }}
}}
</style>
</head>
<body>
  <div class="top has-photo" style="background-image:url('assets/abr-header.jpg');">
    <div class="wrap" style="padding-top:0;padding-bottom:0;">
      <div class="brand">Google Ads Monthly · Prepared by The Cooperative Agency</div>
      <h1>Audi Baton Rouge</h1>
      <div class="sub">Search campaigns only · {data['curr']['label']} vs {data['prior']['label']}</div>
    </div>
  </div>
  <div class="wrap page-main">
    <div class="meta">This page is for <strong>Audi Baton Rouge</strong> only · Coop ops · Generated {stamp} · <span id="conv-def">site CTA conversions</span></div>
    <div class="theme-row">
      <button type="button" class="theme-btn" id="themeBtn" aria-label="Toggle color theme">Dark mode</button>
    </div>

    <div class="verdict">
      <div class="lbl">One move</div>
      <div class="txt">{data['one_move']}</div>
      <div class="when">{data['curr']['label']} · compared with {data['prior']['label']}</div>
    </div>

    <div class="block">
      <h2>Month so far</h2>
      <div class="when">{data['curr']['label']} vs same days last month</div>
      <div class="stat-grid">
        <div class="stat">
          <div class="k">Spend</div>
          <div class="v">{money(c['spend'])}</div>
          <div class="s"><span class="{cls(spend_d)}">{spend_d}</span> · prior {money(p['spend'])}</div>
        </div>
        <div class="stat">
          <div class="k">Clicks</div>
          <div class="v">{num(c['clicks'])}</div>
          <div class="s"><span class="{cls(click_d)}">{click_d}</span> · prior {num(p['clicks'])}</div>
        </div>
        <div class="stat">
          <div class="k">Site CTAs</div>
          <div class="v">{num(c['site_cta'])}</div>
          <div class="s"><span class="{cls(cta_d)}">{cta_d}</span> · prior {num(p['site_cta'])}</div>
        </div>
        <div class="stat">
          <div class="k">Calls from ads</div>
          <div class="v">{num(c['calls'])}</div>
          <div class="s"><span class="{cls(call_d)}">{call_d}</span> · prior {num(p['calls'])}</div>
        </div>
        <div class="stat">
          <div class="k">Avg CPC</div>
          <div class="v">${c['cpc']:.2f}</div>
          <div class="s"><span class="{cls(cpc_d)}">{cpc_d}</span> · prior ${p['cpc']:.2f}</div>
        </div>
        <div class="stat">
          <div class="k">Impressions</div>
          <div class="v">{num(c['impr'])}</div>
          <div class="s">CTR {c['clicks']/c['impr']*100:.1f}% · prior {p['clicks']/p['impr']*100:.1f}%</div>
        </div>
      </div>
      <div class="why"><strong>What counts as a conversion on this page</strong>Site CTAs only: {cta_bits}. Page views on inventory lists or vehicle pages do not count. Ads call conversions stay in their own column.</div>
    </div>

    <div class="block">
      <h2>Campaigns</h2>
      <div class="when">Search only · site CTA vs Ads calls</div>
      <div class="table-scroll" role="region" aria-label="Scrollable table" tabindex="0">
        <table class="wide">
          <thead>
            <tr>
              <th>Campaign</th>
              <th>Role</th>
              <th>Status</th>
              <th class="num">Spend</th>
              <th class="num">Clicks</th>
              <th class="num">CPC</th>
              <th class="num">Site CTA</th>
              <th class="num">Ads calls</th>
            </tr>
          </thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>
      <div class="why"><strong>What this means</strong>Site CTA is the conversion column for Offers and models. Ads calls still matter for Brand and Service. Shopping VLA is not in this table.</div>
    </div>

    <p class="foot">Account {data['customer_id']} · search only · conversion definition locked in build_abr_google_ads_monthly.py · not a GM Weekly page.</p>
  </div>
  <footer>Audi Baton Rouge · Generated {stamp} · <a href="https://thecooperativeagency.github.io/email-creative/gm-weekly/abr.html">GM Weekly</a></footer>
<script>
(function () {{
  var root = document.documentElement;
  var btn = document.getElementById('themeBtn');
  function apply(theme) {{
    root.setAttribute('data-theme', theme);
    try {{ localStorage.setItem('abr-ads-theme', theme); }} catch (e) {{}}
    btn.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
  }}
  var saved = null;
  try {{ saved = localStorage.getItem('abr-ads-theme'); }} catch (e) {{}}
  apply(saved === 'dark' || saved === 'light' ? saved : 'light');
  btn.addEventListener('click', function () {{
    apply(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  }});
}})();
</script>
</body>
</html>
"""


def main() -> None:
    start, end, pstart, pend = windows()
    token = pipeboard_token()
    print(f"Window curr {start}–{end} prior {pstart}–{pend}")
    curr_camps, curr_tot = ads_window(token, start, end)
    prior_camps, prior_tot = ads_window(token, pstart, pend)
    curr_cta, curr_cta_tot = ga4_ctas(start, end)
    prior_cta, prior_cta_tot = ga4_ctas(pstart, pend)
    attach_ctas(curr_camps, curr_tot, curr_cta, curr_cta_tot)
    attach_ctas(prior_camps, prior_tot, prior_cta, prior_cta_tot)
    payload = {
        "store": "Audi Baton Rouge",
        "customer_id": CID,
        "generated": date.today().isoformat(),
        "conv_def": list(SITE_CTA_EVENTS),
        "curr": {"start": start.isoformat(), "end": end.isoformat(), "label": fmt_range(start, end)},
        "prior": {"start": pstart.isoformat(), "end": pend.isoformat(), "label": fmt_range(pstart, pend)},
        "totals": {"curr": curr_tot, "prior": prior_tot},
        "campaigns": curr_camps,
        "one_move": one_move(curr_camps, curr_tot),
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(payload, indent=2))
    HTML_PATH.write_text(render(payload))
    print(f"Wrote {DATA_PATH}")
    print(f"Wrote {HTML_PATH}")
    print(f"site_cta={curr_tot['site_cta']} calls={curr_tot['calls']} spend={curr_tot['spend']}")


if __name__ == "__main__":
    main()
