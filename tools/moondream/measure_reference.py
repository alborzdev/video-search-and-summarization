"""Bounded non-Photon comparison using the pinned official PyTorch forward.

This is an offline diagnostic, not a supported segmentation service. The
supervisor preserves the saved Spark reserve and stops only its own child.
"""
import argparse
import datetime
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark/moondream-photon'


def available_gib():
    return next(int(s.split()[1]) / 2**20 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))


def child(args):
    import torch
    from PIL import Image
    from reference_loader import load_reference_model
    from reference_decode import segment
    from mask_artifacts import save_mask_artifacts
    faulthandler.enable()
    faulthandler.dump_traceback_later(120, repeat=True)
    torch.set_num_threads(4)
    directory = Path(os.environ['MOONDREAM_REFERENCE_RUN_DIR'])

    def emit(stage, **data):
        if torch.cuda.is_initialized():
            torch.cuda.synchronize()
        print(json.dumps({'stage': stage, 'available_gib': available_gib(),
            'cuda_allocated_gib': torch.cuda.memory_allocated()/2**30,
            'cuda_reserved_gib': torch.cuda.memory_reserved()/2**30,
            'cuda_peak_allocated_gib': torch.cuda.max_memory_allocated()/2**30,
            'cuda_peak_reserved_gib': torch.cuda.max_memory_reserved()/2**30,
            **data}), flush=True)

    def progress(data):
        if data['loaded'] % 50 == 0 or data['loaded'] == data['total']:
            emit('load_progress', **data)

    reserve = json.loads((ROOT/'.spark/settings.json').read_text())['reserve_gib']
    emit('before_load', torch_version=torch.__version__, cuda_version=torch.version.cuda)
    model, receipt = load_reference_model(
        (STATE/'reference-source-path.txt').read_text().strip(),
        (STATE/'preview-model-path.txt').read_text().strip(),
        (STATE/'tokenizer-path.txt').read_text().strip(),
        reserve_gib=reserve, progress=progress)
    (directory/'load-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    emit('loaded', elapsed_s=receipt['elapsed_seconds'], max_context=model.config.text.max_context)
    for case in json.loads(Path(args.cases).read_text()):
        image = Image.open(case['image']).convert('RGB')
        image.thumbnail((1024,1024))
        emit('case_start', case=case['id'], task=case['task'])
        started = time.monotonic()
        try:
            with torch.inference_mode():
                if case['task'] == 'query':
                    result = model.query(image, case['prompt'], reasoning=False,
                        settings={'max_tokens':48, 'temperature':0})
                elif case['task'] == 'detect':
                    result = model.detect(image, case['object'], settings={'max_objects':3})
                else:
                    result = segment(model, image, case['object'],
                        spatial_refs=case.get('spatial_refs'),
                        max_tokens=case.get('max_tokens',256),
                        condition_svg=case.get('condition_svg',False))
            torch.cuda.synchronize()
            inference_s = time.monotonic()-started
            if case['task'] == 'segment':
                result['mask_receipt'] = save_mask_artifacts(image, result,
                    directory/'masks', stem=case['id'])
            emit(case['task'], case=case['id'], elapsed_s=time.monotonic()-started,
                inference_s=inference_s, image_size=list(image.size),
                image_sha256=hashlib.sha256(Path(case['image']).read_bytes()).hexdigest(), result=result)
        except Exception:
            emit(case['task'], case=case['id'], elapsed_s=time.monotonic()-started,
                error=traceback.format_exc())
            raise
    forbidden = sorted(n for n in sys.modules if n == 'kestrel' or n.startswith('kestrel.') or n == 'moondream' or n.startswith('moondream.'))
    emit('closed', photon_modules_loaded=forbidden)
    if forbidden:
        raise RuntimeError('Comparison unexpectedly imported Photon SDK/runtime')


def supervise(args):
    reserve = json.loads((ROOT/'.spark/settings.json').read_text())['reserve_gib']
    if reserve < 20:
        raise SystemExit('The comparison must preserve at least the selected 20 GiB reserve.')
    if subprocess.run(['systemctl','--user','is-active','--quiet','vss-spark-guard.service']).returncode:
        raise SystemExit('Spark guard must remain active.')
    if available_gib() < reserve:
        raise SystemExit('Need the saved memory reserve available.')
    site = Path(sys.prefix)/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    libs = sorted({str(p) for root in ('nvidia','nvpl') for p in (site/root).glob('**/lib') if p.is_dir()})
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = STATE/'runs'/f'{stamp}-preview-pytorch-reference'
    directory.mkdir(parents=True)
    (STATE/'latest-reference-run.txt').write_text(str(directory)+'\n')
    env = dict(os.environ, LD_LIBRARY_PATH=':'.join(libs+[os.environ.get('LD_LIBRARY_PATH','')]),
        PYTHONUNBUFFERED='1', HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
        MOONDREAM_REFERENCE_RUN_DIR=str(directory), OMP_NUM_THREADS='4')
    (directory/'settings.json').write_text(json.dumps(vars(args),indent=2)+'\n')
    (directory/'cases.json').write_text(Path(args.cases).read_text())
    print(json.dumps({'run_dir':str(directory)}),flush=True)
    began = time.monotonic()
    stop_reason = None
    with (directory/'inference.jsonl').open('w') as out, (directory/'inference.stderr').open('w') as err, (directory/'memory.jsonl').open('w') as mem:
        process = subprocess.Popen([sys.executable,__file__,'--child','--cases',args.cases],
            env=env,stdout=out,stderr=err,start_new_session=True)
        try:
            while process.poll() is None:
                elapsed, available = time.monotonic()-began, available_gib()
                mem.write(json.dumps({'elapsed_s':elapsed,'available_gib':available})+'\n'); mem.flush()
                if available < reserve+3 or elapsed > args.timeout:
                    stop_reason = 'reserve_headroom' if available < reserve+3 else 'timeout'
                    os.killpg(process.pid,signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL)
                    break
                time.sleep(.2)
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL)
            process.wait()
    reports = [json.loads(line) for line in (directory/'inference.jsonl').read_text().splitlines() if line.startswith('{')]
    cases = json.loads(Path(args.cases).read_text())
    completed = {r['case'] for r in reports if 'result' in r and 'error' not in r}
    missing = sorted({c['id'] for c in cases}-completed)
    failures = []
    for r in reports:
        if r['stage'] != 'segment' or 'result' not in r:
            continue
        c = next(c for c in cases if c['id'] == r['case'])
        result = r['result']; mask = result['mask_receipt']
        passed = result['finish_reason'] == 'eos' and (mask.get('valid_mask') if c.get('expect_present',True) else mask['status'] == 'empty_result')
        if not passed:
            failures.append({'case':r['case'],'status':mask['status'],'finish_reason':result['finish_reason']})
    effective = process.returncode or (2 if missing else 3 if failures else 0)
    result = {'returncode':effective,'child_returncode':process.returncode,'stop_reason':stop_reason,
        'missing_cases':missing,'mask_failures':failures,'elapsed_s':time.monotonic()-began,'run_dir':str(directory)}
    (directory/'exit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return effective


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--cases',required=True)
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    if args.child:
        child(args)
    else:
        raise SystemExit(supervise(args))
