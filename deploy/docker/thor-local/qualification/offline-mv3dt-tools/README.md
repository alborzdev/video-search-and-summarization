# Offline MV3DT tool qualification

This package executes the two checked-in `mv3dt-config-utils` repository tools
against a tiny, code-authored two-camera calibration fixture:

- `tool.mv3dt.cam-info-generator`
- `tool.mv3dt.pub-sub-generator`

It is deliberately candidate-only. A successful observation does not change an
official capability or oracle, create runtime evidence, or prove the Warehouse
profile. The official Warehouse sample bundle is excluded. The accepted
boundary remains the alternate local custom-data lane, and these utilities are
non-Compose `repository-tooling` rather than a `warehouse-mv3dt` service.

The executor imports the source tools directly. It cannot invoke Docker or a
subprocess, open a network connection, download artifacts, access credentials,
load a model, or mutate a service. Its only writes are two isolated runs below a
fresh private temporary root. It removes the exact owned root, checks an
adjacent sentinel, and then removes the private parent.

Run the candidate observation and focused tests from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/offline-mv3dt-tools/executor.py

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/offline-mv3dt-tools/tests
```

`contract.json` locks the advertised entries, generator sources, dependency
declaration, fixture, execution inputs, and expected output-tree hashes. The
result additionally records the exact locally imported distribution versions.
Those observed versions are evidence about this candidate run, not a claim that
they equal the reviewed `requirements.txt` pins.
