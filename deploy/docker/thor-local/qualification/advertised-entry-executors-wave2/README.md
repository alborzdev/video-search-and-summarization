# Advertised-entry executors: wave two

This isolated package deterministically exercises a second, disjoint subset of
21 advertised-entry gaps. It consumes the exact 87-entry gap plan, anchors the
previous 8-entry candidate inventory, selects 21 of the prior 79 open entries,
and leaves 58 entries open.

The output is candidate-only evidence. It does not mark a capability
`passed_current`, mutate the live acceptance/oracle/runtime-lane files, or
claim that a service or model is deployable on Thor.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/executor.py
```

List or run exact cases:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/executor.py --list

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/executor.py \
  --case manifest-gap.rt-vlm-media.03-allowlisted-file-uri
```

Run the adversarial suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/tests \
  -p 'test_*.py' -v
```

## Safety boundary

Each case is bound to an exact manifest pointer, gap-plan identity, adapter,
and digest-locked source set. Selected AST definitions execute against
in-memory fixtures and fakes. Network, Docker, subprocesses, lifecycle work,
downloads, credentials, and filesystem writes are forbidden by policy.

Media URI, RTSP, dense-caption, incident, and reasoning results demonstrate
only the named request pattern, serializer, or helper contract. Sampling,
GOP, decoder, asset, and timestamp results demonstrate only the named source
helper. Synthetic-data cases do not modify USD, image, HDF5, video, or dataset
files.

Model-family cases cross-check exact checked-in model rows and README checkout
references. They deliberately retain unqualified statuses and set both
`availability_proven` and `readiness_proven` to false.

See [EVIDENCE.md](EVIDENCE.md) for the exact selection and exclusions.
