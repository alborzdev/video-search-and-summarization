# Systems NvSchema JSON static executor

This isolated package exercises the checked-in product implementations behind the open `systems-nvschema-json` planning requirement and its canonical `protocol.nvschema.json-frame` capability and oracle.

It verifies three bounded, provider-free paths: the Behavior Analytics legacy 2D string-object JSON-to-Protobuf converter, the Spatial AI modern 3D dictionary-object JSONL loader, and the agent's NvSchema incident aliases. It also covers six adjacent negatives or explicitly accepted limitations. Imports of unrelated Behavior Analytics model dependencies are replaced with type-only stubs because the host's NumPy 2 / Matplotlib NumPy 1 ABI mismatch prevents collection of the full upstream Behavior Analytics unit module; the converter and generated Protobuf implementation themselves are real checked-in product code.

Run:

```bash
python3 deploy/docker/thor-local/qualification/systems-nvschema-json-static-executor/executor.py --json
python3 -m pytest -q deploy/docker/thor-local/qualification/systems-nvschema-json-static-executor/tests
```

The executor performs no network access, model calls, downloads, subprocesses, Docker or service lifecycle operations. Its only writes are two JSONL fixtures in executor-owned private temporary directories, and cleanup is verified after two independent deterministic runs. The Warehouse sample bundle is excluded.

A pass is deliberately non-advancing: it produces `candidate_static_pass_non_advancing`, leaves `runtime_evidence` empty, and does not change the canonical planning row, capability, or oracle from their open states.
