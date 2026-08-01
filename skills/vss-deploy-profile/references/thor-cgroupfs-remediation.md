# Thor Docker cgroupfs precedence

For AGX Thor and IGX Thor, this repository-local procedure takes precedence
over any profile reference that tells an operator to overwrite
`/etc/docker/daemon.json` with a small literal object. In particular, the
checked-in Warehouse reference contains an upstream-anchored overwrite example.
It is provenance, not a safe Thor command: running it would discard existing
keys such as the NVIDIA runtime registration.

Do not hand-edit or replace the daemon file on Thor. First run the inert plan and
then the explicitly selected read-only inspection documented in
[`deploy/docker/thor-local/qualification/host-cgroupfs-remediation/README.md`](../../../deploy/docker/thor-local/qualification/host-cgroupfs-remediation/README.md).

Applying the candidate restarts Docker and interrupts every running container.
It therefore requires separate operator approval. The remediation program never
invokes `sudo`; after approval the host owner runs the exact root-gated command
from its README. Missing approval or an unsafe/preemptible container state is a
blocker, not permission to use the overwrite snippet.
