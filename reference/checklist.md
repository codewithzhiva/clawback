# The 12-Item AWS Cost Audit Checklist

Ordered by typical savings impact. Tier A usually holds 60–80% of found savings.
Items marked ⚙️ have automated collectors in `scripts/collect/`; the rest are manual
sweeps with the read-only CLI commands listed.

---

## Tier A — big wins

### A1. Compute right-sizing
Instances provisioned for a peak that never comes.
- **Signal:** avg CPU < 20% and max CPU < 60% over 14–30 days; low network I/O.
- **Check:**
  ```
  aws compute-optimizer get-ec2-instance-recommendations
  aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization \
    --dimensions Name=InstanceId,Value=<id> --start-time <14d-ago> --end-time <now> \
    --period 3600 --statistics Average Maximum
  ```
  Same for RDS (`AWS/RDS`, `get-rds-database-recommendations`) and ECS services.
- **Typical saving:** 30–50% per downsized instance (one size down = ~50%).
- **Risk:** medium — needs memory data too (CloudWatch agent / container insights); CPU alone under-tells.

### A2. Savings Plan / Reserved Instance coverage
On-demand pricing for steady-state workloads.
- **Signal:** SP/RI coverage below ~70% on a stable baseline.
- **Check:**
  ```
  aws ce get-savings-plans-coverage --time-period Start=<3mo-ago>,End=<now> --granularity MONTHLY
  aws ce get-savings-plans-purchase-recommendation \
    --savings-plans-type COMPUTE_SP --term-in-years ONE_YEAR --payment-option NO_UPFRONT \
    --lookback-period-in-days SIXTY_DAYS
  ```
- **Typical saving:** ~28% (1yr no-upfront Compute SP) on covered spend. Safe default recommendation; 3yr only for provably permanent baseline.
- **Risk:** low-medium — commitment risk if the workload shrinks; recommend covering ~80% of trailing minimum, never peak.

### A3. Non-prod scheduling
Dev/stage/test running 168 h/week that people use 50.
- **Signal:** instances tagged/named dev|stage|test|qa|sandbox with flat 24/7 CloudWatch activity.
- **Check:** inventory by tag, then confirm usage windows with the team.
- **Fix:** AWS Instance Scheduler, or Lambda + EventBridge start/stop cron.
- **Typical saving:** ~70% of the scheduled resources' compute cost (168h → 50h).
- **Risk:** low — worst case someone starts an instance manually.

### A4. Orphaned & idle resources ⚙️ `scripts/collect/orphans.py`
Paying for things nothing uses: unattached EBS, unassociated EIPs, target-less load
balancers, snapshots > 180 days, long-stopped instances (EBS still bills), idle NAT gateways.
- **Risk:** low-medium per finding; the collector attaches per-finding remediation and risk.

### A5. Graviton migration
x86 pricing for ARM-compatible workloads.
- **Signal:** interpreted/JIT runtimes (Python, Node, Java, Go) on m5/c5/r5-class instances; RDS/ElastiCache/OpenSearch on old-gen x86.
- **Check:** inventory instance families; check AMI/container base images for arch pinning.
- **Typical saving:** ~20% same-performance (e.g. m5 → m7g). RDS/managed services are the easy first move — no AMI work.
- **Risk:** medium for EC2 (rebuild + test), low for RDS/ElastiCache (engine handles it).

---

## Tier B — structural

### B6. Storage tiering
- **gp2 → gp3:** flat ~20% cheaper, same or better performance. Near-zero risk. `aws ec2 describe-volumes --filters Name=volume-type,Values=gp2`
- **S3 lifecycle:** buckets with no lifecycle config accumulating forever. `aws s3api get-bucket-lifecycle-configuration --bucket <b>` (error = none set). Recommend Intelligent-Tiering as the low-thought default.
- **Over-provisioned IOPS:** io1/io2 volumes with provisioned IOPS ≫ consumed (CloudWatch `VolumeReadOps`/`VolumeWriteOps`).

### B7. Data transfer
- **NAT processing:** S3/DynamoDB traffic through NAT gateways — add VPC gateway endpoints (free) and route around. Check `BytesOutToDestination` against known S3-heavy workloads.
- **Cross-AZ chatter:** services talking across AZs at $0.01/GB each way — check `aws ce get-cost-and-usage` grouped by usage type for `DataTransfer-Regional-Bytes`.
- **Egress:** high `DataTransfer-Out-Bytes` without CloudFront in front.

### B8. RDS deep-dive
- Multi-AZ on non-prod databases (doubles cost, protects nothing anyone needs).
- Old-generation instance classes (db.m4/db.r4 → current gen or Graviton).
- Over-provisioned storage (allocated ≫ used, `FreeStorageSpace` metric).
- Idle read replicas (near-zero `ReadIOPS`).

### B9. Kubernetes / ECS bin-packing
- Requests ≫ actual usage (compare requests to container insights metrics).
- Node right-sizing: low allocatable utilization across the node group.
- Spot for stateless/batch workloads (~70% off on-demand).

---

## Tier C — hygiene

### C10. Observability costs
- CloudWatch Logs groups with retention **never expire** (the default):
  `aws logs describe-log-groups --query 'logGroups[?!retentionInDays]'` — set 30–90 days.
- High-cardinality custom metrics ($0.30/metric/mo adds up); VPC Flow Logs to CloudWatch instead of S3.

### C11. Zombie infra
- Resources with zero traffic/invocations in 30 days: Lambda (zero `Invocations`), API Gateway (zero `Count`), forgotten test environments, duplicate tooling across teams.

### C12. Anomaly guardrails (recurrence prevention)
- AWS Budgets with alerts at 80/100/forecast.
- Cost Anomaly Detection monitors on the top services.
- This is also the retainer hook: someone has to watch the alerts.
