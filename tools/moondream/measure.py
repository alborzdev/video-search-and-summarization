"""Bounded Photon qualification; serial image cases and no HTTP service."""
import argparse
import dataclasses
import io
import datetime
import faulthandler
import traceback
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark/moondream-photon'
MODEL = 'moondream3.1-9B-A2B'


def available_gib():
    return next(int(s.split()[1]) / 2**20 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))


def child(args):
    import torch
    import moondream as md
    from PIL import Image
    faulthandler.enable()
    faulthandler.dump_traceback_later(120, repeat=True)
    diagnostic_case = {}
    from kestrel.models.moondream.skills.segment import SegmentSkill
    from kestrel.models.moondream.runtime import TextToken
    original_prompt = SegmentSkill.build_prompt_tokens
    def diagnostic_prompt(skill, runtime, context):
        if diagnostic_case.get('leading_space'):
            context = dataclasses.replace(context, object=' '+context.object)
        tokens = list(original_prompt(skill, runtime, context))
        if diagnostic_case.get('double_answer'):
            tokens.append(TextToken(token_id=int(runtime.prompt_template.answer_id)))
        return tokens
    SegmentSkill.build_prompt_tokens = diagnostic_prompt
    if args.probe_decode:
        from decode_diagnostics import install_decode_diagnostics
        install_decode_diagnostics(diagnostic_case)
    if args.trace_segment:
        from trace_segment import install_trace
        install_trace(Path(os.environ['MOONDREAM_RUN_DIR'])/'segment-trace.jsonl')
    if args.probe_md2_segment:
        # Diagnostic only: test the shared tokenizer's known MD3 segment prompt
        # against MD2 weights. This does not add a learned skill or claim support.
        from copy import deepcopy
        from kestrel.models import get_spec
        from kestrel.models.moondream.config import DEFAULT_MOONDREAM3_CONFIG
        get_spec('moondream2').default_config['tokenizer']['templates']['segment'] = deepcopy(DEFAULT_MOONDREAM3_CONFIG['tokenizer']['templates']['segment'])
        print(json.dumps({'stage':'diagnostic_prompt_override','model':'moondream2','source':'official MD3 segment template','supported_configuration':False}),flush=True)
    if args.compat:
        from gb10_compat import install_gb10_compat
        print(json.dumps({"stage": "compat_install", "details": install_gb10_compat()}), flush=True)
    def emit(stage, **data):
        torch.cuda.synchronize()
        print(json.dumps({'stage': stage, 'available_gib': available_gib(), 'cuda_allocated_gib': torch.cuda.memory_allocated()/2**30, 'cuda_reserved_gib': torch.cuda.memory_reserved()/2**30, 'cuda_peak_allocated_gib': torch.cuda.max_memory_allocated()/2**30, 'cuda_peak_reserved_gib':torch.cuda.max_memory_reserved()/2**30, **data}), flush=True)
    emit('before_load')
    start = time.monotonic()
    path_file = {'moondream3.1-9B-A2B':'model-path.txt','moondream3-preview':'preview-model-path.txt','moondream2':'md2-model-path.txt'}[args.model]
    model_path = args.model_path or (STATE/path_file).read_text().strip()
    with md.photon(args.model, model_path=model_path, tokenizer_path=(STATE/'tokenizer-path.txt').read_text().strip(), device='cuda', max_batch_size=1, kv_cache_pages=2048 if args.model == 'moondream2' else 4096, enable_cuda_graphs=False, enable_prefix_cache=False, decode_path='native') as model:
        emit('loaded', elapsed_s=time.monotonic()-start, tasks=model.tasks)
        time.sleep(5)
        emit('idle_after_5s')
        # This generated illustration checks functionality only, not inspection accuracy.
        cases = json.loads(Path(args.cases).read_text()) if args.cases else [{'id':'single','image':args.image or str(ROOT/'services/ui/apps/nv-metropolis-bp-vss-ui/public/defense-preview/drone-close.png'),'object':args.object,'prompt':args.prompt}]
        for case in cases:
            diagnostic_case.clear()
            diagnostic_case.update(case.get('diagnostic_prompt',{}))
            image = Image.open(case['image']).convert('RGB')
            image.thumbnail((1024,1024))
            for task in args.tasks.split(','):
                start = time.monotonic()
                try:
                    if task == 'query': result = model.query(image, case.get('prompt',args.prompt), settings={'max_tokens':48})
                    elif task == 'detect': result = model.detect(image, case.get('object',args.object), settings={'max_tokens':48})
                    else:
                        encoded = io.BytesIO(); image.save(encoded,format='PNG')
                        raw = model._run(model._model.segment(image=encoded.getvalue(),object=case.get('object',args.object),spatial_refs=case.get('spatial_refs'),settings={'max_tokens':case.get('max_tokens',512)}))
                        result = {'request_id':raw.request_id,'output':raw.output,'finish_reason':raw.finish_reason,'metrics':dataclasses.asdict(raw.metrics),'diagnostic_prompt':dict(diagnostic_case),'spatial_refs':case.get('spatial_refs')}
                        from mask_artifacts import save_mask_artifacts
                        segment = raw.output.get('segments', [{}])[0]
                        result['mask_receipt'] = save_mask_artifacts(image, {'path':segment.get('svg_path',''),'bbox':segment.get('bbox')}, Path(os.environ['MOONDREAM_RUN_DIR'])/'masks', stem=case['id'])
                    emit(task, case=case['id'], elapsed_s=time.monotonic()-start, result=result)
                except Exception as e:
                    emit(task, case=case['id'], elapsed_s=time.monotonic()-start, error=repr(e))
    emit('closed')


def supervise(args):
    reserve = json.loads((ROOT/'.spark/settings.json').read_text())['reserve_gib']
    if subprocess.run(['systemctl','--user','is-active','--quiet','vss-spark-guard.service']).returncode:
        raise SystemExit('Spark guard must be active.')
    if available_gib() < reserve:
        raise SystemExit('Need the saved memory reserve available.')
    site = Path(sys.prefix) / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    libs = sorted({str(p) for root in ('nvidia','nvpl') for p in (site/root).glob('**/lib') if p.is_dir()})
    env = dict(os.environ, LD_LIBRARY_PATH=':'.join(libs+[os.environ.get('LD_LIBRARY_PATH','')]), PYTHONUNBUFFERED='1', HF_HUB_OFFLINE='1')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_dir = STATE/'runs'/f'{stamp}-{args.model}-{"gb10" if args.compat else "stock"}'
    run_dir.mkdir(parents=True)
    env['MOONDREAM_RUN_DIR'] = str(run_dir)
    (STATE/'latest-run.txt').write_text(str(run_dir)+'\n')
    (run_dir/'settings.json').write_text(json.dumps(vars(args), indent=2)+'\n')
    log = run_dir/'inference.jsonl'
    telemetry = run_dir/'memory.jsonl'
    began = time.monotonic()
    with log.open('w') as out, (run_dir/'inference.stderr').open('w') as err, telemetry.open('w') as mem:
        process = subprocess.Popen([sys.executable,__file__,'--child','--tasks',args.tasks,'--prompt',args.prompt,'--object',args.object,'--model',args.model] + (['--model-path',args.model_path] if args.model_path else []) + (['--cases',args.cases] if args.cases else []) + (['--image',args.image] if args.image else []) + (['--compat'] if args.compat else []) + (['--probe-md2-segment'] if args.probe_md2_segment else []) + (['--probe-decode'] if args.probe_decode else []) + (['--trace-segment'] if args.trace_segment else []),env=env,stdout=out,stderr=err,start_new_session=True)
        try:
            while process.poll() is None:
                elapsed = time.monotonic()-began
                available = available_gib()
                mem.write(json.dumps({'elapsed_s':elapsed,'available_gib':available})+'\n');mem.flush()
                if available < reserve+3 or elapsed>args.timeout:
                    reason='reserve_headroom' if available<reserve+3 else 'timeout'
                    mem.write(json.dumps({'stop_reason':reason})+'\n');mem.flush()
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL)
                    break
                time.sleep(0.2)
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL)
            process.wait()
    reports=[]
    for line in log.read_text().splitlines():
        try: reports.append(json.loads(line))
        except json.JSONDecodeError: pass
    cases = json.loads(Path(args.cases).read_text()) if args.cases else [{'id':'single'}]
    completed={(r.get('case'),r.get('stage')) for r in reports if 'result' in r and 'error' not in r}
    missing={(c['id'],t) for c in cases for t in args.tasks.split(',')}-completed
    mask_failures=[]
    for report in reports:
        if report.get('stage') != 'segment' or 'result' not in report: continue
        expected = next(c.get('expect_present',True) for c in cases if c['id']==report['case'])
        receipt = report['result'].get('mask_receipt',{})
        # Negative controls must produce neither a path nor a spurious box.
        naturally_completed = report['result'].get('finish_reason') == 'stop'
        passes = naturally_completed and (bool(receipt.get('valid_mask')) if expected else receipt.get('status') == 'empty_result')
        if not passes: mask_failures.append({'case':report['case'],'expected_present':expected,'status':receipt.get('status','unvalidated'),'finish_reason':report['result'].get('finish_reason')})
    effective_code=process.returncode or (2 if missing else 3 if mask_failures else 0)
    result={'returncode':effective_code,'child_returncode':process.returncode,'missing_or_failed_tasks':sorted(missing),'mask_failures':mask_failures,'elapsed_s':time.monotonic()-began,'log':str(log)}
    (run_dir/'exit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    return effective_code

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--compat',action='store_true',help='Use our opt-in GB10 MoE adapter.')
    parser.add_argument('--tasks',default='query,detect,segment')
    parser.add_argument('--image')
    parser.add_argument('--model',default=MODEL,choices=[MODEL,'moondream3-preview','moondream2'])
    parser.add_argument('--model-path')
    parser.add_argument('--cases',help='JSON list of image/object/prompt cases tested after one model load.')
    parser.add_argument('--object',default='metal panel')
    parser.add_argument('--probe-md2-segment',action='store_true',help='Diagnostic only: test MD3 segment prompt against MD2 weights; not advertised support.')
    parser.add_argument('--trace-segment',action='store_true',help='Record prompts, sampled tokens and stopping diagnostics without changing sampling.')
    parser.add_argument('--probe-decode',action='store_true',help='Unsupported diagnostic: enable per-case coordinate LUT or one-step EOS suppression experiments.')
    parser.add_argument('--prompt',default='Describe the object lying on the concrete.')
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    if args.probe_md2_segment and args.model != 'moondream2':
        parser.error('--probe-md2-segment requires --model moondream2')
    if args.cases and not args.probe_decode:
        for case in json.loads(Path(args.cases).read_text()):
            if any(case.get('diagnostic_prompt',{}).get(k) for k in ('coord_denominator_1024','suppress_first_path_eos','force_svg_start_after_bbox')):
                parser.error('Decode diagnostic cases require --probe-decode')
    if set(args.tasks.split(',')) - {'query','detect','segment'}:
        parser.error('Tasks must be query, detect or segment.')
    if args.child:
        try:
            child(args)
        except Exception:
            import torch
            print(json.dumps({'stage':'fatal','error':traceback.format_exc(),'cuda_allocated_gib':torch.cuda.memory_allocated()/2**30,'cuda_reserved_gib':torch.cuda.memory_reserved()/2**30,'cuda_peak_allocated_gib':torch.cuda.max_memory_allocated()/2**30}),flush=True)
            raise
    else:raise SystemExit(supervise(args))
