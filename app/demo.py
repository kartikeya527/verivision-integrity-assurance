from __future__ import annotations
from pathlib import Path
import json, time, uuid, shutil
from PIL import Image, ImageDraw
import numpy as np
from .engines.provenance_engine import Signer
from .engines.common import sha256_file, stable_json
BASE=Path(__file__).resolve().parent.parent; DEMO=BASE/'demo_assets'; UP=BASE/'data'/'uploads'; KEYS=BASE/'data'/'keys'

def make_images():
    ref=DEMO/'reference'; cur=DEMO/'current'; data=DEMO/'dataset';
    for p in (ref,cur,data): p.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(7)
    for i in range(12):
        a=np.zeros((256,256,3),dtype=np.uint8); a[:]=rng.integers(45,75,size=(1,1,3));
        # terrain texture
        noise=rng.normal(0,12,(256,256,1)); a=np.clip(a+noise,0,255).astype(np.uint8)
        im=Image.fromarray(a); d=ImageDraw.Draw(im); x=30+(i*17)%150; y=60+(i*13)%140; d.rectangle((x,y,x+55,y+24),fill=(130,130,125)); d.line((0,220,256,180),fill=(95,95,95),width=8)
        im.save(ref/f'img_{i:03}.png')
        if i<10: im.save(data/f'img_{i:03}.png')
        # natural lighting drift
        c=np.clip(np.asarray(im).astype(np.float32)*1.35,0,255).astype(np.uint8); Image.fromarray(c).save(cur/f'img_{i:03}.png')
    # poisoned copies with obvious corner trigger and label inconsistency demo
    for i in (0,1):
        p=data/f'img_{i:03}.png'; im=Image.open(p).convert('RGB'); d=ImageDraw.Draw(im); d.rectangle((0,0,30,30),fill=(250,30,30)); im.save(data/f'poison_{i:03}.png')
    coco={'images':[],'annotations':[],'categories':[{'id':1,'name':'truck'},{'id':2,'name':'car'}]}
    for i,p in enumerate(sorted(data.glob('*.png'))): coco['images'].append({'id':i+1,'file_name':p.name,'width':256,'height':256}); coco['annotations'].append({'id':i+1,'image_id':i+1,'category_id':2 if p.name.startswith('poison') else 1,'bbox':[30,60,55,24],'area':1320})
    (DEMO/'dataset_coco.json').write_text(json.dumps(coco,indent=2))
    return ref,cur,data

def create_demo():
    ref,cur,data=make_images(); out=UP/'DEMO_outputs.json'; signer=Signer(KEYS/'ed25519_private.raw'); records=[]; prev='GENESIS';
    for i in range(20):
        payload={'id':f'INF-DEMO-{i+1:03}','timestamp':time.time()+i,'model_digest':'demo-model-digest','image_digest':sha256_file(sorted(ref.glob('*.png'))[i%len(list(ref.glob('*.png')))]),'prediction':{'class':'truck' if i%3 else 'car','confidence':round(.72+i*.01,3)},'prev_hash':prev}
        signed=signer.sign(payload); records.append(signed); import hashlib; prev=hashlib.sha256(stable_json(payload).encode()).hexdigest()
    # Add a deliberately invalid record so the provenance engine demonstrates detection.
    bad=records[-1].copy(); bad['payload']=dict(bad['payload']); bad['payload']['prediction']={'class':'bridge','confidence':.02}; records[-1]=bad
    out.write_text(json.dumps({'records':records},indent=2))
    assets=[]
    model_path=DEMO/'model_demo.pt'
    if not model_path.exists():
        try:
            import torch, torch.nn as nn
            class TinyVision(nn.Module):
                def __init__(self):
                    super().__init__(); self.net=nn.Sequential(nn.Conv2d(3,8,3,padding=1),nn.ReLU(),nn.AdaptiveAvgPool2d(1),nn.Flatten(),nn.Linear(8,2))
                def forward(self,x): return self.net(x)
            m=torch.jit.trace(TinyVision().eval(),torch.randn(1,3,64,64)); m.save(str(model_path))
        except Exception:
            model_path.write_bytes(b'VeriVision demo model placeholder')
    for p,t in [(DEMO/'dataset_coco.json','data'),(model_path,'model'),(out,'output')]:
        aid='AST-'+uuid.uuid4().hex[:10].upper(); dest=UP/f'{aid}_{p.name}'; shutil.copy2(p,dest); assets.append({'id':aid,'filename':p.name,'asset_type':t,'path':str(dest),'sha256':sha256_file(dest),'size':dest.stat().st_size})
    for p in sorted(data.glob('*.png'))[:6]:
        aid='AST-'+uuid.uuid4().hex[:10].upper(); dest=UP/f'{aid}_{p.name}'; shutil.copy2(p,dest); assets.append({'id':aid,'filename':p.name,'asset_type':'data','path':str(dest),'sha256':sha256_file(dest),'size':dest.stat().st_size})
    # references/current for drift engine
    for p in sorted(ref.glob('*.png'))[:8]:
        aid='AST-'+uuid.uuid4().hex[:10].upper(); dest=UP/f'{aid}_{p.name}'; shutil.copy2(p,dest); assets.append({'id':aid,'filename':p.name,'asset_type':'reference','path':str(dest),'sha256':sha256_file(dest),'size':dest.stat().st_size})
    for p in sorted(cur.glob('*.png'))[:8]:
        aid='AST-'+uuid.uuid4().hex[:10].upper(); dest=UP/f'{aid}_cur_{p.name}'; shutil.copy2(p,dest); assets.append({'id':aid,'filename':p.name,'asset_type':'current','path':str(dest),'sha256':sha256_file(dest),'size':dest.stat().st_size})
    return {'message':'Demo assets generated. Use POST /api/inspect with these assets or the dashboard demo button.','assets':assets,'demo_paths':{'dataset':str(DEMO/'dataset_coco.json'),'reference':str(ref),'current':str(cur),'outputs':str(out),'model':str(DEMO/'model_demo.pt')}}
