#!/usr/bin/env python3
"""Savings Plan / Reserved Instance coverage analysis — checklist item A2.

Read-only: Cost Explorer Get* calls only. CE is a global endpoint (us-east-1);
no region loop. Note: each CE API request costs $0.01 — a full run is ~$0.05.

Finds:
  - uncovered steady-state compute spend (uses AWS's own 1yr no-upfront Compute SP
    recommendation, including its EstimatedMonthlySavingsAmount — defensible number)
  - underutilized existing Savings Plans (committed $ evaporating unused)
  - underutilized Reserved Instances

Usage:
  python3 commitments.py --out findings/commitments.json [--profile p]
"""

import argparse
import datetime as dt
import json
import pathlib
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from finding import Finding

CHECKLIST_ITEM = "A2-commitments"
UTILIZATION_FLOOR = 90.0  # % below which a commitment is a finding

BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "adaptive"})


def month_range(months_back=3):
    today = dt.date.today()
    first_of_this_month = today.replace(day=1)
    start = (first_of_this_month - dt.timedelta(days=months_back * 31)).replace(day=1)
    return start.isoformat(), first_of_this_month.isoformat()


def sp_purchase_recommendation(ce):
    """AWS's own recommendation: 1yr no-upfront Compute SP, 60-day lookback."""
    findings = []
    resp = ce.get_savings_plans_purchase_recommendation(
        SavingsPlansType="COMPUTE_SP",
        TermInYears="ONE_YEAR",
        PaymentOption="NO_UPFRONT",
        LookbackPeriodInDays="SIXTY_DAYS",
    )
    rec = resp.get("SavingsPlansPurchaseRecommendation", {})
    summary = rec.get("SavingsPlansPurchaseRecommendationSummary", {})
    monthly_savings = float(summary.get("EstimatedMonthlySavingsAmount", 0) or 0)
    if monthly_savings < 1:
        return findings

    hourly_commit = summary.get("HourlyCommitmentToPurchase", "?")
    savings_pct = summary.get("EstimatedSavingsPercentage", "?")
    on_demand = float(summary.get("EstimatedOnDemandCostWithCurrentCommitment", 0) or 0)
    findings.append(Finding(
        resource_id="compute-savings-plan-gap",
        resource_type="savings-plan-coverage",
        region="global",
        checklist_item=CHECKLIST_ITEM,
        evidence=(f"AWS recommends a 1yr no-upfront Compute SP at ${hourly_commit}/hr commitment "
                  f"based on 60-day usage: ~{savings_pct}% savings on "
                  f"${on_demand:,.0f}/mo of currently on-demand spend. "
                  f"Estimate is AWS's own (Cost Explorer recommendation), not ours."),
        estimated_monthly_savings=monthly_savings,
        remediation_steps=[
            "Sanity-check the workload baseline is stable (no planned migration/shutdown "
            "of the covered compute in the next 12 months)",
            "Prefer covering ~80% of the trailing minimum, never peak — it's fine to "
            "buy a smaller commitment than recommended",
            f"Purchase in console: Billing → Savings Plans → recommendations, "
            f"or: aws savingsplans create-savings-plan (1yr, no-upfront, ${hourly_commit}/hr)",
        ],
        risk="medium",
        clearances=["recommendation computed by AWS Cost Explorer from actual 60-day usage"],
    ))
    return findings


def sp_utilization(ce, start, end):
    """Existing Savings Plans burning committed dollars unused."""
    findings = []
    resp = ce.get_savings_plans_utilization(TimePeriod={"Start": start, "End": end})
    total = resp.get("Total", {})
    util = total.get("Utilization", {})
    pct = float(util.get("UtilizationPercentage", 100) or 100)
    if pct >= UTILIZATION_FLOOR:
        return findings
    unused = float(util.get("UnusedCommitment", 0) or 0)
    months = max(1, (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days // 30)
    findings.append(Finding(
        resource_id="savings-plan-utilization",
        resource_type="savings-plan-waste",
        region="global",
        checklist_item=CHECKLIST_ITEM,
        evidence=(f"Savings Plan utilization {pct:.1f}% over {start}→{end}; "
                  f"${unused:,.0f} of committed spend went unused in the period"),
        estimated_monthly_savings=unused / months,
        remediation_steps=[
            "Identify which workload shrank or moved off covered usage "
            "(Cost Explorer → Savings Plans → Utilization report)",
            "Shift eligible workloads onto covered compute (SP applies across "
            "EC2/Fargate/Lambda automatically — check what left)",
            "Factor the unused commitment into any new purchase decisions; "
            "commitments can't be cancelled, only grown into",
        ],
        risk="low",
    ))
    return findings


def ri_utilization(ce, start, end):
    """Legacy Reserved Instances with poor utilization."""
    findings = []
    resp = ce.get_reservation_utilization(TimePeriod={"Start": start, "End": end})
    total = resp.get("Total", {})
    pct = float(total.get("UtilizationPercentage", 100) or 100)
    if pct >= UTILIZATION_FLOOR:
        return findings
    unused_hours = total.get("UnusedHours", "0")
    net_savings = float(total.get("NetRISavings", 0) or 0)
    months = max(1, (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days // 30)
    # negative NetRISavings = RIs cost more than the on-demand equivalent used
    wasted = abs(min(net_savings, 0.0))
    findings.append(Finding(
        resource_id="reserved-instance-utilization",
        resource_type="reserved-instance-waste",
        region="global",
        checklist_item=CHECKLIST_ITEM,
        evidence=(f"RI utilization {pct:.1f}% over {start}→{end}, {unused_hours} unused hours"
                  + (f"; RIs currently NET-NEGATIVE by ${wasted:,.0f} vs on-demand"
                     if wasted else "")),
        estimated_monthly_savings=wasted / months if wasted else 0.0,
        remediation_steps=[
            "List underused RIs: aws ce get-reservation-utilization --group-by Type=DIMENSION,Key=SUBSCRIPTION_ID",
            "Convertible RIs: exchange for a family/size you actually run",
            "Standard RIs: sell on the RI Marketplace, or resize instances into them",
            "Stop auto-renewing; replace expiring RIs with Compute SPs (flexible)",
        ],
        risk="low",
    ))
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="findings/commitments.json")
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    session = boto3.Session(profile_name=args.profile)
    ce = session.client("ce", region_name="us-east-1", config=BOTO_CFG)
    start, end = month_range()

    all_findings = []
    steps = [
        ("SP purchase recommendation", lambda: sp_purchase_recommendation(ce)),
        ("SP utilization", lambda: sp_utilization(ce, start, end)),
        ("RI utilization", lambda: ri_utilization(ce, start, end)),
    ]
    for label, fn in steps:
        try:
            found = fn()
            all_findings.extend(found)
            print(f"  {label}: {len(found)} finding(s)", file=sys.stderr)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("AccessDeniedException", "AccessDenied", "DataUnavailableException"):
                print(f"  {label}: skipped ({code})", file=sys.stderr)
            else:
                raise

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([f.to_dict() for f in all_findings], indent=2, default=str))

    total = sum(f.estimated_monthly_savings for f in all_findings)
    print(f"\n{len(all_findings)} findings, est. ${total:,.0f}/month "
          f"(${total * 12:,.0f}/year) → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
