# Thor host-prerequisite evidence

This isolated package collects current, read-only evidence for exactly four
source-bound prerequisite pairs:

- `prereq.platform.validated-gpus` / `oracle.prereq.platform.validated-gpus`;
- `prereq.platform.agx-thor-software` / `oracle.prereq.platform.agx-thor-software`;
- `prereq.platform.toolchain-versions` / `oracle.prereq.platform.toolchain-versions`;
- `prereq.platform.capacity-and-access` / `oracle.prereq.platform.capacity-and-access`.

It does not edit the parity ledger, acceptance inventory, runtime lanes, or any
evidence receipt. It does not qualify a VSS application feature. A consumer
must separately review and integrate a passing record.

## Inert plan

The default executes no command and reads no host file:

```bash
python3 deploy/docker/thor-local/qualification/host-prerequisite-evidence/collector.py
```

The plan verifies the four selected oracle rows against their canonical hashes,
validates itself against `result.schema.json`, and lists only probe/source IDs.

## Read-only collection

Live inspection requires an exact acknowledgement:

```bash
python3 deploy/docker/thor-local/qualification/host-prerequisite-evidence/collector.py \
  inspect \
  --acknowledgement I_ACCEPT_READ_ONLY_HOST_PREREQUISITE_EVIDENCE
```

The collector executes a closed table of informational commands: `uname`,
`nvidia-smi`, Docker `version`, Docker Compose `version`, `nvidia-ctk
--version`, `ngc --version`, `getconf`, `df`, `lsblk`, `ip route get`, and
`ss`. Docker application/lifecycle verbs, Compose application commands,
network clients, registry requests, shell execution, arbitrary arguments, and
caller-selected paths are absent. The command environment removes ambient
credentials and points Docker/NGC configuration homes at `/nonexistent`.

NGC executable discovery is deferred until after the exact acknowledgement
and source-bound oracle validation. It checks only `/usr/bin/ngc` and
`/usr/local/bin/ngc`; the candidate must be a regular non-symlink, root-owned,
executable file that is not group/world-writable. User-home candidates are not
admitted. If neither system candidate is safe, the NGC observation is a
sanitized unknown. Import, plan mode, rejected acknowledgements, and source
drift do not stat an NGC candidate.

Three fixed files are read: the device-tree model, Tegra release, and
`/proc/meminfo`. Network capacity is summarized from `/sys/class/net` after
rejecting virtual interfaces, CAN, loopback, unsafe names, and paths outside
`/sys/devices`. The result never emits interface names, addresses, MACs, SSIDs,
raw command/file output, error text, hostnames, usernames, or timestamps.

Every emitted evidence object is validated against the raw-byte self-locked
strict Draft 2020-12 result schema. `evidence_sha256` covers the canonical
unsigned object. The same parsed observations and source contract therefore
produce byte-semantic equivalent evidence.

Exit status is 0 for the inert plan or four satisfied contracts, 1 for a known
contract failure, and 2 for unknown/invalid evidence. Operational headroom does
not change the contract exit result.

## Capacity semantics

Official `GB`/`TB` minimums use decimal SI bytes. The storage minimum requires
the root filesystem to provide at least 1 TB and its backing block device to be
nonrotational.

The 1 Gbps network contract is satisfied only when at least one nonvirtual,
physical Ethernet-class interface has carrier and reports at least 1000 Mbps.
The active default route is a separate diagnostic. Its speed may be lower or
unavailable (for example, Wi-Fi); it neither substitutes for a qualifying
physical link nor negates available physical-link capacity. No interface
identifier is emitted.

The official capacity contract uses total RAM and storage. Current free memory
and disk are reported separately under `operational_admission`, including the
50 GiB local-model start gate, 20 GiB stack-start gate, 80% official-edge
available-memory gate, and 150 GiB free-disk warning. A host can therefore
satisfy the advertised hardware contract while remaining operationally blocked
for a launch at that moment.

## Tests

Tests use injected runners/readers only; they do not inspect the live host:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/host-prerequisite-evidence/tests
```

Coverage includes exact source locks, inert defaults, acknowledgement gating,
command and path allowlists, sterile environments, raw-output sanitization,
schema enforcement, deterministic evidence digests, version boundaries,
nonrotational storage, physical-link versus active-route behavior, aarch64 CPU
scope, missing observations, operational-admission separation, pre-gate NGC
stat exclusion, and rejection of unsafe NGC candidates.
