#!/usr/bin/env python3
"""Controlled real VT backend evidence, never an on-screen streaming verdict.

Exit 0: at least one real backend case validated, 1: failed/incomplete,
2: no usable backend or toolchain; unsupported is explicitly not a pass.
"""
import argparse,json,subprocess,tempfile,math,copy,hashlib
from pathlib import Path
import apple_toolchain
ROOT=Path(__file__).resolve().parents[1]
def classify(report):
    if (report.get('schema') != 1 or report.get('syntheticInput') is not True or
            report.get('realVTBackend') is not True or report.get('streamingValidated') is not False):
        return 1
    cases=report.get('cases')
    if not isinstance(cases,list) or not cases:return 1
    validated=0
    allowed={'backend_validated','failed','unsupported','model_not_ready','probe_format_unhandled','api_unavailable','capability_only'}
    for c in cases:
        if not isinstance(c,dict) or c.get('status') not in allowed or c['status']=='failed':return 1
        if c['status']!='backend_validated':continue
        try:
            if c['completedFrames']!=16 or c['measuredFrames']!=12 or c['distinctOutputSignatures']<2:return 1
            w,h,scale=c['sourceWidth'],c['sourceHeight'],c['scale']
            if w<=0 or h<=0 or scale<1 or not math.isfinite(scale):return 1
            if c['outputWidth']!=round(w*scale) or c['outputHeight']!=round(h*scale):return 1
            p50,p95,maximum=c['p50ProcessMs'],c['p95ProcessMs'],c['maxProcessMs']
            if not all(math.isfinite(n) for n in (p50,p95,maximum)) or not 0<=p50<=p95<=maximum:return 1
        except (KeyError,TypeError,ValueError):return 1
        validated+=1
    return 0 if validated else 2

def self_test():
    good={'schema':1,'syntheticInput':True,'realVTBackend':True,'streamingValidated':False,'cases':[
        {'status':'backend_validated','sourceWidth':1280,'sourceHeight':720,'scale':1.5,
         'outputWidth':1920,'outputHeight':1080,'completedFrames':16,'measuredFrames':12,
         'distinctOutputSignatures':16,'p50ProcessMs':2,'p95ProcessMs':3,'maxProcessMs':3}]}
    assert classify(good)==0
    for key,value in [('completedFrames',0),('measuredFrames',0),('distinctOutputSignatures',1),
                      ('outputWidth',1280),('p95ProcessMs',float('nan')),('p50ProcessMs',4),('status','invented')]:
        bad=copy.deepcopy(good);bad['cases'][0][key]=value;assert classify(bad)==1,key
    for status in ('unsupported','model_not_ready','capability_only','api_unavailable','probe_format_unhandled'):
        report=copy.deepcopy(good);report['cases']=[{'status':status}];assert classify(report)==2,status
    bad=copy.deepcopy(good);bad['streamingValidated']=True;assert classify(bad)==1
    print('ok: probe report verifier; incomplete output rejected, unsupported never a pass');return 0

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out');p.add_argument('--self-test',action='store_true');args=p.parse_args()
    if args.self_test:return self_test()
    if not args.out:p.error('--out is required for a hardware run')
    pair=apple_toolchain.clang_and_sdk_or_none()
    if pair is None:print('UNVERIFIED: '+apple_toolchain.NO_TOOLCHAIN_MESSAGE);return 2
    clang,sdk=pair
    with tempfile.TemporaryDirectory(prefix='ml-real-vt-') as d:
        exe=Path(d)/'probe'
        built=subprocess.run([clang,'-isysroot',sdk,'-fobjc-arc','-Wall','-Werror','-framework','Foundation',
            '-framework','CoreVideo','-framework','CoreMedia','-framework','VideoToolbox',
            str(ROOT/'scripts/probes/vt-enhancement-hardware.m'),'-o',str(exe)],capture_output=True,text=True)
        if built.returncode:print(built.stderr);return 1
        try:ran=subprocess.run([str(exe)],capture_output=True,text=True,timeout=180)
        except subprocess.TimeoutExpired:print('UNVERIFIED: backend probe timed out, no completed report');return 1
        if ran.returncode:print('FAILED: native probe exit',ran.returncode,ran.stderr[-2000:]);return 1
        report=json.loads(ran.stdout)
    report['probeSourceSha256']=hashlib.sha256((ROOT/'scripts/probes/vt-enhancement-hardware.m').read_bytes()).hexdigest()
    report['latencyScope']='synchronous_process_call_only'
    report['qualityValidated']=False
    Path(args.out).parent.mkdir(parents=True,exist_ok=True);Path(args.out).write_text(json.dumps(report,indent=2)+'\n')
    cases=report['cases'];validated=sum(c['status']=='backend_validated' for c in cases)
    for c in cases:print(c['engine'],c.get('sourceWidth',''),c.get('sourceHeight',''),c['status'],
                         'P95(ms)=',c.get('p95ProcessMs','--'),'slots=',c.get('slots','--'))
    print('actual_backend_validated_cases:',validated,'; streaming_validated: false; report:',args.out)
    outcome=classify(report)
    if outcome==1:print('NOT PASSED: failed or incomplete case; see retained per-case evidence')
    return outcome
if __name__=='__main__':raise SystemExit(main())
