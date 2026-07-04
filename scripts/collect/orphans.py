#!/usr/bin/env python3
"""Collect orphaned and idle AWS resources — checklist item A4.

Read-only: this module only ever calls Describe*/List*/Get* APIs.

Finds:
  - unattached EBS volumes
  - unassociated Elastic IPs
  - load balancers with zero registered targets (ALB/NLB/GWLB) or instances (classic)
  - EBS snapshots older than SNAPSHOT_AGE_DAYS
  - stopped EC2 instances (still billing for attached EBS)
  - NAT gateways with near-zero traffic over NAT_LOOKBACK_DAYS

Every finding is safety-verified where possible ("cleared to delete"):
  - snapshots are cross-referenced against self-owned AMIs
  - NAT gateways are cross-referenced against route tables
  - load balancers and EIPs are cross-referenced against Route53 records
A finding that FAILS a safety check is kept but elevated to risk=high with the
blocking reference in the evidence — deleting it would break something.

Usage:
  python3 orphans.py --out findings/orphans.json [--profile p] [--regions r1,r2]
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
import pricing

CHECKLIST_ITEM = "A4-orphans"
SNAPSHOT_AGE_DAYS = 180
STOPPED_INSTANCE_MIN_DAYS = 30
NAT_LOOKBACK_DAYS = 14
NAT_IDLE_BYTES = 1_000_000_000  # < 1 GB over the lookback window = idle

BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "adaptive"})


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def enabled_regions(session):
    ec2 = session.client("ec2", region_name="us-east-1", config=BOTO_CFG)
    resp = ec2.describe_regions(AllRegions=False)
    return sorted(r["RegionName"] for r in resp["Regions"])


def name_tag(tags):
    for t in tags or []:
        if t["Key"] == "Name":
            return t["Value"]
    return ""


def build_dns_index(session):
    """Global Route53 scan for safety cross-refs. Returns (ips, targets) or None
    if Route53 isn't readable — callers then skip DNS clearances rather than fail."""
    r53 = session.client("route53", config=BOTO_CFG)
    ips, targets = set(), set()

    def norm(name):
        name = name.rstrip(".").lower()
        return name[len("dualstack."):] if name.startswith("dualstack.") else name

    try:
        for zpage in r53.get_paginator("list_hosted_zones").paginate():
            for zone in zpage["HostedZones"]:
                pages = r53.get_paginator("list_resource_record_sets").paginate(
                    HostedZoneId=zone["Id"])
                for rpage in pages:
                    for rr in rpage["ResourceRecordSets"]:
                        if "AliasTarget" in rr:
                            targets.add(norm(rr["AliasTarget"]["DNSName"]))
                        for rec in rr.get("ResourceRecords", []):
                            if rr["Type"] == "A":
                                ips.add(rec["Value"])
                            elif rr["Type"] == "CNAME":
                                targets.add(norm(rec["Value"]))
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"  Route53 not scanned ({code}) — DNS clearances skipped", file=sys.stderr)
        return None
    return ips, targets


def ami_referenced_snapshots(ec2):
    """Snapshot IDs backing self-owned AMIs — these can't (and shouldn't) be deleted."""
    ids = set()
    for page in ec2.get_paginator("describe_images").paginate(Owners=["self"]):
        for img in page["Images"]:
            for bdm in img.get("BlockDeviceMappings", []):
                sid = bdm.get("Ebs", {}).get("SnapshotId")
                if sid:
                    ids.add(sid)
    return ids


def collect_unattached_ebs(ec2, region):
    findings = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for vol in page["Volumes"]:
            vol_type = vol["VolumeType"]
            size = vol["Size"]
            age_days = (utcnow() - vol["CreateTime"]).days
            name = name_tag(vol.get("Tags"))
            findings.append(Finding(
                resource_id=vol["VolumeId"],
                resource_type="ebs-volume",
                region=region,
                checklist_item=CHECKLIST_ITEM,
                evidence=f"Unattached {vol_type} volume, {size} GB, created {age_days} days ago"
                         + (f", Name={name}" if name else ""),
                estimated_monthly_savings=pricing.ebs_monthly(vol_type, size),
                remediation_steps=[
                    "Confirm no application depends on reattaching this volume",
                    f"Snapshot it: aws ec2 create-snapshot --volume-id {vol['VolumeId']}",
                    f"Delete it: aws ec2 delete-volume --volume-id {vol['VolumeId']}",
                ],
                risk="low",
            ))
    return findings


def collect_unassociated_eips(ec2, region, dns_index):
    findings = []
    for addr in ec2.describe_addresses()["Addresses"]:
        if "AssociationId" in addr or "InstanceId" in addr or "NetworkInterfaceId" in addr:
            continue
        alloc = addr.get("AllocationId", addr.get("PublicIp", "unknown"))
        ip = addr.get("PublicIp", "")
        evidence = f"Elastic IP {ip or '?'} not associated with any instance or ENI"
        risk, clearances = "low", []
        if dns_index is None:
            evidence += " (Route53 not scanned — check DNS manually)"
            risk = "medium"
        elif ip and ip in dns_index[0]:
            risk = "high"
            evidence += "; BLOCKED: a Route53 A record points at this IP"
        else:
            clearances.append("no Route53 A record points at this IP")
        findings.append(Finding(
            resource_id=alloc,
            resource_type="elastic-ip",
            region=region,
            checklist_item=CHECKLIST_ITEM,
            evidence=evidence,
            estimated_monthly_savings=pricing.eip_monthly(),
            remediation_steps=[
                "Confirm the IP is not in external DNS providers or third-party allowlists",
                f"Release it: aws ec2 release-address --allocation-id {alloc}",
            ],
            risk=risk,
            clearances=clearances,
        ))
    return findings


def _lb_finding(region, lb_type, lb_name, lb_dns, evidence, delete_cmd, dns_index):
    risk, clearances = "medium", []
    if dns_index is None:
        evidence += " (Route53 not scanned — check DNS manually)"
    elif lb_dns and lb_dns.lower() in dns_index[1]:
        risk = "high"
        evidence += "; BLOCKED: a Route53 record points at this load balancer"
    else:
        clearances.append("no Route53 alias/CNAME points at this load balancer")
        risk = "low"
    return Finding(
        resource_id=lb_name,
        resource_type=f"{lb_type}-load-balancer",
        region=region,
        checklist_item=CHECKLIST_ITEM,
        evidence=evidence,
        estimated_monthly_savings=pricing.load_balancer_monthly(lb_type),
        remediation_steps=[
            "Confirm no deploy pipeline registers targets on demand (blue/green idle side)",
            "Check external (non-Route53) DNS providers if any",
            delete_cmd,
        ],
        risk=risk,
        clearances=clearances,
    )


def collect_idle_load_balancers(session, region, dns_index):
    findings = []
    elbv2 = session.client("elbv2", region_name=region, config=BOTO_CFG)
    for page in elbv2.get_paginator("describe_load_balancers").paginate():
        for lb in page["LoadBalancers"]:
            arn = lb["LoadBalancerArn"]
            tgs = elbv2.describe_target_groups(LoadBalancerArn=arn)["TargetGroups"]
            total_targets = 0
            for tg in tgs:
                health = elbv2.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
                total_targets += len(health["TargetHealthDescriptions"])
            if total_targets == 0:
                findings.append(_lb_finding(
                    region, lb["Type"], lb["LoadBalancerName"], lb.get("DNSName", ""),
                    f"{lb['Type']} LB with {len(tgs)} target group(s) and zero registered targets",
                    f"Delete it: aws elbv2 delete-load-balancer --load-balancer-arn {arn}",
                    dns_index,
                ))

    elb = session.client("elb", region_name=region, config=BOTO_CFG)
    for page in elb.get_paginator("describe_load_balancers").paginate():
        for lb in page["LoadBalancerDescriptions"]:
            if not lb["Instances"]:
                findings.append(_lb_finding(
                    region, "classic", lb["LoadBalancerName"], lb.get("DNSName", ""),
                    "Classic ELB with zero registered instances",
                    f"Delete it: aws elb delete-load-balancer --load-balancer-name {lb['LoadBalancerName']}",
                    dns_index,
                ))
    return findings


def collect_old_snapshots(ec2, region):
    findings = []
    cutoff = utcnow() - dt.timedelta(days=SNAPSHOT_AGE_DAYS)
    ami_snaps = ami_referenced_snapshots(ec2)
    paginator = ec2.get_paginator("describe_snapshots")
    for page in paginator.paginate(OwnerIds=["self"]):
        for snap in page["Snapshots"]:
            if snap["StartTime"] > cutoff:
                continue
            age_days = (utcnow() - snap["StartTime"]).days
            snap_id = snap["SnapshotId"]
            evidence = (f"Snapshot of {snap['VolumeSize']} GB, {age_days} days old"
                        + (f", desc: {snap.get('Description', '')[:80]}"
                           if snap.get("Description") else ""))
            if snap_id in ami_snaps:
                risk, clearances = "high", []
                evidence += "; BLOCKED: backs a registered self-owned AMI"
                remediation = [
                    "Deregister the AMI first if genuinely unused: "
                    "aws ec2 describe-images --owners self "
                    f"--filters Name=block-device-mapping.snapshot-id,Values={snap_id}",
                    f"Then delete: aws ec2 delete-snapshot --snapshot-id {snap_id}",
                ]
            else:
                risk = "low"
                clearances = ["not referenced by any self-owned AMI"]
                remediation = [
                    "Confirm retention policy allows deletion (compliance/backup requirements)",
                    f"Delete it: aws ec2 delete-snapshot --snapshot-id {snap_id}",
                ]
            findings.append(Finding(
                resource_id=snap_id,
                resource_type="ebs-snapshot",
                region=region,
                checklist_item=CHECKLIST_ITEM,
                evidence=evidence,
                estimated_monthly_savings=pricing.snapshot_monthly(snap["VolumeSize"]),
                remediation_steps=remediation,
                risk=risk,
                clearances=clearances,
            ))
    return findings


def collect_stopped_instances(ec2, region):
    findings = []
    paginator = ec2.get_paginator("describe_instances")
    filters = [{"Name": "instance-state-name", "Values": ["stopped"]}]
    for page in paginator.paginate(Filters=filters):
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                # StateTransitionReason looks like: "User initiated (2026-05-01 12:00:00 GMT)"
                reason = inst.get("StateTransitionReason", "")
                stopped_days = None
                if "(" in reason and "GMT" in reason:
                    try:
                        ts = reason.split("(")[1].split(" GMT")[0]
                        stopped_at = dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=dt.timezone.utc)
                        stopped_days = (utcnow() - stopped_at).days
                    except ValueError:
                        pass
                if stopped_days is not None and stopped_days < STOPPED_INSTANCE_MIN_DAYS:
                    continue

                ebs_gb = 0
                ebs_cost = 0.0
                for bdm in inst.get("BlockDeviceMappings", []):
                    vol_id = bdm.get("Ebs", {}).get("VolumeId")
                    if vol_id:
                        for v in ec2.describe_volumes(VolumeIds=[vol_id])["Volumes"]:
                            ebs_gb += v["Size"]
                            ebs_cost += pricing.ebs_monthly(v["VolumeType"], v["Size"])
                if ebs_gb == 0:
                    continue  # no EBS billing while stopped — nothing to save
                name = name_tag(inst.get("Tags"))
                stopped_str = f"stopped {stopped_days} days" if stopped_days is not None \
                    else "stopped (duration unknown)"
                findings.append(Finding(
                    resource_id=inst["InstanceId"],
                    resource_type="stopped-instance",
                    region=region,
                    checklist_item=CHECKLIST_ITEM,
                    evidence=f"{inst['InstanceType']} {stopped_str}, {ebs_gb} GB EBS still billing"
                             + (f", Name={name}" if name else ""),
                    estimated_monthly_savings=ebs_cost,
                    remediation_steps=[
                        "Confirm with the owner the instance is no longer needed",
                        f"Create AMI backup if needed: aws ec2 create-image --instance-id {inst['InstanceId']} --name backup-{inst['InstanceId']}",
                        f"Terminate it: aws ec2 terminate-instances --instance-ids {inst['InstanceId']}",
                    ],
                    risk="medium",
                ))
    return findings


def collect_idle_nat_gateways(session, ec2, region):
    findings = []
    cw = session.client("cloudwatch", region_name=region, config=BOTO_CFG)
    end = utcnow()
    start = end - dt.timedelta(days=NAT_LOOKBACK_DAYS)
    paginator = ec2.get_paginator("describe_nat_gateways")
    for page in paginator.paginate(Filters=[{"Name": "state", "Values": ["available"]}]):
        for nat in page["NatGateways"]:
            nat_id = nat["NatGatewayId"]
            resp = cw.get_metric_statistics(
                Namespace="AWS/NATGateway",
                MetricName="BytesOutToDestination",
                Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
                StartTime=start, EndTime=end,
                Period=86400, Statistics=["Sum"],
            )
            total_bytes = sum(dp["Sum"] for dp in resp["Datapoints"])
            if total_bytes >= NAT_IDLE_BYTES:
                continue

            evidence = (f"NAT gateway moved {total_bytes / 1e6:.1f} MB in {NAT_LOOKBACK_DAYS} days "
                        f"(threshold: {NAT_IDLE_BYTES / 1e9:.0f} GB)")
            rtbs = ec2.describe_route_tables(
                Filters=[{"Name": "route.nat-gateway-id", "Values": [nat_id]}])["RouteTables"]
            if rtbs:
                risk, clearances = "high", []
                rtb_ids = ", ".join(r["RouteTableId"] for r in rtbs)
                evidence += f"; BLOCKED: route table(s) {rtb_ids} still route through it"
                remediation = [
                    f"Repoint or confirm dead: subnets on {rtb_ids} lose outbound internet on deletion",
                    "Watch for monthly/quarterly batch jobs — 14 quiet days is suggestive, not proof",
                    f"Delete it: aws ec2 delete-nat-gateway --nat-gateway-id {nat_id}",
                ]
            else:
                risk = "low"
                clearances = ["no route tables reference this NAT gateway"]
                remediation = [
                    f"Delete it: aws ec2 delete-nat-gateway --nat-gateway-id {nat_id}",
                ]
            findings.append(Finding(
                resource_id=nat_id,
                resource_type="nat-gateway",
                region=region,
                checklist_item=CHECKLIST_ITEM,
                evidence=evidence,
                estimated_monthly_savings=pricing.nat_gateway_monthly(),
                remediation_steps=remediation,
                risk=risk,
                clearances=clearances,
            ))
    return findings


def collect_region(session, region, dns_index):
    ec2 = session.client("ec2", region_name=region, config=BOTO_CFG)
    findings = []
    collectors = [
        ("unattached EBS", lambda: collect_unattached_ebs(ec2, region)),
        ("unassociated EIPs", lambda: collect_unassociated_eips(ec2, region, dns_index)),
        ("idle load balancers", lambda: collect_idle_load_balancers(session, region, dns_index)),
        ("old snapshots", lambda: collect_old_snapshots(ec2, region)),
        ("stopped instances", lambda: collect_stopped_instances(ec2, region)),
        ("idle NAT gateways", lambda: collect_idle_nat_gateways(session, ec2, region)),
    ]
    for label, fn in collectors:
        try:
            found = fn()
            findings.extend(found)
            if found:
                print(f"  [{region}] {label}: {len(found)} finding(s)", file=sys.stderr)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("UnauthorizedOperation", "AccessDenied", "AccessDeniedException"):
                print(f"  [{region}] {label}: skipped (no permission: {code})", file=sys.stderr)
            else:
                raise
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="findings/orphans.json")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--regions", default=None, help="comma-separated; default: all enabled")
    args = ap.parse_args()

    session = boto3.Session(profile_name=args.profile)
    regions = args.regions.split(",") if args.regions else enabled_regions(session)

    print("Building Route53 index for DNS safety checks...", file=sys.stderr)
    dns_index = build_dns_index(session)

    all_findings = []
    for region in regions:
        print(f"Scanning {region}...", file=sys.stderr)
        all_findings.extend(collect_region(session, region, dns_index))

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([f.to_dict() for f in all_findings], indent=2, default=str))

    total = sum(f.estimated_monthly_savings for f in all_findings)
    cleared = sum(1 for f in all_findings if f.clearances)
    blocked = sum(1 for f in all_findings if f.risk == "high")
    print(f"\n{len(all_findings)} findings ({cleared} cleared-to-delete, {blocked} blocked), "
          f"est. ${total:,.0f}/month (${total * 12:,.0f}/year) → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
