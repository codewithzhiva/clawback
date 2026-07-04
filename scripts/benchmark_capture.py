#!/usr/bin/env python3
"""Capture anonymized audit stats for the waste-benchmark dataset.

Privacy contract: NO client identifiers are ever stored — no account IDs, no
resource IDs, no service-level costs. Only: spend band, waste %, top waste
categories, finding counts. The raw dataset lives outside the repo by default.

Usage:
  python3 benchmark_capture.py --findings findings/            # append one audit's stats
  python3 benchmark_capture.py --aggregate                     # regenerate reference/benchmarks.json
"""

import argparse
import datetime as dt
import json
import pathlib
import statistics
import sys

DEFAULT_DATASET = pathlib.Path.home() / ".cloudcost" / "benchmarks-raw.jsonl"
BENCHMARKS_OUT = pathlib.Path(__file__).resolve().parents[1] / "reference" / "benchmarks.json"
MIN_AUDITS_TO_PUBLISH = 10

BANDS = [(0, 5_000, "0-5k"), (5_000, 20_000, "5k-20k"),
         (20_000, 50_000, "20k-50k"), (50_000, float("inf"), "50k+")]


def spend_band(avg_monthly: float) -> str:
    for lo, hi, label in BANDS:
        if lo <= avg_monthly < hi:
            return label
    return "50k+"


def capture(findings_dir: pathlib.Path, dataset: pathlib.Path):
    spend_file = findings_dir / "spend.json"
    if not spend_file.exists():
        sys.exit("spend.json required (run spend_summary.py) — waste % needs a denominator")
    spend = json.loads(spend_file.read_text())

    findings = []
    for f in sorted(findings_dir.glob("*.json")):
        if f.name == "spend.json":
            continue
        findings.extend(json.loads(f.read_text()))
    if not findings:
        sys.exit("no findings to capture")

    monthly_savings = sum(f["estimated_monthly_savings"] for f in findings)
    avg_bill = spend["avg_monthly_total"]
    by_type = {}
    for f in findings:
        by_type[f["resource_type"]] = by_type.get(f["resource_type"], 0) \
            + f["estimated_monthly_savings"]
    top_categories = sorted(by_type, key=by_type.get, reverse=True)[:3]

    record = {
        "month": dt.date.today().strftime("%Y-%m"),
        "spend_band": spend_band(avg_bill),
        "waste_pct": round(monthly_savings / avg_bill * 100, 1) if avg_bill else 0,
        "finding_count": len(findings),
        "top_categories": top_categories,
    }
    dataset.parent.mkdir(parents=True, exist_ok=True)
    with dataset.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    print(f"Captured (anonymized): {record}")


def aggregate(dataset: pathlib.Path):
    if not dataset.exists():
        sys.exit(f"no dataset at {dataset}")
    records = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    if len(records) < MIN_AUDITS_TO_PUBLISH:
        sys.exit(f"{len(records)} audits captured; benchmarks publish at {MIN_AUDITS_TO_PUBLISH} "
                 "(small-n numbers are noise, not benchmarks)")

    bands = {}
    for _, _, label in BANDS:
        pcts = sorted(r["waste_pct"] for r in records if r["spend_band"] == label)
        if len(pcts) >= 3:  # don't publish a band from 1-2 data points
            bands[label] = {
                "median_waste_pct": round(statistics.median(pcts), 1),
                "top_quartile_waste_pct": round(pcts[max(0, len(pcts) // 4 - 1)], 1),
                "n": len(pcts),
            }

    out = {
        "updated": dt.date.today().isoformat(),
        "audit_count": len(records),
        "bands": bands,
    }
    BENCHMARKS_OUT.write_text(json.dumps(out, indent=2))
    print(f"Benchmarks from {len(records)} audits → {BENCHMARKS_OUT}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--findings", default="findings/")
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--aggregate", action="store_true")
    args = ap.parse_args()

    dataset = pathlib.Path(args.dataset)
    if args.aggregate:
        aggregate(dataset)
    else:
        capture(pathlib.Path(args.findings), dataset)


if __name__ == "__main__":
    main()
