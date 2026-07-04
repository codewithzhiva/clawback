#!/usr/bin/env python3
"""Spend context for the report header — not a waste finding, executive orientation.

Read-only: one Cost Explorer GetCostAndUsage call (~$0.01).
Last 3 full months, grouped by service.

Usage:
  python3 spend_summary.py --out findings/spend.json [--profile p]
"""

import argparse
import datetime as dt
import json
import pathlib
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "adaptive"})


def month_range(months_back=3):
    first_of_this_month = dt.date.today().replace(day=1)
    start = first_of_this_month
    for _ in range(months_back):
        start = (start - dt.timedelta(days=1)).replace(day=1)
    return start.isoformat(), first_of_this_month.isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="findings/spend.json")
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    session = boto3.Session(profile_name=args.profile)
    ce = session.client("ce", region_name="us-east-1", config=BOTO_CFG)
    start, end = month_range()

    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"].get("Message", "")
        if code in ("AccessDeniedException", "AccessDenied", "DataUnavailableException"):
            sys.exit(f"Cost Explorer unavailable ({code}: {msg}). "
                     "If never enabled on this account: Billing console → Cost Explorer "
                     "→ enable, data appears within 24h. Report will render without "
                     "the spend-context header.")
        raise

    months = []
    by_service = {}
    for period in resp["ResultsByTime"]:
        month = period["TimePeriod"]["Start"][:7]
        months.append(month)
        for group in period["Groups"]:
            svc = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            by_service.setdefault(svc, {})[month] = amount

    total_by_month = {
        m: sum(v.get(m, 0.0) for v in by_service.values()) for m in months
    }
    top_services = sorted(
        ((svc, sum(vals.values()) / len(months)) for svc, vals in by_service.items()),
        key=lambda kv: -kv[1],
    )[:5]

    summary = {
        "months": months,
        "total_by_month": total_by_month,
        "avg_monthly_total": sum(total_by_month.values()) / max(1, len(months)),
        "top_services": [{"service": s, "avg_monthly": round(v, 2)} for s, v in top_services],
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(f"Spend summary ({start} → {end}) → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
