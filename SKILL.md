---
name: clawback
description: Audit an AWS account for cost waste using a proven 12-item methodology (orphaned resources, right-sizing, commitments, scheduling, storage tiering). Read-only — never modifies infrastructure. Use when the user wants to find AWS savings, audit their AWS bill, or asks why their AWS costs are high.
---

# Clawback — AWS Cost Audit

You are running a structured AWS cost audit. The methodology found ~$370K/year of savings on a Fortune-500 account; it works on any account. **You never modify infrastructure** — every command in this skill is read-only (`Describe*`, `List*`, `Get*`). If a step would require a write call, stop and put it in the report as a remediation step instead.

## Step 0 — Preflight

1. Confirm AWS credentials work and identify the account:
   ```
   aws sts get-caller-identity
   ```
   Ask which profile/region set to use if ambiguous. Prefer a read-only role/profile if the user has one.
2. Confirm Python 3.9+ and boto3 are available (`python3 -c "import boto3"`). If boto3 is missing, `pip install boto3`.
3. Ask the user for their approximate monthly AWS spend if they haven't said — it calibrates which findings matter.

## Step 1 — Automated collection

Run the collectors from this skill's `scripts/` directory into `findings/`:

```
python3 scripts/collect/spend_summary.py --out findings/spend.json      # bill context (1 CE call, ~$0.01)
python3 scripts/collect/orphans.py --out findings/orphans.json          # A4: orphaned/idle, safety-verified
python3 scripts/collect/commitments.py --out findings/commitments.json  # A2: SP/RI coverage (~$0.05 CE)
```

Options: `--profile <name>`; orphans also takes `--regions us-east-1,eu-west-1` (defaults to all enabled regions). Collection takes a few minutes on multi-region accounts; run it in the background if long.

The orphans collector safety-verifies findings (snapshot→AMI refs, NAT→route tables, LB/EIP→Route53): ✅ cleared findings are safe to act on; BLOCKED findings have a live reference named in the evidence — surface these prominently, they're the ones that would cause an outage if deleted naively.

## Step 2 — Manual checklist sweep

Collectors don't cover everything yet. Walk `reference/checklist.md` top-to-bottom and, for each item without a collector, investigate with read-only `aws` CLI calls (the checklist lists the exact commands and thresholds per item). Prioritize Tier A — it typically holds 60–80% of savings:

1. Compute right-sizing (CloudWatch CPU/memory vs provisioned)
2. Savings Plan / RI coverage and utilization
3. Non-prod scheduling opportunities
4. Orphaned & idle resources (automated above)
5. Graviton migration candidates

Record every manual finding in the same JSON schema the collectors emit (see `scripts/finding.py`) and append to a `findings/manual.json` file.

## Step 3 — Analysis and ranking

- Load all `findings/*.json`.
- Sanity-check savings estimates against the user's stated monthly spend — if findings total more than ~70% of the bill, something is double-counted; investigate before reporting.
- Rank by estimated monthly savings × ease of implementation. Low-risk/high-dollar first.

## Step 4 — Report

Generate the report:

```
python3 scripts/report.py --findings findings/ --out AUDIT_REPORT.md          # markdown
python3 scripts/report_html.py --findings findings/ --out AUDIT_REPORT.html   # shareable single-file HTML
```

Markdown for working in the terminal/repo; HTML when the user wants to share the
report (email attachment, non-technical stakeholders) — it's fully self-contained.

Then present the user a summary in chat: total estimated monthly/annual savings, top 5 findings with dollar amounts, and the single easiest win they can do today. Reference `reference/remediation/` guides for safe implementation steps and risk ratings — never execute remediations yourself; the report is the deliverable.

## Step 5 — Verification (follow-up sessions)

When the user has implemented fixes and wants proof the savings landed, or asks
"did it work" after a previous audit:

```
python3 scripts/collect/orphans.py --out findings/after/orphans.json   # fresh state
python3 scripts/verify.py --before <audit-day findings> --after findings/after/ \
        --out VERIFICATION_REPORT.md
```

Present: realized $/month, the realized-vs-found percentage, still-open findings
ranked by savings, and any new waste since the audit. This is why keeping the raw
audit-day findings JSON matters.

## Rules

- Read-only, always. No `Create*`, `Delete*`, `Modify*`, `Terminate*`, `Put*` calls under any circumstances, even if the user asks — direct them to the remediation guide instead.
- Every finding needs evidence (metric values, resource IDs, ages) — no hand-waving.
- Savings estimates use `scripts/pricing.py` (us-east-1 baseline). State the assumption in the report.
- Keep raw findings JSON — the user may want to re-run and diff after implementing fixes.
