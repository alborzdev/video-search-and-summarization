# Thor SpatialAI offline environment

This package proves that the SpatialAI data-utils dependency set used by the
local Thor qualification paths can be built reproducibly from artifacts that
already exist in Thor's pip cache. It does not deploy VSS, start containers or
services, access models, or use the Warehouse sample.

The environment is deliberately ephemeral. A successful run creates a private
temporary wheelhouse and Python 3.12 virtual environment, verifies them, emits
a receipt, and removes the temporary tree. It never puts wheel binaries in this
repository and does not modify the source cache.

## Contract

`lock.json` records the complete 56-wheel closure selected for Linux AArch64,
CPython 3.12. Every artifact has a canonical wheel filename, byte length,
SHA-256, embedded `METADATA` SHA-256, dist-info identity, purelib flag, and wheel
tags. Cache lookup is path-independent: the materializer walks only configured
local cache roots and identifies candidates by size and content hash. Paths from
the machine that created the lock are not embedded in it.

The 23 roots come from the SpatialAI release dependency groups needed by the
qualification imports (base, evaluation, and visualization). The exact selected
versions are frozen in the artifact inventory. In particular, NumPy 1.26.4 and
Shapely 2.0.7 keep the nuScenes 1.2.0 constraints coherent. The repository
`Pipfile` currently names Python 3.13, while the release package permits Python
3.11 or newer; this qualification package intentionally targets Thor's system
CPython 3.12 and does not alter either declaration.

The schemas are fail-closed:

- `lock.schema.json` requires exactly 23 roots and 56 artifacts.
- `receipt.schema.json` accepts only a fully successful execution receipt.
- `producer-lock.json` binds the reviewed canonical producer, its four program
  files, seven tiny fixtures, 24 explicit product source controls, both canonical
  parity documents, a complete 252-file manifest of the product root, and a
  complete 14-file manifest of the producer root, including all tracked package
  data. The 303 lock rows cover 268 unique files.
  `producer-lock.schema.json` fixes their
  cardinalities and the all-seven accounting contract. Its binding commit must
  resolve to a real commit ancestor of the current checkout, and every locked
  file must have the same content hash in that commit and in the worktree.
- `integrated-receipt.schema.json` accepts only the combined all-seven success
  shape; the materializer additionally derives every aggregate and nested
  binding independently.
- `materializer.py` accepts only the canonical adjacent `lock.json`; an
  alternate copy cannot be substituted through `--lock`.

Receipt validation does not trust reported totals. It independently reconstructs
the wheelhouse count, byte total, inventory hash, installed-version count and
version hash from the canonical lock. The complete lock policy, confinement
policy, promotion policy, target, cleanup state, source inventory, lock, and
materializer bindings must match exactly. Runtime-only observations (the exact
cache-scan result and randomly created temporary-root identity) are supplied
directly by the executor to validation and are also covered by an execution
digest. The digest is an integrity binding, not a signature or claim of evidence
from an external trust authority.

## Safety boundaries

The default invocation is read-only and prints an inert plan:

```bash
python3 -I deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/materializer.py
```

Execution requires both `--execute` and the literal acknowledgement. Child
processes inherit an AArch64 seccomp filter that returns `EPERM` for all socket
syscalls. A Python startup guard independently rejects socket construction and
name resolution. The materializer probes both layers before creating the venv.
Pip additionally receives `--no-index`, a private `--find-links` wheelhouse,
`--no-deps`, `--only-binary=:all:`, `--require-hashes`, a null config file, a
disabled cache, and no proxy configuration. User site packages are disabled.

No Docker command, service lifecycle operation, model access, Warehouse sample
access, download, or package-index request is part of the code path. Cache and
work directories containing a `warehouse`, `model`, or `models` path component
are rejected.

Integrated mode also verifies the exact Git-tracked path sets under the entire
product and producer roots before the first product import. Its recursive
live-tree scan rejects
unlisted package data, untracked Python files, `.pyc`/`.pyo`, every native-module
suffix recognized by the running interpreter, any `__pycache__`, symlink, or
special file. Ignored caches elsewhere in the repository are outside this gate.

## Execute on Thor

Choose a new receipt path; publishing is exclusive and will not overwrite an
existing file:

```bash
python3 -I deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/materializer.py \
  --execute \
  --acknowledge I_ACKNOWLEDGE_EPHEMERAL_OFFLINE_SPATIAL_AI_ENV \
  --cache-root "$HOME/.cache/pip" \
  --work-parent /tmp \
  --output /tmp/thor-spatial-ai-offline-env-receipt.json
```

The work parent must exist, must be outside the repository, and must not be a
symlink. The output parent must already exist. The receipt is created mode 0600.

During a successful run the materializer:

1. Validates the lock, schemas, host ABI, repository boundary, and cache roots.
2. Finds all 56 exact cache bodies by size and SHA-256, validates their ZIP CRC,
   embedded metadata, and wheel tags, then copies them under canonical names.
3. Creates a CPython 3.12 venv and installs only those hashes with networking
   denied by the kernel.
4. Runs `pip check`, verifies all 56 installed versions, and imports the 18
   dependency and SpatialAI modules recorded in the lock.
5. Rehashes every source artifact, removes only its randomly named temporary
   tree, checks an adjacent sentinel, and emits the validated receipt.

The receipt is qualification evidence for this offline environment package. It
is explicitly not VSS runtime evidence and does not promote or mutate canonical
parity results or the existing runtime evidence producer.

## Integrated all-seven execution

The reviewed integrated mode builds the same private environment and then calls
only the adjacent canonical SpatialAI producer. The CLI intentionally exposes no
arbitrary command, producer path, contract path, partial selection, or dirty-tree
override. It always supplies all seven full capability IDs, uses the producer's
literal acknowledgement, inherits the kernel network-denial filter, and applies
a 930-second outer deadline around the producer's own 900-second product deadline.

Run it only from a completely clean committed checkout; the canonical producer
fails closed otherwise. The product and producer trees must also contain no
ignored bytecode/native-module shadows or other unlisted files. Direct CLI use
without Python isolated mode (`-I`) is rejected before any shadowable import:

```bash
python3 -I deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/materializer.py \
  --execute \
  --acknowledge I_ACKNOWLEDGE_EPHEMERAL_OFFLINE_SPATIAL_AI_ENV \
  --run-canonical-spatial-ai-producer \
  --producer-selection all \
  --producer-acknowledge I_ACKNOWLEDGE_OFFLINE_SPATIAL_AI_UTILS_RUNTIME_EVIDENCE \
  --cache-root "$HOME/.cache/pip" \
  --work-parent /tmp \
  --output /tmp/thor-spatial-ai-integrated-receipt.json
```

Success means exactly seven passing capabilities, 49 bounded actions, 49
requests, 76 imported product function calls, 14 independent positive runs, 35
rejected adjacent negatives, and zero network, Docker, service lifecycle, model,
download, Warehouse sample, product subprocess, or filesystem-escape activity.
The materializer independently validates the child schema and these values,
rehashes the complete producer/source/canonical lock before and after execution,
removes the materializer and producer temporary roots, then exclusively publishes
one mode-0600 integrated receipt outside the repository. The nested and combined
receipts remain explicitly non-promoting.

## Tests

The tests need no network or wheel downloads:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -I \
  deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/test_materializer.py
```

They cover canonical-lock enforcement, the 56-artifact invariant, all 303
producer-lock rows and both exact tracked root manifests, binding-commit ancestry and
blob identity, manifest omissions/additions, ignored bytecode and native-module
shadows, untracked code/data, symlinks and special files, opaque cache paths,
exact wheelhouse copying, hash drift, both network denial layers, the 930-second
timeout, cleanup after an injected failure, the exact all-seven child invocation,
aggregate and row mutation rejection, inert defaults, bounded CLI rules, secure
exclusive receipt publication, and the no-wheel-binaries repository rule.

## Lock maintenance

The lock is intentionally not refreshed at execution time. Updating it is a
separate reviewed operation: resolve the release dependency groups for the
target ABI, require that every selected wheel body already exists locally,
validate each wheel's embedded `METADATA` and `WHEEL` records, recompute all
hashes and canonical filenames, confirm `pip check` and the full import smoke in
an offline temporary venv, and review the resulting JSON diff. Never commit the
wheel bodies themselves.
