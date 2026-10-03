from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_health():
    r=client.get('/api/health'); assert r.status_code==200; assert r.json()['offline'] is True

def test_demo_inspection_and_report():
    d=client.post('/api/demo'); assert d.status_code==200
    r=client.post('/api/inspect',json={'name':'Automated Test','assets':d.json()['assets']}); assert r.status_code==200
    iid=r.json()['inspection_id']; x=client.get('/api/inspections/'+iid).json()
    assert x['overall']>=0 and x['overall']<=100
    assert x['findings']; assert x['metrics']['output']['signed']==20
    assert x['metrics']['output']['merkle_root']
    assert client.get('/api/report/'+iid).status_code==200

def test_tamper_replay_detects_modified_payload():
    d=client.post('/api/demo').json(); iid=client.post('/api/inspect',json={'name':'Tamper Test','assets':d['assets']}).json()['inspection_id']
    r=client.post('/api/simulate-tamper/'+iid); assert r.status_code==200; j=r.json(); assert j['original_signature_valid'] is True; assert j['tampered_signature_valid'] is False

def test_verify_reports_bad_signed_record():
    d=client.post('/api/demo').json(); iid=client.post('/api/inspect',json={'name':'Crypto Test','assets':d['assets']}).json()['inspection_id']
    j=client.get('/api/verify/'+iid).json(); assert j['valid'] is False; assert any(not x['valid'] for x in j['signed_records'])

def test_analytics_endpoint_returns_judge_ready_breakdown():
    d=client.post('/api/demo').json(); iid=client.post('/api/inspect',json={'name':'Analytics Test','assets':d['assets']}).json()['inspection_id']
    r=client.get('/api/analytics/'+iid); assert r.status_code==200
    j=r.json(); assert set(j['risk_vector'])=={'data','model','output','shift'}
    assert 'finding_breakdown' in j and 'governance' in j and 'crypto' in j
