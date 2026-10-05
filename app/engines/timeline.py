"""
timeline.py — Chronological Audit Timeline Engine
=================================================
Builds a timeline of all integrity events across data, model,
output, shift, and policy evaluation phases for a given inspection.
"""

from __future__ import annotations
import time
from typing import Any


def build_timeline(inspection: dict, case: dict | None = None) -> list[dict]:
    """
    Construct an ordered timeline of events:
      - Asset ingestion
      - Audit trail chained hashes
      - Domain inspection triggers and findings
      - Decision verdict computation
    """
    events = []
    base_time = inspection.get("created_at", time.time())
    iid = inspection.get("id", "UNKNOWN")

    # 1. Pipeline Start
    events.append({
        "event_id": f"EVT-START-{iid[:8]}",
        "timestamp": base_time,
        "type": "PIPELINE_INIT",
        "domain": "PIPELINE",
        "title": "Inspection Pipeline Initialized",
        "description": f"Inspection '{inspection.get('name', 'Inspection')}' registered with ID {iid}.",
        "severity": "INFO",
        "linked_ids": {"inspection_id": iid}
    })

    # 2. Asset Ingestion Events
    assets = inspection.get("assets", [])
    for idx, asset in enumerate(assets):
        events.append({
            "event_id": f"EVT-AST-{asset.get('id', str(idx))[:8]}",
            "timestamp": base_time + 0.1 * (idx + 1),
            "type": "ASSET_INGESTED",
            "domain": asset.get("asset_type", "DATA").upper(),
            "title": f"Asset Registered: {asset.get('filename', 'file')}",
            "description": f"Ingested {asset.get('asset_type')} artifact (SHA-256: {asset.get('sha256', '')[:12]}...).",
            "severity": "INFO",
            "linked_ids": {"asset_id": asset.get("id"), "sha256": asset.get("sha256")}
        })

    # 3. Audit trail events
    audit_rows = inspection.get("audit", [])
    for row in audit_rows:
        ts = row.get("ts", base_time + 1.0)
        events.append({
            "event_id": f"EVT-AUDIT-{row.get('id', '0')}",
            "timestamp": ts,
            "type": row.get("event", "AUDIT_RECORD"),
            "domain": "PROVENANCE",
            "title": f"Audit Log: {row.get('event')}",
            "description": f"Chained hash {row.get('hash', '')[:16]}... linked to prev_hash {row.get('prev_hash', '')[:16]}...",
            "severity": "INFO",
            "linked_ids": {"audit_id": row.get("id"), "hash": row.get("hash")}
        })

    # 4. Findings Events
    findings = inspection.get("findings", [])
    for idx, f in enumerate(findings):
        sev = f.get("severity", "MEDIUM").upper()
        events.append({
            "event_id": f"EVT-FIND-{f.get('id', str(idx))}",
            "timestamp": base_time + 2.0 + (idx * 0.2),
            "type": "INTEGRITY_FINDING",
            "domain": f.get("category", "INTEGRITY").upper(),
            "title": f.get("title", "Integrity Finding"),
            "description": f.get("claim", ""),
            "severity": sev,
            "linked_ids": {
                "finding_id": f.get("id"),
                "engine": f.get("engine"),
                "action": f.get("action")
            }
        })

    # 5. Policy Decision
    verdict = inspection.get("verdict", "INCONCLUSIVE")
    dec_sev = "CRITICAL" if verdict == "QUARANTINE" else ("MEDIUM" if verdict == "REVIEW" else "INFO")
    events.append({
        "event_id": f"EVT-DEC-{iid[:8]}",
        "timestamp": base_time + 3.0 + len(findings) * 0.2,
        "type": "POLICY_DECISION",
        "domain": "POLICY",
        "title": f"Policy Verdict: {verdict}",
        "description": f"Final decision rendered with overall risk score {inspection.get('overall', 0)}/100.",
        "severity": dec_sev,
        "linked_ids": {"verdict": verdict, "overall": inspection.get("overall")}
    })

    # Sort events by timestamp
    events.sort(key=lambda x: x["timestamp"])
    return events
