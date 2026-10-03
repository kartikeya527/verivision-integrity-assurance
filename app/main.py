from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import hashlib, json, sqlite3, time, uuid, os, shutil
from typing import Optional

from .engines.common import sha256_file, stable_json
from .engines.data_engine import inspect_data, parse_coco, parse_yolo
from .engines.model_engine import inspect_model
from .engines.provenance_engine import Signer, inspect_outputs, merkle_root
from .engines.shift_engine import inspect_shift

BASE=Path(__file__).resolve().parent.parent
DATA=BASE/'data'; UP=DATA/'uploads'; REPORTS=DATA/'reports'; KEYS=DATA/'keys'; DB=DATA/'verivision.db'
for p in (UP,REPORTS,KEYS): p.mkdir(parents=True,exist_ok=True)
SIGNER=Signer(KEYS/'ed25519_private.raw')
app=FastAPI(title='VeriVision Trust & Integrity Inspector',version='3.0.0',description='Offline evidence-based integrity assurance for computer-vision data, models and inference outputs.')
app.mount('/static',StaticFiles(directory=BASE/'app'/'static'),name='static')

SCHEMA='''
CREATE TABLE IF NOT EXISTS inspections(id TEXT PRIMARY KEY,name TEXT,created_at REAL,data_risk REAL,model_risk REAL,output_risk REAL,shift_risk REAL,overall REAL,verdict TEXT,status TEXT,coverage TEXT,trace TEXT,metrics TEXT);
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,inspection_id TEXT,filename TEXT,asset_type TEXT,path TEXT,sha256 TEXT,size INTEGER,created_at REAL);
CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY,inspection_id TEXT,category TEXT,title TEXT,claim TEXT,evidence TEXT,confidence REAL,limits TEXT,action TEXT,severity TEXT,engine TEXT,metrics TEXT,created_at REAL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,inspection_id TEXT,event TEXT,payload TEXT,prev_hash TEXT,hash TEXT,ts REAL);
CREATE TABLE IF NOT EXISTS signed_records(id TEXT PRIMARY KEY,inspection_id TEXT,record_json TEXT,record_hash TEXT,signature TEXT,public_key TEXT,created_at REAL);
CREATE TABLE IF NOT EXISTS registrations(asset_type TEXT PRIMARY KEY,sha256 TEXT,registered_at REAL,notes TEXT);
'''

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.executescript(SCHEMA)
    cols=[r['name'] for r in c.execute('PRAGMA table_info(inspections)')]
    if len(cols)<13:
        try: c.execute('ALTER TABLE inspections RENAME TO inspections_legacy')
        except Exception: pass
        c.execute('''CREATE TABLE IF NOT EXISTS inspections(id TEXT PRIMARY KEY,name TEXT,created_at REAL,data_risk REAL,model_risk REAL,output_risk REAL,shift_risk REAL,overall REAL,verdict TEXT,status TEXT,coverage TEXT,trace TEXT,metrics TEXT)''')
        try: c.execute('''INSERT OR IGNORE INTO inspections(id,name,created_at,data_risk,model_risk,output_risk,shift_risk,overall,verdict,status) SELECT id,name,created_at,data_risk,model_risk,output_risk,shift_risk,overall,verdict,status FROM inspections_legacy''')
        except Exception: pass
    fcols=[r['name'] for r in c.execute('PRAGMA table_info(findings)')]
    if len(fcols)<13:
        try: c.execute('ALTER TABLE findings RENAME TO findings_legacy')
        except Exception: pass
        c.execute('''CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY,inspection_id TEXT,category TEXT,title TEXT,claim TEXT,evidence TEXT,confidence REAL,limits TEXT,action TEXT,severity TEXT,engine TEXT,metrics TEXT,created_at REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS signed_records(id TEXT PRIMARY KEY,inspection_id TEXT,record_json TEXT,record_hash TEXT,signature TEXT,public_key TEXT,created_at REAL)''')
    c.commit(); return c

def audit(c,iid,event,payload):
    row=c.execute('SELECT hash FROM audit WHERE inspection_id=? ORDER BY id DESC LIMIT 1',(iid,)).fetchone(); prev=row['hash'] if row else 'GENESIS'; ts=time.time(); raw=f'{prev}|{iid}|{event}|{payload}|{ts}'.encode(); hv=hashlib.sha256(raw).hexdigest(); c.execute('INSERT INTO audit(inspection_id,event,payload,prev_hash,hash,ts) VALUES(?,?,?,?,?,?)',(iid,event,payload,prev,hv,ts)); return hv

def add_finding(c,iid,f):
    fid='F-'+uuid.uuid4().hex[:8].upper(); c.execute('INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(fid,iid,f.category,f.title,f.claim,json.dumps(f.evidence),f.confidence,f.limits,f.action,f.severity,f.engine,json.dumps(f.metrics),time.time())); return fid

def verdict_for(scores):
    overall=round(scores['data']*.30+scores['model']*.20+scores['output']*.30+scores['shift']*.20,1)
    if any(v>=85 for v in scores.values()): verdict='QUARANTINE'
    elif overall>=55 or any(v>=45 for v in scores.values()): verdict='REVIEW'
    else: verdict='ACCEPT'
    return overall,verdict

def insert_inspection(c,iid,name,scores,coverage,trace,metrics,status='complete'):
    overall,verdict=verdict_for(scores); c.execute('INSERT INTO inspections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(iid,name,time.time(),scores['data'],scores['model'],scores['output'],scores['shift'],overall,verdict,status,json.dumps(coverage),json.dumps(trace),json.dumps(metrics))); return overall,verdict

def persist_assets(c,iid,assets):
    for a in assets:
        c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)',(a['id'],iid,a['filename'],a['asset_type'],a['path'],a['sha256'],a['size'],time.time()))

def get_inspection(iid):
    c=db(); r=c.execute('SELECT * FROM inspections WHERE id=?',(iid,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Inspection not found')
    ins=dict(r); ins['coverage']=json.loads(ins['coverage']); ins['trace']=json.loads(ins['trace']); ins['metrics']=json.loads(ins['metrics'])
    ins['assets']=[dict(x) for x in c.execute('SELECT id,filename,asset_type,sha256,size FROM assets WHERE inspection_id=? ORDER BY created_at',(iid,))]
    fs=[]
    for x in c.execute('SELECT * FROM findings WHERE inspection_id=? ORDER BY created_at', (iid,)):
        d=dict(x); d['evidence']=json.loads(d['evidence']); d['metrics']=json.loads(d['metrics']); fs.append(d)
    ins['findings']=fs
    ins['audit']=[dict(x) for x in c.execute('SELECT * FROM audit WHERE inspection_id=? ORDER BY id',(iid,))]
    ins['signed_records']=[dict(x) for x in c.execute('SELECT id,record_hash,signature,public_key,created_at FROM signed_records WHERE inspection_id=? ORDER BY created_at',(iid,))]
    c.close(); return ins

@app.get('/',response_class=HTMLResponse)
def index(): return FileResponse(BASE/'app'/'static'/'index.html')

@app.get('/api/health')
def health():
    return {'status':'ok','version':'3.0.0','offline':True,'crypto':'Ed25519 + SHA-256','public_key':SIGNER.public.hex()}

@app.post('/api/upload')
async def upload(file:UploadFile=File(...),asset_type:str='data'):
    safe=Path(file.filename or 'upload.bin').name; aid='AST-'+uuid.uuid4().hex[:10].upper(); dest=UP/f'{aid}_{safe}'
    with dest.open('wb') as out: shutil.copyfileobj(file.file,out)
    return {'id':aid,'filename':safe,'asset_type':asset_type,'sha256':sha256_file(dest),'size':dest.stat().st_size,'path':str(dest)}

@app.post('/api/register')
def register(payload:dict):
    asset_type=payload.get('asset_type','model'); digest=payload.get('sha256'); notes=payload.get('notes','')
    if not digest: raise HTTPException(400,'sha256 required')
    c=db(); c.execute('INSERT OR REPLACE INTO registrations VALUES(?,?,?,?)',(asset_type,digest,time.time(),notes)); audit(c,'REGISTRY','REGISTER',json.dumps(payload)); c.commit(); c.close(); return {'registered':True,'asset_type':asset_type,'sha256':digest}

@app.post('/api/demo')
def demo():
    from .demo import create_demo
    return create_demo()

@app.post('/api/inspect')
async def inspect(payload:dict):
    name=payload.get('name') or 'Offline assurance inspection'; assets=payload.get('assets',[]); iid='INS-'+uuid.uuid4().hex[:8].upper(); c=db(); persist_assets(c,iid,assets)
    data_paths=[a['path'] for a in assets if a.get('asset_type')=='data']
    model=[a for a in assets if a.get('asset_type')=='model']
    outputs=[a for a in assets if a.get('asset_type')=='output']
    ref=[a['path'] for a in assets if a.get('asset_type')=='reference']
    current=[a['path'] for a in assets if a.get('asset_type')=='current']
    all_data=[a['path'] for a in assets if a.get('asset_type') in ('data','reference','current')]
    findings=[]; metrics={}; coverage=[]
    fs,dm,dr=inspect_data(all_data); findings+=fs; metrics['data']=dm; coverage+=['COCO/YOLO parsing','exact duplicate hashing','near-duplicate analysis','visible trigger candidate scan','annotation schema validation']
    if model:
        reg=c.execute('SELECT sha256 FROM registrations WHERE asset_type=?',('model',)).fetchone(); expected=reg['sha256'] if reg else None
        fs,mm,mr=inspect_model(model[0]['path'],expected); findings+=fs; metrics['model']=mm; coverage+=['PyTorch weight fingerprint','ONNX graph validation','model digest swap check']
    else:
        mr=100; coverage+=['Model engine: unavailable — no model uploaded']
    if outputs:
        fs,om,orr=inspect_outputs(outputs[0]['path'],SIGNER); findings+=fs; metrics['output']=om; coverage+=['Ed25519 signature verification','hash-chain verification','replay detection','Merkle root']
        # persist canonical signed records if present
        try:
            rows=json.loads(Path(outputs[0]['path']).read_text())
            rows=rows if isinstance(rows,list) else rows.get('records',[])
            for r in rows:
                rec=r.get('signed_record',r) if isinstance(r,dict) else {}
                if all(k in rec for k in ('payload','signature','public_key')):
                    rh=hashlib.sha256(stable_json(rec['payload']).encode()).hexdigest(); c.execute('INSERT OR REPLACE INTO signed_records VALUES(?,?,?,?,?,?,?)',(str(rec['payload'].get('id',uuid.uuid4().hex)),iid,json.dumps(rec),rh,rec['signature'],rec['public_key'],time.time()))
        except: pass
    else: orr=100
    if ref and current:
        fs,sm,sr=inspect_shift(ref,current); findings+=fs; metrics['shift']=sm; coverage+=['drift attribution: brightness/contrast/entropy/edge statistics','natural-vs-manipulation candidate classification']
    else:
        sr=50; metrics['shift']={'classification':'INSUFFICIENT EVIDENCE','reference':len(ref),'current':len(current)}; coverage+=['Shift engine requires reference + current image populations']
    scores={'data':dr,'model':mr,'output':orr,'shift':sr}
    checked=sum(1 for v in scores.values() if v not in (100,50))
    evidence_items=sum(len(f.evidence) for f in findings); max_evidence=max(1,len(findings)*3)
    metrics['governance']={'evidence_coverage_score':round((checked/4)*100,1),'evidence_density':round(min(100,evidence_items/max_evidence*100),1),'confidence_budget':round(sum(f.confidence for f in findings)/max(1,len(findings))*100,1)}
    trace={'nodes':['DATA','MODEL','OUTPUT'],'edges':['DATA→MODEL','MODEL→OUTPUT'],'affected_outputs':metrics.get('output',{}).get('records',0),'evidence_links':sum(1 for f in findings if f.evidence)}
    overall,verdict=insert_inspection(c,iid,name,scores,coverage,trace,metrics)
    for f in findings: add_finding(c,iid,f)
    audit(c,iid,'INSPECTION_CREATED',json.dumps({'assets':len(assets),'scores':scores,'overall':overall,'verdict':verdict})); c.commit(); c.close(); return {'inspection_id':iid,'overall':overall,'verdict':verdict}

@app.post('/api/sign-output')
def sign_output(payload:dict):
    record={'id':payload.get('id','INF-'+uuid.uuid4().hex[:8].upper()),'timestamp':payload.get('timestamp',time.time()),'model_digest':payload.get('model_digest',''),'image_digest':payload.get('image_digest',''),'prediction':payload.get('prediction',{}),'prev_hash':payload.get('prev_hash','GENESIS')}
    signed=SIGNER.sign(record); return {'signed_record':signed,'record_hash':hashlib.sha256(stable_json(record).encode()).hexdigest()}

@app.get('/api/inspections')
def inspections():
    c=db(); rows=[dict(x) for x in c.execute('SELECT id,name,created_at,overall,verdict,status FROM inspections ORDER BY created_at DESC')]; c.close(); return rows

@app.get('/api/inspections/{iid}')
def inspection(iid): return get_inspection(iid)

@app.get('/api/verify/{iid}')
def verify(iid):
    ins=get_inspection(iid); prev='GENESIS'; checks=[]; ok=True
    for a in ins['audit']:
        raw=f"{prev}|{a['inspection_id']}|{a['event']}|{a['payload']}|{a['ts']}".encode(); expected=hashlib.sha256(raw).hexdigest(); match=(expected==a['hash'] and a['prev_hash']==prev); checks.append({'id':a['id'],'valid':match}); ok=ok and match; prev=a['hash']
    signed=[]; c=db()
    try:
        for s in ins['signed_records']:
            rec=c.execute('SELECT record_json FROM signed_records WHERE id=?',(s['id'],)).fetchone()
            if rec:
                obj=json.loads(rec['record_json']); signed.append({'id':s['id'],'valid':Signer.verify(obj)})
    finally:
        c.close()
    signed_ok=all(x['valid'] for x in signed) if signed else True
    return {'valid':ok and signed_ok,'checks':checks,'signed_records':signed,'records':len(checks),'message':'Audit chain and signed records verified' if ok and signed_ok else ('Audit chain verified, but signed-record verification failed' if ok else 'Audit chain broken')}

@app.get('/api/analytics/{iid}')
def analytics(iid):
    ins=get_inspection(iid)
    findings=ins['findings']; severity={}; engines={}; actions={}
    for f in findings:
        severity[f['severity']]=severity.get(f['severity'],0)+1
        engines[f['engine']]=engines.get(f['engine'],0)+1
        actions[f['action']]=actions.get(f['action'],0)+1
    return {
        'inspection_id':iid,
        'risk_vector':{'data':ins['data_risk'],'model':ins['model_risk'],'output':ins['output_risk'],'shift':ins['shift_risk']},
        'finding_breakdown':{'severity':severity,'engines':engines,'actions':actions},
        'governance':ins['metrics'].get('governance',{}),
        'assets_by_type':{t:sum(1 for a in ins['assets'] if a['asset_type']==t) for t in sorted({a['asset_type'] for a in ins['assets']})},
        'crypto':{'signed':ins['metrics'].get('output',{}).get('signed',0),'verified':ins['metrics'].get('output',{}).get('verified',0),'invalid':ins['metrics'].get('output',{}).get('invalid_signatures',0),'merkle_root':ins['metrics'].get('output',{}).get('merkle_root')},
        'trace':ins['trace']
    }

@app.post('/api/simulate-tamper/{iid}')
def simulate_tamper(iid):
    ins=get_inspection(iid)
    if not ins['signed_records']: raise HTTPException(400,'No signed output record is available for this inspection')
    rec=json.loads(db().execute('SELECT record_json FROM signed_records WHERE id=?',(ins['signed_records'][0]['id'],)).fetchone()['record_json'])
    tampered=json.loads(json.dumps(rec)); tampered['payload']['prediction']={'class':'NO_THREAT','confidence':0.01}
    return {'record_id':ins['signed_records'][0]['id'],'original_prediction':rec['payload'].get('prediction'),'tampered_prediction':tampered['payload'].get('prediction'),'original_signature_valid':SIGNER.verify(rec),'tampered_signature_valid':SIGNER.verify(tampered),'explanation':'The payload was changed without re-signing it; Ed25519 verification fails while the original remains valid.'}

@app.get('/api/report/{iid}')
def report(iid):
    ins=get_inspection(iid); esc=lambda x:str(x).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    blocks=''.join(f'''<article class="finding"><h2>{esc(f["id"])} · {esc(f["title"])}</h2><p><b>{esc(f["category"])} · {esc(f["severity"])} · {esc(f["action"])}</b></p><p>{esc(f["claim"])}</p><ul>{''.join('<li>'+esc(e)+'</li>' for e in f['evidence'])}</ul><p>Confidence: {f["confidence"]:.0%}</p><p class="muted">Limits: {esc(f["limits"])}</p></article>''' for f in ins['findings'])
    html=f'''<!doctype html><html><head><meta charset="utf-8"><title>VeriVision Assurance Report {esc(iid)}</title><style>body{{font-family:Inter,Arial,sans-serif;background:#071019;color:#e8eef3;max-width:1100px;margin:0 auto;padding:48px}}.card,.finding{{background:#0e1b26;border:1px solid #263744;border-radius:16px;padding:22px;margin:16px 0}}.risk{{font-size:38px;font-weight:800}}.muted{{color:#8da0ad}}li{{margin:7px 0}}h1{{letter-spacing:-.03em}}</style></head><body><p class="muted">OFFLINE · AIR-GAPPED · EVIDENCE-BASED</p><h1>VERIVISION ASSURANCE REPORT</h1><p>{esc(ins['name'])} · <code>{esc(iid)}</code></p><section class="card"><div class="risk">{ins['overall']} / 100 · {esc(ins['verdict'])}</div><p>Data {ins['data_risk']} · Model {ins['model_risk']} · Output {ins['output_risk']} · Shift {ins['shift_risk']}</p></section>{blocks}<section class="card"><h2>Audit integrity</h2><p>Records: {len(ins['audit'])}. SHA-256 chained audit trail. Ed25519 public key: <code>{SIGNER.public.hex()}</code></p></section></body></html>'''
    path=REPORTS/f'{iid}.html'; path.write_text(html,encoding='utf-8'); return FileResponse(path,media_type='text/html',filename=path.name)

@app.get('/api/export/{iid}')
def export_json(iid):
    return JSONResponse(get_inspection(iid))
