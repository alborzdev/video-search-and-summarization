"""Serial, guarded Spark image-mask comparison; each model gets a fresh child."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark/local-segmentation'


def available_gib():
    return next(int(s.split()[1])/2**20 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))


def distribution(samples):
    ordered = sorted(samples)
    return {'samples':samples, 'median':statistics.median(samples),
        'p95_observed':ordered[min(len(ordered)-1, int(.95*len(ordered)))],
        'min':min(samples), 'max':max(samples)}


def child(args):
    import numpy as np
    import torch
    from PIL import Image
    from adapter import load
    from evaluate import evaluate_mask, save_overlay
    torch.set_num_threads(4)
    directory = Path(os.environ['SEGMENTATION_RUN_DIR'])

    def emit(stage, **data):
        if torch.cuda.is_initialized(): torch.cuda.synchronize()
        print(json.dumps({'stage':stage,'available_gib':available_gib(),
            'cuda_allocated_gib':torch.cuda.memory_allocated()/2**30,
            'cuda_reserved_gib':torch.cuda.memory_reserved()/2**30,
            'cuda_peak_reserved_gib':torch.cuda.max_memory_reserved()/2**30,
            **data}),flush=True)

    start=time.monotonic(); model=load(args.model)
    emit('loaded',elapsed_s=time.monotonic()-start,receipt=model.receipt)
    cases=json.loads(Path(args.cases).read_text())
    for case in cases:
        # A point/box segmenter assumes an object prompt. Absence is evaluated
        # separately in the grounding-to-mask pipeline, not with invented prompts.
        prompts=[]
        for kind,key in [('box','oracle_box'),('point','oracle_point')]:
            if case.get(key) is not None:prompts.append((kind,case[key],'oracle_ground_truth'))
        for kind,key in [('box','prompt_box'),('point','prompt_point'),('point','manual_point')]:
            if case.get(key) is not None:prompts.append((kind,case[key],case.get('prompt_source','manual')))
        if not prompts:
            emit('skipped',case=case['id'],reason='No point or box; requires separate grounding/presence decision')
            continue
        image=Image.open(case['image']).convert('RGB')
        gt=np.asarray(Image.open(case['gt_mask']))>0 if case.get('gt_mask') else None
        for prompt_index,(kind,prompt,prompt_source) in enumerate(prompts):
            kwargs={'box':prompt,'multimask':False} if kind=='box' else {'points':[prompt],'labels':[1],'multimask':True}
            emit('case_start',case=case['id'],prompt_type=kind,prompt_source=prompt_source)
            samples=[];encodes=[];decodes=[];last=None;mask_hashes=[]
            for iteration in range(args.warmups+args.repeats):
                torch.cuda.synchronize();start=time.perf_counter()
                encoded=model.set_image(image)
                last=model.predict(**kwargs)
                torch.cuda.synchronize();elapsed=(time.perf_counter()-start)*1000
                if iteration>=args.warmups:
                    samples.append(elapsed);encodes.append(encoded['encode_ms']);decodes.append(last['decode_ms'])
                    mask_hashes.append(hashlib.sha256(np.asarray(last['mask'],dtype=np.uint8).tobytes()).hexdigest())
            cached=[]
            for _ in range(args.repeats):
                torch.cuda.synchronize();start=time.perf_counter()
                model.predict(**kwargs)
                torch.cuda.synchronize();cached.append((time.perf_counter()-start)*1000)
            stem=f"{case['id']}-{kind}-{prompt_source}-{prompt_index}"
            mask_path=directory/(stem+'.mask.png');overlay_path=directory/(stem+'.overlay.png')
            Image.fromarray(np.asarray(last['mask'],dtype=np.uint8)*255).save(mask_path)
            save_overlay(image,last['mask'],overlay_path,ground_truth=gt)
            metrics=evaluate_mask(last['mask'],gt,prompt_source=prompt_source,
                positive_points=[prompt] if kind=='point' else None, coordinate_space='normalized')
            emit('mask',case=case['id'],prompt_type=kind,prompt_source=prompt_source,prompt=prompt,
                image_size=list(image.size),image_sha256=hashlib.sha256(Path(case['image']).read_bytes()).hexdigest(),
                score=float(last['score']),candidate_count=last.get('candidate_count'),metrics=metrics,
                full_image_ms=distribution(samples),encode_ms=distribution(encodes),decode_ms=distribution(decodes),
                cached_image_prompt_ms=distribution(cached),unique_mask_hashes=sorted(set(mask_hashes)),
                mask=str(mask_path),overlay=str(overlay_path))
    emit('closed')


def supervise(args):
    reserve=json.loads((ROOT/'.spark/settings.json').read_text())['reserve_gib']
    if reserve<20:raise SystemExit('Preserve the selected 20 GiB reserve.')
    if subprocess.run(['systemctl','--user','is-active','--quiet','vss-spark-guard.service']).returncode:
        raise SystemExit('Spark guard must be active.')
    if available_gib() < reserve:raise SystemExit('Need the saved memory reserve available.')
    site=Path(sys.prefix)/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    libs=sorted({str(p) for root in ('nvidia','nvpl') for p in (site/root).glob('**/lib') if p.is_dir()})
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory=STATE/'runs'/f'{stamp}-{args.model}';directory.mkdir(parents=True)
    env=dict(os.environ,LD_LIBRARY_PATH=':'.join(libs+[os.environ.get('LD_LIBRARY_PATH','')]),
        PYTHONUNBUFFERED='1',HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',SEGMENTATION_RUN_DIR=str(directory),OMP_NUM_THREADS='4')
    (directory/'settings.json').write_text(json.dumps(vars(args),indent=2)+'\n')
    (directory/'cases.json').write_text(Path(args.cases).read_text())
    print(json.dumps({'run_dir':str(directory)}),flush=True)
    began=time.monotonic();reason=None
    with (directory/'inference.jsonl').open('w') as out,(directory/'inference.stderr').open('w') as err,(directory/'memory.jsonl').open('w') as mem:
        process=subprocess.Popen([sys.executable,__file__,'--child','--model',args.model,'--cases',args.cases,'--warmups',str(args.warmups),'--repeats',str(args.repeats)],env=env,stdout=out,stderr=err,start_new_session=True)
        try:
            while process.poll() is None:
                elapsed=time.monotonic()-began;available=available_gib()
                mem.write(json.dumps({'elapsed_s':elapsed,'available_gib':available})+'\n');mem.flush()
                if available<reserve+3 or elapsed>args.timeout:
                    reason='reserve_headroom' if available<reserve+3 else 'timeout'
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL)
                    break
                time.sleep(.2)
        finally:
            if process.poll() is None:os.killpg(process.pid,signal.SIGKILL)
            process.wait()
    result={'returncode':process.returncode,'stop_reason':reason,'elapsed_s':time.monotonic()-began,'run_dir':str(directory)}
    (directory/'exit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return process.returncode


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--model',required=True,choices=['sam2.1-tiny','edgetam'])
    parser.add_argument('--cases',required=True)
    parser.add_argument('--warmups',type=int,default=2)
    parser.add_argument('--repeats',type=int,default=10)
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    if not 1<=args.repeats<=100 or not 0<=args.warmups<=10:parser.error('Require1–100 repeats and0–10 warmups')
    if args.child:child(args)
    else:raise SystemExit(supervise(args))
