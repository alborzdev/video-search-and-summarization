# Thor host preflight qualification

This directory provides a read-only readiness inventory for later Thor-local
VSS runtime qualification. It does **not** qualify a VSS feature or create
runtime evidence. It inventories the platform/BSP, memory, disk, Docker,
Compose, NVIDIA Container Toolkit, cgroup driver, kernel limits, cache cleaner,
required ports, existing container/image conflicts, and the exact official-edge
artifact/image blockers.

The default is an inert JSON plan. It executes no command and reads no host
file:

```bash
python3 deploy/docker/thor-local/qualification/host-preflight/preflight.py
```

After the operator explicitly chooses host inspection, use:

```bash
python3 deploy/docker/thor-local/qualification/host-preflight/preflight.py inspect
```

`inspect` remains read-only. Its command table is hard-coded in
`preflight.py`; each entry pins an absolute executable and its complete argv.
The runner rejects altered or additional arguments, uses no shell, clears the
ambient environment (including Docker/HF/NGC settings), supplies no input,
and caps time and output. Docker access is limited to `version`, `info`, `ps`,
`image ls`, and `compose version`. It cannot call a Compose application command
or any container/image lifecycle verb.
There are no network clients, credential readers, arbitrary paths, Docker
helpers, registry probes, or artifact downloads.

Host-file reads use a separate fixed key-to-path allowlist. Reports contain
parsed facts and SHA-256 evidence fingerprints rather than raw command/file
output. Credential-shaped keys and common token forms are redacted again at
the output boundary.

The official-edge section is deliberately fail-closed. It loads the exact
checked-in contract and artifact lock, compares local Docker inventory only
against exact digest/image identities, and reports that artifact filesystem
trees are unverified. It never searches caches or treats a similarly named
model as equivalent. Once reviewed exact artifact paths exist, the separate
`official-edge/official_edge.py audit` is still required.

Exit status is 0 for the inert plan or a ready inspection, 1 when inspection
finds a blocker, and 2 for invalid/unverified inspection. An occupied port is a
warning because it may be an intentionally running workload; named VSS/MDX
containers are reported as conflicts for operator review. The 150 GiB free-disk
threshold is the documented Thor warning, not the excluded Warehouse sample
bundle requirement.

Only mocked tests may exercise inspect mode during static qualification:

```bash
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/host-preflight/tests -v
```

Do not run `inspect` against a live host without explicit operator intent.
