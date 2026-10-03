# VeriVision — Trust & Integrity Inspector

VeriVision is an offline-first, evidence-based assurance platform for computer-vision AI pipelines. It inspects **data, models, inference outputs and distribution shift together**, then produces an actionable **ACCEPT / REVIEW / QUARANTINE** decision.

The architecture follows the SIH problem framing: contributor data can be poisoned, models can be substituted or backdoored, and saved inference outputs can be edited/replayed. The application therefore combines integrity checks, cryptographic provenance, traceability and explicit limits.

## What is implemented

### Data integrity
- COCO JSON parsing and annotation-schema checks
- YOLO normalized `class x_center y_center width height` parsing
- SHA-256 exact-duplicate detection
- Lightweight perceptual near-duplicate detection
- PCA image embeddings for OOD candidate detection
- Visible high-contrast patch/trigger candidate scan
- Source/file-level evidence and findings

### Model integrity
- SHA-256 model digest registration and swap check
- PyTorch checkpoint inspection with `weights_only=True` when applicable
- TorchScript behavioral fingerprinting
- Baseline-repeat and visible corner-patch counterfactual probe
- ONNX graph validation and graph fingerprinting when `onnx` is installed
- ONNX Runtime interface discovery when `onnxruntime` is installed
- Explicit unavailable/partial results rather than false passes

### Output integrity
- JSON/JSONL signed inference records
- Ed25519 signing and verification
- Per-record SHA-256 payload hashes
- Hash-chain continuity checking
- Replay/duplicate-ID detection
- Merkle root over verified payload hashes
- Live tamper-replay demonstration

### Shift / anomaly
- Reference-vs-current image statistics
- Brightness, contrast, entropy and edge distribution shift
- Natural-lighting/sensor candidate attribution
- Manipulation candidate attribution
- `CANNOT DISTINGUISH` when evidence is thin
- Confidence is a deterministic, calibration-ready heuristic; local validation data should be used before treating it as a statistical probability.

### Governance and novelty
- **Evidence Coverage Score:** how many core trust surfaces were actually checked
- **Confidence Budget:** aggregate confidence across recorded findings
- **Evidence Graph:** DATA → MODEL → OUTPUT links are shown separately instead of silently implying causality
- **Live Tamper Replay:** changes a signed output payload in memory and demonstrates that Ed25519 verification fails
- Standalone HTML assurance report
- Cryptographic audit trail
- Plugin-style engine separation for future detectors

## Command Center experience (v3.0)

The interface is designed as an offline assurance command center rather than a generic CRUD dashboard:

- **Integrity spine** — Collect → Inspect → Probe → Verify → Decide.
- **Evidence constellation** — visual DATA → MODEL → OUTPUT → SHIFT relationships with an explicit non-causality rule.
- **Risk posture radar** — four-surface risk vector and control-state banner.
- **Evidence Coverage / Density / Confidence Budget** — makes measurement completeness visible.
- **Cryptographic evidence vault** — signed-record count, invalid signatures, audit events and Merkle commitment.
- **Live Tamper Replay** — mutates an in-memory prediction to demonstrate signature failure without changing stored evidence.
- **Executive Assurance Brief** — judge/leadership-ready infographic view generated from the same inspection record.
- **Local inspection history and JSON export** — no cloud dependency.

## Project layout

```text
verivision/
├── app/
│   ├── main.py
│   ├── demo.py
│   ├── engines/
│   │   ├── common.py
│   │   ├── data_engine.py
│   │   ├── model_engine.py
│   │   ├── provenance_engine.py
│   │   └── shift_engine.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── app.css
├── demo_assets/
├── scripts/
│   └── make_demo_model.py
├── tests/
│   └── test_end_to_end.py
├── data/
├── requirements.txt
├── requirements-ml.txt
├── requirements-offline.txt
├── Dockerfile
├── docker-compose.yml
└── run.py
```

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv

# Windows
.venv\\Scripts\\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:8000`.

For richer ONNX/PyTorch analysis:

```bash
pip install -r requirements-ml.txt
```

The base build already includes the lightweight image/data engines. Heavy ML runtimes are optional so the application can remain deployable on constrained air-gapped systems.

## Run tests

```bash
pip install pytest
pytest -q
```

## Docker

```bash
docker compose up --build
```

## Air-gapped installation

Build a wheelhouse on a connected staging machine, transfer it through your approved process, then install without network access:

```bash
pip download -r requirements-ml.txt -d wheelhouse
```

On the isolated machine:

```bash
pip install --no-index --find-links ./wheelhouse -r requirements-ml.txt
python run.py
```

No external API, telemetry, CDN, cloud database or internet call is required by the application.

## API

FastAPI exposes interactive API documentation at:

- `/docs`
- `/redoc`

Important endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Local system status and crypto public key |
| `POST /api/upload` | Hash and stage an asset |
| `POST /api/register` | Register an expected asset digest |
| `POST /api/demo` | Generate reproducible Integrity Assurance Demonstration assets |
| `POST /api/inspect` | Run the complete assurance pipeline |
| `POST /api/sign-output` | Sign an inference record with Ed25519 |
| `GET /api/inspections` | List inspections |
| `GET /api/inspections/{id}` | Full evidence object |
| `GET /api/verify/{id}` | Verify audit chain and signed records |
| `GET /api/analytics/{id}` | Return visualisation-ready risk, findings, governance and crypto breakdown |
| `POST /api/simulate-tamper/{id}` | Non-destructive tamper replay |
| `GET /api/report/{id}` | Standalone HTML report |
| `GET /api/export/{id}` | JSON export |

## Example signed inference record

The `/api/sign-output` endpoint accepts a payload such as:

```json
{
  "id": "INF-001",
  "model_digest": "...",
  "image_digest": "...",
  "prediction": {
    "class": "truck",
    "confidence": 0.94
  },
  "prev_hash": "GENESIS"
}
```

The returned signed envelope contains `payload`, `signature` and `public_key`.

## Coverage honesty

VeriVision intentionally does **not** claim universal backdoor detection. Targeted checks include visible triggers, label/schema anomalies, duplicate flooding, OOD candidates, model substitution/digest mismatch and output tampering. Invisible, adaptive, input-specific and signing-key compromise scenarios require stronger evidence or are outside the prototype's claims.

For a defence deployment, use controlled validation datasets, known-good model baselines, approved key-management infrastructure and locally validated thresholds before relying on a verdict operationally.
