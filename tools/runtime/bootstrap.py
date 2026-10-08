#!/usr/bin/env python3
"""Select the deployment helper using the current host's GPU identity."""
import os
from pathlib import Path
import sys

from platforms import inventory


def main():
    hardware = inventory()
    selected = hardware['platform']
    if selected not in ('spark', 'thor'):
        raise RuntimeError(f'No deployment profile for {hardware["gpu"]} on {hardware["architecture"]}')
    helper = Path(__file__).resolve().parents[1] / selected / 'bootstrap.py'
    print(f'Using {selected} deployment profile ({hardware["gpu"]}).', flush=True)
    os.execv(sys.executable, [sys.executable, str(helper), *sys.argv[1:]])


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
