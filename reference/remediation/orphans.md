# Remediation Guide — Orphaned & Idle Resources (A4)

Safe-order rule for everything here: **snapshot/backup → wait → delete.** Storage is
cheap; recreating a lost volume is not.

> The collector auto-runs several of these checks: snapshot→AMI references,
> NAT→route tables, LB/EIP→Route53. Findings marked ✅ **Cleared** passed them;
> findings marked **BLOCKED** failed and are elevated to risk=high with the live
> reference named in the evidence. Checks that can't be automated (external DNS
> providers, third-party allowlists, deploy pipelines) remain below — do them anyway.

## Unattached EBS volumes — risk: low
1. Check the `Name` tag and CloudTrail (`LookupEvents` on the volume ID) for who created it and when it detached.
2. Snapshot before deleting: `aws ec2 create-snapshot --volume-id <id> --description "pre-cleanup backup"`.
3. Delete: `aws ec2 delete-volume --volume-id <id>`.
4. Snapshot costs ~50% of gp2 GB-price and can itself be deleted after 90 quiet days.

## Unassociated Elastic IPs — risk: low
1. Grep infrastructure code, DNS zones, and third-party allowlists for the IP before releasing — a released IP goes back to the AWS pool and someone else can get it.
2. Release: `aws ec2 release-address --allocation-id <id>`.

## Idle load balancers — risk: medium
1. **Blue/green trap:** some deploy pipelines keep a target-less LB as the idle side of a blue/green pair. Check deploy tooling before deleting.
2. Check DNS records pointing at the LB hostname.
3. Delete listeners' certificates references are unaffected (ACM certs persist).
4. Delete: `aws elbv2 delete-load-balancer --load-balancer-arn <arn>`.

## Old EBS snapshots — risk: medium
1. **AMI trap:** a snapshot backing a registered AMI can't be deleted (and shouldn't be). Cross-check: `aws ec2 describe-images --owners self --query 'Images[].BlockDeviceMappings[].Ebs.SnapshotId'`.
2. Check compliance/backup retention requirements before bulk deletion.
3. Prevent recurrence: Data Lifecycle Manager policy (automated snapshot expiry) beats manual cleanup.

## Long-stopped instances — risk: medium
1. Find the owner (tags, CloudTrail). A stopped instance is often someone's "I might need this" — get sign-off.
2. Back up as AMI: `aws ec2 create-image --instance-id <id> --name "archive-<id>"` (this snapshots all attached volumes).
3. Terminate: `aws ec2 terminate-instances --instance-ids <id>`.
4. Note: termination deletes volumes with `DeleteOnTermination=true` — the AMI backup covers this.

## Idle NAT gateways — risk: medium
1. Check every route table for `0.0.0.0/0 → nat-xxxx` routes: `aws ec2 describe-route-tables --filters Name=route.nat-gateway-id,Values=<id>`.
2. Subnets routing through it lose outbound internet on deletion — confirm the subnets are themselves dead, or repoint them first.
3. Watch for monthly/quarterly batch jobs that would wake it — 14 days of quiet is suggestive, not proof.
4. Delete: `aws ec2 delete-nat-gateway --nat-gateway-id <id>`.
