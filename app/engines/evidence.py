"""
evidence.py — VeriVision Central Evidence Model
================================================
Defines the canonical data structures that all engines produce and the
decision engine consumes.  Every inspection is expressed as a single Case
containing one or more EvidenceItems; the decision engine collapses the Case
into a DecisionRecord with a structured machine-readable verdict.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"
    INFO     = "INFO"

class Action(str, Enum):
    QUARANTINE = "QUARANTINE"
    REVIEW     = "REVIEW"
    ACCEPT     = "ACCEPT"

class Verdict(str, Enum):
    QUARANTINE   = "QUARANTINE"
    REVIEW       = "REVIEW"
    ACCEPT       = "ACCEPT"
    INCONCLUSIVE = "INCONCLUSIVE"

class Domain(str, Enum):
    DATA      = "DATA"
    MODEL     = "MODEL"
    OUTPUT    = "OUTPUT"
    SHIFT     = "SHIFT"
    COMPOSITE = "COMPOSITE"


@dataclass
class EvidenceItem:
    eid:         str
    domain:      str
    engine:      str
    title:       str
    claim:       str
    rationale:   str
    evidence:    list
    confidence:  float
    severity:    str
    action:      str
    limits:      str
    metrics:     dict
    asset_ids:   list
    created_at:  float
    tags:        list

    def as_dict(self) -> dict:
        return asdict(self)


def make_evidence(
    domain, engine, title, claim, rationale, evidence,
    confidence, severity, action, limits,
    metrics=None, asset_ids=None, tags=None,
) -> EvidenceItem:
    return EvidenceItem(
        eid        = "EVI-" + uuid.uuid4().hex[:10].upper(),
        domain     = domain,
        engine     = engine,
        title      = title,
        claim      = claim,
        rationale  = rationale,
        evidence   = evidence,
        confidence = max(0.0, min(1.0, float(confidence))),
        severity   = severity,
        action     = action,
        limits     = limits,
        metrics    = metrics or {},
        asset_ids  = asset_ids or [],
        created_at = time.time(),
        tags       = tags or [],
    )


@dataclass
class Case:
    case_id:           str
    inspection_id:     str
    name:              str
    evidence:          list
    risk_vector:       dict
    overall_risk:      float
    verdict:           str
    coverage:          list
    trace:             list
    asset_manifest:    list
    contributor_risks: dict
    batch_risks:       dict
    created_at:        float
    closed_at:         object   # float | None

    def by_severity(self, sev):
        return [e for e in self.evidence if e.severity == sev]

    def by_domain(self, domain):
        return [e for e in self.evidence if e.domain == domain]

    def by_action(self, action):
        return [e for e in self.evidence if e.action == action]

    def quarantine_items(self):
        return self.by_action(Action.QUARANTINE.value)

    def highest_severity(self):
        order = ["CRITICAL","HIGH","MEDIUM","LOW","INFO"]
        for sev in order:
            if any(e.severity == sev for e in self.evidence):
                return sev
        return None

    def as_dict(self) -> dict:
        return asdict(self)


def make_case(
    inspection_id, name, evidence, risk_vector, overall_risk,
    verdict, coverage, trace, asset_manifest,
    contributor_risks=None, batch_risks=None,
) -> Case:
    return Case(
        case_id           = "CASE-" + uuid.uuid4().hex[:10].upper(),
        inspection_id     = inspection_id,
        name              = name,
        evidence          = evidence,
        risk_vector       = risk_vector,
        overall_risk      = float(overall_risk),
        verdict           = verdict,
        coverage          = coverage,
        trace             = trace,
        asset_manifest    = asset_manifest,
        contributor_risks = contributor_risks or {},
        batch_risks       = batch_risks or {},
        created_at        = time.time(),
        closed_at         = None,
    )


@dataclass
class DecisionRecord:
    record_id:        str
    case_id:          str
    inspection_id:    str
    verdict:          str
    overall_risk:     float
    risk_vector:      dict
    rationale:        str
    critical_items:   list
    blocking_domains: list
    policy_version:   str
    created_at:       float

    def as_dict(self) -> dict:
        return asdict(self)


def make_decision(
    case: Case,
    rationale: str,
    critical_items: list,
    blocking_domains: list,
    policy_version: str = "1.0.0",
) -> DecisionRecord:
    return DecisionRecord(
        record_id        = "DEC-" + uuid.uuid4().hex[:10].upper(),
        case_id          = case.case_id,
        inspection_id    = case.inspection_id,
        verdict          = case.verdict,
        overall_risk     = case.overall_risk,
        risk_vector      = case.risk_vector,
        rationale        = rationale,
        critical_items   = critical_items,
        blocking_domains = blocking_domains,
        policy_version   = policy_version,
        created_at       = time.time(),
    )
