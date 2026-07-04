"""Shared finding schema. Every collector and every manual finding uses this shape,
so ranking, reporting, and any future tooling stay trivial."""

from dataclasses import dataclass, field, asdict
from typing import List


RISK_LEVELS = ("low", "medium", "high")


@dataclass
class Finding:
    resource_id: str
    resource_type: str          # e.g. "ebs-volume", "elastic-ip", "nat-gateway"
    region: str
    checklist_item: str         # which methodology item produced this, e.g. "A4-orphans"
    evidence: str               # concrete facts: sizes, ages, metric values
    estimated_monthly_savings: float
    remediation_steps: List[str] = field(default_factory=list)
    risk: str = "low"           # one of RISK_LEVELS
    clearances: List[str] = field(default_factory=list)  # safety checks that passed,
                                                         # e.g. "not referenced by any self-owned AMI"

    def __post_init__(self):
        if self.risk not in RISK_LEVELS:
            raise ValueError(f"risk must be one of {RISK_LEVELS}, got {self.risk!r}")

    def to_dict(self) -> dict:
        return asdict(self)
