from __future__ import annotations
from pathlib import Path
import base64, json, hashlib, time, uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from .common import finding, sha256_file

class Signer:
    def __init__(self, key_path):
        self.key_path=Path(key_path); self.key_path.parent.mkdir(parents=True,exist_ok=True)
        if self.key_path.exists(): self.key=Ed25519PrivateKey.from_private_bytes(self.key_path.read_bytes())
        else:
            self.key=Ed25519PrivateKey.generate(); self.key_path.write_bytes(self.key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()))
        self.public=self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    def sign(self,payload:dict):
        raw=json.dumps(payload,sort_keys=True,separators=(',',':')).encode(); sig=self.key.sign(raw)
        return {'payload':payload,'signature':base64.b64encode(sig).decode(),'public_key':base64.b64encode(self.public).decode()}
    @staticmethod
    def verify(record):
        raw=json.dumps(record['payload'],sort_keys=True,separators=(',',':')).encode();
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(record['public_key'])).verify(base64.b64decode(record['signature']),raw); return True
        except Exception: return False

def merkle_root(hashes):
    hs=list(hashes)
    if not hs: return None
    while len(hs)>1:
        if len(hs)%2: hs.append(hs[-1])
        hs=[hashlib.sha256((hs[i]+hs[i+1]).encode()).hexdigest() for i in range(0,len(hs),2)]
    return hs[0]

def parse_records(path):
    p=Path(path); text=p.read_text(errors='ignore')
    if p.suffix.lower()=='.json':
        o=json.loads(text); return o if isinstance(o,list) else o.get('records',o.get('outputs',[]))
    rows=[]
    for line in text.splitlines():
        line=line.strip()
        if line:
            try: rows.append(json.loads(line))
            except: pass
    return rows

def inspect_outputs(path, signer:Signer):
    findings=[]; metrics={'records':0,'signed':0,'verified':0,'invalid_signatures':0,'hash_chain_breaks':0,'replay_candidates':0,'merkle_root':None,'public_key':signer.public.hex()}
    try: rows=parse_records(path)
    except Exception as e:
        return [finding('OUTPUT PROVENANCE','Output format unreadable','The output file could not be parsed as JSON/JSONL.',[str(e)],.95,'Supported formats are JSON and JSONL records.','REVIEW','HIGH','provenance_parse')],metrics,70
    rows=rows if isinstance(rows,list) else []
    metrics['records']=len(rows); signed=[]; prev='GENESIS'; seen_ids=set(); chain_ok=True
    for i,r in enumerate(rows):
        rid=str(r.get('id',f'REC-{i+1:05d}'))
        if rid in seen_ids: metrics['replay_candidates']+=1
        seen_ids.add(rid)
        rec=r.get('signed_record') if isinstance(r,dict) and 'signed_record' in r else r
        if isinstance(rec,dict) and all(k in rec for k in ('payload','signature','public_key')):
            metrics['signed']+=1; ok=Signer.verify(rec); metrics['verified']+=int(ok); metrics['invalid_signatures']+=int(not ok)
            payload=rec['payload']; record_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest(); signed.append(record_hash)
            expected_prev=payload.get('prev_hash','GENESIS')
            if expected_prev!=prev: metrics['hash_chain_breaks']+=1; chain_ok=False
            prev=record_hash
        else:
            metrics['signed']+=0
    metrics['merkle_root']=merkle_root(signed)
    if metrics['invalid_signatures']:
        findings.append(finding('OUTPUT PROVENANCE','Invalid signed inference records',f'{metrics["invalid_signatures"]} signed record(s) failed Ed25519 verification.',[f'Signed records: {metrics["signed"]}',f'Invalid signatures: {metrics["invalid_signatures"]}'],.999,'Verification depends on the public key embedded with each record; key compromise is outside scope.','QUARANTINE','CRITICAL','ed25519_verify',{'invalid':metrics['invalid_signatures']}))
    if metrics['hash_chain_breaks']:
        findings.append(finding('OUTPUT PROVENANCE','Inference hash-chain break detected','One or more records do not reference the immediately preceding verified record hash.',[f'Broken links: {metrics["hash_chain_breaks"]}',f'Merkle root of verified payloads: {metrics["merkle_root"]}'],.98,'Deletion/reordering after key compromise may require external anchors.','QUARANTINE','CRITICAL','hash_chain',{'breaks':metrics['hash_chain_breaks']}))
    if metrics['replay_candidates']:
        findings.append(finding('OUTPUT PROVENANCE','Replay candidate detected','Duplicate record identifiers appear in the submitted output stream.',[f'Duplicate IDs: {metrics["replay_candidates"]}'],.96,'Identifier duplication is a replay signal, not proof of malicious intent.','REVIEW','HIGH','replay_check',{'duplicates':metrics['replay_candidates']}))
    if rows and not metrics['signed']:
        findings.append(finding('OUTPUT PROVENANCE','Unsigned output records','Records were parsed but no Ed25519 signed envelope was found.',[f'Records parsed: {len(rows)}','Expected fields: payload, signature, public_key'],1.0,'Unsigned records cannot provide cryptographic provenance.','REVIEW','HIGH','signature_presence'))
    risk=90 if any(f.action=='QUARANTINE' for f in findings) else (55 if findings else 5)
    return findings,metrics,risk
