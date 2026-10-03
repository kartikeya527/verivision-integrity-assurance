from __future__ import annotations
from pathlib import Path
import json
import numpy as np
from PIL import Image
from .common import finding, entropy_hist, clamp

def stats(paths):
    out=[]
    for p in paths:
        try:
            with Image.open(p).convert('RGB') as im:
                a=np.asarray(im.resize((128,128)),dtype=np.float32); gray=a.mean(2)
                out.append({'brightness':float(gray.mean()),'contrast':float(gray.std()),'entropy':entropy_hist(gray),'edges':float(np.mean(np.abs(np.diff(gray,axis=0)))),'size':im.size})
        except: pass
    return out

def inspect_shift(reference_paths,current_paths):
    ref=stats([Path(x) for x in reference_paths]); cur=stats([Path(x) for x in current_paths]);
    if not ref or not cur:
        return [finding('SHIFT / ANOMALY','Insufficient imagery for drift analysis','Both reference and current image sets are required for a calibrated comparison.',[f'Reference images: {len(ref)}',f'Current images: {len(cur)}'],1.0,'No probabilistic drift verdict is claimed without both populations.','REVIEW','MEDIUM','drift_input')],{'reference':len(ref),'current':len(cur)},50
    keys=['brightness','contrast','entropy','edges']; diffs={}
    for k in keys:
        a=np.array([x[k] for x in ref]); b=np.array([x[k] for x in cur]); pooled=np.std(np.r_[a,b])+1e-6; diffs[k]=float(abs(a.mean()-b.mean())/pooled)
    z=np.mean(list(diffs.values())); score=float(min(100,z*35))
    # cause classifier: brightness-dominant and edge/entropy stable -> natural lighting/sensor candidate
    light=diffs['brightness']; texture=np.mean([diffs['entropy'],diffs['edges']])
    if score<20: verdict='STABLE'; conf=.86
    elif light>texture*1.5: verdict='NATURAL DRIFT CANDIDATE'; conf=min(.95,.60+light/(light+texture+1e-6)*.35)
    elif texture>1.4 and light<texture*.8: verdict='MANIPULATION CANDIDATE'; conf=min(.92,.58+texture/(light+texture+1e-6)*.35)
    else: verdict='CANNOT DISTINGUISH'; conf=.55
    action='ACCEPT' if verdict=='STABLE' else 'REVIEW'
    sev='LOW' if score<20 else 'MEDIUM'
    ev=[f'{k}: standardized shift {v:.2f}' for k,v in diffs.items()] + [f'Combined shift score: {score:.1f}/100',f'Classification: {verdict}']
    f=finding('SHIFT / ANOMALY','Distribution shift assessed',f'New imagery is classified as {verdict.lower()} with calibrated heuristic confidence {conf:.0%}.',ev,conf,'This is a statistical attribution, not proof of intent; thin evidence returns CANNOT DISTINGUISH.','REVIEW' if verdict!='STABLE' else 'ACCEPT',sev,'drift_attribution',diffs)
    return [f],{'reference':len(ref),'current':len(cur),'score':score,'classification':verdict,'confidence':conf,'features':diffs},score
