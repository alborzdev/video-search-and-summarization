# Evidence

- Released image: `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1`
- Exact image ID: `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`
- Architecture: arm64
- Dynamic configuration: 24/24 NVIDIA scenarios passed
- Configuration wire contract: `upsert`, `upsert-all`, `ack`, and `request-config`
- Acknowledgements: `success`, `partial-success`, and `failure` observed
- Application: valid files landed atomically and all three watchdogs applied them
- Rejection: forbidden, malformed, invalid, and non-allowlisted updates did not land files
- Startup: full controller snapshot, empty failure reply, and 15-second no-reply disk fallback passed
- Dynamic calibration: 7/7 NVIDIA scenarios passed
- Calibration wire contract: `upsert-all`, `upsert`, and `delete`, with no acknowledgement
- Calibration rejection: three schema-invalid and one stale update left state unchanged
- Type selection: image → `CalibrationI` (2 sensors), Cartesian → `CalibrationE` (3), geo → `Calibration` (50)
- Immutable type: an image-tagged update to an existing Cartesian runtime stayed delegated to `CalibrationE`; zero type-switch markers appeared
- Exit integrity: every disposable probe exited 0, was not OOM-killed, and had restart count 0
- Cleanup: all disposable containers and qualification topics are absent; both normal consumers remain running

The receipt locks NVIDIA's official drivers and documentation, the released
implementation and atomic-write tests, the Thor wrapper/probes and fixtures,
the container identity, exact log digests, scenario totals, semantic outcomes,
and cleanup postconditions. No VSS Agent generation, external request, main
VIOS mutation, main RT-CV mutation, or 100 GB Warehouse sample occurred.
