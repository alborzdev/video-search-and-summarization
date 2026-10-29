#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stage the reviewed NVIDIA road baseline; no GPU allocation or stack mutation."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

MODEL = 'nvidia/tao/trafficcamnet_transformer_lite'
VERSION = 'deployable_resnet18_v2.0'
BASE = f'https://api.ngc.nvidia.com/v2/models/{MODEL}/versions/{VERSION}'
EXPECTED = {
    'resnet18_trafficcamnet_rtdetr.onnx': '869a317494552773e424ae2228135b3c111052804e22100cb43c0cb2639293c4',
    'resnet18_trafficcamnet_rtdetr.fp16.onnx': 'c533a2fb51994a7770dbdfb89c93582c91150043a239776ad4f17624d2cf2247',
}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--inspect-graph', action='store_true', help='Inspect graph with isolated ONNX package; never runs GPU inference')
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(urllib.request.urlopen(BASE + '/files', timeout=60).read())
    (args.directory / 'upstream-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    files = []
    for item in metadata['modelFiles']:
        name = item['path']
        if name not in (*EXPECTED, 'labels.txt', 'nvdsinfer_config.yaml'):
            continue
        expected = base64.b64decode(item['sha256_base64']).hex()
        if name in EXPECTED and expected != EXPECTED[name]:
            raise RuntimeError('Upstream model changed from reviewed hash')
        target = args.directory / name
        url = BASE + '/files/' + name
        if not target.exists():
            partial = target.with_suffix(target.suffix + '.partial')
            with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
            if digest(partial) != expected:
                partial.unlink(missing_ok=True)
                raise RuntimeError('NGC download checksum mismatch')
            partial.replace(target)
        if digest(target) != expected:
            raise RuntimeError('Cached NGC artifact checksum mismatch')
        files.append({'name': name, 'path': str(target), 'url': url, 'sha256': expected, 'bytes': target.stat().st_size})
    notice = 'Licensed by NVIDIA Corporation under the NVIDIA Open Model License\n'
    (args.directory / 'NOTICE.txt').write_text(notice)
    receipt = {'model': MODEL, 'version': VERSION, 'license': 'NVIDIA Open Model License Agreement',
        'licenseUrl': 'https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/',
        'modelCardUrl': 'https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/trafficcamnet_transformer_lite/-',
        'inputResolution': [544, 960], 'files': files, 'gpuUsed': False,
        'stage': 'downloaded; TensorRT plugin and positive-control qualification required before evaluation',
        'limitation': 'Four native classes; no independent bus/truck output. Not a six-class city replacement.'}
    if args.inspect_graph:
        import onnx
        graph = onnx.load(str(args.directory / 'resnet18_trafficcamnet_rtdetr.onnx'))
        def shape(value):
            return [d.dim_value if d.HasField('dim_value') else d.dim_param
                    for d in value.type.tensor_type.shape.dim]
        custom = sorted({f'{node.domain}:{node.op_type}' for node in graph.graph.node
                         if node.domain not in ('', 'ai.onnx')})
        receipt['graph'] = {'inputs': {v.name: shape(v) for v in graph.graph.input},
            'outputs': {v.name: shape(v) for v in graph.graph.output},
            'customOperators': custom, 'onnxVersion': onnx.__version__}
        receipt['cpuOnnxRuntimeCompatible'] = not bool(custom)
        receipt['nativeLabels'] = (args.directory / 'labels.txt').read_text().splitlines()
    (args.directory / 'stage-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
