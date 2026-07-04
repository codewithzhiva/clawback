"""Static pricing tables, us-east-1 baseline (July 2026 list prices).

Good enough for audit estimates: most regions are within ~20% of us-east-1,
and findings are ranked relative to each other. Reports must state this
assumption. v1: replace with the AWS Pricing API, cached.
"""

HOURS_PER_MONTH = 730

# EBS $/GB-month by volume type
EBS_GB_MONTH = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}

EBS_SNAPSHOT_GB_MONTH = 0.05

# Unassociated Elastic IP $/hour
ELASTIC_IP_HOUR = 0.005

# NAT gateway $/hour (excludes per-GB processing, which idle NATs don't incur)
NAT_GATEWAY_HOUR = 0.045

# Load balancer $/hour by type (excludes LCU/data charges — idle LBs don't incur them)
LOAD_BALANCER_HOUR = {
    "application": 0.0225,
    "network": 0.0225,
    "gateway": 0.0125,
    "classic": 0.025,
}


def ebs_monthly(volume_type: str, size_gb: int) -> float:
    return EBS_GB_MONTH.get(volume_type, EBS_GB_MONTH["gp2"]) * size_gb


def snapshot_monthly(size_gb: int) -> float:
    return EBS_SNAPSHOT_GB_MONTH * size_gb


def eip_monthly() -> float:
    return ELASTIC_IP_HOUR * HOURS_PER_MONTH


def nat_gateway_monthly() -> float:
    return NAT_GATEWAY_HOUR * HOURS_PER_MONTH


def load_balancer_monthly(lb_type: str) -> float:
    return LOAD_BALANCER_HOUR.get(lb_type, LOAD_BALANCER_HOUR["application"]) * HOURS_PER_MONTH
