"""Bounded, CPU-only provenance comparisons; never downloads full checkpoints.

Checks Preview modelv2 samples against the cached FP8 checkpoint. It also
compares moondream-next's remote PT storage CRCs with locally computed CRCs
of the cached 3.1 safetensors payloads. The remote ZIP metadata is inspected
without executing pickle globals. Network response bodies are capped at
16 MiB/request and 50 MiB for the entire invocation.
"""

import argparse
from collections import OrderedDict
import datetime
import io
import json
import os
from pathlib import Path
import pickle
import struct
import sys
import urllib.request
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark/moondream-photon'
PREVIEW_REVISION = '5112966d1a723413b1c9a1e8bea272b72e647b35'
NEXT_REVISION = 'a5b63b4e19d1be4ae8dbd1d02b2bde864cc09913'


class BoundedHTTP:
    def __init__(self):
        self.bytes_read = 0
        self.requests = []

    def read(self, url, *, start=None, length=None):
        limit = 1024 * 1024 if length is None else length
        if limit > 16 * 1024**2 or self.bytes_read + limit > 50 * 1024**2:
            raise RuntimeError('Network byte budget exceeded')
        headers = {} if start is None else {'Range': f'bytes={start}-{start + length - 1}'}
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            if start is not None:
                expected = f'bytes {start}-{start + length - 1}/'
                if response.status != 206 or not response.headers.get('Content-Range', '').startswith(expected):
                    raise RuntimeError('Server did not honor the exact requested byte range')
            data = response.read(limit + 1)
        if len(data) > limit or (length is not None and len(data) != length):
            raise RuntimeError('Response exceeded its limit or returned an incomplete range')
        self.bytes_read += len(data)
        self.requests.append({'url': url, 'start': start, 'length': len(data)})
        return data

    def json(self, url):
        return json.loads(self.read(url))


class RemoteZipFile(io.RawIOBase):
    def __init__(self, http, url, size):
        self.http, self.url, self.size, self.position = http, url, size, 0

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if not 0 <= self.position <= self.size:
            raise ValueError('Invalid remote ZIP position')
        return self.position

    def tell(self):
        return self.position

    def read(self, length=-1):
        length = self.size - self.position if length < 0 else min(length, self.size - self.position)
        if length <= 0:
            return b''
        data = self.http.read(self.url, start=self.position, length=length)
        self.position += length
        return data


def _tensor(storage, offset, shape, stride, requires_grad, backward_hooks, *extra):
    dtype = extra[0] if extra and isinstance(extra[0], tuple) else storage['dtype']
    return {'storage': storage, 'offset': offset, 'shape': list(shape),
            'stride': list(stride), 'dtype': dtype}


class MetadataOnlyUnpickler(pickle.Unpickler):
    """Accept only inert storage descriptors and tensor metadata constructors."""
    def find_class(self, module, name):
        allowed = {
            ('collections', 'OrderedDict'): OrderedDict,
            ('torch', 'BFloat16Storage'): ('BF16', 2),
            ('torch', 'FloatStorage'): ('F32', 4),
            ('torch', 'BoolStorage'): ('BOOL', 1),
            ('torch', 'float8_e4m3fn'): ('F8_E4M3', 1),
            ('torch.storage', 'UntypedStorage'): ('U8', 1),
            ('torch._utils', '_rebuild_tensor_v2'): _tensor,
            ('torch._utils', '_rebuild_tensor_v3'): _tensor,
        }
        if (module, name) not in allowed:
            raise pickle.UnpicklingError(f'Unrecognized pickle global: {module}.{name}')
        return allowed[module, name]

    def persistent_load(self, pid):
        if len(pid) != 5 or pid[0] != 'storage' or not isinstance(pid[1], tuple):
            raise pickle.UnpicklingError('Unexpected persistent storage descriptor')
        return {'dtype': pid[1], 'key': str(pid[2]), 'size': int(pid[4])}


def remote_safetensors_header(http, url):
    size = struct.unpack('<Q', http.read(url, start=0, length=8))[0]
    if size > 1024**2:
        raise RuntimeError('Safetensors header is larger than the allowed metadata size')
    return size + 8, json.loads(http.read(url, start=8, length=size))


def local_safetensors_header(path):
    with path.open('rb') as source:
        size = struct.unpack('<Q', source.read(8))[0]
        return size + 8, json.loads(source.read(size))


def compare_preview(http):
    import torch
    checkpoint = Path((STATE / 'preview-model-path.txt').read_text().strip())
    weights = torch.load(checkpoint, map_location='cpu', weights_only=True, mmap=True)
    base = f'https://huggingface.co/moondream/moondream3-preview/resolve/{PREVIEW_REVISION}/'
    index = http.json(base + 'model.safetensors.index.json')['weight_map']
    headers = {name: remote_safetensors_header(http, base + name)
               for name in sorted(set(index.values()))}
    shards = []
    for name, (offset, header) in headers.items():
        size = offset + max(value['data_offsets'][1] for key, value in header.items() if key != '__metadata__')
        shards.append({'filename': name, 'bytes': size})
    pairs = {
        'model.region.ln.weight': 'region_model.ln.weight',
        'model.region.ln.bias': 'region_model.ln.bias',
        'model.region.coord_encoder.bias': 'region_model.coordinate_encoder.bias',
        'model.text.blocks.4.mlp.router.bias': 'text_model.transformer.h.4.gate.bias',
        'model.text.post_ln.weight': 'text_model.lm_head.ln.weight',
        'model.text.lm_head.bias': 'text_model.lm_head.linear.bias',
    }
    direct = []
    for key, local_key in pairs.items():
        filename = index[key]
        offset, header = headers[filename]
        first, last = header[key]['data_offsets']
        data = http.read(base + filename, start=offset + first, length=last - first)
        tensor = torch.frombuffer(bytearray(data), dtype=torch.bfloat16).reshape(header[key]['shape'])
        cached = weights[local_key].to(torch.bfloat16)
        direct.append({'remote_key': key, 'local_key': local_key,
                       'shape': list(tensor.shape), 'equal': torch.equal(tensor, cached),
                       'max_absolute_difference': float((tensor.float() - cached.float()).abs().max())})
    rows = []
    for part, cached_part, scale_part, expert, row in (
        ('fc1', 'experts', 'up', 0, 0), ('fc1', 'experts', 'up', 0, 1024),
        ('fc1', 'experts', 'up', 63, 2047), ('fc2', 'output_experts', 'down', 0, 0),
        ('fc2', 'output_experts', 'down', 63, 2047),
    ):
        key = f'model.text.blocks.4.mlp.{part}.weight'
        filename = index[key]
        offset, header = headers[filename]
        descriptor = header[key]
        _, outputs, inputs = descriptor['shape']
        first = offset + descriptor['data_offsets'][0] + (expert * outputs + row) * inputs * 2
        data = http.read(base + filename, start=first, length=inputs * 2)
        tensor = torch.frombuffer(bytearray(data), dtype=torch.bfloat16)
        cached = weights[f'text_model.transformer.h.4.mlp.{cached_part}.weight'][expert, row]
        scale = weights[f'text_model.transformer.h.4.moe_quant.{scale_part}_scale'][expert, row].float()
        dequantized = cached.float() * scale
        requantized = (tensor.float() / scale).clamp(-448, 448).to(torch.float8_e4m3fn)
        rows.append({'remote_key': key, 'expert': expert, 'row': row, 'elements': inputs,
                     'requantized_bits_equal_fraction': float((requantized.view(torch.uint8) == cached.view(torch.uint8)).float().mean()),
                     'bf16_equals_dequantized_cached_fp8': torch.equal(tensor, dequantized.to(torch.bfloat16)),
                     'cosine': float(torch.nn.functional.cosine_similarity(tensor.float(), dequantized, dim=0)),
                     'cached_scale': float(scale)})
    return {'revision': PREVIEW_REVISION, 'local_checkpoint': str(checkpoint),
            'shards': shards, 'total_bf16_bytes': sum(item['bytes'] for item in shards),
            'direct_samples': direct, 'expert_row_samples': rows,
            'cuda_initialized': torch.cuda.is_initialized(),
            'limitation': 'Sampled tensor equality is not a comparison of every Preview tensor.'}


def compare_next(http):
    metadata = http.json(f'https://huggingface.co/api/models/moondream/moondream-next/revision/{NEXT_REVISION}?blobs=true')
    files = {item['rfilename']: item for item in metadata['siblings']}
    cached_manifest = json.loads((STATE / 'model-manifest.json').read_text())
    cached_file = next(item for item in cached_manifest['siblings'] if item['rfilename'] == 'model.safetensors')
    source = Path((STATE / 'model-path.txt').read_text().strip())
    result = {'revision': NEXT_REVISION, 'local_31_checkpoint': str(source),
              'next_safetensors_lfs_sha256': files['model.safetensors']['lfs']['sha256'],
              'cached_31_safetensors_lfs_sha256': cached_file['lfs']['sha256'],
              'same_advertised_safetensors_sha256': files['model.safetensors']['lfs']['sha256'] == cached_file['lfs']['sha256']}
    remote = RemoteZipFile(http,
                          f'https://huggingface.co/moondream/moondream-next/resolve/{NEXT_REVISION}/model.pt',
                          files['model.pt']['size'])
    archive = zipfile.ZipFile(remote)
    pickle_info = next(item for item in archive.infolist() if item.filename.endswith('/data.pkl'))
    tensors = MetadataOnlyUnpickler(io.BytesIO(archive.read(pickle_info))).load()
    prefix = pickle_info.filename.rsplit('/', 1)[0] + '/data/'
    offset, header = local_safetensors_header(source)
    names = {name for name in header if name != '__metadata__'}
    result.update(remote_pt_tensors=len(tensors), local_safetensors_tensors=len(names),
                  missing_local_names=sorted(set(tensors) - names),
                  missing_remote_names=sorted(names - set(tensors)))
    matches, differences, skipped, local_bytes = [], [], [], 0
    with source.open('rb') as data_file:
        for name, tensor in tensors.items():
            descriptor = header.get(name)
            if descriptor is None:
                continue
            storage = archive.getinfo(prefix + tensor['storage']['key'])
            first, last = descriptor['data_offsets']
            expected_stride, contiguous = 1, True
            for dimension, stride in zip(reversed(tensor['shape']), reversed(tensor['stride'])):
                contiguous &= stride == expected_stride
                expected_stride *= dimension
            if (tensor['offset'] != 0 or not contiguous or tensor['shape'] != descriptor['shape']
                    or tensor['dtype'][0] != descriptor['dtype'] or storage.file_size != last - first):
                skipped.append({'name': name, 'reason': 'layout_or_dtype_mismatch',
                                'remote': tensor, 'local': descriptor})
                continue
            data_file.seek(offset + first)
            remaining, crc = last - first, 0
            while remaining:
                chunk = data_file.read(min(remaining, 8 * 1024**2))
                if not chunk:
                    raise RuntimeError('Unexpected end of cached safetensors file')
                crc = zlib.crc32(chunk, crc)
                remaining -= len(chunk)
                local_bytes += len(chunk)
            (matches if crc == storage.CRC else differences).append(name)
    result.update(storage_crc_matches=len(matches), storage_crc_differences=differences,
                  skipped=skipped, local_payload_bytes_read=local_bytes,
                  remote_pt_advertised_sha256=files['model.pt']['lfs']['sha256'],
                  comparison='Remote ZIP central-directory CRC32 versus CRC32 computed from each local tensor payload.',
                  limitation='Remote PT tensor bodies and its complete SHA256 were not downloaded or independently verified. CRC32 is not a cryptographic proof.')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    # Disable CUDA before importing PyTorch, and discover this venv's ARM64
    # runtime libraries without importing torch or changing any installed file.
    if not os.environ.get('MOONDREAM_COMPARE_LIBS'):
        site = Path(sys.prefix) / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
        libraries = sorted({str(path) for name in ('nvidia', 'nvpl')
                            for path in (site / name).glob('**/lib') if path.is_dir()})
        os.environ.update(CUDA_VISIBLE_DEVICES='', MOONDREAM_COMPARE_LIBS='1',
                          LD_LIBRARY_PATH=':'.join(libraries))
        os.execv(sys.executable, [sys.executable, *sys.argv])
    available = next(int(line.split()[1]) / 2**20 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    reserve = json.loads((ROOT / '.spark/settings.json').read_text())['reserve_gib']
    if available < reserve + 2:
        raise SystemExit('Need 2 GiB above the saved reserve for CPU provenance inspection')
    http = BoundedHTTP()
    receipt = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'network_per_request_cap_bytes': 16 * 1024**2,
               'network_total_cap_bytes': 50 * 1024**2, 'gpu_tests': False}
    try:
        receipt['preview'] = compare_preview(http)
        receipt['next'] = compare_next(http)
    finally:
        receipt['network_response_body_bytes'] = http.bytes_read
        receipt['network_requests'] = http.requests
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(args.receipt.resolve()), 'network_bytes': http.bytes_read,
                      'network_requests': len(http.requests),
                      'next_crc_matches': receipt['next']['storage_crc_matches'],
                      'next_crc_differences': len(receipt['next']['storage_crc_differences']),
                      'next_skipped': len(receipt['next']['skipped'])}))


if __name__ == '__main__':
    main()
