# Clawback

**Find out what AWS owes you.**

The open-source AWS cost audit built from a playbook that recovered **$370K/year** on a
Fortune-500 account — packaged as a [Claude Code](https://claude.com/claude-code) skill
and standalone Python collectors.

![Clawback auditing a live AWS account](assets/demo.gif)

Most companies under $100K/month have nobody watching the bill and waste **30–60%** of
it. Every cost tool on GitHub will hand you a list of suspects. Clawback is built
around what happens *after* the list:

## Find → Clear → Verify

**🔍 Find** — 12-item methodology ordered by dollar impact: orphaned resources,
right-sizing, Savings Plan coverage, non-prod scheduling, storage tiering,
data-transfer leaks. Every finding ships with evidence, a dollar estimate, and
step-by-step remediation.

**✅ Clear** — the part nobody else does. Before telling you to delete something,
Clawback cross-checks it against the things that make deletion dangerous:

| Finding | Auto-verified against |
|---|---|
| Old EBS snapshot | Self-owned AMI block-device references |
| Idle NAT gateway | Route tables still routing through it |
| Target-less load balancer | Route53 aliases and CNAMEs |
| Unassociated Elastic IP | Route53 A records |

Findings come back **✅ cleared to delete** or **⛔ BLOCKED** with the live reference
named — the difference between a cleanup and an outage.

**📊 Verify** — after you implement fixes, Clawback re-audits and diffs against the
audit-day state: resolved findings, realized $/month, still-open savings, and new
waste since. Recommendations are cheap; receipts are the product.

## Read-only, by design

Clawback **never modifies your infrastructure.**

- Collectors call only `Describe*` / `List*` / `Get*` APIs — enforced by
  [CI](.github/workflows/ci.yml) that fails the build if a mutating call appears
  ([scripts/check_readonly.sh](scripts/check_readonly.sh)).
- `ViewOnlyAccess` + Billing read is all the credential it needs. Never use root keys.
- Remediation is delivered as documented steps. You (or your pipeline) make the
  changes; the tool never does.

## Quickstart

As a Claude Code skill:

```bash
git clone https://github.com/codewithzhiva/clawback ~/.claude/skills/clawback
pip install boto3
```

Then, with AWS credentials configured:

```
> audit my AWS account for cost savings
```

Standalone (no Claude required):

```bash
python3 scripts/collect/spend_summary.py --out findings/spend.json      # bill context
python3 scripts/collect/orphans.py --out findings/orphans.json          # all regions
python3 scripts/collect/commitments.py --out findings/commitments.json  # SP/RI gaps
python3 scripts/report.py --findings findings/ --out AUDIT_REPORT.md
python3 scripts/report_html.py --findings findings/ --out AUDIT_REPORT.html  # email-able single file
```

Later, prove the savings landed:

```bash
python3 scripts/collect/orphans.py --out after/orphans.json
python3 scripts/verify.py --before findings/orphans.json --after after/ \
        --out VERIFICATION_REPORT.md
```

## What it checks

| Tier | Items | Typical share of savings |
|------|-------|--------------------------|
| **A — big wins** | right-sizing, SP/RI coverage, non-prod scheduling, orphaned/idle resources, Graviton | 60–80% |
| **B — structural** | storage tiering, data transfer, RDS deep-dive, k8s bin-packing | 10–30% |
| **C — hygiene** | observability costs, zombie infra, anomaly guardrails | 5–10% |

Automated collectors cover A2 + A4 today and are expanding; the full methodology with
CLI commands and thresholds per item is in
[reference/checklist.md](reference/checklist.md) — Claude walks the manual items with
you. Remediation guides with the traps that bite
([blue/green idle LBs, AMI-locked snapshots, batch-job NATs](reference/remediation/orphans.md))
are included.

## Want it implemented — and guaranteed?

I run this as a service on **gain-share: no savings, no fee.** I audit, implement
through your change process, and get paid a percentage of measured first-year savings —
measured by the same `verify` tooling you can read in this repo. The $370K above is my
track record, not a projection.

→ **[Book a call](https://calendly.com/workwithzhiva/30min)**

## License

[MIT](LICENSE)
