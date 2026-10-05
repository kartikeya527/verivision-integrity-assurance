"""
recommendations.py — Actionable Recommendation Engine
=====================================================
Generates deterministic, operator-ready remediation recommendations
tied to specific evidence findings and overall pipeline decision.
Fully offline and policy-driven.
"""

from __future__ import annotations
from typing import Any


def generate_recommendations(evidence_items: list[dict] | list[Any], verdict: str) -> list[dict]:
    """
    Generate prioritized recommendations based on evidence findings and final verdict.
    Each recommendation specifies:
      - priority: CRITICAL | HIGH | MEDIUM | LOW | INFO
      - domain: DATA | MODEL | OUTPUT | SHIFT | PIPELINE
      - action_title: Short action statement
      - description: Detailed operator instruction
      - affected_scope: Target batch, asset, contributor, or service
      - rationale: Why this action is required
    """
    recommendations = []
    seen_keys = set()

    for item in evidence_items:
        # Normalize item
        if hasattr(item, "as_dict"):
            d = item.as_dict()
        elif isinstance(item, dict):
            d = item
        else:
            continue

        domain = d.get("domain", "PIPELINE").upper()
        severity = d.get("severity", "MEDIUM").upper()
        title = d.get("title", "")
        claim = d.get("claim", "")
        tags = [t.lower() for t in d.get("tags", [])]
        action = d.get("action", "REVIEW")

        # 1. Output Cryptographic Mismatch
        if "signature" in title.lower() or "signature" in claim.lower() or "provenance" in tags:
            key = "crypto_signature_invalid"
            if key not in seen_keys:
                seen_keys.add(key)
                recommendations.append({
                    "priority": "CRITICAL",
                    "domain": "OUTPUT",
                    "action_title": "Reject Unsigned / Tampered Inference Outputs",
                    "description": "Quarantine invalid inference output records immediately. Inspect the inference serving gateway for unauthorized payload modifications or corrupted transport channels. Rotate Ed25519 signing keys if key compromise is suspected.",
                    "affected_scope": "Inference Serving Gateway / Output Storage",
                    "rationale": "Cryptographic Ed25519 signatures failed validation against registered public keys.",
                })

        # 2. Replay Detection
        if "replay" in title.lower() or "replay" in claim.lower() or "nonce" in tags:
            key = "crypto_replay_detected"
            if key not in seen_keys:
                seen_keys.add(key)
                recommendations.append({
                    "priority": "CRITICAL",
                    "domain": "OUTPUT",
                    "action_title": "Invalidate Replayed Inference Nonces",
                    "description": "Block identified replayed inference payload IDs at the API gateway. Ensure strict timestamp window validation and monotonic nonce verification are enforced.",
                    "affected_scope": "Output Verification & Ingestion",
                    "rationale": "Identical inference payload digests or nonces were submitted multiple times.",
                })

        # 3. Model Weight / Digest Mismatch
        if "digest" in title.lower() or "model" in title.lower() and ("mismatch" in claim.lower() or "mismatch" in title.lower()):
            key = "model_digest_mismatch"
            if key not in seen_keys:
                seen_keys.add(key)
                recommendations.append({
                    "priority": "CRITICAL",
                    "domain": "MODEL",
                    "action_title": "Halt Model Promotion & Verify Checkpoint Digest",
                    "description": "Halt promotion of current model weights to staging/production. Cross-reference model SHA-256 fingerprint against the cryptographic baseline registered during model training sign-off.",
                    "affected_scope": "Model Registry / Weights Artifacts",
                    "rationale": "Active model weights hash does not match registered baseline.",
                })

        # 4. Trigger / Backdoor Pattern
        if "trigger" in title.lower() or "patch" in title.lower() or "backdoor" in tags:
            key = "data_trigger_backdoor"
            if key not in seen_keys:
                seen_keys.add(key)
                recommendations.append({
                    "priority": "HIGH",
                    "domain": "DATA",
                    "action_title": "Quarantine Trigger Candidate Samples & Retrain",
                    "description": "Isolate all samples flagged with high-contrast localized trigger artifacts. Audit the contributing annotators/vendors and verify if downstream models exhibit backdoor sensitivity on targeted classes.",
                    "affected_scope": "Contributed Dataset / Flagged Batches",
                    "rationale": "Synthetic or localized geometric trigger artifacts detected in training samples.",
                })

        # 5. Duplicates Flooding
        if "duplicate" in title.lower() or "flooding" in claim.lower():
            key = "data_duplicate_flooding"
            if key not in seen_keys:
                seen_keys.add(key)
                recommendations.append({
                    "priority": "MEDIUM",
                    "domain": "DATA",
                    "action_title": "Deduplicate Dataset & Audit Contributor Volume",
                    "description": "Remove near-identical duplicate image copies from training splits to prevent sample bias and memorization. Audit contributor submission rates for automated scraping or flooding.",
                    "affected_scope": "Training Dataset / Split Partitions",
                    "rationale": "Excessive exact or near-duplicate visual hashes detected in dataset.",
                })

        # 6. Environmental Shift vs Manipulation
        if domain == "SHIFT":
            key = "shift_adaptation"
            if key not in seen_keys:
                seen_keys.add(key)
                if "natural" in claim.lower() or "lighting" in claim.lower() or "drift" in claim.lower():
                    recommendations.append({
                        "priority": "LOW",
                        "domain": "SHIFT",
                        "action_title": "Calibrate Models for Environmental Drift (Non-Malicious)",
                        "description": "Collect representative field samples under current lighting/sensor conditions and schedule routine fine-tuning or domain adaptation. This is confirmed operational drift, not a malicious tampering event.",
                        "affected_scope": "Model Domain Adaptation Pipeline",
                        "rationale": "Gradual distribution drift detected across illumination/contrast statistics without localized manipulation artifacts.",
                    })
                else:
                    recommendations.append({
                        "priority": "HIGH",
                        "domain": "SHIFT",
                        "action_title": "Forensic Inspection of Distribution Anomalies",
                        "description": "Isolate current data population for statistical outlier analysis and inspect sensors for hardware degradation or synthetic artifact injection.",
                        "affected_scope": "Active Ingestion Stream",
                        "rationale": "Unexplained variance in statistical entropy or edge distribution.",
                    })

    # Add verdict-level baseline recommendations if empty or general
    if verdict == "ACCEPT":
        recommendations.append({
            "priority": "INFO",
            "domain": "PIPELINE",
            "action_title": "Archive Verification Evidence & Proceed",
            "description": "All integrity gates passed. Archive cryptographic evidence package and signed audit logs to immutable compliance storage and clear pipeline assets for operational deployment.",
            "affected_scope": "Full Pipeline Pipeline",
            "rationale": "Zero critical or high-risk findings detected.",
        })
    elif verdict == "QUARANTINE" and not recommendations:
        recommendations.append({
            "priority": "CRITICAL",
            "domain": "PIPELINE",
            "action_title": "Pipeline Halt — Full Forensic Triage",
            "description": "Quarantine all pipeline artifacts immediately. Conduct audit review with security team before any assets are unlocked or deployed.",
            "affected_scope": "Entire Inspection Artifact Bundle",
            "rationale": "Quarantine verdict issued by policy decision engine.",
        })

    return recommendations
