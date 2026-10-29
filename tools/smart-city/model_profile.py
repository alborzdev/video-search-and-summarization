#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Select a qualified device-local detector and generate its native configs.

CPU/filesystem only. Selection does not launch inference or qualify a new model.
The default remains Small until an explicit, validated selection is persisted.
"""
from __future__ import annotations
import argparse
import configparser
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RESOLUTIONS = {'small': 512, 'medium': 576, 'large': 704}
TRAFFIC = 'trafficcamnet-transformer'
SELECTIONS = (*RESOLUTIONS, TRAFFIC)
ADAPTER_FILES = ('city-worker', 'libcity_parser.so', 'libcity_preprocess.so')
CLASSES = ['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck']
COCO_SLOTS = [1, 2, 3, 4, 6, 8]


class ProfileError(RuntimeError):
    pass


def _device(device):
    if not isinstance(device,str) or device not in ('spark', 'thor'):
        raise ProfileError('Unknown city device; expected spark or thor')
    return device


def _size(size):
    if not isinstance(size,str) or size not in RESOLUTIONS:
        raise ProfileError('Unknown detector size; expected small, medium or large')
    return size


def _directory(root, device):
    platform=Path(root).resolve() / f'.{_device(device)}'
    if platform.is_symlink():raise ProfileError('Refusing symlinked device storage')
    return platform / 'city'


def _controlled(path, base):
    """Generated/model files must not redirect outside the device directory."""
    path, base = Path(path), Path(base)
    if not path.is_relative_to(base):
        raise ProfileError('Model profile path is outside controlled device storage')
    current = base
    if current.is_symlink():
        raise ProfileError('Refusing symlinked city storage')
    for part in path.relative_to(base).parts:
        current = current / part
        if current.is_symlink():
            raise ProfileError('Refusing symlinked model/profile files')
    return path


@lru_cache(maxsize=64)
def _digest_at_stat(path, _device_id, _inode, _size_bytes, _mtime_ns, _ctime_ns):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def digest(path):
    path = Path(path)
    stat = path.stat()
    # Repeated controller/catalog reads avoid re-reading hundreds of MB. Content
    # mutation changes mtime/ctime and invalidates this process-local cache.
    return _digest_at_stat(str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _json_file(path, base):
    path = _controlled(path, base)
    if not path.is_file():
        raise ProfileError(f'Required qualification receipt is missing: {path.name}')
    try:
        value=json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise ProfileError(f'Invalid qualification JSON: {path.name}') from exc
    if not isinstance(value,dict):raise ProfileError(f'Qualification receipt must be an object: {path.name}')
    return value


def _atomic_bytes(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(value);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def selection_name(root, device):
    """Read the chosen size without claiming that model files are ready."""
    directory = _directory(root, device)
    path = _controlled(directory/'state/model-selection.json', directory)
    if not path.exists():
        return 'small'
    selection = _json_file(path, directory)
    if selection.get('schemaVersion') != 'city.model-selection.v1' or selection.get('device') != device:
        raise ProfileError('Model selection belongs to a different device/schema')
    size = selection.get('size')
    if size not in SELECTIONS:
        raise ProfileError('Unknown detector selection')
    return size


def _quality(directory, device, size, engine_hash, graph_hash):
    receipts=[];subset_hash=None
    for batch in (1, 2):
        quality_path = directory/f'eval/results/rfdetr-{size}-fp16-b{batch}/receipt.json'
        quality = _json_file(quality_path, directory)
        gate=quality.get('precisionRetentionGate', {})
        classes=quality.get('sixRoadClasses', {})
        reference=quality.get('fp32Reference', {})
        if not all(isinstance(value,dict) for value in (gate,classes,reference)):
            raise ProfileError('FP16 quality receipt has an invalid object schema')
        metrics=classes.get('metrics',{});per_class=classes.get('perClass',{})
        if not isinstance(metrics,dict) or not isinstance(per_class,dict):
            raise ProfileError('FP16 quality metrics must be objects')
        ap=metrics.get('AP');count=quality.get('imageCount')
        if (quality.get('schemaVersion') != 'city.tensorrt-corpus-quality.v1'
                or quality.get('model') != f'rfdetr-{size}' or quality.get('engineSha256') != engine_hash
                or quality.get('batch') != batch or not isinstance(count,int) or isinstance(count,bool) or count < 100
                or classes.get('imageCount') != count or classes.get('categories') != COCO_SLOTS
                or set(per_class) != set(CLASSES)
                or quality.get('gpuUsedForInference') is not True or gate.get('passed') is not True
                or reference.get('onnxSha256') != graph_hash
                or not isinstance(ap, (int,float)) or isinstance(ap,bool) or not math.isfinite(ap) or not 0 < ap <= 1):
            raise ProfileError(f'Actual FP16 batch-{batch} quality receipt does not qualify this engine')
        allowed_drop=gate.get('maximumApDropPercentagePoints')
        deltas=reference.get('metricDeltaPercentagePoints',{})
        delta=deltas.get('AP') if isinstance(deltas,dict) else None
        if (not isinstance(allowed_drop,(int,float)) or isinstance(allowed_drop,bool)
                or not math.isfinite(allowed_drop) or not 0 <= allowed_drop <= 1
                or not isinstance(delta,(int,float)) or isinstance(delta,bool)
                or not math.isfinite(delta) or delta < -allowed_drop):
            raise ProfileError('FP16 precision-retention gate is missing or too permissive')
        current_subset=quality.get('subsetManifestSha256')
        if not isinstance(current_subset,str) or len(current_subset) != 64:
            raise ProfileError('Quality receipt lacks its evaluated dataset hash')
        if subset_hash is not None and current_subset != subset_hash:
            raise ProfileError('Batch-one and batch-two quality datasets differ')
        subset_hash=current_subset
        run_path=directory/f'runtime/corpus-outputs/rfdetr-{size}-fp16-b{batch}/run-receipt.json'
        run=_json_file(run_path,directory)
        gpu=str(run.get('gpu','')).upper()
        if (digest(run_path) != quality.get('runReceiptSha256')
                or run.get('schemaVersion') != 'city.tensorrt-corpus-run.v1'
                or run.get('engineSha256') != engine_hash or run.get('model') != f'rfdetr-{size}'
                or run.get('batch') != batch or run.get('imageCount') != quality.get('imageCount')
                or run.get('gpuUsed') is not True or run.get('subsetManifestSha256') != subset_hash
                or ('GB10' not in gpu if device == 'spark' else 'THOR' not in gpu)):
            raise ProfileError('Quality evidence does not match an actual target-device engine run')
        receipts.append({'batch':batch,'path':str(quality_path),'sha256':digest(quality_path),
                         'runPath':str(run_path),'runSha256':digest(run_path),'AP':ap})
    return receipts


def _qualified_model(root, device, size):
    root=Path(root).resolve();size=_size(size);directory=_directory(root,device)
    lock_path=root/'tools/smart-city/artifacts.lock.json'
    try:lock=json.loads(lock_path.read_text())
    except (OSError,ValueError) as exc:raise ProfileError('Pinned city artifact lock is unavailable') from exc
    if not isinstance(lock,dict) or not isinstance(lock.get('models'),dict):
        raise ProfileError('Pinned city artifact lock must contain model objects')
    model=lock['models'].get(size,{})
    if not isinstance(model,dict):raise ProfileError('Pinned model entry must be an object')
    if (lock.get('classes') != CLASSES or lock.get('cocoSlots') != COCO_SLOTS
            or model.get('resolution') != RESOLUTIONS[size]):
        raise ProfileError('Artifact class/resolution contract is not the reviewed RF-DETR profile')
    engine=_controlled(directory/f'models/rfdetr-{size}-fp16-b2.engine',directory)
    graph=_controlled(directory/f'models/rfdetr-{size}/rfdetr-{size}.onnx',directory)
    if not engine.is_file() or not graph.is_file():
        raise ProfileError(f'{size.capitalize()} device-local engine/ONNX is not staged')
    engine_hash=digest(engine);graph_hash=digest(graph)
    if graph_hash != model.get('onnxSha256'):
        raise ProfileError('Local ONNX does not match artifacts.lock.json')
    if device == 'spark' and engine_hash != model.get('sparkObservedEngineSha256'):
        raise ProfileError('Local Spark engine does not match artifacts.lock.json')
    if device == 'thor' and engine_hash == model.get('sparkObservedEngineSha256'):
        raise ProfileError('A Spark engine cannot qualify a Thor deployment')
    export_path=graph.parent/'export-receipt.json';export=_json_file(export_path,directory)
    if (export.get('model') != size or export.get('onnxSha256') != graph_hash
            or export.get('spatialResolution') != RESOLUTIONS[size] or export.get('dynamicBatch') is not True):
        raise ProfileError('Export receipt does not match the selected ONNX/resolution')
    build_path=engine.with_suffix('.build.json');build_hash=None
    if build_path.exists():
        build=_json_file(build_path,directory)
        if (build.get('schemaVersion') != 'city.engine-build.v1' or build.get('device') != device
                or build.get('model') != size or build.get('engineSha256') != engine_hash
                or build.get('onnxSha256') != graph_hash or build.get('batchRange') != [1,2]
                or 'FP16' not in str(build.get('precision','')).upper()):
            raise ProfileError('Device-local engine build receipt does not match selected artifacts')
        if device == 'thor' and 'THOR' not in str(build.get('gpu','')).upper():
            raise ProfileError('Thor requires an actual Thor GPU engine build receipt')
        build_hash=digest(build_path)
    elif size in ('medium', 'large') or device == 'thor':
        raise ProfileError('Medium, Large and Thor require a device-local engine build receipt')
    quality=_quality(directory,device,size,engine_hash,graph_hash)
    return {'schemaVersion':'city.selected-model.v1','device':device,'size':size,
        'name':f'RF-DETR {size.capitalize()}','resolution':RESOLUTIONS[size],
        'enginePath':str(engine),'onnxPath':str(graph),'engineSha256':engine_hash,'onnxSha256':graph_hash,
        'modelRevision':f'rfdetr-{size}-fp16@sha256:{engine_hash}',
        'engineContainerPath':f'/models/{engine.name}',
        'onnxContainerPath':f'/models/rfdetr-{size}/rfdetr-{size}.onnx',
        'artifactLockSha256':digest(lock_path),'buildReceiptSha256':build_hash,
        'qualityReceipts':quality,'qualification':'Target-device FP16 corpus quality; native pipeline qualification remains separate.'}


def _traffic_model(root, device):
    """Pinned experimental Spark artifact; not the RF-DETR qualification gate."""
    if device != 'spark':
        raise ProfileError('TrafficCamNet experimental selection is currently Spark-only')
    root = Path(root).resolve(); directory = _directory(root, device)
    lock_path = root/'tools/smart-city/artifacts.lock.json'
    try: lock = json.loads(lock_path.read_text())['trafficCamNetTransformer']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProfileError('TrafficCamNet artifact lock unavailable') from exc
    engine = _controlled(directory/'models/trafficcamnet-transformer-r18-fp16-b2.engine', directory)
    graph = _controlled(directory/'models/trafficcamnet-transformer-r18/model.onnx', directory)
    build_path = _controlled(directory/'models/trafficcamnet-transformer-r18/build-receipt.json', directory)
    positive_path = _controlled(directory/'models/trafficcamnet-transformer-r18/positive-receipt.json', directory)
    if not engine.is_file() or not graph.is_file():
        raise ProfileError('TrafficCamNet engine/ONNX is not staged on this device')
    engine_hash = digest(engine); graph_hash = digest(graph)
    if graph_hash != lock.get('onnxSha256') or engine_hash != lock.get('sparkObservedEngineSha256'):
        raise ProfileError('TrafficCamNet staged artifacts do not match their pinned hashes')
    build = _json_file(build_path, directory); positive = _json_file(positive_path, directory)
    if (build.get('schemaVersion') != 'city.nvidia-isolated-engine-build.v1'
            or build.get('success') is not True or build.get('engineSha256') != engine_hash
            or build.get('onnxSha256') != graph_hash
            or positive.get('schemaVersion') != 'city.nvidia-positive-control.v1'
            or positive.get('success') is not True or positive.get('engineSha256') != engine_hash
            or positive.get('image') != build.get('image')):
        raise ProfileError('TrafficCamNet build/positive-control receipts do not match artifacts')
    adapter = _traffic_adapter(root, device)
    if adapter['buildImage'] != build.get('image'):
        raise ProfileError('TrafficCamNet adapter and engine were built against different images')
    return {'schemaVersion':'city.selected-model.v1','device':device,'size':TRAFFIC,
        'name':'NVIDIA TrafficCamNet Transformer Lite R18','resolution':None,
        'enginePath':str(engine),'onnxPath':str(graph),'engineSha256':engine_hash,'onnxSha256':graph_hash,
        'modelRevision':f'trafficcamnet-transformer-r18-fp16@sha256:{engine_hash}',
        'engineContainerPath':f'/models/{engine.name}',
        'onnxContainerPath':'/models/trafficcamnet-transformer-r18/model.onnx',
        'artifactLockSha256':digest(lock_path),'buildReceiptSha256':digest(build_path),
        'positiveReceiptSha256':digest(positive_path),
        'adapterReceiptSha256':adapter['receiptSha256'], 'adapterImage':adapter['buildImage'], 'adapterMounts':adapter['mounts'],
        'supportedClasses':['person','car','two-wheeler'],
        'qualification':'Experimental Spark simulation: matched detector evaluation and isolated TensorRT positive control; native pipeline/tracking qualification remains separate.'}


def _traffic_adapter(root, device):
    directory = _directory(root, device)
    base = _controlled(directory/'runtime/trafficcam-adapter-20261026', directory)
    receipt_path = _controlled(base/'receipt.json', directory)
    receipt = _json_file(receipt_path, directory)
    hashes = receipt.get('fileHashes')
    if (receipt.get('schemaVersion') != 'city.trafficcam-adapter.v1'
            or receipt.get('success') is not True or not isinstance(hashes, dict)
            or set(hashes) != set(ADAPTER_FILES)):
        raise ProfileError('TrafficCamNet adapter receipt is invalid')
    mounts = []
    for name in ADAPTER_FILES:
        path = _controlled(base/name, directory)
        if not path.is_file() or digest(path) != hashes[name]:
            raise ProfileError('TrafficCamNet adapter artifact changed or is missing')
        mounts.append({'hostPath':str(path),'containerPath':f'/opt/city/{name}'})
    return {'receiptSha256':digest(receipt_path),'buildImage':receipt.get('buildImage'),'mounts':mounts}


def _model(root, device, size):
    return _traffic_model(root, device) if size == TRAFFIC else _qualified_model(root, device, size)


def selected_model(root, device):
    """Return current qualified artifacts, or raise; never silently fall back."""
    size=selection_name(root,device);profile=_model(root,device,size)
    directory=_directory(root,device);selection=directory/'state/model-selection.json'
    if selection.exists():
        pinned=_json_file(selection,directory)
        if pinned.get('engineSha256') != profile['engineSha256'] or pinned.get('modelRevision') != profile['modelRevision']:
            raise ProfileError('Selected engine changed; explicitly reselect after its qualification')
        if size == TRAFFIC and pinned.get('adapterReceiptSha256') != profile['adapterReceiptSha256']:
            raise ProfileError('Selected TrafficCamNet adapter changed; explicitly reselect it')
    profile['selectionSource']='explicit' if selection.exists() else 'default-small'
    return profile


def select_model(root, device, size):
    """Persist only a qualified size; this does not start or switch a worker."""
    profile=_model(root,device,size);directory=_directory(root,device)
    path=_controlled(directory/'state/model-selection.json',directory)
    selection={'schemaVersion':'city.model-selection.v1','device':device,'size':size,
        'engineSha256':profile['engineSha256'],'modelRevision':profile['modelRevision'],
        'selectedAt':datetime.now(timezone.utc).isoformat()}
    if size == TRAFFIC:
        selection['adapterReceiptSha256'] = profile['adapterReceiptSha256']
    _atomic_bytes(path,(json.dumps(selection,indent=2)+'\n').encode())
    profile['selectionSource']='explicit'
    return profile


def _ini_bytes(path, changes):
    parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str
    parser.read_string(path.read_text())
    for section, options in changes.items():
        if not parser.has_section(section):raise ProfileError(f'Missing native config section {section}')
        for key,value in options.items():parser.set(section,key,str(value))
    output=io.StringIO();parser.write(output,space_around_delimiters=False)
    return output.getvalue().encode()


def _materialize(root, device, profile):
    root=Path(root).resolve();directory=_directory(root,device)
    name=f"{profile['size']}-{profile['engineSha256'][:12]}"
    target=_controlled(directory/'state/model-config'/name,directory)
    source=root/'services/rtvi/rt-cv/smart-city/configs';container=f'/state/model-config/{name}'
    if (source/'labels.txt').read_text().splitlines() != CLASSES:
        raise ProfileError('Native labels differ from the qualified six-class contract')
    resolution=profile['resolution']
    infer_changes={'model-engine-file':profile['engineContainerPath'],'onnx-file':profile['onnxContainerPath'],
                   'labelfile-path':f'{container}/labels.txt','batch-size':2,'num-detected-classes':6}
    prep_changes={'network-input-shape':f'2;3;{resolution};{resolution}',
                  'processing-width':resolution,'processing-height':resolution}
    if profile['size'] == TRAFFIC:
        infer_changes.update({'parse-bbox-func-name':'NvDsInferParseCityTrafficCamNet',
                              'output-blob-names':'pred_logits;pred_boxes', 'num-detected-classes':7,
                              'maintain-aspect-ratio':1})
        prep_changes.update({'network-input-shape':'2;3;544;960','processing-width':960,
            'processing-height':544,'tensor-name':'inputs','maintain-aspect-ratio':1,
            'symmetric-padding':0,'custom-tensor-preparation-function':'CustomTrafficCamTensorPreparation'})
    generated={
        'infer.ini':_ini_bytes(source/'infer.ini',{'property':infer_changes}),
        'preprocess.ini':_ini_bytes(source/'preprocess.ini',{'property':prep_changes}),
        **{name:(source/name).read_bytes() for name in ('labels.txt','tracker.yml','analytics.ini')}}
    if profile['size'] == TRAFFIC:
        generated['labels.txt'] = ('\n'.join([*CLASSES, 'two-wheeler']) + '\n').encode()
    target.mkdir(parents=True,exist_ok=True)
    for filename,data in generated.items():
        path=_controlled(target/filename,directory)
        if not path.is_file() or path.read_bytes()!=data:_atomic_bytes(path,data)
    manifest={**profile,'configDir':container,'nativeFlag':'--model-revision',
        'sourceConfigSha256':{name:digest(source/name) for name in generated},
        'generatedFileSha256':{name:hashlib.sha256(data).hexdigest() for name,data in generated.items()}}
    manifest_path=_controlled(target/'model-profile.json',directory)
    _atomic_bytes(manifest_path,(json.dumps(manifest,indent=2)+'\n').encode())
    return {**profile,'hostConfigDir':str(target),'configDir':container,
        'configManifest':str(manifest_path),
        'nativeArgs':['--config-dir',container,'--model-revision',profile['modelRevision']]}


def config_for_launch(root, device):
    """Materialize selected configs and return their exact container arguments."""
    return _materialize(root,device,selected_model(root,device))


def config_for_model(root, device, size):
    """Prepare a qualified candidate for a bounded test without selecting it."""
    profile=_model(root,device,size);profile['selectionSource']='candidate-test'
    return _materialize(root,device,profile)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--device',choices=['spark','thor'],default='spark')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('show');generate=sub.add_parser('config')
    generate.add_argument('--size',choices=SELECTIONS,help='Prepare a test candidate without changing the current selection')
    pick=sub.add_parser('select');pick.add_argument('size',choices=SELECTIONS)
    args=parser.parse_args()
    if args.command=='select':result=select_model(args.root,args.device,args.size)
    elif args.command=='config':
        result=config_for_model(args.root,args.device,args.size) if args.size else config_for_launch(args.root,args.device)
    else:result=selected_model(args.root,args.device)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
