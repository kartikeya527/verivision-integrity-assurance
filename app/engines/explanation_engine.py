"""
explanation_engine.py — Plain-language explanation generator
=============================================================
Converts a Case or list of EvidenceItems into structured, readable
summaries fit for display in the dashboard, audit reports, and
machine-readable policy outputs.

All text is deterministic (no LLM calls) so it works fully offline.
"""

from __future__ import annotations
from .evidence import Case, EvidenceItem


# ---------------------------------------------------------------------------
# Action-word map
# ---------------------------------------------------------------------------

_ACTION_VERB = {
    "QUARANTINE": "must be quarantined",
    "REVIEW":     "requires manual review",
    "ACCEPT":     "is cleared to proceed",
}

_SEVERITY_LABEL = {
    "CRITICAL": "critical integrity violation",
    "HIGH":     "high-severity anomaly",
    "MEDIUM":   "medium-severity concern",
    "LOW":      "low-severity observation",
    "INFO":     "informational note",
}

_DOMAIN_CONTEXT = {
    "DATA":      "training / evaluation data",
    "MODEL":     "model weights and behaviour",
    "OUTPUT":    "signed inference outputs",
    "SHIFT":     "distribution drift between datasets",
    "COMPOSITE": "cross-domain pipeline",
}


def _one_liner(item: EvidenceItem) -> str:
    """Generate a single natural-language sentence for one EvidenceItem."""
    verb  = _ACTION_VERB.get(item.action, "has been flagged")
    label = _SEVERITY_LABEL.get(item.severity, "finding")
    domain_ctx = _DOMAIN_CONTEXT.get(item.domain, item.domain.lower())
    conf_pct = round(item.confidence * 100)
    return (
        f"The {domain_ctx} raised a {label}: \u201c{item.title}\u201d "
        f"({conf_pct}% confidence). The asset {verb}."
    )


def explain_item(item: EvidenceItem) -> dict:
    """
    Return a fully-rendered explanation dict for one EvidenceItem.

    Keys
    ----
    eid, title, one_liner, detail, rationale, evidence_bullets,
    confidence_pct, action, severity, domain, engine, limits, metrics, tags
    """
    bullets = [f"• {e}" for e in item.evidence]
    detail_lines = [item.claim]
    if item.evidence:
        detail_lines.append("Supporting evidence:")
        detail_lines += bullets

    return {
        "eid":               item.eid,
        "title":             item.title,
        "one_liner":         _one_liner(item),
        "plain_explanation": _one_liner(item),
        "detail":            "\n".join(detail_lines),
        "rationale":       item.rationale,
        "evidence_bullets": bullets,
        "confidence_pct":  round(item.confidence * 100, 1),
        "action":          item.action,
        "severity":        item.severity,
        "domain":          item.domain,
        "engine":          item.engine,
        "limits":          item.limits,
        "metrics":         item.metrics,
        "tags":            item.tags,
    }


def explain_case(case: Case) -> dict:
    """
    Return a rich, structured explanation of an entire Case.

    This is the primary object the dashboard and the /api/case/{id}/explain
    endpoint returns.

    Top-level keys
    --------------
    case_id, inspection_id, name, verdict, overall_risk, risk_vector,
    summary_paragraph, verdict_rationale, domain_summaries,
    critical_count, high_count, quarantine_count, items
    """
    items_exp = [explain_item(e) for e in case.evidence]

    critical_count   = sum(1 for e in case.evidence if e.severity == "CRITICAL")
    high_count       = sum(1 for e in case.evidence if e.severity == "HIGH")
    quarantine_count = sum(1 for e in case.evidence if e.action   == "QUARANTINE")
    review_count     = sum(1 for e in case.evidence if e.action   == "REVIEW")
    accept_count     = sum(1 for e in case.evidence if e.action   == "ACCEPT")

    # Domain-level summaries
    domain_summaries: dict[str, dict] = {}
    for domain, score in case.risk_vector.items():
        domain_items = [e for e in case.evidence if e.domain == domain.upper()]
        if domain_items:
            worst = max(domain_items, key=lambda e: e.confidence if e.action == "QUARANTINE" else 0)
            top_finding = worst.title
        else:
            top_finding = "No findings"
        domain_summaries[domain] = {
            "risk_score":  round(score, 1),
            "item_count":  len(domain_items),
            "top_finding": top_finding,
        }

    # Overall summary paragraph
    if case.verdict == "QUARANTINE":
        opening = (
            f"This inspection of \u201c{case.name}\u201d returned a QUARANTINE verdict "
            f"with an overall risk score of {case.overall_risk:.0f}/100. "
            f"{critical_count} critical and {high_count} high-severity findings were raised. "
            f"Immediate human review is mandatory before any artefact in this pipeline is used in production."
        )
    elif case.verdict == "REVIEW":
        opening = (
            f"This inspection of \u201c{case.name}\u201d returned a REVIEW verdict "
            f"with an overall risk score of {case.overall_risk:.0f}/100. "
            f"{review_count} finding(s) require analyst sign-off before the pipeline is cleared."
        )
    elif case.verdict == "ACCEPT":
        opening = (
            f"This inspection of \u201c{case.name}\u201d passed all checks with an overall risk "
            f"score of {case.overall_risk:.0f}/100. No blocking integrity issues were detected."
        )
    else:
        opening = (
            f"This inspection of \u201c{case.name}\u201d produced an INCONCLUSIVE result "
            f"(risk {case.overall_risk:.0f}/100). Insufficient assets were provided to run all checks."
        )

    # Verdict rationale (mirrors DecisionRecord.rationale if present)
    if quarantine_count:
        rationale = (
            f"{quarantine_count} quarantine-level finding(s) were detected across the following domains: "
            f"{', '.join(sorted({e.domain for e in case.evidence if e.action == 'QUARANTINE'}))}. "
            "The pipeline must not proceed."
        )
    elif review_count:
        rationale = (
            f"{review_count} review-level finding(s) were detected. "
            "A qualified analyst must sign off before the pipeline is cleared."
        )
    else:
        rationale = "All automated checks passed. No human intervention is required."

    return {
        "case_id":          case.case_id,
        "inspection_id":    case.inspection_id,
        "name":             case.name,
        "verdict":          case.verdict,
        "overall_risk":     round(case.overall_risk, 1),
        "risk_vector":      {k: round(v, 1) for k, v in case.risk_vector.items()},
        "summary":          opening,
        "summary_paragraph": opening,
        "verdict_rationale": rationale,
        "domain_summaries": domain_summaries,
        "critical_count":   critical_count,
        "high_count":       high_count,
        "quarantine_count": quarantine_count,
        "review_count":     review_count,
        "accept_count":     accept_count,
        "coverage":         case.coverage,
        "trace":            case.trace,
        "contributor_risks": case.contributor_risks,
        "batch_risks":      case.batch_risks,
        "items":            items_exp,
        "explanations":     items_exp,
    }
