"""
asset_tracer.py — Asset Lineage and Traceability Tracker
=========================================================
Builds a lightweight, offline asset lineage graph for a VeriVision inspection.

Every asset (data file, model, output log) that enters the inspection is
registered as a node.  The tracer produces:

* A directed lineage graph (nodes + edges as dicts) showing
  DATA → MODEL → OUTPUT flow.
* Per-asset provenance records (hash, type, size, submission time).
* A "tainted" flag propagated along the graph: if a DATA asset is
  quarantined, every MODEL and OUTPUT that depends on it inherits
  a taint flag.
* A human-readable lineage summary string.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any


# ---------------------------------------------------------------------------
# Graph node / edge helpers
# ---------------------------------------------------------------------------

def _node_id(asset: dict) -> str:
    return asset.get("id", hashlib.sha256(str(asset).encode()).hexdigest()[:12])


def _node_label(asset: dict) -> str:
    fname = asset.get("filename", asset.get("id", "unknown"))
    atype = asset.get("asset_type", "unknown").upper()
    return f"{atype}: {fname}"


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def build_lineage(
    assets: list[dict],
    findings: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Build a lineage graph from an asset manifest.

    Parameters
    ----------
    assets   : list of asset dicts (id, filename, asset_type, sha256, size, …).
    findings : list of finding dicts; used to mark tainted nodes.

    Returns
    -------
    dict with keys:
        nodes   : list of node dicts
        edges   : list of edge dicts
        tainted : set of asset IDs that are tainted (serialised as list)
        summary : human-readable lineage description string
        stats   : counts per asset type
    """
    findings = findings or []

    # Collect quarantine asset references from findings
    quarantined_asset_ids: set[str] = set()
    for f in findings:
        if f.get("action") == "QUARANTINE":
            for aid in f.get("asset_ids", []):
                quarantined_asset_ids.add(str(aid))

    # Build type buckets
    by_type: dict[str, list[dict]] = {}
    for a in assets:
        t = a.get("asset_type", "unknown")
        by_type.setdefault(t, []).append(a)

    data_assets    = by_type.get("data", []) + by_type.get("reference", []) + by_type.get("current", [])
    model_assets   = by_type.get("model", [])
    output_assets  = by_type.get("output", [])

    nodes: list[dict] = []
    edges: list[dict] = []
    tainted: set[str] = set(quarantined_asset_ids)

    def _make_node(asset: dict, tainted_flag: bool) -> dict:
        aid = _node_id(asset)
        return {
            "id":         aid,
            "label":      _node_label(asset),
            "asset_type": asset.get("asset_type", "unknown"),
            "filename":   asset.get("filename", ""),
            "sha256":     asset.get("sha256", ""),
            "size":       asset.get("size", 0),
            "tainted":    tainted_flag,
            "registered_at": asset.get("created_at", time.time()),
        }

    # DATA nodes
    data_tainted = False
    for a in data_assets:
        aid = _node_id(a)
        t_flag = aid in tainted
        if t_flag:
            data_tainted = True
        nodes.append(_make_node(a, t_flag))

    # MODEL nodes — inherit taint from data
    model_tainted = False
    for a in model_assets:
        aid = _node_id(a)
        t_flag = (aid in tainted) or data_tainted
        if t_flag:
            tainted.add(aid)
            model_tainted = True
        nodes.append(_make_node(a, t_flag))
        # edges: each data asset feeds each model
        for da in data_assets:
            edges.append({
                "from":  _node_id(da),
                "to":    aid,
                "label": "trained-on",
                "tainted": data_tainted,
            })

    # OUTPUT nodes — inherit taint from model
    for a in output_assets:
        aid = _node_id(a)
        t_flag = (aid in tainted) or model_tainted or data_tainted
        if t_flag:
            tainted.add(aid)
        nodes.append(_make_node(a, t_flag))
        for ma in model_assets:
            edges.append({
                "from":  _node_id(ma),
                "to":    aid,
                "label": "produced-by",
                "tainted": model_tainted,
            })
        # If no model registered, link directly from data
        if not model_assets:
            for da in data_assets:
                edges.append({
                    "from":  _node_id(da),
                    "to":    aid,
                    "label": "derived-from",
                    "tainted": data_tainted,
                })

    # Stats
    stats = {t: len(v) for t, v in by_type.items()}
    stats["total"] = len(assets)

    # Summary text
    tainted_count = len([n for n in nodes if n["tainted"]])
    if tainted_count:
        summary = (
            f"Lineage graph: {len(nodes)} nodes, {len(edges)} edges. "
            f"{tainted_count} node(s) are tainted due to upstream quarantine-level findings. "
            f"Data → Model → Output dependency chain is fully mapped."
        )
    else:
        summary = (
            f"Lineage graph: {len(nodes)} nodes, {len(edges)} edges. "
            f"No tainted nodes detected. "
            f"Data → Model → Output dependency chain is fully mapped."
        )

    return {
        "nodes":   nodes,
        "edges":   edges,
        "tainted": sorted(tainted),
        "summary": summary,
        "stats":   stats,
    }
