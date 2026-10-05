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

# ── New functional intelligence layer ──────────────────────────────────────
from .engines.evidence import (
    make_evidence, make_case, make_decision,
    EvidenceItem, Case, DecisionRecord,
)
from .engines.explanation_engine import explain_case, explain_item
from .engines.batch_risk import analyse_batch_and_contributor_risk
from .engines.asset_tracer import build_lineage
from .engines.decision_engine import decide
from .engines.recommendations import generate_recommendations
from .engines.timeline import build_timeline
from .engines.coverage import get_coverage_matrix
from .engines.attack_lab import list_scenarios, setup_scenario_assets, evaluate_ground_truth
from .engines.evidence_graph import build_evidence_graph

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
CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,inspection_id TEXT,case_json TEXT,decision_json TEXT,created_at REAL);
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
    trace_dict={'nodes':['DATA','MODEL','OUTPUT'],'edges':['DATA→MODEL','MODEL→OUTPUT'],'affected_outputs':metrics.get('output',{}).get('records',0),'evidence_links':sum(1 for f in findings if f.evidence)}
    overall,verdict=insert_inspection(c,iid,name,scores,coverage,trace_dict,metrics)
    for f in findings: add_finding(c,iid,f)
    audit(c,iid,'INSPECTION_CREATED',json.dumps({'assets':len(assets),'scores':scores,'overall':overall,'verdict':verdict}))

    # ── Build the evidence-model Case and DecisionRecord ───────────────
    _DOMAIN_MAP = {'data':'DATA','model':'MODEL','output':'OUTPUT','shift':'SHIFT'}
    _sev_from_action = {'QUARANTINE':'HIGH','REVIEW':'MEDIUM','ACCEPT':'LOW'}
    evi_items = []
    for f in findings:
        cat_u = (f.category or '').upper()
        if 'DATA' in cat_u:
            dom = 'DATA'
        elif 'MODEL' in cat_u:
            dom = 'MODEL'
        elif 'OUTPUT' in cat_u or 'PROVENANCE' in cat_u:
            dom = 'OUTPUT'
        elif 'SHIFT' in cat_u or 'ANOMALY' in cat_u:
            dom = 'SHIFT'
        else:
            eng_l = (f.engine or '').lower()
            if any(k in eng_l for k in ('ed25519', 'signature', 'provenance', 'hash', 'replay')):
                dom = 'OUTPUT'
            elif any(k in eng_l for k in ('model', 'pytorch', 'torch', 'onnx')):
                dom = 'MODEL'
            elif any(k in eng_l for k in ('drift', 'shift')):
                dom = 'SHIFT'
            else:
                dom = 'DATA'
        # map Finding to EvidenceItem
        rationale_text = (
            f"{f.claim} Engine: {f.engine}. "
            f"Confidence: {f.confidence:.0%}. "
            f"Limits: {f.limits}"
        )
        evi = make_evidence(
            domain=dom, engine=f.engine,
            title=f.title, claim=f.claim,
            rationale=rationale_text,
            evidence=f.evidence, confidence=f.confidence,
            severity=f.severity, action=f.action,
            limits=f.limits, metrics=f.metrics,
            asset_ids=[], tags=[f.category.lower().replace(' ','_')],
        )
        evi_items.append(evi)

    # Build per-contributor/batch risk
    findings_dicts = [f.as_dict() for f in findings]
    batch_result = analyse_batch_and_contributor_risk(assets, {})

    case = make_case(
        inspection_id=iid, name=name,
        evidence=evi_items,
        risk_vector={k: float(v) for k,v in scores.items()},
        overall_risk=float(overall),
        verdict=verdict,
        coverage=coverage,
        trace=list(trace_dict.get('edges',[])),
        asset_manifest=assets,
        contributor_risks=batch_result['contributor_risks'],
        batch_risks=batch_result['batch_risks'],
    )
    decision = decide(case)

    # Persist Case + Decision
    c.execute('CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,inspection_id TEXT,case_json TEXT,decision_json TEXT,created_at REAL)')
    c.execute('INSERT OR REPLACE INTO cases VALUES(?,?,?,?,?)',
        (case.case_id, iid, json.dumps(case.as_dict()), json.dumps(decision.as_dict()), time.time()))
    c.commit(); c.close()
    return {
        'inspection_id': iid,
        'case_id':       case.case_id,
        'overall':       overall,
        'verdict':       decision.verdict,
        'decision_id':   decision.record_id,
    }

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
    recs = generate_recommendations(findings, ins['verdict'])
    timeline = build_timeline(ins)
    return {
        'inspection_id':iid,
        'risk_vector':{'data':ins['data_risk'],'model':ins['model_risk'],'output':ins['output_risk'],'shift':ins['shift_risk']},
        'finding_breakdown':{'severity':severity,'engines':engines,'actions':actions},
        'governance':ins['metrics'].get('governance',{}),
        'assets_by_type':{t:sum(1 for a in ins['assets'] if a['asset_type']==t) for t in sorted({a['asset_type'] for a in ins['assets']})},
        'crypto':{'signed':ins['metrics'].get('output',{}).get('signed',0),'verified':ins['metrics'].get('output',{}).get('verified',0),'invalid':ins['metrics'].get('output',{}).get('invalid_signatures',0),'merkle_root':ins['metrics'].get('output',{}).get('merkle_root')},
        'trace':ins['trace'],
        'recommendations': recs,
        'timeline': timeline,
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
    
    # Load Decision Record if available
    dec_block = ''
    try:
        _, dec_dict = _load_case(iid)
        if dec_dict:
            dec_block = f'''<section class="card"><h2>Policy Decision &amp; Rationale</h2><p><b>Verdict:</b> <span class="risk" style="font-size:24px">{esc(dec_dict.get('verdict'))}</span> (Policy v{esc(dec_dict.get('policy_version'))})</p><p>{esc(dec_dict.get('rationale'))}</p><p class="muted">Blocking Domains: {', '.join(dec_dict.get('blocking_domains', [])) or 'None'}</p></section>'''
    except Exception:
        pass

    # Remediation Recommendations
    recs = generate_recommendations(ins['findings'], ins['verdict'])
    rec_items = ''.join(f'''<li><b>[{esc(r["priority"])}] {esc(r["action_title"])}:</b> {esc(r["description"])}</li>''' for r in recs)
    rec_block = f'''<section class="card"><h2>Remediation Recommendations</h2><ul>{rec_items}</ul></section>''' if recs else ''

    html=f'''<!doctype html><html><head><meta charset="utf-8"><title>VeriVision Assurance Report {esc(iid)}</title><style>body{{font-family:Inter,Arial,sans-serif;background:#071019;color:#e8eef3;max-width:1100px;margin:0 auto;padding:48px}}.card,.finding{{background:#0e1b26;border:1px solid #263744;border-radius:16px;padding:22px;margin:16px 0}}.risk{{font-size:38px;font-weight:800}}.muted{{color:#8da0ad}}li{{margin:7px 0}}h1{{letter-spacing:-.03em}}</style></head><body><p class="muted">OFFLINE · AIR-GAPPED · EVIDENCE-BASED</p><h1>VERIVISION ASSURANCE REPORT</h1><p>{esc(ins['name'])} · <code>{esc(iid)}</code></p><section class="card"><div class="risk">{ins['overall']} / 100 · {esc(ins['verdict'])}</div><p>Data {ins['data_risk']} · Model {ins['model_risk']} · Output {ins['output_risk']} · Shift {ins['shift_risk']}</p></section>{dec_block}{blocks}{rec_block}<section class="card"><h2>Audit integrity</h2><p>Records: {len(ins['audit'])}. SHA-256 chained audit trail. Ed25519 public key: <code>{SIGNER.public.hex()}</code></p></section></body></html>'''
    path=REPORTS/f'{iid}.html'; path.write_text(html,encoding='utf-8'); return FileResponse(path,media_type='text/html',filename=path.name)

@app.get('/api/export/{iid}')
def export_json(iid):
    return JSONResponse(get_inspection(iid))


# ─────────────────────────────────────────────────────────────────────────────
# NEW: Evidence / Case / Decision / Explanation / Lineage / Batch-Risk APIs
# ─────────────────────────────────────────────────────────────────────────────

def _load_case(iid: str):
    """Retrieve the Case JSON stored for a given inspection_id."""
    c = db()
    c.execute('CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,inspection_id TEXT,case_json TEXT,decision_json TEXT,created_at REAL)')
    row = c.execute('SELECT case_json, decision_json FROM cases WHERE inspection_id=? ORDER BY created_at DESC LIMIT 1', (iid,)).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, f'No Case found for inspection {iid}. Run /api/inspect first.')
    return json.loads(row['case_json']), json.loads(row['decision_json'])


@app.get('/api/case/{iid}')
def get_case(iid: str):
    """
    Return the full Case JSON for an inspection, including all EvidenceItems,
    risk vector, contributor/batch risks, and the persisted verdict.
    """
    case_dict, decision_dict = _load_case(iid)
    return JSONResponse({'case': case_dict, 'decision': decision_dict})


@app.get('/api/case/{iid}/explain')
def explain(iid: str):
    """
    Return a rich, plain-language explanation of the Case:
    summary paragraph, per-domain summaries, per-evidence explanations.
    """
    case_dict, _ = _load_case(iid)
    # Re-hydrate EvidenceItems from dict list
    from .engines.evidence import EvidenceItem, Case as CaseType, make_case as _mc
    raw_evidence = case_dict.get('evidence', [])
    evi_items = [EvidenceItem(**e) for e in raw_evidence]
    case = _mc(
        inspection_id     = case_dict['inspection_id'],
        name              = case_dict['name'],
        evidence          = evi_items,
        risk_vector       = case_dict['risk_vector'],
        overall_risk      = case_dict['overall_risk'],
        verdict           = case_dict['verdict'],
        coverage          = case_dict['coverage'],
        trace             = case_dict['trace'],
        asset_manifest    = case_dict['asset_manifest'],
        contributor_risks = case_dict.get('contributor_risks', {}),
        batch_risks       = case_dict.get('batch_risks', {}),
    )
    return JSONResponse(explain_case(case))


@app.get('/api/case/{iid}/graph')
def case_graph(iid: str):
    """
    Return the complete Evidence Graph 2.0 structure:
    - 4-level investigation hierarchy (Decision -> Domains -> Findings -> Supporting Evidence)
    - Semantic directional relationships with human-readable labels
    - Case story, why quarantined breakdown, evidence convergence summary,
      what graph tells us, uncertainties, and interactive evidence paths.
    """
    case_dict, decision_dict = _load_case(iid)
    ins = get_inspection(iid)
    from .engines.evidence import EvidenceItem, DecisionRecord, make_case as _mc
    raw_evidence = case_dict.get('evidence', [])
    evi_items = [EvidenceItem(**e) for e in raw_evidence]
    case = _mc(
        inspection_id     = case_dict['inspection_id'],
        name              = case_dict['name'],
        evidence          = evi_items,
        risk_vector       = case_dict['risk_vector'],
        overall_risk      = case_dict['overall_risk'],
        verdict           = case_dict['verdict'],
        coverage          = case_dict['coverage'],
        trace             = case_dict['trace'],
        asset_manifest    = case_dict['asset_manifest'],
        contributor_risks = case_dict.get('contributor_risks', {}),
        batch_risks       = case_dict.get('batch_risks', {}),
    )
    decision = DecisionRecord(**decision_dict)
    graph_data = build_evidence_graph(case, decision, ins)
    return JSONResponse(graph_data)


@app.get('/api/case/{iid}/lineage')
def lineage(iid: str):
    """
    Return the asset lineage graph (nodes + edges) for an inspection,
    with taint propagation from quarantined assets.
    """
    ins = get_inspection(iid)
    assets = ins.get('assets', [])
    findings_raw = ins.get('findings', [])
    # Convert findings to asset_tracer format (include action/severity fields)
    lineage_data = build_lineage(assets, findings_raw)
    return JSONResponse(lineage_data)


@app.get('/api/case/{iid}/batch-risk')
def batch_risk(iid: str):
    """
    Return per-contributor and per-batch risk scores for an inspection.
    """
    ins = get_inspection(iid)
    assets   = ins.get('assets', [])
    findings = ins.get('findings', [])
    # Build asset_id → findings map
    findings_by_asset: dict = {}
    for f in findings:
        # findings don't carry asset_ids in the legacy schema, so we map globally
        for a in assets:
            findings_by_asset.setdefault(a['id'], []).append(f)
        break  # only do this once; real asset_id mapping requires engine upgrade
    result = analyse_batch_and_contributor_risk(assets, {})
    return JSONResponse(result)


@app.get('/api/case/{iid}/decision')
def decision(iid: str):
    """
    Return the DecisionRecord for an inspection — the machine-readable final
    verdict with rationale, blocking domains, and critical EVI IDs.
    """
    _, decision_dict = _load_case(iid)
    return JSONResponse(decision_dict)


@app.get('/api/case/{iid}/evidence/{eid}')
def get_evidence_item(iid: str, eid: str):
    """
    Return the full explanation for a single EvidenceItem by its EVI ID.
    """
    case_dict, _ = _load_case(iid)
    raw_evidence = case_dict.get('evidence', [])
    for e in raw_evidence:
        if e.get('eid') == eid:
            from .engines.evidence import EvidenceItem
            item = EvidenceItem(**e)
            return JSONResponse(explain_item(item))
    raise HTTPException(404, f'EvidenceItem {eid} not found in case for inspection {iid}')


@app.get('/api/case/{iid}/timeline')
def case_timeline(iid: str):
    """Return chronological event timeline for the inspection."""
    ins = get_inspection(iid)
    return JSONResponse(build_timeline(ins))


@app.get('/api/case/{iid}/recommendations')
def case_recommendations(iid: str):
    """Return operator remediation recommendations for the inspection."""
    ins = get_inspection(iid)
    return JSONResponse(generate_recommendations(ins['findings'], ins['verdict']))


@app.get('/api/coverage')
def coverage_matrix():
    """Return capability coverage matrix detailing verified capabilities and limitations."""
    return JSONResponse(get_coverage_matrix())


@app.get('/api/scenarios')
def get_attack_scenarios():
    """Return catalog of reproducible Attack Lab scenarios."""
    return JSONResponse(list_scenarios())


@app.post('/api/scenarios/{scenario_id}/run')
async def run_attack_scenario(scenario_id: str):
    """
    Execute a reproducible Attack Lab scenario:
    Generates controlled scenario assets, executes full inspection,
    evaluates Ground Truth vs VeriVision Decision, and returns structured comparison.
    """
    try:
        assets, gt = setup_scenario_assets(scenario_id, UP, SIGNER)
    except ValueError as e:
        raise HTTPException(404, str(e))

    # If model scenario, manage registrations table for accurate baseline testing
    if scenario_id == "model_substitution":
        c = db()
        c.execute('INSERT OR REPLACE INTO registrations VALUES(?,?,?,?)',
                  ('model', 'KNOWN_TRUSTED_MODEL_DIGEST_CANONICAL_V1', time.time(), 'expected baseline'))
        c.commit()
        c.close()
    elif scenario_id == "clean_pipeline":
        model_asset = next((a for a in assets if a['asset_type'] == 'model'), None)
        if model_asset:
            c = db()
            c.execute('INSERT OR REPLACE INTO registrations VALUES(?,?,?,?)',
                      ('model', model_asset['sha256'], time.time(), 'certified clean baseline'))
            c.commit()
            c.close()

    # Run inspection
    inspect_res = await inspect({'name': f'Attack Lab: {scenario_id}', 'assets': assets})
    iid = inspect_res['inspection_id']
    ins = get_inspection(iid)
    case_dict, dec_dict = _load_case(iid)

    evaluation = evaluate_ground_truth(gt, ins, dec_dict)
    return JSONResponse({
        'scenario_id': scenario_id,
        'inspection_id': iid,
        'ground_truth': gt,
        'evaluation': evaluation,
        'verdict': dec_dict.get('verdict'),
        'decision': dec_dict,
        'findings_count': len(ins['findings']),
    })


