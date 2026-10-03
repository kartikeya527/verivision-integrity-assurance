let current = null;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const num = value => Number.isFinite(Number(value)) ? Number(value) : 0;
const pill = value => String(value || '').toLowerCase() === 'accept' ? 'p-accept' : String(value || '').toLowerCase() === 'review' ? 'p-review' : 'p-quarantine';
const tone = value => num(value) >= 85 ? 'quarantine' : num(value) >= 45 ? 'review' : 'accept';

async function api(url, options = {}) {
  const r = await fetch(url, options);
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {detail:text}; }
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
}

function toast(message, bad = false) {
  const t = document.createElement('div');
  t.className = `toast ${bad ? 'bad' : ''}`;
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3600);
}

function setCounts() {
  const map = [
    ['dataInput','dataCount'],['modelInput','modelCount'],['outputInput','outputCount'],['refInput','refCount'],['curInput','curCount']
  ];
  map.forEach(([input, out]) => { if ($(input) && $(out)) $(out).textContent = $(input).files.length; });
}

['dataInput','modelInput','outputInput','refInput','curInput'].forEach(id => $(id)?.addEventListener('change', setCounts));

async function upload(file, type) {
  if (!file) return null;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('asset_type', type);
  const r = await fetch('/api/upload', {method:'POST', body:fd});
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || `Upload failed for ${file.name}`);
  return data;
}

async function runAssets(name, groups) {
  $('ingestStatus').textContent = 'Hashing evidence and preparing inspection…';
  const assets = [];
  for (const [type, files] of groups) {
    for (const f of files || []) {
      if (!f) continue;
      const uploaded = await upload(f, type);
      if (uploaded) assets.push(uploaded);
    }
  }
  if (!assets.length) {
    toast('Add at least one evidence asset or launch the demonstration.', true);
    return;
  }
  $('ingestStatus').textContent = `Evidence sealed · ${assets.length} asset${assets.length === 1 ? '' : 's'} ready`;
  const r = await api('/api/inspect', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name, assets})
  });
  $('ingestStatus').textContent = `Inspection complete · ${r.verdict} · risk ${Number(r.overall).toFixed(0)}`;
  await openInspection(r.inspection_id);
}

async function inspect() {
  await runAssets($('name').value, [
    ['data', $('dataInput').files],
    ['model', [$('modelInput').files[0]]],
    ['output', [$('outputInput').files[0]]],
    ['reference', $('refInput').files],
    ['current', $('curInput').files]
  ]);
}

async function demo() {
  $('ingestStatus').textContent = 'Building Integrity Assurance Demonstration evidence…';
  const d = await api('/api/demo', {method:'POST'});
  const r = await api('/api/inspect', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:'Integrity Assurance Demonstration', assets:d.assets})
  });
  $('ingestStatus').textContent = 'Demonstration complete · evidence graph assembled';
  await openInspection(r.inspection_id);
}

function scoreCard(label, value, accent = 'cyan') {
  const v = Math.max(0, Math.min(100, num(value)));
  return `<div class="surface-card panel" style="--accent:var(--${accent})"><div class="surface-top"><span class="surface-label">${esc(label)}</span><span class="surface-score">${v.toFixed(0)}</span></div><p>${surfaceDescription(label)}</p><div class="surface-bar"><i style="width:${v}%"></i></div><div class="surface-foot"><span>${v >= 85 ? 'MATERIAL RISK' : v >= 45 ? 'REVIEW SIGNAL' : 'WITHIN TOLERANCE'}</span><span>${v.toFixed(0)}/100</span></div></div>`;
}

function surfaceDescription(label) {
  const map = {
    'TRAINING DATA':'Duplicates, schema integrity, trigger candidates and OOD signals.',
    'AI MODEL':'Artifact digest, behavioral fingerprint and counterfactual probe.',
    'INFERENCE OUTPUT':'Signed records, replay resistance, hash continuity and Merkle proof.',
    'ENVIRONMENT SHIFT':'Reference/current comparison with drift attribution.'
  };
  return map[label] || 'Evidence surface under inspection.';
}

function gaugeSvg(value) {
  const v = Math.max(0, Math.min(100, num(value)));
  const color = v >= 85 ? 'var(--red)' : v >= 55 ? 'var(--amber)' : 'var(--green)';
  const circumference = 282.7;
  const dash = (circumference * v / 100).toFixed(1);
  return `<svg viewBox="0 0 220 150" role="img" aria-label="Overall risk ${v}"><path d="M 30 125 A 80 80 0 0 1 190 125" fill="none" stroke="#162a36" stroke-width="13" stroke-linecap="round"/><path d="M 30 125 A 80 80 0 0 1 190 125" fill="none" stroke="${color}" stroke-width="13" stroke-linecap="round" stroke-dasharray="${dash} ${circumference}"/><path d="M 42 125 A 68 68 0 0 1 178 125" fill="none" stroke="#18323f" stroke-width="1" stroke-dasharray="2 5"/><text x="110" y="110" text-anchor="middle" fill="#607984" font-size="7" font-family="monospace" letter-spacing="1.5">ASSURANCE RISK</text></svg>`;
}

function pipelineNode(num, title, text, state) {
  const icon = state === 'bad' ? '×' : state === 'warn' ? '!' : '✓';
  return `<div class="pipe-node"><div class="num">${num}</div><h4>${esc(title)} <span class="${state === 'bad' ? 'bad' : state === 'warn' ? 'warn' : 'ok'}">${icon}</span></h4><p>${esc(text)}</p></div>`;
}

function constellationSvg(x) {
  const d = x.metrics.data || {}, m = x.metrics.model || {}, o = x.metrics.output || {}, s = x.metrics.shift || {};
  const dr = num(x.data_risk), mr = num(x.model_risk), or = num(x.output_risk), sr = num(x.shift_risk);
  const n1 = dr >= 60 ? 'risk' : 'ok', n2 = mr >= 60 ? 'risk' : 'ok', n3 = or >= 60 ? 'risk' : 'ok', n4 = sr >= 60 ? 'risk' : 'ok';
  const c = (t) => t === 'risk' ? '#ff647c' : '#35e2a1';
  return `<svg viewBox="0 0 760 270" preserveAspectRatio="xMidYMid meet">
    <defs><filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
    <path d="M190 135 C280 55 315 55 380 135 S490 215 570 135" fill="none" stroke="#284a58" stroke-width="1.5" stroke-dasharray="4 6"/>
    <path d="M190 135 C280 215 315 215 380 135 S490 55 570 135" fill="none" stroke="#1e3a48" stroke-width="1" stroke-dasharray="2 8"/>
    <line x1="380" y1="55" x2="380" y2="215" stroke="#173441" stroke-dasharray="2 8"/>
    <g transform="translate(92 94)"><circle cx="55" cy="41" r="39" fill="#0a1a24" stroke="${c(n1)}" stroke-width="2" filter="url(#glow)"/><text x="55" y="36" text-anchor="middle" class="node-label">DATA</text><text x="55" y="50" text-anchor="middle" class="node-sub">${num(d.images)} images</text></g>
    <g transform="translate(325 94)"><circle cx="55" cy="41" r="39" fill="#0a1a24" stroke="${c(n2)}" stroke-width="2" filter="url(#glow)"/><text x="55" y="36" text-anchor="middle" class="node-label">MODEL</text><text x="55" y="50" text-anchor="middle" class="node-sub">${esc(m.format || 'artifact')}</text></g>
    <g transform="translate(558 94)"><circle cx="55" cy="41" r="39" fill="#0a1a24" stroke="${c(n3)}" stroke-width="2" filter="url(#glow)"/><text x="55" y="36" text-anchor="middle" class="node-label">OUTPUT</text><text x="55" y="50" text-anchor="middle" class="node-sub">${num(o.records)} records</text></g>
    <g transform="translate(325 8)"><rect width="110" height="28" rx="7" fill="#0a1a24" stroke="${c(n4)}"/><text x="55" y="12" text-anchor="middle" class="node-label" font-size="8">SHIFT</text><text x="55" y="23" text-anchor="middle" class="node-sub">${esc(s.classification || 'not checked')}</text></g>
    <text x="380" y="257" text-anchor="middle" fill="#55727e" font-size="8" font-family="monospace">EVIDENCE LINKS · NOT CAUSALITY CLAIMS</text>
  </svg>`;
}

function radarSvg(x) {
  const values = [num(x.data_risk), num(x.model_risk), num(x.output_risk), num(x.shift_risk)];
  const labels = ['DATA','MODEL','OUTPUT','SHIFT'];
  const center = 150, cy = 132, maxR = 92;
  const pts = values.map((v,i) => { const a = (-Math.PI/2)+(i*Math.PI/2); const r=maxR*v/100; return [center+Math.cos(a)*r,cy+Math.sin(a)*r]; });
  const rings = [25,50,75,100].map(v => `<circle cx="${center}" cy="${cy}" r="${maxR*v/100}" fill="none" stroke="#183542" stroke-width="1" stroke-dasharray="2 5"/>`).join('');
  const axes = labels.map((l,i)=>{const a=(-Math.PI/2)+(i*Math.PI/2); const x2=center+Math.cos(a)*maxR, y2=cy+Math.sin(a)*maxR; const tx=center+Math.cos(a)*(maxR+17),ty=cy+Math.sin(a)*(maxR+17); return `<line x1="${center}" y1="${cy}" x2="${x2}" y2="${y2}" stroke="#193743"/><text x="${tx}" y="${ty}" text-anchor="middle" fill="#75909a" font-size="8" font-family="monospace">${l}</text>`}).join('');
  const polygon=pts.map(p=>p.join(',')).join(' ');
  return `<svg viewBox="0 0 300 270"><g>${rings}${axes}<polygon points="${polygon}" fill="rgba(45,224,255,.10)" stroke="#2de0ff" stroke-width="2"/>${pts.map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="#2de0ff"/>`).join('')}<circle cx="${center}" cy="${cy}" r="4" fill="#eaf4f7"/></g></svg>`;
}

function findingHTML(f) {
  const action = String(f.action || '').toUpperCase();
  const tagClass = action === 'ACCEPT' ? 'accept' : action === 'REVIEW' ? 'review' : 'quarantine';
  const evidence = (f.evidence || []).map(e => `<li>${esc(e)}</li>`).join('');
  return `<details class="finding-row"><summary><span class="finding-id">${esc(f.id)}</span><div><div class="finding-title">${esc(f.title)}</div><div class="finding-meta">${esc(f.category)} · ${esc(f.severity)} · ${esc(f.engine)} · ${(num(f.confidence)*100).toFixed(0)}% confidence</div></div><span class="tag ${tagClass}">${esc(action)}</span></summary><div class="finding-body"><p><b>Assessment:</b> ${esc(f.claim)}</p><p><b>Observed evidence</b></p><ul>${evidence || '<li>No evidence items recorded.</li>'}</ul><p><b>Limits:</b> ${esc(f.limits)}</p><div class="metric-grid"><div class="metric"><div class="v">${(num(f.confidence)*100).toFixed(0)}%</div><div class="l">CONFIDENCE</div></div><div class="metric"><div class="v">${esc(f.severity)}</div><div class="l">SEVERITY</div></div><div class="metric"><div class="v">${esc(f.engine)}</div><div class="l">ENGINE</div></div><div class="metric"><div class="v">${esc(action)}</div><div class="l">ACTION</div></div></div></div></details>`;
}

function briefCard(title, number, text) {
  return `<div class="brief-card panel"><h4>${esc(title)}</h4><div class="brief-number">${esc(number)}</div><p>${esc(text)}</p></div>`;
}

function render() {
  const x = current;
  const g = x.metrics.governance || {};
  const o = x.metrics.output || {};
  const d = x.metrics.data || {};
  const m = x.metrics.model || {};
  const s = x.metrics.shift || {};
  const t = tone(x.overall);
  const checked = [x.data_risk,x.model_risk,x.output_risk,x.shift_risk].filter(v => !(num(v) === 100 || num(v) === 50)).length;
  const decisionCopy = x.verdict === 'QUARANTINE' ? 'Integrity risk requires containment.' : x.verdict === 'REVIEW' ? 'Evidence requires human assurance.' : 'Available evidence supports release.';

  $('main').innerHTML = `<div class="workspace">
    <section class="panel command-strip">
      <div class="command-title"><div class="command-icon">V</div><div><h2>${esc(x.name)}</h2><p><span class="mono">${esc(x.id)}</span> · ${new Date(x.created_at*1000).toLocaleString()} · ${x.assets.length} sealed assets</p></div></div>
      <div class="command-actions"><span class="status-chip">LOCAL · ${esc(x.status).toUpperCase()}</span><button class="small-btn" onclick="window.open('/api/report/${x.id}','_blank')">Assurance report ↗</button><button class="small-btn" onclick="exportInspection()">Export JSON</button><button class="small-btn" onclick="showBrief()">Executive brief</button></div>
    </section>

    <section class="panel risk-hero">
      <div class="risk-gauge">${gaugeSvg(x.overall)}<div class="gauge-value"><strong>${num(x.overall).toFixed(0)}</strong><span>OUT OF 100</span></div></div>
      <div class="risk-copy"><div class="eyebrow">ASSURANCE DECISION</div><h2>${esc(decisionCopy)}</h2><p>Risk is weighted across data integrity, model integrity, output provenance and environment shift. A high-risk surface can force quarantine even when the aggregate score is lower.</p><div class="coverage-strip"><span class="coverage-badge">Evidence coverage ${num(g.evidence_coverage_score).toFixed(0)}%</span><span class="coverage-badge">Evidence density ${num(g.evidence_density).toFixed(0)}%</span><span class="coverage-badge">Confidence budget ${num(g.confidence_budget).toFixed(0)}%</span><span class="coverage-badge">${checked}/4 surfaces measured</span></div></div>
      <div class="decision-banner ${t}"><small>RECOMMENDED CONTROL STATE</small><b>${esc(x.verdict)}</b><small>${esc(decisionCopy)}</small></div>
    </section>

    <section class="surface-grid">
      ${scoreCard('TRAINING DATA',x.data_risk,'cyan')}${scoreCard('AI MODEL',x.model_risk,'blue')}${scoreCard('INFERENCE OUTPUT',x.output_risk,'green')}${scoreCard('ENVIRONMENT SHIFT',x.shift_risk,'amber')}
    </section>

    <section class="panel pipeline"><div class="section-title"><div><h3>Integrity spine</h3><p>Five gates turn raw artifacts into a defensible control decision.</p></div><button class="small-btn" onclick="openTrace()">Open evidence graph</button></div><div class="pipeline-track">
      ${pipelineNode('01','COLLECT','Hash the supplied evidence before interpretation.',x.data_risk>=60?'warn':'ok')}<div class="pipe-arrow active">→</div>
      ${pipelineNode('02','INSPECT','Parse schemas, duplicates, OOD and trigger candidates.',x.data_risk>=60?'warn':'ok')}<div class="pipe-arrow active">→</div>
      ${pipelineNode('03','PROBE','Fingerprint the artifact and test a counterfactual input.',x.model_risk>=60?'warn':'ok')}<div class="pipe-arrow active">→</div>
      ${pipelineNode('04','VERIFY','Check signatures, replay resistance and Merkle integrity.',x.output_risk>=60?'bad':'ok')}<div class="pipe-arrow active">→</div>
      ${pipelineNode('05','DECIDE',decisionCopy,x.verdict==='QUARANTINE'?'bad':x.verdict==='REVIEW'?'warn':'ok')}
    </div></section>

    <section class="analytics-grid">
      <div class="panel evidence-map"><div class="section-title"><div><h3>Evidence constellation</h3><p>Cross-surface links show where a hypothesis travels — without silently claiming causality.</p></div><span class="pill ${pill(x.verdict)}">${esc(x.verdict)}</span></div><div class="constellation">${constellationSvg(x)}</div></div>
      <div class="panel posture-panel"><div class="section-title"><div><h3>Integrity posture</h3><p>Risk vector across the four assurance surfaces.</p></div><button class="small-btn" onclick="showBrief()">Explain</button></div><div class="radar-wrap">${radarSvg(x)}</div><div class="legend-row"><span>LOW <b>0</b></span><span>REVIEW <b>45</b></span><span>HIGH <b>85</b></span><span>MAX <b>100</b></span></div></div>
    </section>

    <section class="panel findings-panel"><div class="section-title"><div><h3>Forensic findings</h3><p>Each finding is a bounded claim: evidence · confidence · limits · action.</p></div><div class="command-actions"><button class="small-btn" onclick="expandFindings()">Expand all</button><button class="small-btn" onclick="window.open('/api/report/${x.id}','_blank')">Full report ↗</button></div></div><div class="findings-list">${x.findings.length ? x.findings.map(findingHTML).join('') : '<div class="empty-state"><strong>No findings recorded</strong>The selected evidence did not produce a finding.</div>'}</div></section>

    <section class="panel crypto-panel"><div class="section-title"><div><h3>Cryptographic evidence vault</h3><p>Sealed delivery receipts, chained audit events and a Merkle commitment.</p></div><div class="command-actions"><button class="small-btn" onclick="verifyChain()">Verify now</button><button class="small-btn" onclick="simulateTamper()">Live tamper replay</button></div></div><div id="verifyBox" class="ingest-status">Not verified in this view.</div><div class="crypto-grid"><div class="crypto-stat"><div class="v">${x.signed_records.length}</div><div class="l">SIGNED RECORDS</div></div><div class="crypto-stat"><div class="v ${num(o.invalid_signatures)>0?'bad':'ok'}">${num(o.invalid_signatures)}</div><div class="l">INVALID SIGNATURES</div></div><div class="crypto-stat"><div class="v">${x.audit.length}</div><div class="l">AUDIT EVENTS</div></div><div class="crypto-stat"><div class="v">${esc((o.merkle_root || '—').slice(0,16))}</div><div class="l">MERKLE ROOT</div></div></div><div class="hash-line">PUBLIC KEY · ${esc(o.public_key || 'available from local signer')}<br>MERKLE · ${esc(o.merkle_root || 'not available')}</div><div class="audit-feed">${x.audit.slice(-5).map(a=>`<div class="audit-row"><b>${esc(a.event)}</b> · ${esc(a.hash.slice(0,32))}… · prev ${esc(a.prev_hash.slice(0,18))}…</div>`).join('')}</div></section>

    <section class="brief-grid">
      ${briefCard('EVIDENCE COVERAGE', `${num(g.evidence_coverage_score).toFixed(0)}%`, 'How much of the four trust surfaces was actually measurable in this inspection.')} 
      ${briefCard('CONFIDENCE BUDGET', `${num(g.confidence_budget).toFixed(0)}%`, 'Average confidence of recorded findings; not a probability of compromise.')} 
      ${briefCard('SIGNED TRAIL', `${num(o.signed).toFixed(0)} / ${num(o.records).toFixed(0)}`, 'Signed inference records inspected for authenticity and continuity.')} 
    </section>

    <section class="panel pipeline"><div class="section-title"><div><h3>Coverage & limitations</h3><p>The product makes its uncertainty visible instead of manufacturing certainty.</p></div><button class="small-btn" onclick="history()">Inspection history</button></div><div class="coverage-strip">${x.coverage.map(c=>`<span class="coverage-badge">${esc(c)}</span>`).join('')}</div></section>
  </div>`;
}

async function openInspection(id) { current = await api('/api/inspections/'+id); render(); window.scrollTo({top:0,behavior:'smooth'}); }

function expandFindings() { document.querySelectorAll('.finding-row').forEach(x => x.open = true); }

async function verifyChain() {
  const j = await api('/api/verify/'+current.id);
  const validSigned = (j.signed_records || []).filter(x => x.valid).length;
  $('verifyBox').innerHTML = `<span class="${j.valid ? 'ok' : 'bad'}"><b>${j.valid ? '✓ INTEGRITY VERIFIED' : '✕ VERIFICATION EXCEPTION'}</b> · ${esc(j.message)} · ${j.records} audit events · ${validSigned}/${j.signed_records.length} signed records valid.</span>`;
}

async function simulateTamper() {
  const j = await api('/api/simulate-tamper/'+current.id,{method:'POST'});
  const modal=document.createElement('div'); modal.className='modal';
  modal.innerHTML=`<div class="modal-card panel"><div class="modal-head"><div><div class="eyebrow">NOVELTY · LIVE TAMPER REPLAY</div><h2>Can the receipt detect a forged result?</h2><p>VeriVision mutates only the in-memory prediction payload. The stored record is never changed.</p></div><button class="close" onclick="this.closest('.modal').remove()">✕</button></div><div class="tamper-compare"><div class="tamper-card valid"><div class="ok mono">✓ SIGNATURE VALID</div><strong>Original payload</strong><pre>${esc(JSON.stringify(j.original_prediction,null,2))}</pre></div><div style="text-align:center;font-size:24px;color:#55727e">→</div><div class="tamper-card invalid"><div class="bad mono">✕ SIGNATURE INVALID</div><strong>Tampered payload</strong><pre>${esc(JSON.stringify(j.tampered_prediction,null,2))}</pre></div></div><div class="hash-line" style="margin-top:18px">RECORD · ${esc(j.record_id)}<br>${esc(j.explanation)}</div></div>`;
  document.body.appendChild(modal);
}

function openTrace() {
  const x=current;
  const d=x.metrics.data||{},m=x.metrics.model||{},o=x.metrics.output||{};
  const modal=document.createElement('div'); modal.className='modal';
  modal.innerHTML=`<div class="modal-card panel"><div class="modal-head"><div><div class="eyebrow">EVIDENCE GRAPH</div><h2>From suspicious ingredient to operational impact</h2><p>The graph is intentionally conservative: an edge means the evidence is relevant to the next review stage, not that causality has been proven.</p></div><button class="close" onclick="this.closest('.modal').remove()">✕</button></div><div class="constellation" style="height:330px;margin-top:18px">${constellationSvg(x)}</div><div class="metric-grid" style="margin-top:12px"><div class="metric"><div class="v">${num(d.trigger_candidates)}</div><div class="l">TRIGGER CANDIDATES</div></div><div class="metric"><div class="v">${esc((m.behavioral_fingerprint||'—').slice(0,12))}</div><div class="l">MODEL FINGERPRINT</div></div><div class="metric"><div class="v">${num(o.invalid_signatures)}</div><div class="l">SIGNATURE FAILURES</div></div><div class="metric"><div class="v">${num(x.trace?.affected_outputs || o.records)}</div><div class="l">AFFECTED OUTPUTS</div></div></div></div>`;
  document.body.appendChild(modal);
}

function showBrief() {
  const x=current, g=x.metrics.governance||{}, d=x.metrics.data||{}, m=x.metrics.model||{}, o=x.metrics.output||{}, s=x.metrics.shift||{};
  const modal=document.createElement('div'); modal.className='modal';
  modal.innerHTML=`<div class="modal-card panel"><div class="modal-head"><div><div class="eyebrow">COMMAND BRIEF · ${esc(x.id)}</div><h2>Integrity Assurance Brief</h2><p>A judge-ready executive view generated from the same evidence store as the inspection dashboard.</p></div><button class="close" onclick="this.closest('.modal').remove()">✕</button></div><div class="brief-grid" style="margin-top:18px"><div class="brief-card panel"><h4>CONTROL STATE</h4><div class="brief-number">${esc(x.verdict)}</div><p>Overall risk ${num(x.overall).toFixed(1)}/100. Surface risks: data ${num(x.data_risk).toFixed(0)}, model ${num(x.model_risk).toFixed(0)}, output ${num(x.output_risk).toFixed(0)}, shift ${num(x.shift_risk).toFixed(0)}.</p></div><div class="brief-card panel"><h4>MEASURED EVIDENCE</h4><div class="brief-number">${num(g.evidence_coverage_score).toFixed(0)}%</div><p>${num(g.evidence_density).toFixed(0)}% evidence density across ${x.findings.length} findings. ${x.assets.length} assets were sealed into the inspection.</p></div><div class="brief-card panel"><h4>CRYPTOGRAPHIC TRAIL</h4><div class="brief-number">${num(o.invalid_signatures)} FAIL</div><p>${num(o.signed).toFixed(0)} signed records checked. Merkle root ${esc((o.merkle_root||'not available').slice(0,18))}…</p></div></div><div class="pipeline" style="margin-top:12px"><div class="section-title"><div><h3>What the system actually found</h3><p>Numbers below are evidence metrics, not marketing claims.</p></div></div><div class="metric-grid" style="margin-top:12px"><div class="metric"><div class="v">${num(d.images)}</div><div class="l">IMAGES</div></div><div class="metric"><div class="v">${num(d.trigger_candidates)}</div><div class="l">TRIGGER CANDIDATES</div></div><div class="metric"><div class="v">${num(d.ood_candidates)}</div><div class="l">OOD CANDIDATES</div></div><div class="metric"><div class="v">${num(s.brightness_shift)}</div><div class="l">BRIGHTNESS SHIFT</div></div></div><div class="coverage-strip"><span class="coverage-badge">Model ${esc(m.format||'not supplied')}</span><span class="coverage-badge">Shift ${esc(s.classification||'not checked')}</span><span class="coverage-badge">Confidence ${num(g.confidence_budget).toFixed(0)}%</span></div></div><div class="modal-actions"><button class="action-primary" style="margin:0" onclick="window.open('/api/report/${x.id}','_blank')">Open full assurance report ↗</button></div></div>`;
  document.body.appendChild(modal);
}

async function exportInspection() {
  const data = await api('/api/export/'+current.id);
  const blob = new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`${current.id}_verivision_assurance.json`; a.click(); URL.revokeObjectURL(a.href);
}

async function history() {
  const rows=await api('/api/inspections');
  const modal=document.createElement('div'); modal.className='modal';
  modal.innerHTML=`<div class="modal-card panel"><div class="modal-head"><div><div class="eyebrow">LOCAL EVIDENCE STORE</div><h2>Inspection history</h2><p>Every inspection remains locally addressable for review and export.</p></div><button class="close" onclick="this.closest('.modal').remove()">✕</button></div><div class="history-list">${rows.length ? rows.map(r=>`<div class="history-item" onclick="this.closest('.modal').remove();openInspection('${esc(r.id)}')"><div><b>${esc(r.name)}</b><div class="mono muted" style="font-size:8px;margin-top:4px">${esc(r.id)} · ${new Date(r.created_at*1000).toLocaleString()}</div></div><span class="pill ${pill(r.verdict)}">${esc(r.verdict)} · ${num(r.overall).toFixed(0)}</span></div>`).join('') : '<div class="empty-state"><strong>No inspections yet</strong>Run the demonstration or create an inspection from local evidence.</div>'}</div></div>`;
  document.body.appendChild(modal);
}

async function health() {
  const h=await api('/api/health');
  toast(`VeriVision ${h.version} · ${h.offline ? 'offline-ready' : 'network mode'} · ${h.crypto}`);
}

$('inspectBtn').onclick=()=>inspect().catch(e=>toast(e.message,true));
$('demoBtn').onclick=()=>demo().catch(e=>toast(e.message,true));
$('welcomeDemo').onclick=()=>demo().catch(e=>toast(e.message,true));
$('historyBtn').onclick=()=>history().catch(e=>toast(e.message,true));
$('healthBtn').onclick=()=>health().catch(e=>toast(e.message,true));
$('heroBrief').onclick=()=>toast('Run an inspection first to open the evidence-backed command brief.');
setCounts();
