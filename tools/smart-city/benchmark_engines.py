#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate RF-DETR TensorRT prediction sets and measure standalone engine latency.

Run inside the pinned DeepStream container after acquiring the GPU work slot.
This measures one repeated real input image, not dataset accuracy or video latency.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from typing import Any

CITY_SLOTS = {1: 'person', 2: 'bicycle', 3: 'car', 4: 'motorcycle', 6: 'bus', 8: 'truck'}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_outputs(path: Path) -> dict[str, Any]:
    import numpy as np
    result = {}
    for output in json.loads(path.read_text()):
        dimensions = tuple(int(v) for v in str(output['dimensions']).split('x'))
        value = np.asarray(output['values'], dtype=np.float32)
        if value.size != math.prod(dimensions):
            raise ValueError(f"Invalid output size for {output['name']}")
        result[output['name']] = value.reshape(dimensions)
    if set(result) != {'dets', 'labels'}:
        raise ValueError('RF-DETR outputs must be named dets and labels')
    return result


def detections(boxes, logits, threshold: float = .35) -> list[dict[str, Any]]:
    import numpy as np
    if boxes.ndim != 2 or boxes.shape[1] != 4 or logits.ndim != 2 or logits.shape[0] != boxes.shape[0] or logits.shape[1] != 91:
        raise ValueError('Expected sparse COCO RF-DETR query x 4 / query x 91 tensors')
    if not np.isfinite(boxes).all() or not np.isfinite(logits).all():
        raise ValueError('Non-finite RF-DETR output')
    probabilities = np.exp(-np.logaddexp(0., -logits))
    # Stable tie order matches the native parser's deterministic diagnostic order.
    selected = np.argsort(-probabilities.ravel(), kind='stable')[:300]
    result = []
    for index in selected:
        query, slot = divmod(int(index), 91)
        score = float(probabilities.ravel()[index])
        if score < threshold or slot not in CITY_SLOTS:
            continue
        cx, cy, width, height = map(float, boxes[query])
        if width <= 0 or height <= 0:
            raise ValueError('Selected positive detection has invalid box geometry')
        result.append({'query': query, 'cocoSlot': slot, 'class': CITY_SLOTS[slot], 'score': score,
                       'boxCxCyWh': [cx, cy, width, height],
                       'boxXyxy': [max(0., cx - width / 2), max(0., cy - height / 2),
                                   min(1., cx + width / 2), min(1., cy + height / 2)]})
    return result


def iou(a: list[float], b: list[float]) -> float:
    intersection = max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))
    union = max(0., a[2] - a[0]) * max(0., a[3] - a[1]) + max(0., b[2] - b[0]) * max(0., b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.


def compare_outputs(reference: dict[str, Any], actual: dict[str, Any], batch: int,
                    threshold: float = .35, minimum_iou: float = .9, maximum_score_error: float = .03) -> dict[str, Any]:
    import numpy as np
    raw = {}
    for name in ('dets', 'labels'):
        expected = np.repeat(reference[name], batch, axis=0)
        observed = actual[name]
        if observed.shape != expected.shape or not np.isfinite(observed).all():
            raise ValueError(f'{name}: wrong output shape or non-finite values')
        errors = np.abs(observed.astype(np.float64) - expected)
        raw[name] = {'maxAbsoluteError': float(errors.max()), 'meanAbsoluteError': float(errors.mean()),
                     'p95AbsoluteError': float(np.percentile(errors, 95)),
                     'elementwiseAllcloseAtol0_002Rtol0_001': bool(np.allclose(observed, expected, atol=.002, rtol=.001))}
    samples = []
    passed = True
    for index in range(batch):
        expected = detections(reference['dets'][0], reference['labels'][0], threshold)
        observed = detections(actual['dets'][index], actual['labels'][index], threshold)
        if not expected or not observed:
            raise ValueError('Real traffic positive control produced no city detections')
        # Class-restricted maximum-IoU bipartite assignment. Query number is not
        # object identity; FP16 encoder top-k can change query ordering.
        from scipy.optimize import linear_sum_assignment
        scores = np.asarray([[iou(a['boxXyxy'], b['boxXyxy']) if a['cocoSlot'] == b['cocoSlot'] else -1.
                              for b in observed] for a in expected])
        ref_indices, obs_indices = linear_sum_assignment(-scores)
        matches = []
        for a, b in zip(ref_indices, obs_indices):
            ref, obs = expected[int(a)], observed[int(b)]
            score_error = abs(ref['score'] - obs['score'])
            valid = bool(scores[a, b] >= minimum_iou and score_error <= maximum_score_error)
            matches.append({'class': ref['class'], 'referenceQuery': ref['query'], 'engineQuery': obs['query'],
                            'iou': float(scores[a, b]), 'scoreAbsoluteError': score_error,
                            'boxMaximumAbsoluteError': max(abs(x-y) for x, y in zip(ref['boxCxCyWh'], obs['boxCxCyWh'])),
                            'passed': valid})
        sample_passed = len(expected) == len(observed) == len(matches) and all(m['passed'] for m in matches)
        passed &= sample_passed
        samples.append({'sampleIndex': index, 'referenceDetections': len(expected), 'engineDetections': len(observed),
                        'referenceClasses': sorted({d['class'] for d in expected}),
                        'engineClasses': sorted({d['class'] for d in observed}),
                        'matches': matches, 'passed': sample_passed})
    return {'batch': batch, 'finite': True, 'rawTensorDiagnostics': raw, 'predictionSetSamples': samples,
            'gates': {'confidenceThreshold': threshold, 'sameSelectedDetectionCount': True,
                      'classRestrictedMatching': True, 'minimumMatchedIoU': minimum_iou,
                      'maximumMatchedScoreAbsoluteError': maximum_score_error},
            'passed': bool(passed),
            'scope': 'One repeated real image; finite outputs and class/IoU/score prediction-set agreement, not tensor equality or dataset accuracy'}


def summarize_times(records: list[dict[str, Any]]) -> dict[str, Any]:
    import numpy as np
    if not records:
        raise ValueError('TensorRT exported no timing samples')
    result = {'sampleCount': len(records)}
    for key in ('computeMs', 'latencyMs', 'h2dMs', 'd2hMs'):
        values = np.asarray([r[key] for r in records], dtype=np.float64)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f'Invalid timing values: {key}')
        result[key] = {'mean': float(values.mean()), 'p50': float(np.percentile(values, 50)),
                       'p95': float(np.percentile(values, 95)), 'minimum': float(values.min()),
                       'maximum': float(values.max())}
    return result


def available_gib() -> float:
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) / (1024 * 1024)
    raise RuntimeError('Cannot read available memory before GPU allocation')


def command_output(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    return (result.stdout + result.stderr).strip()


def run_trtexec(command: list[str], output: Path, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    started_utc = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    output.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'trtexec failed; inspect {output}')
    return {'command': command, 'startedUtc': started_utc, 'endedUtc': datetime.now(timezone.utc).isoformat(),
            'wallSeconds': time.perf_counter() - started, 'log': str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--golden', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--model-name', required=True)
    parser.add_argument('--batches', default='1,2')
    parser.add_argument('--input-name', default='input')
    parser.add_argument('--precision', default='fp16')
    parser.add_argument('--warmup-ms', default=5000, type=int)
    parser.add_argument('--duration-seconds', default=10, type=int)
    parser.add_argument('--image-id', default='unresolved')
    parser.add_argument('--memory-reserve-gib', default=20, type=float)
    parser.add_argument('--parity-only', action='store_true')
    parser.add_argument('--trtexec', default=shutil.which('trtexec') or '/usr/src/tensorrt/bin/trtexec')
    args = parser.parse_args()
    import numpy as np
    reference = dict(np.load(args.golden))
    batches = [int(b) for b in args.batches.split(',')]
    if set(reference) != {'input', 'dets', 'labels'} or reference['input'].dtype != np.float32 or reference['input'].shape[0] != 1:
        raise ValueError('Golden artifact must contain FP32 input and one-frame dets/labels')
    if any(b not in (1, 2) for b in batches) or args.warmup_ms < 0 or args.duration_seconds < 1:
        raise ValueError('Use batches one/two and valid measurement durations')
    memory = available_gib()
    if memory < args.memory_reserve_gib:
        raise RuntimeError(f'Available {memory:.2f} GiB is below saved {args.memory_reserve_gib} GiB reserve')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_snapshot = args.output_dir / 'benchmark-source.py'
    shutil.copy2(Path(__file__), source_snapshot)
    source_receipt = args.golden.parent / 'parity-receipt.json'
    receipt = {'schemaVersion': 'city.engine-benchmark.v1', 'model': args.model_name,
               'engine': str(args.engine), 'engineSha256': sha256(args.engine),
               'golden': str(args.golden), 'goldenSha256': sha256(args.golden),
               'benchmarkSourceSha256': sha256(Path(__file__)), 'benchmarkSourceSnapshot': str(source_snapshot),
               'imageId': args.image_id, 'timingValid': False,
               'cudaLibraryPath': os.environ.get('LD_LIBRARY_PATH', ''),
               'declaredBuildPrecision': args.precision, 'inputDtype': 'float32', 'captureFormat': 'trtexec FP32-valued JSON output export',
               'gpu': command_output(['nvidia-smi', '--query-gpu=name,driver_version,uuid', '--format=csv,noheader']),
               'operatingStateBefore': command_output(['nvidia-smi', '--query-gpu=clocks.current.sm,temperature.gpu,power.draw,power.limit,utilization.gpu', '--format=csv,noheader']),
               'tensorRTPackage': command_output(['dpkg-query', '-W', '-f=${Version}', 'libnvinfer10']),
               'cudaToolkit': command_output(['/usr/local/cuda/bin/nvcc', '--version']),
               'platform': platform.platform(), 'memoryBeforeGiB': memory,
               'savedMemoryReserveGiB': args.memory_reserve_gib,
               'referenceToOnnxReceipt': json.loads(source_receipt.read_text()) if source_receipt.exists() else None,
               'measurementContext': 'Other VSS model services may be loaded; coordinated serial benchmark with no concurrent inference requested.',
               'parity': [], 'benchmarks': [], 'passed': False,
               'scope': 'Standalone engine on one repeated real video frame; excludes decode, preprocessing, tracking, analytics, transport and display; no dataset accuracy or Thor qualification.'}
    receipt_path = args.output_dir / 'receipt.json'
    try:
        for batch in batches:
            memory = available_gib()
            if memory < args.memory_reserve_gib:
                raise RuntimeError('Saved memory reserve no longer available')
            input_data = np.repeat(reference['input'], batch, axis=0)
            input_path = args.output_dir / f'input-b{batch}.bin'
            input_data.tofile(input_path)
            shape = 'x'.join(map(str, input_data.shape))
            common = [args.trtexec, f'--loadEngine={args.engine}', f'--shapes={args.input_name}:{shape}',
                      f'--loadInputs={args.input_name}:{input_path}', '--infStreams=1']
            output_path = args.output_dir / f'outputs-b{batch}.json'
            parity_run = run_trtexec(common + ['--iterations=1', '--duration=0', '--warmUp=0',
                                                f'--exportOutput={output_path}'], args.output_dir / f'parity-b{batch}.log', 120)
            comparison = compare_outputs(reference, read_outputs(output_path), batch)
            comparison['run'] = parity_run
            comparison['outputSha256'] = sha256(output_path)
            comparison['inputSha256'] = sha256(input_path)
            receipt['parity'].append(comparison)
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            if not comparison['passed']:
                raise RuntimeError(f'FP16 prediction-set consistency failed for batch {batch}; see {receipt_path}')
            if not args.parity_only:
                times = args.output_dir / f'timings-b{batch}.json'
                run = run_trtexec(common + [f'--warmUp={args.warmup_ms}', f'--duration={args.duration_seconds}',
                    '--iterations=1', f'--exportTimes={times}'], args.output_dir / f'benchmark-b{batch}.log',
                    args.warmup_ms / 1000 + args.duration_seconds + 120)
                summary = summarize_times(json.loads(times.read_text()))
                summary.update({'batch': batch, 'inputShape': list(input_data.shape),
                                'warmupMilliseconds': args.warmup_ms, 'minimumMeasurementSeconds': args.duration_seconds,
                                'dataTransfersEnabled': True, 'cudaGraph': False, 'inferenceStreams': 1,
                                'run': run, 'timingsSha256': sha256(times), 'inputSha256': sha256(input_path)})
                log = (args.output_dir / f'benchmark-b{batch}.log').read_text()
                match = re.search(r'Throughput:\s*([0-9.]+)\s*qps', log)
                summary['inferencesPerSecond'] = float(match.group(1)) if match else None
                summary['imagesPerSecond'] = summary['inferencesPerSecond'] * batch if match else None
                receipt['benchmarks'].append(summary)
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        receipt['passed'] = True
        receipt['timingValid'] = bool(receipt['benchmarks'])
    except Exception as exc:
        receipt['failure'] = str(exc)
        raise
    finally:
        receipt['memoryAfterGiB'] = available_gib()
        receipt['operatingStateAfter'] = command_output(['nvidia-smi', '--query-gpu=clocks.current.sm,temperature.gpu,power.draw,power.limit,utilization.gpu', '--format=csv,noheader'])
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(receipt_path), 'passed': receipt['passed'],
                      'benchmarks': [{'batch': b['batch'], 'sampleCount': b['sampleCount'],
                                      'computeMs': b['computeMs'], 'latencyMs': b['latencyMs']} for b in receipt['benchmarks']]}, indent=2))


if __name__ == '__main__':
    main()
