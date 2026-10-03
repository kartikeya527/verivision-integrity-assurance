from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib, json, math, re
import numpy as np

@dataclass
class Finding:
    category: str
    title: str
    claim: str
    evidence: list[str]
    confidence: float
    limits: str
    action: str
    severity: str
    engine: str
    metrics: dict
    def as_dict(self): return asdict(self)

def finding(category,title,claim,evidence,confidence,limits,action,severity,engine,metrics=None):
    return Finding(category,title,claim,evidence,max(0,min(1,float(confidence))),limits,action,severity,engine,metrics or {})

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def stable_json(x): return json.dumps(x,sort_keys=True,separators=(',',':'))

def clamp(x,a=0,b=100): return max(a,min(b,float(x)))

def robust_z(values):
    a=np.asarray(values,dtype=float)
    if len(a)<2: return np.zeros_like(a)
    med=np.median(a); mad=np.median(np.abs(a-med))+1e-9
    return 0.6745*(a-med)/mad

def entropy_hist(img):
    hist=np.histogram(img.ravel(),bins=32,range=(0,256),density=True)[0]+1e-12
    return float(-np.sum(hist*np.log(hist)))
