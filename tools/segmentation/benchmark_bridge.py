"""Bounded end-to-end Moondream grounding plus local mask evaluation."""
import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.segmentation.benchmark import available_gib


def child(args):
    import numpy as np
    import torch
    from PIL import Image
    from tools.segmentation.moondream_bridge import MoondreamBridge
    from tools.segmentation.evaluate import evaluate_mask, save_overlay
    torch.set_num_threads(4)
    output = Path(os.environ['SEGMENTATION_RUN_DIR'])
    def emit(stage, **data):
        if torch.cuda.is_initialized(): torch.cuda.synchronize()
        print(json.dumps({'stage':stage, 'available_gib':available_gib(),
            'cuda_allocated_gib':torch.cuda.memory_allocated()/2**30,
            'cuda_reserved_gib':torch.cuda.memory_reserved()/2**30,
            'cuda_peak_reserved_gib':torch.cuda.max_memory_reserved()/2**30,
            **data}), flush=True)
    cases = json.loads(Path(args.cases).read_text())
    with MoondreamBridge(model=args.model, segmenter_name=args.segmenter,
                        gb10_compat=args.model!='moondream2') as bridge:
        first = Image.open(cases[0]['image']).convert('RGB')
        # Loading and first-call compilation are reported separately from warm requests.
        for task in ('detect', 'point', 'describe'):
            result = getattr(bridge,task)(first, cases[0]['expression']) if task!='describe' else bridge.describe(first)
            emit(task, case=cases[0]['id'], result=result)
        for mode in args.presence_modes.split(','):
            bridge.presence_mode=mode
            for case in cases:
                image=Image.open(case['image']).convert('RGB')
                original_size=list(image.size)
                image.thumbnail((1024,1024))
                gt=np.asarray(Image.open(case['gt_mask']))>0 if case.get('gt_mask') else None
                if gt is not None and gt.shape!=(image.height,image.width):
                    raise ValueError('Do not resize annotated fixtures silently')
                for repeat in range(args.repeats):
                    emit('case_start',case=case['id'],mode=mode,repeat=repeat)
                    result=bridge.segment(image,case['expression'],grounded_by=args.grounded_by)
                    union=np.zeros((image.height,image.width),dtype=bool)
                    for index,obj in enumerate(result['objects']):
                        mask=obj.pop('mask');union|=mask
                        name=f"{case['id']}-{mode}-{repeat}-{index}"
                        mask_path=output/(name+'.mask.png')
                        overlay_path=output/(name+'.overlay.png')
                        Image.fromarray(mask.astype(np.uint8)*255).save(mask_path)
                        save_overlay(image,mask,overlay_path,ground_truth=gt)
                        obj.update(mask=str(mask_path),overlay=str(overlay_path),
                            metrics=evaluate_mask(mask,gt,prompt_source='moondream_predicted',
                                positive_points=[obj['point']] if 'point' in obj else None,
                                coordinate_space='normalized'))
                    # Union is fixed in advance, not selected by matching ground truth.
                    metrics=evaluate_mask(union,gt,prompt_source='moondream_predicted')
                    emit('segment',case=case['id'],mode=mode,repeat=repeat,
                        expected_present=case.get('expect_present',True),original_size=original_size,
                        union_metrics=metrics,result=result)
    emit('closed')


def supervise(args):
    reserve=max(20,json.loads((ROOT/'.spark/settings.json').read_text())['reserve_gib'])
    if subprocess.run(['systemctl','--user','is-active','--quiet','vss-spark-guard.service']).returncode:
        raise SystemExit('Spark guard must be active.')
    if available_gib()<reserve+30:raise SystemExit('Need30GiB above saved reserve for initial qualification.')
    site=Path(sys.prefix)/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    libs=sorted({str(p) for root in ('nvidia','nvpl') for p in (site/root).glob('**/lib') if p.is_dir()})
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory=ROOT/'.spark/local-segmentation/runs'/f'{stamp}-bridge-{args.model}-{args.segmenter}'
    directory.mkdir(parents=True)
    env=dict(os.environ,LD_LIBRARY_PATH=':'.join(libs+[os.environ.get('LD_LIBRARY_PATH','')]),
        PYTHONUNBUFFERED='1',HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
        SEGMENTATION_RUN_DIR=str(directory),OMP_NUM_THREADS='4')
    (directory/'settings.json').write_text(json.dumps(vars(args),indent=2)+'\n')
    (directory/'cases.json').write_text(Path(args.cases).read_text())
    print(json.dumps({'run_dir':str(directory)}),flush=True)
    began=time.monotonic();reason=None
    with (directory/'inference.jsonl').open('w') as out,(directory/'inference.stderr').open('w') as err,(directory/'memory.jsonl').open('w') as mem:
        process=subprocess.Popen([sys.executable,__file__,'--child','--model',args.model,
            '--segmenter',args.segmenter,'--cases',args.cases,'--repeats',str(args.repeats),
            '--presence-modes',args.presence_modes,'--grounded-by',args.grounded_by],env=env,stdout=out,stderr=err,start_new_session=True)
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
    result={'returncode':process.returncode,'stop_reason':reason,
        'elapsed_s':time.monotonic()-began,'run_dir':str(directory)}
    (directory/'exit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return process.returncode


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--model',choices=['moondream2','moondream3-preview','moondream3.1-9B-A2B'],default='moondream2')
    parser.add_argument('--segmenter',choices=['sam2.1-tiny','edgetam'],default='edgetam')
    parser.add_argument('--cases',required=True)
    parser.add_argument('--presence-modes',default='off,query')
    parser.add_argument('--grounded-by',choices=['detect','point'],default='detect')
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    if not 1<=args.repeats<=10 or any(m not in ('off','query') for m in args.presence_modes.split(',')):
        parser.error('Require1–10 repeats and off/query presence modes')
    if args.child:child(args)
    else:raise SystemExit(supervise(args))
