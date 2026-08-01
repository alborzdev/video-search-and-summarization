# Advertised-entry executors: wave five

This isolated package checks the six `vios-codecs-audio` advertised-entry
gaps. It digest-locks the exact 87-entry gap plan, manifest, all four
predecessor inventories (8 + 21 + 23 + 5 entries), and every source or offline
package descriptor it reads. The six cases leave 24 plan entries without a
candidate executor.

The executor performs bounded C++ source-contract, structured VIOS JSON, exact
59-package ARM64 lock, and networkless-Dockerfile assertions. It does not
compile or import VIOS, execute a codec fixture, contact a service, open an
RTSP session, record media, run a CPU pipeline, invoke Docker, or create files.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave5/executor.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave5/tests \
  -p 'test_*.py' -v
```

Use `--list` to print exact IDs and repeat `--case <entry-id>` to run a bounded
subset.

## Boundary

Every observation is candidate-only static source and offline-package evidence.
Network, Docker, subprocesses, lifecycle actions, credentials, downloads, and
filesystem writes are forbidden. Results explicitly report no runtime
execution, codec-fixture proof, RTSP proof, recording proof, CPU-pipeline proof,
service readiness, runtime evidence, or official capability effect.

All six `runtime_codec_audio_matrix` oracles remain `open_unexecuted`. The
optional Warehouse sample bundle is neither used nor relevant. See
[EVIDENCE.md](EVIDENCE.md) for exact non-claims.
