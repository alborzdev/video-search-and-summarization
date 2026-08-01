# Thor Docker cgroupfs remediation

NVIDIA VSS requires Docker's native cgroup driver to be `cgroupfs`. This tool
provides the Thor-local, failure-closed way to add that option without replacing
the rest of `/etc/docker/daemon.json` and without starting containers that were
not running immediately before the authorized Docker restart.

The tool never invokes `sudo`. Its default is an inert plan that executes no
command and reads no host file:

```bash
python3 deploy/docker/thor-local/qualification/host-cgroupfs-remediation/remediate.py
```

An operator may explicitly request the read-only inspection. It reads the fixed
daemon file, fixed Docker socket, and fixed systemd unit; it validates the
prospective candidate through `/usr/bin/dockerd --validate` using standard input.
It writes no file and uses no Docker lifecycle verb:

```bash
python3 deploy/docker/thor-local/qualification/host-cgroupfs-remediation/remediate.py inspect
```

## Authorized execution

Execution requires all three gates:

1. the operator has separately approved interrupting every running container;
2. the process has effective uid zero;
3. the exact acknowledgement is supplied.

After approval, the host owner runs this command themselves:

```bash
sudo python3 \
  deploy/docker/thor-local/qualification/host-cgroupfs-remediation/remediate.py \
  execute \
  --ack I_AUTHORIZE_DOCKER_CGROUPFS_RESTART_AND_EXACT_WORKLOAD_RESTORATION
```

Do not run that command merely because it appears in this document. A Docker
restart stops every current workload, including unrelated applications, and
local model services may have a long cold start. The program rejects remote or
rootless Docker, Swarm mode, live-restore, unreviewed unit drop-ins, conflicting
daemon flags, running auto-remove/paused/restarting containers, and non-running
containers whose restart policy might activate them unexpectedly.

The transaction:

1. strictly parses JSON and rejects duplicate keys;
2. preserves every existing setting while replacing at most one
   `native.cgroupdriver=*` entry with exactly
   `native.cgroupdriver=cgroupfs`;
3. verifies that this is the only semantic change and asks the installed
   `dockerd` to validate the candidate;
4. snapshots every container ID and the exact running subset;
5. fsyncs the original bytes, metadata, candidate, snapshot, and phase journal
   below `/var/lib/vss-thor/cgroup-remediation/`;
6. durably records `candidate_installing` before atomically installing the
   candidate, so recovery must conservatively roll back even if a crash occurs
   between replacement and the later `candidate_installed` receipt, then
   requests a bounded Docker restart;
7. starts only pre-snapshot IDs that were running but did not return through
   their restart policy;
8. requires identical pre/post inventory, running-set, daemon bytes, ownership,
   mode, and extended-attribute identities before it can emit passed evidence.

An unexpected new or activated container is external interference. The tool
does not stop it, because the acknowledgement authorizes restoring the prior
set, not terminating a workload created by somebody else. It refuses to claim
success. Use a maintenance window and keep other Docker clients idle during the
transaction.

## Failure recovery

After candidate installation, every ordinary error and SIGINT/SIGTERM enters
rollback while those signals remain blocked. Rollback restores the exact
original bytes, ownership, mode, and extended attributes, restarts Docker with
the original driver, and restores only the original running IDs. SIGKILL, power
loss, or a host crash cannot run in-process cleanup, so the durable active
journal deliberately blocks a new execute operation.

After inspecting the journal and approving another Docker interruption, recover
with:

```bash
sudo python3 \
  deploy/docker/thor-local/qualification/host-cgroupfs-remediation/remediate.py \
  recover \
  --ack I_AUTHORIZE_DOCKER_CGROUPFS_FAILURE_RECOVERY
```

Recovery always prefers the exact original state over guessing whether an
interrupted candidate should be promoted. If original restoration, Docker
restart, or container restoration is incomplete, the root-only journal is left
for manual diagnosis and the result cannot pass. With no active journal,
`recover` reports `ready`; absence of work is never represented as a passed
recovery transaction.

## Evidence and tests

All output is JSON. Unknown daemon values are never echoed; the report contains
only approved facts, container IDs, counts, file-metadata identities, and
SHA-256 digests. The strict
[`evidence.schema.json`](evidence.schema.json) rejects extra fields, while the
semantic validator additionally requires equal pre/post container-set digests,
candidate/active configuration equality, an exact `cgroupfs` post-driver, and
start actions drawn only from the pre-snapshot set.

Static qualification must exercise mocks only:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/host-cgroupfs-remediation/tests
```

The transaction proves configuration and container-state restoration. It does
not prove VSS application readiness; profile-specific endpoint and functional
qualification still follows after this prerequisite passes.
