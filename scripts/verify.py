#!/usr/bin/env python3
"""Verify realized savings: diff audit-day findings against current account state.

The closing half of find → clear → verify. Re-run the collectors into a fresh
directory, then diff against the saved audit-day findings:

  resolved     — in the audit, gone now: savings realized
  still_open   — in the audit, still present: savings on the table
  new          — not in the audit: new waste since (retainer material)

Optionally pulls Cost Explorer month totals for bill-level context; degrades
gracefully when CE is unavailable. Read-only throughout.

Usage:
  python3 collect/orphans.py --out after/orphans.json          # fresh state first
  python3 verify.py --before findings/before-2026-07-04.json \
                    --after after/ --out VERIFICATION_REPORT.md [--profile p]
"""

import argparse
import datetime as dt
import json
import pathlib
import sys

from botocore.config import Config
from botocore.exceptions import ClientError

BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "adaptive"})
CONTEXT_FILES = {"spend.json"}


def fmt_usd(x: float) -> str:
    return f"${x:,.0f}"


def load(path: pathlib.Path):
    findings = []
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    for f in files:
        if f.name in CONTEXT_FILES:
            continue
        findings.extend(json.loads(f.read_text()))
    return {f["resource_id"]: f for f in findings}


def ce_month_totals(profile):
    """Bill totals for the last 3 full months, or None if CE unavailable."""
    import boto3
    session = boto3.Session(profile_name=profile)
    ce = session.client("ce", region_name="us-east-1", config=BOTO_CFG)
    first = dt.date.today().replace(day=1)
    start = first
    for _ in range(3):
        start = (start - dt.timedelta(days=1)).replace(day=1)
    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": first.isoformat()},
            Granularity="MONTHLY", Metrics=["UnblendedCost"],
        )
    except ClientError:
        return None
    return {p["TimePeriod"]["Start"][:7]: float(p["Total"]["UnblendedCost"]["Amount"])
            for p in resp["ResultsByTime"]}


def generate(before, after, month_totals) -> str:
    resolved = {rid: f for rid, f in before.items() if rid not in after}
    still_open = {rid: f for rid, f in before.items() if rid in after}
    new = {rid: f for rid, f in after.items() if rid not in before}

    realized = sum(f["estimated_monthly_savings"] for f in resolved.values())
    found = sum(f["estimated_monthly_savings"] for f in before.values())
    open_total = sum(f["estimated_monthly_savings"] for f in still_open.values())
    new_total = sum(f["estimated_monthly_savings"] for f in new.values())
    ratio = (realized / found * 100) if found else 0

    lines = [
        "# Savings Verification Report",
        "",
        f"*{dt.date.today().isoformat()}*",
        "",
        f"## Realized: {fmt_usd(realized)}/month ({fmt_usd(realized * 12)}/year)",
        "",
        f"**{len(resolved)} of {len(before)} audit findings resolved — "
        f"{ratio:.0f}% of identified savings realized.**",
        "",
        "| | Findings | Est. monthly |",
        "|---|---|---|",
        f"| ✅ Resolved (realized) | {len(resolved)} | {fmt_usd(realized)} |",
        f"| ⏳ Still open | {len(still_open)} | {fmt_usd(open_total)} |",
        f"| 🆕 New since audit | {len(new)} | {fmt_usd(new_total)} |",
        "",
    ]

    if month_totals:
        months = sorted(month_totals)
        lines += [
            "## Bill context (Cost Explorer actuals)",
            "",
            " → ".join(f"{m}: {fmt_usd(month_totals[m])}" for m in months),
            "",
            "Estimated savings are per-resource list prices; the bill also moves with "
            "usage growth. Attribute at resource level (above), not bill level.",
            "",
        ]

    def section(title, items):
        if not items:
            return []
        out = [f"## {title}", ""]
        for f in sorted(items.values(), key=lambda x: -x["estimated_monthly_savings"]):
            out.append(f"- `{f['resource_id']}` ({f['resource_type']}, {f['region']}) — "
                       f"{fmt_usd(f['estimated_monthly_savings'])}/mo")
        out.append("")
        return out

    lines += section("Resolved", resolved)
    lines += section("Still open — savings on the table", still_open)
    lines += section("New waste since audit", new)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", required=True, help="audit-day findings JSON file or dir")
    ap.add_argument("--after", required=True, help="fresh findings JSON file or dir")
    ap.add_argument("--out", default="VERIFICATION_REPORT.md")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--no-ce", action="store_true", help="skip Cost Explorer context")
    args = ap.parse_args()

    before = load(pathlib.Path(args.before))
    after = load(pathlib.Path(args.after))
    if not before:
        sys.exit("no before-findings — nothing to verify against")

    month_totals = None if args.no_ce else ce_month_totals(args.profile)
    pathlib.Path(args.out).write_text(generate(before, after, month_totals))

    resolved = [r for r in before if r not in after]
    realized = sum(before[r]["estimated_monthly_savings"] for r in resolved)
    found = sum(f["estimated_monthly_savings"] for f in before.values())
    print(f"Verification → {args.out}: {len(resolved)}/{len(before)} findings resolved, "
          f"{fmt_usd(realized)}/mo realized ({realized / found * 100:.0f}% of found)"
          if found else "nothing found in before-state")


if __name__ == "__main__":
    main()
