#!/usr/bin/env python3
"""Identify hardware from the host, rather than saved deployment variables."""
import json
from pathlib import Path
import platform
import subprocess


def identify(gpu_names, architecture):
    if architecture != 'aarch64':
        return 'unsupported'
    names = gpu_names.upper()
    if 'THOR' in names:
        return 'thor'
    if 'GB10' in names:
        return 'spark'
    return 'unsupported'


def inventory():
    result = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
                            check=True, capture_output=True, text=True, timeout=15)
    memory = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
              if line.startswith(('MemTotal:', 'MemAvailable:'))}
    model_path = Path('/proc/device-tree/model')
    release_path = Path('/etc/nv_tegra_release')
    return {'platform': identify(result.stdout, platform.machine()), 'architecture': platform.machine(),
            'gpu': result.stdout.strip(), 'kernel': platform.release(),
            'device_model': model_path.read_text().rstrip('\0') if model_path.exists() else None,
            'jetson_release': release_path.read_text().splitlines()[0] if release_path.exists() else None,
            'total_gib': round(memory['MemTotal'] / 1048576, 3),
            'available_gib': round(memory['MemAvailable'] / 1048576, 3)}


if __name__ == '__main__':
    print(json.dumps(inventory(), indent=2))
