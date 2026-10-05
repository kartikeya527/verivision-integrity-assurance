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

def test_case_and_decision_endpoints():
    d = client.post('/api/demo').json()
    inspect_res = client.post('/api/inspect', json={'name': 'Case Test', 'assets': d['assets']})
    assert inspect_res.status_code == 200
    iid = inspect_res.json()['inspection_id']

    # 1. Full Case
    case_res = client.get(f'/api/case/{iid}')
    assert case_res.status_code == 200
    c_json = case_res.json()
    assert 'case' in c_json and 'decision' in c_json
    case_data = c_json['case']
    assert case_data['inspection_id'] == iid
    assert len(case_data['evidence']) > 0
    eid = case_data['evidence'][0]['eid']

    # 2. Decision
    dec_res = client.get(f'/api/case/{iid}/decision')
    assert dec_res.status_code == 200
    dec_data = dec_res.json()
    assert dec_data['inspection_id'] == iid
    assert dec_data['verdict'] in ('ACCEPT', 'REVIEW', 'QUARANTINE', 'INCONCLUSIVE')
    assert 'rationale' in dec_data

    # 3. Explain Case
    exp_res = client.get(f'/api/case/{iid}/explain')
    assert exp_res.status_code == 200
    exp_data = exp_res.json()
    assert 'summary' in exp_data
    assert 'domain_summaries' in exp_data
    assert 'explanations' in exp_data

    # 4. Explain single EvidenceItem
    item_res = client.get(f'/api/case/{iid}/evidence/{eid}')
    assert item_res.status_code == 200
    item_data = item_res.json()
    assert item_data['eid'] == eid
    assert 'plain_explanation' in item_data

    # 5. Lineage Graph
    lin_res = client.get(f'/api/case/{iid}/lineage')
    assert lin_res.status_code == 200
    lin_data = lin_res.json()
    assert 'nodes' in lin_data and 'edges' in lin_data

    # 6. Batch & Contributor Risk
    br_res = client.get(f'/api/case/{iid}/batch-risk')
    assert br_res.status_code == 200
    br_data = br_res.json()
    assert 'contributor_risks' in br_data
    assert 'batch_risks' in br_data

    # 7. Timeline
    tl_res = client.get(f'/api/case/{iid}/timeline')
    assert tl_res.status_code == 200
    tl_data = tl_res.json()
    assert isinstance(tl_data, list) and len(tl_data) > 0
    assert 'event_id' in tl_data[0] and 'timestamp' in tl_data[0]

    # 8. Recommendations
    rec_res = client.get(f'/api/case/{iid}/recommendations')
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert isinstance(rec_data, list)
    assert any('action_title' in r for r in rec_data)

def test_coverage_matrix_endpoint():
    r = client.get('/api/coverage')
    assert r.status_code == 200
    caps = r.json()
    assert isinstance(caps, list) and len(caps) >= 5
    cap_names = [c['capability_id'] for c in caps]
    assert 'CAP-DATA-INTEGRITY' in cap_names
    assert 'CAP-OUTPUT-PROVENANCE' in cap_names
    assert 'CAP-MODEL-INTEGRITY' in cap_names
    for c in caps:
        assert 'evidence_strength' in c and 'limitation' in c

def test_attack_lab_scenarios_and_ground_truth():
    # 1. Catalog check
    cat_res = client.get('/api/scenarios')
    assert cat_res.status_code == 200
    scenarios = cat_res.json()
    scen_ids = [s['id'] for s in scenarios]
    assert 'trigger_poison' in scen_ids
    assert 'model_substitution' in scen_ids
    assert 'output_tampering' in scen_ids
    assert 'illumination_shift' in scen_ids

    # 2. Run Trigger Poison Attack Scenario
    tp_res = client.post('/api/scenarios/trigger_poison/run')
    assert tp_res.status_code == 200
    tp_data = tp_res.json()
    assert tp_data['verdict'] == 'QUARANTINE'
    assert tp_data['evaluation']['distinction_honored'] is True

    # 3. Run Illumination Shift Drift Scenario (Must be identified as operational drift, NOT an attack)
    shift_res = client.post('/api/scenarios/illumination_shift/run')
    assert shift_res.status_code == 200
    shift_data = shift_res.json()
    assert shift_data['ground_truth']['is_attack'] is False
    assert shift_data['evaluation']['distinction_honored'] is True

def test_evidence_graph_2_endpoint():
    d = client.post('/api/demo').json()
    inspect_res = client.post('/api/inspect', json={'name': 'Graph 2.0 Test', 'assets': d['assets']})
    assert inspect_res.status_code == 200
    iid = inspect_res.json()['inspection_id']

    graph_res = client.get(f'/api/case/{iid}/graph')
    assert graph_res.status_code == 200
    g = graph_res.json()

    # 1. Core Graph Hierarchy
    assert 'nodes' in g and 'edges' in g
    node_ids = [n['id'] for n in g['nodes']]
    assert 'CASE_DECISION' in node_ids
    assert 'DOMAIN_DATA' in node_ids
    assert 'DOMAIN_OUTPUT' in node_ids
    assert any(n['type'] == 'finding' for n in g['nodes'])

    # 2. Semantic Relationships
    relationships = [e['relationship'] for e in g['edges']]
    assert any(r in ('CONTRIBUTES_TO', 'SUPPORTS') for r in relationships)
    for e in g['edges']:
        assert 'source' in e and 'target' in e and 'explanation' in e

    # 3. Narratives & Explanations
    assert len(g['case_story']) > 20
    assert 'why_decision' in g and len(g['why_decision']['reasons']) > 0
    assert len(g['what_graph_tells_us']) > 20
    assert len(g['uncertainties']) >= 3
    assert len(g['evidence_paths']) > 0
    assert len(g['how_to_read']) == 4
    assert 'node_types' in g['legend']



