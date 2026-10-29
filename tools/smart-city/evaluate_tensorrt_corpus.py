#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare on CPU, run an actual TensorRT engine, then score the pinned corpus.

Only the explicit `run --allow-gpu` command allocates GPU resources. Coordinate
that command with the stack owner. This tool measures corpus quality, not latency.
"""
from __future__ import annotations
import argparse
import ctypes as C
import ctypes.util
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from evaluate_detectors import (ROAD, coarse_predictions, decode_rfdetr, evaluate,
                                preprocess_image, sha256)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def prepare(args):
    import numpy as np
    import torch
    torch.set_num_threads(4)
    subset_path = args.subset / 'subset-manifest.json'
    subset = json.loads(subset_path.read_text())
    resolution = {'rfdetr-small':512,'rfdetr-medium':576,'rfdetr-large':704}[args.model]
    args.inputs.mkdir(parents=True, exist_ok=True)
    images = []
    for item in subset['images']:
        image = args.subset / 'images' / item['fileName']
        if sha256(image) != item['sha256']:
            raise RuntimeError('Source image hash differs from pinned subset')
        tensor = preprocess_image(image, resolution, (item['width'], item['height']))
        array = np.asarray(tensor.numpy(), dtype='<f4', order='C')
        target = args.inputs / f"{item['id']:012d}.bin"
        array.tofile(target)
        images.append({'id': item['id'], 'width': item['width'], 'height': item['height'],
                       'fileName': target.name, 'sha256': sha256(target)})
    manifest = {'schemaVersion': 'city.coco-tensorrt-inputs.v1', 'model': args.model,
        'resolution': resolution, 'shape': [1,3,resolution,resolution], 'dtype': 'little-endian-float32',
        'subsetManifestSha256': sha256(subset_path), 'groundTruthSha256': subset['selectedGroundTruthSha256'],
        'preprocess': 'Shared evaluate_detectors.preprocess_image; RGB float resize antialias=false and ImageNet normalization',
        'preprocessorSourceSha256': sha256(Path(__file__).with_name('evaluate_detectors.py')),
        'images': images, 'gpuUsed': False}
    (args.inputs / 'input-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'preparedImages': len(images), 'inputManifest': str(args.inputs/'input-manifest.json'),
                      'gpuUsed': False}), flush=True)


class CudaRuntime:
    """Small explicit CUDA Runtime binding; no PyCUDA/torch GPU dependency."""
    def __init__(self):
        self.lib = C.CDLL(ctypes.util.find_library('cudart') or 'libcudart.so.13')
        signatures = {
            'cudaMalloc': ([C.POINTER(C.c_void_p), C.c_size_t], C.c_int),
            'cudaFree': ([C.c_void_p], C.c_int),
            'cudaMemcpy': ([C.c_void_p,C.c_void_p,C.c_size_t,C.c_int], C.c_int),
            'cudaStreamCreate': ([C.POINTER(C.c_void_p)], C.c_int),
            'cudaStreamSynchronize': ([C.c_void_p], C.c_int),
            'cudaStreamDestroy': ([C.c_void_p], C.c_int),
            'cudaMemGetInfo': ([C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)], C.c_int),
            'cudaRuntimeGetVersion': ([C.POINTER(C.c_int)], C.c_int),
            'cudaGetErrorString': ([C.c_int], C.c_char_p),
        }
        for name, (argtypes,restype) in signatures.items():
            fn = getattr(self.lib,name);fn.argtypes=argtypes;fn.restype=restype

    def check(self, code):
        if code:
            raise RuntimeError(f'CUDA error {code}: {self.lib.cudaGetErrorString(code).decode()}')

    def allocate(self, count):
        pointer = C.c_void_p()
        self.check(self.lib.cudaMalloc(C.byref(pointer),count))
        return pointer

    def free_memory(self):
        free, total = C.c_size_t(), C.c_size_t()
        self.check(self.lib.cudaMemGetInfo(C.byref(free),C.byref(total)))
        return {'freeBytes': free.value, 'totalBytes': total.value}


class Engine:
    def __init__(self, path, shape, reserve_gib):
        import numpy as np
        import tensorrt as trt
        self.trt = trt
        self.cuda = CudaRuntime()
        self.memory_before = self.cuda.free_memory()
        if self.memory_before['freeBytes'] < reserve_gib * 1024**3:
            raise RuntimeError('GPU reserve guard failed before engine load')
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(path.read_bytes())
        if self.engine is None:
            raise RuntimeError('TensorRT could not deserialize engine')
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError('TensorRT could not create execution context')
        if not self.context.set_input_shape('input', shape):
            raise RuntimeError('Engine profile does not accept requested input shape')
        unresolved = self.context.infer_shapes()
        if unresolved:
            raise RuntimeError(f'Engine shapes remain unspecified: {unresolved}')
        self.buffers = {};self.outputs = {};self.stream = C.c_void_p()
        self.cuda.check(self.cuda.lib.cudaStreamCreate(C.byref(self.stream)))
        names = {self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)}
        if names != {'input','dets','labels'}:
            raise RuntimeError(f'Unexpected TensorRT I/O contract: {names}')
        self.contract = {}
        for name in sorted(names):
            actual = tuple(self.context.get_tensor_shape(name))
            dtype = np.dtype(trt.nptype(self.engine.get_tensor_dtype(name)))
            if dtype != np.dtype('float32') or any(v <= 0 for v in actual):
                raise RuntimeError(f'Unexpected engine dtype/shape for {name}: {dtype}/{actual}')
            if self.engine.get_tensor_location(name) != trt.TensorLocation.DEVICE:
                raise RuntimeError('This runner requires device I/O tensors')
            output = self.engine.get_tensor_mode(name) == trt.TensorIOMode.OUTPUT
            array = np.empty(actual,dtype=dtype)
            pointer = self.cuda.allocate(array.nbytes)
            self.buffers[name] = pointer
            if not self.context.set_tensor_address(name,pointer.value):
                raise RuntimeError(f'Could not bind engine tensor {name}')
            if output:self.outputs[name] = array
            self.contract[name] = {'shape': list(actual), 'dtype': str(dtype), 'output': output}
        if tuple(self.context.get_tensor_shape('input')) != tuple(shape):
            raise RuntimeError('Engine input did not adopt requested shape')
        if set(self.outputs) != {'dets','labels'}:
            raise RuntimeError('RF-DETR output direction mismatch')
        self.memory_loaded = self.cuda.free_memory()
        if self.memory_loaded['freeBytes'] < reserve_gib * 1024**3:
            self.close();raise RuntimeError('GPU reserve guard failed after engine load')

    def infer(self, array):
        import numpy as np
        if array.dtype != np.float32 or list(array.shape) != self.contract['input']['shape']:
            raise ValueError('CPU input dtype/shape differs from allocated engine input')
        array = np.ascontiguousarray(array)
        self.cuda.check(self.cuda.lib.cudaMemcpy(self.buffers['input'],C.c_void_p(array.ctypes.data),array.nbytes,1))
        if not self.context.execute_async_v3(self.stream.value):
            raise RuntimeError('TensorRT enqueue failed')
        self.cuda.check(self.cuda.lib.cudaStreamSynchronize(self.stream))
        for name,out in self.outputs.items():
            self.cuda.check(self.cuda.lib.cudaMemcpy(C.c_void_p(out.ctypes.data),self.buffers[name],out.nbytes,2))
            if not np.isfinite(out).all():
                raise RuntimeError(f'Non-finite actual TensorRT output {name}')
        return self.outputs

    def close(self):
        for pointer in getattr(self,'buffers',{}).values():
            self.cuda.check(self.cuda.lib.cudaFree(pointer))
        self.buffers = {}
        if getattr(self,'stream',None) and self.stream.value:
            self.cuda.check(self.cuda.lib.cudaStreamDestroy(self.stream));self.stream=C.c_void_p()
        self.context=None;self.engine=None;self.runtime=None


def run(args):
    import numpy as np
    if not args.allow_gpu:
        raise RuntimeError('run requires --allow-gpu and a coordinated GPU lease')
    if args.reserve_gib < 20:
        raise RuntimeError('The saved Spark reserve floor is 20 GiB')
    available = next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    if available < args.reserve_gib * 1024**3:
        raise RuntimeError('System available-memory reserve guard failed before CUDA initialization')
    manifest_path = args.inputs / 'input-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    started = utc_now();wall_start=time.monotonic()
    resolution = manifest['resolution']
    shape = (args.batch,3,resolution,resolution)
    args.outputs.mkdir(parents=True,exist_ok=True)
    runner = Engine(args.engine,shape,args.reserve_gib)
    files = []
    try:
        for start in range(0,len(manifest['images']),args.batch):
            images = manifest['images'][start:start+args.batch]
            arrays = []
            for item in images:
                path = args.inputs / item['fileName']
                if sha256(path) != item['sha256']:
                    raise RuntimeError('Preprocessed input changed after staging')
                arrays.append(np.fromfile(path,dtype='<f4').reshape(manifest['shape']))
            while len(arrays) < args.batch:arrays.append(arrays[-1])
            result = runner.infer(np.concatenate(arrays,axis=0))
            for index,item in enumerate(images):
                target = args.outputs / f"{item['id']:012d}.npz"
                np.savez(target,**{name:array[index:index+1].copy() for name,array in result.items()})
                files.append({'id':item['id'],'fileName':target.name,'sha256':sha256(target)})
        version = C.c_int();runner.cuda.check(runner.cuda.lib.cudaRuntimeGetVersion(C.byref(version)))
        gpu = subprocess.run(['nvidia-smi','--query-gpu=name,uuid,driver_version','--format=csv,noheader'],
                             capture_output=True,text=True,check=True).stdout.strip()
        receipt = {'schemaVersion':'city.tensorrt-corpus-run.v1','model':manifest['model'],
            'engine':str(args.engine),'engineSha256':sha256(args.engine),'inputManifestSha256':sha256(manifest_path),
            'subsetManifestSha256':manifest['subsetManifestSha256'],'tensorrtVersion':runner.trt.__version__,
            'cudaRuntimeVersion':version.value,'gpu':gpu,'containerImage':args.image,
            'precision':'FP16-enabled engine; mixed internal precision allowed; FP32 I/O',
            'batch':args.batch,'imageCount':len(files),'ioContract':runner.contract,'outputs':files,
            'memoryBefore':runner.memory_before,'memoryLoaded':runner.memory_loaded,'reserveGiB':args.reserve_gib,
            'systemAvailableBytesBefore':available,
            'startedAt':started,'finishedAt':utc_now(),'wallSeconds':time.monotonic()-wall_start,
            'runnerSourceSha256':sha256(Path(__file__)),'gpuUsed':True,
            'scope':'Actual serialized engine corpus outputs. Wall time is not an inference latency benchmark.'}
        (args.outputs/'run-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        (args.outputs/'runner-source.py').write_bytes(Path(__file__).read_bytes())
        print(json.dumps({k:v for k,v in receipt.items() if k!='outputs'},indent=2),flush=True)
    finally:
        runner.close()


def score(args):
    import numpy as np
    subset_path=args.subset/'subset-manifest.json';subset=json.loads(subset_path.read_text())
    run_path=args.outputs/'run-receipt.json';receipt=json.loads(run_path.read_text())
    if sha256(subset_path)!=receipt['subsetManifestSha256']:
        raise RuntimeError('Raw GPU outputs and evaluation subset differ')
    gt=args.subset/'instances_road_subset.json';coarse_gt=args.subset/'instances_coarse_road_subset.json'
    if sha256(gt)!=subset['selectedGroundTruthSha256'] or sha256(coarse_gt)!=subset['coarseGroundTruthSha256']:
        raise RuntimeError('Pinned ground truth changed')
    files={item['id']:item for item in receipt['outputs']}
    if len(receipt['outputs'])!=len(files) or len(files)!=len(subset['images']) or set(files)!={item['id'] for item in subset['images']}:
        raise RuntimeError('TensorRT output set must cover every subset image exactly once')
    predictions=[]
    for image in subset['images']:
        file=files[image['id']];path=args.outputs/file['fileName']
        if sha256(path)!=file['sha256']:raise RuntimeError('GPU output changed after inference')
        with np.load(path,allow_pickle=False) as arrays:
            predictions.extend(decode_rfdetr(arrays,image['id'],image['width'],image['height'],.001))
    args.result.mkdir(parents=True,exist_ok=True)
    prediction=args.result/'predictions.json';prediction.write_text(json.dumps(predictions,separators=(',',':'))+'\n')
    metrics=evaluate(gt,predictions,ROAD,args.result/'coco-eval.txt')
    coarse=evaluate(coarse_gt,coarse_predictions(predictions),[1,2,3],args.result/'coarse-coco-eval.txt')
    scored={'schemaVersion':'city.tensorrt-corpus-quality.v1','model':receipt['model'],
        'engineSha256':receipt['engineSha256'],'batch':receipt['batch'],'imageCount':len(subset['images']),
        'runReceiptSha256':sha256(run_path),'subsetManifestSha256':sha256(subset_path),
        'predictionsSha256':sha256(prediction),'sixRoadClasses':metrics,'coarseRoadClasses':coarse,
        'scorerSourceSha256':sha256(Path(__file__)),'postprocessorSourceSha256':sha256(Path(__file__).with_name('evaluate_detectors.py')),
        'precision':receipt['precision'],'gpuUsedForInference':receipt.get('gpuUsed',False),
        'scope':('Actual TensorRT engine outputs on a stratified COCO100 proxy, not full COCO or final-city/event qualification.'
                 if receipt.get('gpuUsed') else 'Scoring control for supplied outputs; actual GPU inference is not established.')}
    if args.cpu_receipt:
        reference=json.loads(args.cpu_receipt.read_text())
        if reference['model']!=receipt['model'] or reference['subsetManifestSha256']!=sha256(subset_path):
            raise RuntimeError('CPU reference and engine corpus do not match')
        deltas={key:(value-reference['sixRoadClasses']['metrics'][key])*100
                for key,value in metrics['metrics'].items() if value is not None and reference['sixRoadClasses']['metrics'][key] is not None}
        scored['fp32Reference']={'receiptSha256':sha256(args.cpu_receipt),'onnxSha256':reference['onnxSha256'],
            'metricDeltaPercentagePoints':deltas,'perClassApDeltaPercentagePoints':{
                key:((value['AP']-reference['sixRoadClasses']['perClass'][key]['AP'])*100
                     if value['AP'] is not None and reference['sixRoadClasses']['perClass'][key]['AP'] is not None else None)
                for key,value in metrics['perClass'].items()}}
        scored['precisionRetentionGate']={'maximumApDropPercentagePoints':args.maximum_ap_drop,
            'passed':deltas['AP']>=-args.maximum_ap_drop,
            'meaning':'Engineering consistency gate for this paired subset, not a statistical model superiority claim.'}
    (args.result/'receipt.json').write_text(json.dumps(scored,indent=2)+'\n')
    print(json.dumps(scored,indent=2),flush=True)
    if scored.get('precisionRetentionGate',{}).get('passed') is False:
        raise RuntimeError('FP16 actual-engine AP retention gate failed; receipt preserved')


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--subset',type=Path,required=True)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--model',choices=['rfdetr-small','rfdetr-medium','rfdetr-large'],required=True)
    p.set_defaults(func=prepare)
    p=sub.add_parser('run');p.add_argument('--inputs',type=Path,required=True);p.add_argument('--outputs',type=Path,required=True)
    p.add_argument('--engine',type=Path,required=True);p.add_argument('--batch',type=int,choices=[1,2],default=1)
    p.add_argument('--allow-gpu',action='store_true');p.add_argument('--reserve-gib',type=float,default=20)
    p.add_argument('--image',required=True);p.set_defaults(func=run)
    p=sub.add_parser('score');p.add_argument('--subset',type=Path,required=True);p.add_argument('--outputs',type=Path,required=True)
    p.add_argument('--result',type=Path,required=True);p.add_argument('--cpu-receipt',type=Path)
    p.add_argument('--maximum-ap-drop',type=float,default=1.);p.set_defaults(func=score)
    args=parser.parse_args();args.func(args)


if __name__=='__main__':
    main()
