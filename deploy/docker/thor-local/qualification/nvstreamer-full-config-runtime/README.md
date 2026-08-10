# NvStreamer complete-configuration Thor qualifier

This package closes `configuration.nvstreamer.full-contract` against the
official VSS 3.2.1 NvStreamer table. The pinned contract enumerates all 151
documented parameters in the seven advertised sections. The executor verifies
that every key is consumed by the current VIOS parser, derives a local-only
configuration carrying every key explicitly, starts the exact offline arm64
Thor image, reads configuration back through five live service APIs, performs
a reversible STUN configuration round trip, checks startup readback markers,
and restores the exact prior Docker and port state.

Run the static checks:

```bash
pytest -q deploy/docker/thor-local/qualification/nvstreamer-full-config-runtime/tests
```

Run the bounded runtime transaction:

```bash
python3 deploy/docker/thor-local/qualification/nvstreamer-full-config-runtime/execute.py \
  --execute \
  --output deploy/docker/thor-local/qualification/nvstreamer-full-config-runtime/runtime-receipt.json
```

The transaction is loopback-only, installs and downloads nothing, does not use
the warehouse sample bundle, does not add a sensor to the main VIOS or RT-CV
deployment, and never calls the VSS Agent generation endpoint.

The retained `runtime-receipt.json` and `official-runtime-evidence.json` are
the successful current-Thor execution and its capability-oracle projection.
See `EVIDENCE.md` for the tested image identity, results, cleanup proof, and
immutable hashes.
