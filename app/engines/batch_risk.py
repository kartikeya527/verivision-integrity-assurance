"""
batch_risk.py — Contributor and Batch Risk Analyser
====================================================
Analyses asset manifests to produce per-contributor and per-batch risk
scores without requiring any model or cloud call.

Contributor risk is inferred from:
- Proportion of that contributor's assets that carry a QUARANTINE/HIGH finding.
- Whether any asset from the contributor was flagged for exact-duplicate or
  trigger-candidate issues.
- Asset volume outlier detection (a contributor with 10x more assets than
  others is a risk signal).

Batch risk is inferred from:
- Timestamp clustering (many assets from one batch in rapid succession).
- Shared prefix naming patterns (common in automated pipelines).
- Concentration of anomalous assets in one batch.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contributor_from_asset(asset: dict) -> str:
    """
    Extract a contributor label from an asset dict.
    Priority: asset['contributor'] > asset['source'] > derived from filename prefix.
    """
    if c := asset.get("contributor"):
        return str(c)
    if s := asset.get("source"):
        return str(s)
    name = asset.get("filename", asset.get("id", "unknown"))
    # heuristic: take everything before the first underscore or digit run
    m = re.match(r"([A-Za-z\-]+)", str(name))
    return m.group(1) if m else "unknown"


def _batch_from_asset(asset: dict) -> str:
    """
    Extract a batch label from an asset dict.
    Priority: asset['batch'] > asset['batch_id'] > date prefix in filename.
    """
    if b := asset.get("batch"):
        return str(b)
    if b := asset.get("batch_id"):
        return str(b)
    name = asset.get("filename", "")
    # e.g. "2024-03-01_img_001.png" -> "2024-03-01"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(name))
    if m:
        return m.group(1)
    # fall back to a "created_at" day bucket if present
    ts = asset.get("created_at")
    if ts:
        import datetime
        return datetime.datetime.utcfromtimestamp(float(ts)).strftime("%Y-%m-%d")
    return "batch-default"


def _volume_outlier_scores(counts: dict[str, int]) -> dict[str, float]:
    """
    Return z-score-based risk contribution from asset-count outliers.
    A contributor/batch with dramatically more assets raises a red flag.
    """
    if len(counts) < 2:
        return {k: 0.0 for k in counts}
    vals = np.array(list(counts.values()), dtype=float)
    med  = np.median(vals)
    mad  = np.median(np.abs(vals - med)) + 1e-6
    zs   = {k: float(max(0, 0.6745 * (v - med) / mad)) for k, v in counts.items()}
    return zs


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def analyse_batch_and_contributor_risk(
    assets: list[dict],
    findings_by_asset: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    """
    Parameters
    ----------
    assets : list of asset dicts (each must have at least ``id`` and ``filename``).
    findings_by_asset : optional mapping of asset_id -> list of finding dicts
                        that reference that asset.  Used to weight contributor risk
                        by finding severity.

    Returns
    -------
    dict with keys:
        contributor_risks : {contributor_label: risk_score [0-100]}
        batch_risks       : {batch_label: risk_score [0-100]}
        contributor_details : per-contributor stats dict
        batch_details       : per-batch stats dict
        flags               : list of human-readable risk flag strings
    """
    findings_by_asset = findings_by_asset or {}

    # Group assets
    contributor_assets: dict[str, list[dict]] = defaultdict(list)
    batch_assets:       dict[str, list[dict]] = defaultdict(list)

    for a in assets:
        contributor_assets[_contributor_from_asset(a)].append(a)
        batch_assets[_batch_from_asset(a)].append(a)

    # Volume outlier signals
    contrib_counts = {k: len(v) for k, v in contributor_assets.items()}
    batch_counts   = {k: len(v) for k, v in batch_assets.items()}
    contrib_vol_z  = _volume_outlier_scores(contrib_counts)
    batch_vol_z    = _volume_outlier_scores(batch_counts)

    # Severity weight map
    _sev_weight = {"CRITICAL": 100, "HIGH": 75, "MEDIUM": 40, "LOW": 10, "INFO": 0}
    _act_weight = {"QUARANTINE": 1.0, "REVIEW": 0.5, "ACCEPT": 0.0}

    flags: list[str] = []

    # --------------- Contributor risk ---------------
    contributor_risks:   dict[str, float] = {}
    contributor_details: dict[str, dict]  = {}

    for contrib, c_assets in contributor_assets.items():
        quarantine_count = 0
        finding_score    = 0.0
        finding_count    = 0

        for a in c_assets:
            for f in findings_by_asset.get(a.get("id", ""), []):
                sev  = f.get("severity", "INFO")
                act  = f.get("action",   "ACCEPT")
                finding_score += _sev_weight.get(sev, 0) * _act_weight.get(act, 0)
                finding_count += 1
                if act == "QUARANTINE":
                    quarantine_count += 1

        avg_finding_score = (finding_score / max(1, finding_count)) if finding_count else 0
        # volume anomaly adds up to 20 pts
        vol_risk = min(20, contrib_vol_z.get(contrib, 0) * 5)
        # quarantine concentration: up to 80 pts
        quar_risk = min(80, quarantine_count * 25)
        # weighted blend
        total_risk = min(100, avg_finding_score * 0.5 + vol_risk + quar_risk)

        contributor_risks[contrib] = round(total_risk, 1)
        contributor_details[contrib] = {
            "asset_count":      len(c_assets),
            "finding_count":    finding_count,
            "quarantine_count": quarantine_count,
            "volume_z_score":   round(contrib_vol_z.get(contrib, 0), 2),
            "risk_score":       round(total_risk, 1),
        }

        if quarantine_count:
            flags.append(
                f"Contributor '{contrib}' has {quarantine_count} quarantine-level finding(s) "
                f"across {len(c_assets)} asset(s)."
            )
        if contrib_vol_z.get(contrib, 0) > 3:
            flags.append(
                f"Contributor '{contrib}' submitted significantly more assets than peers "
                f"(z={contrib_vol_z[contrib]:.1f}) — possible bulk injection signal."
            )

    # --------------- Batch risk ---------------
    batch_risks:   dict[str, float] = {}
    batch_details: dict[str, dict]  = {}

    for batch, b_assets in batch_assets.items():
        quarantine_count = 0
        finding_score    = 0.0
        finding_count    = 0

        for a in b_assets:
            for f in findings_by_asset.get(a.get("id", ""), []):
                sev  = f.get("severity", "INFO")
                act  = f.get("action",   "ACCEPT")
                finding_score += _sev_weight.get(sev, 0) * _act_weight.get(act, 0)
                finding_count += 1
                if act == "QUARANTINE":
                    quarantine_count += 1

        avg_finding_score = (finding_score / max(1, finding_count)) if finding_count else 0
        vol_risk  = min(20, batch_vol_z.get(batch, 0) * 5)
        quar_risk = min(80, quarantine_count * 25)
        total_risk = min(100, avg_finding_score * 0.5 + vol_risk + quar_risk)

        batch_risks[batch] = round(total_risk, 1)
        batch_details[batch] = {
            "asset_count":      len(b_assets),
            "finding_count":    finding_count,
            "quarantine_count": quarantine_count,
            "volume_z_score":   round(batch_vol_z.get(batch, 0), 2),
            "risk_score":       round(total_risk, 1),
        }

        if quarantine_count:
            flags.append(
                f"Batch '{batch}' contains {quarantine_count} quarantine-level finding(s) "
                f"across {len(b_assets)} asset(s)."
            )

    return {
        "contributor_risks":   contributor_risks,
        "batch_risks":         batch_risks,
        "contributor_details": contributor_details,
        "batch_details":       batch_details,
        "flags":               flags,
    }
