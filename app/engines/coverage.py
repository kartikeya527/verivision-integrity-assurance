"""
coverage.py — Capability Coverage & Evidence Strength Engine
============================================================
Exposes a comprehensive capabilities coverage matrix detailing what
VeriVision genuinely verifies, evidence strength calibration, and limitations.
"""

from __future__ import annotations


def get_coverage_matrix(scores: dict | None = None, findings_count: dict | None = None) -> list[dict]:
    """
    Return machine-readable and UI-renderable capabilities coverage list.
    Never overclaims capabilities.
    """
    fc = findings_count or {}
    sc = scores or {}

    data_tested = "data" in sc and sc["data"] not in (100, 50)
    model_tested = "model" in sc and sc["model"] != 100
    output_tested = "output" in sc and sc["output"] != 100
    shift_tested = "shift" in sc and sc["shift"] not in (100, 50)

    matrix = [
        {
            "capability_id": "CAP-DATA-INTEGRITY",
            "name": "Dataset Schema & Duplicates",
            "domain": "DATA",
            "status": "AVAILABLE" if data_tested else "IDLE",
            "available": "YES",
            "evidence_strength": "HIGH",
            "evidence_basis": ["Exact SHA-256 collision scan", "pHash/dHash near-duplicate clusters", "COCO/YOLO schema validation"],
            "limitation": "Restricted to supported image formats and COCO/YOLO annotation structures.",
            "findings_count": fc.get("data", 0)
        },
        {
            "capability_id": "CAP-DATA-TRIGGER",
            "name": "Visual Trigger / Backdoor Probing",
            "domain": "DATA",
            "status": "AVAILABLE" if data_tested else "IDLE",
            "available": "YES",
            "evidence_strength": "MEDIUM",
            "evidence_basis": ["High-contrast corner/edge patch density", "Uniform geometric artifact detection"],
            "limitation": "Detects visible physical/synthetic patch patterns; imperceptible noise backdoors require white-box gradient attribution.",
            "findings_count": fc.get("trigger", 0)
        },
        {
            "capability_id": "CAP-MODEL-INTEGRITY",
            "name": "Model Architecture & Fingerprint Verification",
            "domain": "MODEL",
            "status": "AVAILABLE" if model_tested else "IDLE",
            "available": "YES",
            "evidence_strength": "HIGH",
            "evidence_basis": ["Cryptographic SHA-256 weight hash against registered checkpoint", "PyTorch/TorchScript structure check"],
            "limitation": "Requires initial registration of trusted reference hash in registry.",
            "findings_count": fc.get("model", 0)
        },
        {
            "capability_id": "CAP-OUTPUT-PROVENANCE",
            "name": "Cryptographic Inference Provenance",
            "domain": "OUTPUT",
            "status": "AVAILABLE" if output_tested else "IDLE",
            "available": "YES",
            "evidence_strength": "HIGH",
            "evidence_basis": ["Ed25519 digital signature verification", "SHA-256 cryptographic hash-chaining", "Merkle tree root commitment"],
            "limitation": "Validates authenticity and transit integrity; does not judge semantic truth of model prediction.",
            "findings_count": fc.get("output", 0)
        },
        {
            "capability_id": "CAP-REPLAY-PROTECTION",
            "name": "Inference Replay & Nonce Enforcement",
            "domain": "OUTPUT",
            "status": "AVAILABLE" if output_tested else "IDLE",
            "available": "YES",
            "evidence_strength": "HIGH",
            "evidence_basis": ["Unique payload ID registry", "Chained hash uniqueness check"],
            "limitation": "Replay detection window scoped to recorded output ledger.",
            "findings_count": fc.get("replay", 0)
        },
        {
            "capability_id": "CAP-SHIFT-ATTRIBUTION",
            "name": "Distribution Shift vs Tampering Attribution",
            "domain": "SHIFT",
            "status": "AVAILABLE" if shift_tested else "IDLE",
            "available": "YES",
            "evidence_strength": "MEDIUM",
            "evidence_basis": ["Population mean brightness/contrast shift", "Edge energy & Shannon entropy deviation"],
            "limitation": "Requires paired reference and current image sets (minimum 5 samples each).",
            "findings_count": fc.get("shift", 0)
        },
        {
            "capability_id": "CAP-CONTRIBUTOR-RISK",
            "name": "Contributor & Batch Risk Concentration",
            "domain": "PIPELINE",
            "status": "AVAILABLE",
            "available": "YES",
            "evidence_strength": "HIGH",
            "evidence_basis": ["Multi-contributor anomaly aggregation", "Batch-level defect clustering analysis"],
            "limitation": "Requires contributor_id / batch_id tags or metadata in manifests.",
            "findings_count": fc.get("batch", 0)
        },
        {
            "capability_id": "CAP-SENSOR-FORENSICS",
            "name": "Hardware Sensor PRNU Fingerprinting",
            "domain": "DATA",
            "status": "PARTIAL",
            "available": "PARTIAL",
            "evidence_strength": "LOW",
            "evidence_basis": ["Metadata EXIF sensor tags comparison"],
            "limitation": "Full photo-response non-uniformity (PRNU) requires uncompressed RAW images and sensor calibration frames.",
            "findings_count": 0
        }
    ]
    return matrix
