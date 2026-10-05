"""
decision_engine.py — Policy-Based Verdict Engine
=================================================
Collapses a fully-populated Case into a final DecisionRecord by applying
a deterministic, layered policy.

Policy v1.0.0 layers (evaluated in order; first blocking layer wins):
  1. HARD BLOCK — any QUARANTINE action in any domain → QUARANTINE verdict.
  2. SOFT BLOCK — overall_risk >= 55 OR any domain score >= 45 → REVIEW.
  3. DATA COVERAGE GATE — fewer than 2 pipeline domains exercised → INCONCLUSIVE.
  4. CLEAR — all checks pass → ACCEPT.

The engine also produces:
  * A human-readable rationale paragraph.
  * A list of the specific EVI IDs that forced the verdict.
  * The domains that contributed blocking evidence.
"""

from __future__ import annotations

from .evidence import Case, DecisionRecord, make_decision

POLICY_VERSION = "1.0.0"

# Risk thresholds
_QUARANTINE_DOMAIN_THRESHOLD = 85   # any domain score at/above this → QUARANTINE
_REVIEW_OVERALL_THRESHOLD    = 55
_REVIEW_DOMAIN_THRESHOLD     = 45
_COVERAGE_MIN_DOMAINS        = 2    # must exercise at least this many domains


def decide(case: Case) -> DecisionRecord:
    """
    Apply the VeriVision policy to a Case and return an immutable DecisionRecord.
    """
    rv = case.risk_vector  # e.g. {"data": 75, "model": 45, "output": 5, "shift": 50}
    evidence = case.evidence

    quarantine_items  = [e for e in evidence if e.action == "QUARANTINE"]
    blocking_domains: list[str] = []
    critical_eids:    list[str] = []

    # ------------------------------------------------------------------ #
    # Layer 1 — HARD BLOCK (any QUARANTINE finding)
    # ------------------------------------------------------------------ #
    if quarantine_items or any(v >= _QUARANTINE_DOMAIN_THRESHOLD for v in rv.values()):
        for e in quarantine_items:
            critical_eids.append(e.eid)
            if e.domain not in blocking_domains:
                blocking_domains.append(e.domain)
        for domain, score in rv.items():
            if score >= _QUARANTINE_DOMAIN_THRESHOLD and domain.upper() not in blocking_domains:
                blocking_domains.append(domain.upper())

        # Craft rationale
        domain_str = ", ".join(blocking_domains) if blocking_domains else "one or more domains"
        rationale = (
            f"QUARANTINE verdict imposed. "
            f"{len(quarantine_items)} finding(s) with action QUARANTINE were raised in {domain_str}. "
            f"The overall risk score is {case.overall_risk:.0f}/100. "
            f"No artefact from this pipeline may be used until all QUARANTINE items are resolved and "
            f"the inspection is re-run from scratch."
        )
        case.verdict = "QUARANTINE"
        return make_decision(case, rationale, critical_eids, blocking_domains, POLICY_VERSION)

    # ------------------------------------------------------------------ #
    # Layer 2 — SOFT BLOCK (score thresholds)
    # ------------------------------------------------------------------ #
    review_domains = [
        d for d, v in rv.items()
        if v >= _REVIEW_DOMAIN_THRESHOLD and v < _QUARANTINE_DOMAIN_THRESHOLD
    ]
    if case.overall_risk >= _REVIEW_OVERALL_THRESHOLD or review_domains:
        blocking_domains = [d.upper() for d in review_domains]
        review_eids = [e.eid for e in evidence if e.action == "REVIEW"][:10]
        rationale = (
            f"REVIEW verdict imposed. "
            f"Overall risk score is {case.overall_risk:.0f}/100"
        )
        if review_domains:
            rationale += f"; domain(s) {', '.join(d.upper() for d in review_domains)} exceed the review threshold."
        else:
            rationale += "."
        rationale += (
            f" {len(review_eids)} finding(s) require analyst sign-off. "
            f"No artefact from this pipeline should be promoted to production without explicit approval."
        )
        case.verdict = "REVIEW"
        return make_decision(case, rationale, review_eids, blocking_domains, POLICY_VERSION)

    # ------------------------------------------------------------------ #
    # Layer 3 — COVERAGE GATE
    # ------------------------------------------------------------------ #
    exercised_domains = [d for d, v in rv.items() if v not in (100.0, 50.0)]
    if len(exercised_domains) < _COVERAGE_MIN_DOMAINS:
        rationale = (
            f"INCONCLUSIVE verdict. Only {len(exercised_domains)} pipeline domain(s) were exercised "
            f"(minimum required: {_COVERAGE_MIN_DOMAINS}). "
            f"Please upload assets for the missing domains and re-run the inspection."
        )
        case.verdict = "INCONCLUSIVE"
        return make_decision(case, rationale, [], [], POLICY_VERSION)

    # ------------------------------------------------------------------ #
    # Layer 4 — ACCEPT
    # ------------------------------------------------------------------ #
    rationale = (
        f"ACCEPT verdict. All {len(exercised_domains)} exercised domain(s) passed their checks. "
        f"Overall risk score is {case.overall_risk:.0f}/100. "
        f"No QUARANTINE or REVIEW-threshold findings were detected."
    )
    case.verdict = "ACCEPT"
    return make_decision(case, rationale, [], [], POLICY_VERSION)
