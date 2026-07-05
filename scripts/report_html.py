#!/usr/bin/env python3
"""Generate a self-contained HTML audit report — the shareable/client-facing artifact.

Same findings JSON as report.py; output is one file with inline CSS and SVG
(no external assets, no JS beyond native <details>): attach it to an email,
open it offline, print it.

Usage:
  python3 report_html.py --findings findings/ --out AUDIT_REPORT.html
"""

import argparse
import html
import json
import pathlib
from collections import defaultdict
from datetime import date

from report import load_findings, load_spend, BENCHMARKS_FILE, BAND_BOUNDS

BOOKING_URL = "https://calendly.com/workwithzhiva/30min"
REPO_URL = "https://github.com/codewithzhiva/clawback"

RISK_STYLE = {
    "low": ("Low risk", "#0a7d33", "#e5f5ea"),
    "medium": ("Medium risk", "#946200", "#fdf3d7"),
    "high": ("BLOCKED", "#b3261e", "#fbe9e7"),
}

CSS = """
:root { --ink:#1a2332; --muted:#5b6779; --line:#e4e8ee; --accent:#0a7d33;
        --bg:#f7f9fb; --card:#ffffff; }
* { box-sizing:border-box; margin:0; }
body { font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       color:var(--ink); background:var(--bg); padding:0; }
.wrap { max-width:840px; margin:0 auto; padding:40px 28px 64px; }
header .brand { font-size:13px; font-weight:700; letter-spacing:.14em;
                text-transform:uppercase; color:var(--accent); }
header h1 { font-size:26px; margin:6px 0 2px; }
header .date { color:var(--muted); font-size:13px; }
.hero { background:var(--card); border:1px solid var(--line); border-radius:14px;
        padding:28px; margin:26px 0; display:flex; gap:32px; flex-wrap:wrap;
        align-items:baseline; }
.hero .big { font-size:44px; font-weight:800; color:var(--accent); }
.hero .big small { font-size:18px; font-weight:600; color:var(--muted); }
.hero .sub { color:var(--muted); font-size:14px; }
.badges { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
.badge { font-size:12px; font-weight:600; padding:3px 10px; border-radius:999px; }
h2 { font-size:17px; margin:34px 0 12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:20px; margin-bottom:12px; }
.f-head { display:flex; justify-content:space-between; gap:12px; align-items:center;
          flex-wrap:wrap; }
.f-title { font-weight:700; font-size:15px; }
.f-title code { font:13px ui-monospace,Menlo,monospace; background:var(--bg);
                padding:2px 6px; border-radius:6px; }
.f-money { font-weight:800; font-size:18px; color:var(--accent); white-space:nowrap; }
.f-meta { color:var(--muted); font-size:13px; margin:6px 0 0; }
.clear { color:var(--accent); font-size:13px; margin-top:6px; }
details { margin-top:10px; }
summary { cursor:pointer; font-size:13px; font-weight:600; color:var(--muted); }
details ol { margin:8px 0 0 20px; font-size:13.5px; }
details li { margin-bottom:4px; }
table { border-collapse:collapse; width:100%; font-size:14px; }
td,th { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; font-size:12.5px; text-transform:uppercase;
     letter-spacing:.05em; }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
.note { color:var(--muted); font-size:12.5px; margin-top:8px; }
.cta { background:var(--ink); color:#fff; border-radius:14px; padding:26px;
       margin-top:40px; }
.cta a.btn { display:inline-block; background:var(--accent); color:#fff;
             text-decoration:none; font-weight:700; padding:10px 22px;
             border-radius:8px; margin-top:12px; }
.cta p { font-size:14px; color:#c8d0dc; }
.cta .lead { font-size:16px; color:#fff; font-weight:600; }
footer { color:var(--muted); font-size:12px; margin-top:22px; }
footer a { color:var(--muted); }
@media print { .hero,.card,.cta { break-inside:avoid; } }
"""


def usd(x):
    return f"${x:,.0f}"


def esc(s):
    return html.escape(str(s), quote=True)


def category_bars(by_type):
    """Horizontal SVG bar chart of estimated savings by resource type."""
    rows = sorted(((t, sum(f["estimated_monthly_savings"] for f in fs))
                   for t, fs in by_type.items()), key=lambda kv: -kv[1])
    if not rows:
        return ""
    top = rows[0][1] or 1
    bar_h, gap, label_w = 22, 10, 250
    height = len(rows) * (bar_h + gap)
    parts = [f'<svg viewBox="0 0 840 {height}" role="img" '
             f'aria-label="Savings by category" style="width:100%;height:auto">']
    for i, (t, total) in enumerate(rows):
        y = i * (bar_h + gap)
        w = max(4, (total / top) * (840 - label_w - 90))
        parts.append(
            f'<text x="{label_w - 10}" y="{y + 15}" text-anchor="end" '
            f'font-size="13" fill="#5b6779">{esc(t)}</text>'
            f'<rect x="{label_w}" y="{y}" width="{w:.0f}" height="{bar_h}" '
            f'rx="4" fill="#0a7d33" opacity="{1 - i * 0.12:.2f}"/>'
            f'<text x="{label_w + w + 8:.0f}" y="{y + 15}" font-size="13" '
            f'font-weight="700" fill="#1a2332">{usd(total)}/mo</text>')
    parts.append("</svg>")
    return "".join(parts)


def trend_bars(spend):
    months = spend["months"]
    totals = [spend["total_by_month"][m] for m in months]
    top = max(totals) or 1
    w, h, bw = 90, 64, 56
    parts = [f'<svg viewBox="0 0 {len(months) * w} {h + 22}" '
             f'style="height:86px" role="img" aria-label="Bill trend">']
    for i, (m, v) in enumerate(zip(months, totals)):
        bh = max(3, v / top * h)
        x = i * w + (w - bw) / 2
        parts.append(
            f'<rect x="{x:.0f}" y="{h - bh:.0f}" width="{bw}" height="{bh:.0f}" '
            f'rx="4" fill="#8fb8a0"/>'
            f'<text x="{i * w + w / 2:.0f}" y="{h + 15}" text-anchor="middle" '
            f'font-size="11" fill="#5b6779">{esc(m)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def benchmark_html(spend, monthly):
    if not BENCHMARKS_FILE.exists() or not spend or not spend["avg_monthly_total"]:
        return ""
    bm = json.loads(BENCHMARKS_FILE.read_text())
    avg = spend["avg_monthly_total"]
    band = next(label for lo, hi, label in BAND_BOUNDS if lo <= avg < hi)
    stats = bm.get("bands", {}).get(band)
    if not stats:
        return ""
    return (f"<h2>How you compare</h2><div class='card'>Across {bm['audit_count']} "
            f"audits in your spend band ({esc(band)}/mo): median waste is "
            f"<b>{stats['median_waste_pct']}%</b> of the bill; the leanest quartile runs at "
            f"<b>{stats['top_quartile_waste_pct']}%</b>. This audit found "
            f"<b>{monthly / avg * 100:.0f}%</b> in yours.</div>")


def finding_card(f):
    label, fg, bg = RISK_STYLE.get(f["risk"], RISK_STYLE["medium"])
    clearances = "".join(f"<div class='clear'>✓ Verified: {esc(c)}</div>"
                         for c in f.get("clearances", []))
    steps = "".join(f"<li>{esc(s)}</li>" for s in f["remediation_steps"])
    return f"""<div class="card">
  <div class="f-head">
    <div class="f-title">{esc(f['resource_type'])} <code>{esc(f['resource_id'])}</code>
      <span class="badge" style="color:{fg};background:{bg}">{label}</span></div>
    <div class="f-money">{usd(f['estimated_monthly_savings'])}/mo</div>
  </div>
  <div class="f-meta">{esc(f['region'])} · {esc(f['evidence'])}</div>
  {clearances}
  <details><summary>How to fix ({len(f['remediation_steps'])} steps)</summary>
    <ol>{steps}</ol></details>
</div>"""


def generate(findings, spend):
    findings.sort(key=lambda f: -f["estimated_monthly_savings"])
    monthly = sum(f["estimated_monthly_savings"] for f in findings)
    cleared = sum(1 for f in findings if f.get("clearances"))
    blocked = sum(1 for f in findings if f["risk"] == "high")

    by_type = defaultdict(list)
    for f in findings:
        by_type[f["resource_type"]].append(f)

    spend_html = ""
    if spend and spend["avg_monthly_total"]:
        avg = spend["avg_monthly_total"]
        pct = monthly / avg * 100
        svc_rows = "".join(
            f"<tr><td>{esc(s['service'])}</td>"
            f"<td class='num'>{usd(s['avg_monthly'])}</td></tr>"
            for s in spend["top_services"])
        spend_html = f"""<h2>Your spend, in context</h2>
<div class="card">
  <div style="display:flex;gap:28px;flex-wrap:wrap;align-items:center">
    <div>{trend_bars(spend)}</div>
    <div><b>{usd(avg)}/month</b> average bill<br>
      <span style="color:var(--muted);font-size:13px">recoverable waste found:
      <b style="color:var(--accent)">{pct:.0f}% of your bill</b></span></div>
  </div>
  <table style="margin-top:14px"><tr><th>Top services</th><th class="num">Avg / month</th></tr>
  {svc_rows}</table>
</div>"""

    cards = "".join(finding_card(f) for f in findings)
    badge = lambda txt, fg, bg: (f"<span class='badge' "
                                 f"style='color:{fg};background:{bg}'>{txt}</span>")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clawback — AWS Cost Audit Report</title><style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <div class="brand">Clawback</div>
  <h1>AWS Cost Audit Report</h1>
  <div class="date">{date.today().strftime('%B %d, %Y')} · read-only audit ·
    estimates at us-east-1 list prices (±20% by region)</div>
</header>

<div class="hero">
  <div>
    <div class="big">{usd(monthly)}<small>/month recoverable</small></div>
    <div class="sub">{usd(monthly * 12)} per year across {len(findings)} findings</div>
    <div class="badges">
      {badge(f"✓ {cleared} safety-cleared", "#0a7d33", "#e5f5ea")}
      {badge(f"⛔ {blocked} blocked by live references", "#b3261e", "#fbe9e7") if blocked else ""}
      {badge("read-only audit — nothing was modified", "#33415c", "#eef1f6")}
    </div>
  </div>
</div>

{spend_html}
{benchmark_html(spend, monthly)}

<h2>Where the money is</h2>
<div class="card">{category_bars(by_type)}</div>

<h2>Findings, highest savings first</h2>
<p class="note">✓ Verified lines are automated safety cross-checks (AMI references,
route tables, DNS records) that passed — these findings are cleared to act on.
BLOCKED findings name the live reference that must be handled first.</p>
{cards}

<div class="cta">
  <div class="lead">Want these implemented — and the savings guaranteed?</div>
  <p>I do this on gain-share: no savings, no fee. Implementation through your change
  process, results measured by the same open-source verify tooling that produced
  this report.</p>
  <a class="btn" href="{BOOKING_URL}">Book a call</a>
</div>

<footer>Generated by <a href="{REPO_URL}">Clawback</a> — the open-source AWS audit
built from a playbook that recovered $370K/year on a Fortune-500 account.</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--findings", default="findings/", help="findings dir or single JSON file")
    ap.add_argument("--out", default="AUDIT_REPORT.html")
    args = ap.parse_args()

    findings = load_findings(pathlib.Path(args.findings))
    if not findings:
        print("No findings found — run the collectors first.")
        return
    spend = load_spend(pathlib.Path(args.findings))
    pathlib.Path(args.out).write_text(generate(findings, spend))
    monthly = sum(f["estimated_monthly_savings"] for f in findings)
    print(f"HTML report → {args.out}: {len(findings)} findings, "
          f"{usd(monthly)}/mo ({usd(monthly * 12)}/yr)")


if __name__ == "__main__":
    main()
