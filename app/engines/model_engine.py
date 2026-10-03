from __future__ import annotations
from pathlib import Path
import hashlib, json, statistics
import numpy as np
from .common import finding, sha256_file

def tensor_stats(state):
    vals=[]; params=0; tensors=0
    for k,v in state.items():
        try:
            a=v.detach().cpu().float().numpy()
            if a.size:
                vals.append((k,float(a.mean()),float(a.std()),float(np.linalg.norm(a)),list(a.shape)))
                params+=a.size; tensors+=1
        except: pass
    return {'parameters':int(params),'tensors':tensors,'layers':vals[:200]}

def inspect_model(path, expected_digest=None):
    p=Path(path); findings=[]; metrics={'format':p.suffix.lower(),'sha256':sha256_file(p),'runtime':'static','parameters':None,'tensors':None,'behavioral_fingerprint':None,'trigger_probe':'not_run'}
    if expected_digest:
        if metrics['sha256']!=expected_digest:
            findings.append(finding('MODEL INTEGRITY','Model weight digest mismatch','The supplied model does not match the registered digest.',[f'Expected: {expected_digest}',f'Observed: {metrics["sha256"]}'],1.0,'Digest comparison proves byte identity only; it does not prove the model is benign.','QUARANTINE','CRITICAL','model_digest',{'expected':expected_digest,'observed':metrics['sha256']}))
        else:
            findings.append(finding('MODEL INTEGRITY','Model weight digest verified','The supplied model bytes match the registered digest.',[f'SHA-256: {metrics["sha256"]}'],.999,'Digest match does not prove semantic safety.','ACCEPT','LOW','model_digest'))
    ext=p.suffix.lower()
    if ext in {'.pt','.pth','.ckpt'}:
        try:
            import torch
            if ext in {'.pt','.pth'}:
                try:
                    obj=torch.jit.load(str(p),map_location='cpu')
                except Exception:
                    obj=torch.load(p,map_location='cpu',weights_only=True)
            else:
                obj=torch.load(p,map_location='cpu',weights_only=True)
            state=obj.get('state_dict',obj.get('model_state_dict',obj)) if isinstance(obj,dict) else obj
            if isinstance(obj,torch.jit.ScriptModule):
                metrics['runtime']='torchscript'
                torch.manual_seed(11)
                base=torch.rand(1,3,64,64)
                with torch.no_grad():
                    y0=obj(base); y1=obj(base.clone())
                    patch=base.clone(); patch[:,:,:12,:12]=1.0
                    y2=obj(patch)
                a=torch.as_tensor(y0).float().flatten(); b=torch.as_tensor(y2).float().flatten()
                delta=float(torch.mean(torch.abs(a-b)).item())
                stability=float(torch.mean(torch.abs(torch.as_tensor(y0).float()-torch.as_tensor(y1).float())).item())
                metrics['trigger_probe']={'baseline_repeat_delta':stability,'corner_patch_delta':delta}; metrics['behavioral_fingerprint']=hashlib.sha256(torch.as_tensor(y0).detach().cpu().numpy().tobytes()).hexdigest()
                if delta>0.01:
                    findings.append(finding('MODEL INTEGRITY','Trigger probe shows behavioral sensitivity','The executable model changes its output under a standardized visible corner-patch probe.',[f'Baseline repeat delta: {stability:.6f}',f'Corner-patch delta: {delta:.6f}'],.82,'A generic probe cannot establish attacker intent or detect input-specific/adaptive triggers.','REVIEW','MEDIUM','torchscript_trigger',{'delta':delta}))
                else:
                    findings.append(finding('MODEL INTEGRITY','Standardized trigger probe stable','The executable model did not show material output change under the standardized corner-patch probe.',[f'Corner-patch delta: {delta:.6f}'],.78,'A negative probe does not rule out hidden or adaptive backdoors.','ACCEPT','LOW','torchscript_trigger',{'delta':delta}))
            if isinstance(state,dict):
                st=tensor_stats(state); metrics.update({'parameters':st['parameters'],'tensors':st['tensors']})
                sig=hashlib.sha256(json.dumps([(x[0],round(x[1],6),round(x[2],6),x[4]) for x in st['layers']],sort_keys=True).encode()).hexdigest()
                metrics['behavioral_fingerprint']=sig
                findings.append(finding('MODEL INTEGRITY','PyTorch weight structure fingerprinted','The checkpoint was read in weights-only mode and its tensor structure/statistics were fingerprinted.',[f'Tensors: {st["tensors"]}',f'Parameters: {st["parameters"]}',f'Fingerprint: {sig[:32]}…'],.93,'A weights-only checkpoint may not contain executable architecture; this is not a full behavioral test.','REVIEW','MEDIUM','pytorch_fingerprint',{'tensors':st['tensors'],'parameters':st['parameters']}))
            else:
                findings.append(finding('MODEL INTEGRITY','PyTorch checkpoint structure unavailable','The file loaded but did not expose a readable state dictionary.',[],.8,'Full behavioral testing requires a known model adapter or TorchScript artifact.','REVIEW','MEDIUM','pytorch_fingerprint'))
        except Exception as e:
            findings.append(finding('MODEL INTEGRITY','PyTorch runtime unavailable','The model could not be inspected with the available local runtime.',[type(e).__name__+': '+str(e)[:180]],.65,'Install the optional ML runtime for richer PyTorch checks.','REVIEW','MEDIUM','pytorch_runtime'))
    elif ext=='.onnx':
        try:
            import onnx
            m=onnx.load(str(p)); onnx.checker.check_model(m)
            ops=[n.op_type for n in m.graph.node]; metrics.update({'format':'onnx','inputs':len(m.graph.input),'outputs':len(m.graph.output),'operators':len(ops)})
            sig=hashlib.sha256(json.dumps({'ops':ops,'inputs':[x.name for x in m.graph.input],'outputs':[x.name for x in m.graph.output]},sort_keys=True).encode()).hexdigest(); metrics['behavioral_fingerprint']=sig
            findings.append(finding('MODEL INTEGRITY','ONNX graph structurally verified','The ONNX graph passed schema validation and a graph fingerprint was generated.',[f'Inputs: {len(m.graph.input)}',f'Outputs: {len(m.graph.output)}',f'Operators: {len(ops)}',f'Graph fingerprint: {sig[:32]}…'],.96,'Structural validity is not proof of behavioral safety; trigger probing needs ONNX Runtime.','REVIEW','LOW','onnx_graph',{'operators':len(ops)}))
            try:
                import onnxruntime as ort
                sess=ort.InferenceSession(str(p),providers=['CPUExecutionProvider']); metrics['runtime']='onnxruntime'; metrics['input_names']=[x.name for x in sess.get_inputs()]; metrics['output_names']=[x.name for x in sess.get_outputs()]
                findings.append(finding('MODEL INTEGRITY','ONNX runtime interface discovered','The model can be loaded by ONNX Runtime and its IO contract was enumerated.',[f'Inputs: {metrics["input_names"]}',f'Outputs: {metrics["output_names"]}'],.98,'Automatic semantic comparison is model-specific without a declared preprocessing/output adapter.','REVIEW','LOW','onnx_runtime'))
            except Exception as e:
                metrics['runtime']='onnx_static_only'
                findings.append(finding('MODEL INTEGRITY','ONNX Runtime unavailable','Static ONNX verification succeeded but runtime probing was not available.',[type(e).__name__+': '+str(e)[:160]],.75,'Install onnxruntime to enable execution-based probes.','REVIEW','MEDIUM','onnx_runtime'))
        except Exception as e:
            findings.append(finding('MODEL INTEGRITY','ONNX inspection unavailable','The ONNX parser/runtime is not installed or the graph is invalid.',[type(e).__name__+': '+str(e)[:180]],.65,'Install the optional ONNX stack for full inspection.','REVIEW','MEDIUM','onnx_parser'))
    else:
        findings.append(finding('MODEL INTEGRITY','Unknown model format','The file hash was captured but no model-specific parser matched the extension.',[f'Extension: {ext or "none"}',f'SHA-256: {metrics["sha256"]}'],.9,'Supported deep inspection: ONNX and PyTorch checkpoint formats; custom adapters can extend this.','REVIEW','MEDIUM','model_dispatch'))
    risk=0
    if any(f.action=='QUARANTINE' for f in findings): risk=90
    elif any(f.action=='REVIEW' for f in findings): risk=45
    return findings,metrics,risk
