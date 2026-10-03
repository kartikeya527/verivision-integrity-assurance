from __future__ import annotations
from pathlib import Path
import json, os, re
import numpy as np
from PIL import Image
from .common import finding, sha256_file, robust_z, clamp

IMG_EXT={'.jpg','.jpeg','.png','.bmp','.tif','.tiff','.webp'}

def _images_from_root(root):
    if root.is_file() and root.suffix.lower() in IMG_EXT: return [root]
    return [p for p in root.rglob('*') if p.suffix.lower() in IMG_EXT]

def parse_coco(path):
    obj=json.loads(path.read_text(encoding='utf-8'))
    cats={int(x['id']):x.get('name',str(x['id'])) for x in obj.get('categories',[])}
    imgs={int(x['id']):x for x in obj.get('images',[])}
    anns=[]
    for a in obj.get('annotations',[]):
        anns.append({'image_id':a.get('image_id'),'category':cats.get(int(a.get('category_id',-1)),'unknown'),'bbox':a.get('bbox'),'area':a.get('area')})
    return {'format':'COCO','images':imgs,'annotations':anns,'categories':cats}

def parse_yolo(label_dir):
    rows=[]
    for p in label_dir.rglob('*.txt'):
        for i,line in enumerate(p.read_text(errors='ignore').splitlines()):
            z=line.split()
            if len(z)>=5:
                try: rows.append({'file':p.name,'class':int(float(z[0])),'xywh':[float(v) for v in z[1:5]]})
                except: pass
    return {'format':'YOLO','annotations':rows}

def _color_signature(path):
    with Image.open(path) as im:
        im=im.convert('RGB').resize((64,64))
        a=np.asarray(im,dtype=np.float32)
        # compact perceptual-ish signature
        gray=(0.299*a[:,:,0]+0.587*a[:,:,1]+0.114*a[:,:,2])
        small=Image.fromarray(gray.astype(np.uint8)).resize((16,16))
        v=np.asarray(small,dtype=np.float32).reshape(-1)
        v=(v-v.mean())/(v.std()+1e-6)
        return v

def inspect_data(asset_paths, metadata=None):
    metadata=metadata or {}
    findings=[]; metrics={'files':0,'images':0,'exact_duplicates':0,'near_duplicates':0,'label_anomalies':0,'trigger_candidates':0,'ood_score':None,'sources':{}}
    files=[Path(p) for p in asset_paths]
    imgs=[]; digests={}
    for p in files:
        if not p.exists(): continue
        metrics['files']+=1; digests.setdefault(sha256_file(p),[]).append(str(p))
        if p.suffix.lower() in IMG_EXT: imgs.append(p)
        elif p.suffix.lower()=='.json':
            try:
                obj=json.loads(p.read_text(errors='ignore'))
                if 'images' in obj and 'annotations' in obj:
                    parsed=parse_coco(p); metrics['coco_images']=len(parsed['images']); metrics['coco_annotations']=len(parsed['annotations'])
            except: pass
    exact=sum(max(0,len(v)-1) for v in digests.values())
    metrics['exact_duplicates']=exact
    if exact:
        findings.append(finding('DATA INTEGRITY','Exact duplicate flooding detected',f'{exact} file(s) share an identical SHA-256 digest.',[f'Duplicate digest groups: {sum(1 for v in digests.values() if len(v)>1)}',f'Duplicate files: {exact}'],.99,'Hash equality does not catch semantic copies with changed encoding.','QUARANTINE','HIGH','data_integrity',{'duplicate_files':exact}))
    # YOLO label parsing (directory/file based; normalized xywh schema validation)
    yolo_rows=[]; yolo_bad=0
    for p in files:
        if p.suffix.lower()=='.txt':
            for line in p.read_text(errors='ignore').splitlines():
                z=line.split()
                if not line.strip(): continue
                if len(z)>=5:
                    try:
                        vals=[float(v) for v in z[:5]]
                        if not (0<=vals[1]<=1 and 0<=vals[2]<=1 and 0<=vals[3]<=1 and 0<=vals[4]<=1): yolo_bad+=1
                        yolo_rows.append(vals)
                    except: yolo_bad+=1
                else: yolo_bad+=1
    metrics['yolo_annotations']=len(yolo_rows); metrics['yolo_invalid']=yolo_bad
    if yolo_rows:
        coverage_msg=f'YOLO annotations parsed: {len(yolo_rows)}'
        if yolo_bad:
            findings.append(finding('DATA INTEGRITY','Invalid YOLO annotation geometry',f'{yolo_bad} YOLO row(s) fall outside the normalized coordinate schema.',[coverage_msg,f'Invalid rows: {yolo_bad}'],.99,'Schema validation does not prove semantic label correctness.','QUARANTINE','HIGH','yolo_validation',{'invalid':yolo_bad}))
    metrics['images']=len(imgs)
    if imgs:
        sigs=[]; valid=[]
        for p in imgs[:1000]:
            try: sigs.append(_color_signature(p)); valid.append(p)
            except: pass
        if len(sigs)>=2:
            A=np.vstack(sigs); D=np.sqrt(((A[:,None,:]-A[None,:,:])**2).mean(axis=2)); np.fill_diagonal(D,np.inf)
            close=np.where(D<0.35); near_pairs={(min(int(i),int(j)),max(int(i),int(j))) for i,j in zip(*close) if i!=j}
            metrics['near_duplicates']=len(near_pairs)
            if near_pairs:
                findings.append(finding('DATA INTEGRITY','Near-duplicate cluster detected',f'{len(near_pairs)} image pair(s) are unusually similar in normalized appearance.',[f'Compared {len(sigs)} image fingerprints',f'Pairs below similarity threshold: {len(near_pairs)}','Similarity is based on compact pixel signatures'],min(.98,.55+len(near_pairs)/max(20,len(sigs))), 'Perceptual signature is lightweight; deep semantic copies may evade this check.','REVIEW','MEDIUM','data_integrity',{'near_duplicate_pairs':len(near_pairs)}))
        # simple visible-trigger candidate scan: repeated high-contrast corner blocks
        patches=[]
        for p in valid[:300]:
            try:
                with Image.open(p).convert('RGB') as im:
                    a=np.asarray(im.resize((128,128)),dtype=np.float32)
                gray=a.mean(2)
                q=[gray[:24,:24].std(),gray[:24,-24:].std(),gray[-24:,:24].std(),gray[-24:,-24:].std()]
                patches.append(max(q))
            except: pass
        if patches:
            z=robust_z(patches); candidates=int((z>5).sum()); metrics['trigger_candidates']=candidates
            if candidates:
                findings.append(finding('DATA INTEGRITY','Repeated high-contrast patch candidate',f'{candidates} image(s) contain an unusually high-variance corner region consistent with a possible visible trigger.',[f'Robust z-score threshold: >5',f'Candidates: {candidates}','This is a trigger-candidate detector, not proof of a backdoor.'],min(.9,.55+candidates/max(10,len(patches))), 'Only simple visible/corner patterns are probed; adaptive or invisible triggers are not claimed.','REVIEW','MEDIUM','trigger_probe',{'candidates':candidates,'sampled_images':len(patches)}))
    if not imgs and not any(p.suffix.lower()=='.json' for p in files):
        findings.append(finding('DATA INTEGRITY','No image/dataset structure recognized','No supported image set or COCO JSON was found.', ['Supported image formats: JPG/PNG/BMP/TIFF/WEBP','COCO JSON can be parsed directly','YOLO label directories are supported by the engine API'],1.0,'The engine does not infer dataset semantics from arbitrary binary files.','REVIEW','MEDIUM','data_integrity'))
    # lightweight label checks for COCO and YOLO
    for p in files:
        if p.suffix.lower()=='.json':
            try:
                o=json.loads(p.read_text(errors='ignore'))
                if 'annotations' in o and 'categories' in o:
                    cats={int(c['id']) for c in o.get('categories',[])}; bad=[a for a in o['annotations'] if int(a.get('category_id',-1)) not in cats]
                    metrics['label_anomalies']+=len(bad)
                    if bad: findings.append(finding('DATA INTEGRITY','Invalid annotation references',f'{len(bad)} annotations reference missing category IDs.',[f'Invalid annotations: {len(bad)}'],.99,'This is schema-level validation, not semantic label verification.','QUARANTINE','HIGH','label_validation',{'invalid_refs':len(bad)}))
            except: pass
    # Lightweight embedding/OOD analysis: deterministic PCA over downsampled RGB vectors.
    # This is intentionally model-free so it remains usable in an air-gapped environment.
    if len(imgs)>=6:
        try:
            from sklearn.decomposition import PCA
            X=[]; used=[]
            for p in imgs[:500]:
                try:
                    with Image.open(p).convert('RGB') as im:
                        a=np.asarray(im.resize((24,24)),dtype=np.float32).reshape(-1)/255.0
                    X.append(a); used.append(p)
                except: pass
            if len(X)>=6:
                X=np.vstack(X); ncomp=max(2,min(12,len(X)-1)); Z=PCA(n_components=ncomp,random_state=7).fit_transform(X); center=Z.mean(0); dist=np.sqrt(((Z-center)**2).sum(1)); q=float(np.quantile(dist,.95)); out=int((dist>q*1.15).sum()); metrics['ood_score']=float(np.mean(dist>q*1.15)); metrics['embedding_dim']=ncomp; metrics['ood_candidates']=out
                if out:
                    findings.append(finding('DATA INTEGRITY','Embedding-space OOD candidates detected',f'{out} image(s) sit unusually far from the dominant dataset embedding cluster.',[f'PCA embedding dimensions: {ncomp}',f'95th percentile distance: {q:.3f}',f'OOD candidates: {out}'],min(.94,.55+out/max(10,len(X))), 'This is a lightweight visual embedding, not a foundation-model semantic embedding; review candidates before attributing intent.','REVIEW','MEDIUM','embedding_ood',{'candidates':out,'embedding_dim':ncomp,'threshold':q*1.15}))
        except Exception as e:
            metrics['ood_unavailable']=str(e)[:160]
    risk=max(0, 75 if exact else 0, 45 if metrics['near_duplicates'] else 0, 60 if metrics['trigger_candidates'] else 0, 80 if metrics['label_anomalies'] else 0, 50 if metrics.get('ood_candidates',0) else 0, 80 if metrics.get('yolo_invalid',0) else 0)
    return findings,metrics,float(risk)
