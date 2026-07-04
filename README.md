# CloudCost

**The open-source AWS cost audit that found $370K/year of savings on a Fortune-500 account.**

CloudCost is a [Claude Code](https://claude.com/claude-code) skill that audits your AWS
account for waste using a 12-item methodology built from real FinOps work — orphaned
resources, right-sizing, commitment coverage, non-prod scheduling, storage tiering,
data-transfer leaks — and generates a ranked savings report with evidence and
step-by-step remediation for every finding.

Most accounts under $100K/month with no dedicated FinOps person are wasting 30–60%.
This finds it.

## Read-only, by design

CloudCost **never modifies your infrastructure.**

- Collectors only call `Describe*` / `List*` / `Get*` APIs — enforced by a CI check
  ([scripts/check_readonly.sh](scripts/check_readonly.sh)) that fails the build if a
  mutating call appears.
- Works with a read-only credential: `ViewOnlyAccess` + `Billing` read is enough.
- Remediation is delivered as documented steps in the report. You (or your pipeline)
  make the changes; the tool never does.

## Install

```bash
git clone https://github.com/codewithzhiva/cloudcost ~/.claude/skills/cloudcost
pip install boto3
```

Then in Claude Code, with AWS credentials configured:

```
> audit my AWS account for cost savings
```

Claude picks up the skill, runs the collectors, walks the manual checklist, and writes
`AUDIT_REPORT.md`.

## Standalone (no Claude)

The collectors are plain Python:

```bash
python3 scripts/collect/orphans.py --out findings/orphans.json   # scan all regions
python3 scripts/report.py --findings findings/ --out AUDIT_REPORT.md
```

## What it checks

| Tier | Items | Typical share of savings |
|------|-------|--------------------------|
| A — big wins | right-sizing, SP/RI coverage, non-prod scheduling, orphaned/idle resources, Graviton | 60–80% |
| B — structural | storage tiering, data transfer, RDS deep-dive, k8s bin-packing | 10–30% |
| C — hygiene | observability costs, zombie infra, anomaly guardrails | 5–10% |

Full methodology: [reference/checklist.md](reference/checklist.md).

## Want it implemented — and guaranteed?

I run this as a service on **gain-share: no savings, no fee.** I audit, implement
through your change process, and get paid a percentage of measured first-year savings.
The $370K number above is my track record, not a projection.

→ **[Book a call](https://calendly.com/shivaroopan)**

## License

MIT
