"""Small local compatibility probe. Does not download or load model weights."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import traceback

# ARM64 CUDA runtime wheels can need explicit library discovery.
if not os.environ.get('MOONDREAM_PROBE_LIBS'):
    site = Path(sys.prefix) / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    libs = sorted({str(p) for root in ('nvidia', 'nvpl') for p in (site / root).glob('**/lib') if p.is_dir()})
    os.environ['LD_LIBRARY_PATH'] = ':'.join(libs + [os.environ.get('LD_LIBRARY_PATH', '')])
    os.environ['MOONDREAM_PROBE_LIBS'] = '1'
    os.execv(sys.executable, [sys.executable, *sys.argv])

available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
settings = Path(__file__).resolve().parents[2] / '.spark/settings.json'
reserve = json.loads(settings.read_text())['reserve_gib']
if available < (reserve + 2) * 2**30:
    raise SystemExit('Not enough memory for the small probe above the saved Spark reserve.')
result = {'available_gib_before': available / 2**30, 'reserve_gib': reserve, 'weights_loaded': False, 'packages': {}}
for package in ('moondream', 'kestrel', 'kestrel-kernels', 'kestrel-native', 'torch'):
    result['packages'][package] = importlib.metadata.version(package)
try:
    import torch
    result['cuda_runtime'] = torch.version.cuda
    result['gpu'] = torch.cuda.get_device_name()
    result['capability'] = torch.cuda.get_device_capability()
    x = torch.ones((1, 2048), device='cuda', dtype=torch.bfloat16)
    result['torch_cuda_matmul'] = (x @ x.T).item()
    import moondream as md
    result['registered_models'] = md.photon_models()
    from kestrel_kernels.rmsnorm import rmsnorm
    y = rmsnorm(x, torch.ones(2048, device='cuda', dtype=torch.bfloat16), 1e-6)
    torch.cuda.synchronize()
    result['photon_rmsnorm'] = {'shape': list(y.shape), 'finite': bool(y.isfinite().all())}
except Exception:
    result['error'] = traceback.format_exc()
print(json.dumps(result, indent=2, default=str))
if 'error' in result:
    raise SystemExit(1)
