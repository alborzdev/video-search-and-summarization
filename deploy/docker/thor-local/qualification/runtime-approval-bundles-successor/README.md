# Thor runtime approval bundles successor

This isolated package deterministically extends the raw-locked 14-bundle runtime approval contract with two firewall-specific scopes. The resulting checked artifact has an exact 16-bundle order: the inherited 14-bundle prefix is byte-source-bound and structurally identical, followed by read-only firewall inspection and then firewall configuration.

It is a contract compiler, not an executor. It performs no host inspection, subprocess, network request, Docker action, file write, download, credential access, lifecycle action, firewall change, cleanup, or rollback. It records zero approvals, receipts, admitted bundles, executable bundles, and runtime evidence. The Warehouse sample bundle remains excluded.

Run either explicit inert mode from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/runtime-approval-bundles-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/runtime-approval-bundles-successor/compiler.py \
  --emit
```

There is no default, write, authorize, or execute mode. `--check` verifies the checked artifact, strict schema, deterministic derivation, source identities, candidate/oracle boundary, exact bundle prefix/order/DAG, and zero-activation claims. `--emit` prints that same checked artifact to stdout.

## New approval scopes

The two new bundles are deliberately non-inheriting:

| Bundle | Exact approval marker | Dependency | Disclosed action flags |
|---|---|---|---|
| `physical-interface-firewall-read-only-inspection` | placeholder `<APPROVE_ONLY_READ_ONLY_PHYSICAL_INTERFACE_FIREWALL_INSPECTION>`; token `I_ACCEPT_READ_ONLY_VSS_PHYSICAL_INTERFACE_FIREWALL_INSPECTION` | none | host inspection and subprocess only |
| `physical-interface-firewall-configuration` | placeholder `<APPROVE_ONLY_EXACT_PHYSICAL_INTERFACE_FIREWALL_TRANSACTION>`; token `I_AUTHORIZE_VSS_PHYSICAL_INTERFACE_FIREWALL_APPLY_AND_EXACT_OWNED_ROLLBACK`; recovery token `I_AUTHORIZE_VSS_PHYSICAL_INTERFACE_FIREWALL_FAILURE_RECOVERY` | read-only inspection only | host inspection, subprocess, writes, lifecycle, and destructive |

Placeholders and recorded tokens grant nothing. A dependency receipt does not approve its dependent. The recovery token is not configuration authorization. Neither bundle publishes a command.

## Why configuration is still blocked

The existing `thor-local.sh` firewall apply/remove behavior is not safe enough to serve as an authorization transaction. Apply deletes any prior product table before installing a replacement without preserving exact prior state. Its failure rollback deletes the table rather than restoring that prior state. Remove likewise deletes the table. Those operations can lose pre-existing state and therefore are not published or authorized by this package.

Configuration remains blocked until a separately reviewed transaction executor and strict receipt schema provide, at minimum, exact pre-state capture, owned-target validation, bounded actions, after-state evidence, lossless exact rollback, and separate failure-recovery authorization. This package does not implement those facilities.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/runtime-approval-bundles-successor/tests
```

Tests are static and temporary-file-only. They cover the exact inherited prefix, extension order, DAG, unique placeholders and tokens, action flags, zero activation, source/package locks, schema strictness, source drift, symlink rejection, candidate/oracle non-admission, legacy transaction blockers, mutation-command absence, and the compiler's lack of action facilities.
