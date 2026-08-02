# Evidence ledger

## Deterministic result

- Overlay ID: `thor-vss-3.2.1-candidate-execution-bindings-wave1`
- Source execution registry raw SHA-256:
  `59600e64e818b553039dd3d623d1a174714f6f51563da08251560c2994c7f544`
- Source execution-registry row payload SHA-256:
  `25b6dc3b2046895b926df837b93560e8f367cc672afdd479eb31438e94cea96c`
- Overlay binding-row canonical SHA-256:
  `b6dc8c0d5c63a21d0baed1a75e392e8c731ea89c92335bfb738ba6395b21b494`
- Overlay raw SHA-256:
  `aeb8eec139138f45a12a7673abe6f65cca455dbc1717e145e626fc58e70add24`

Exact result: two partial service/profile bindings, zero action contracts, zero
cleanup contracts, zero postcondition collectors, zero evidence contracts,
zero runtime evidence records, and zero admission-grade bindings.

## Bound source facts

The locked Compose chain establishes the static `lvs-server` / `vss-lvs` /
host-network / `bp_developer_thor_full_2d` wiring. Production `lvs_mcp.py`
establishes the source-default loopback SSE paths and exact 13-tool catalog.
These are declarations, not observations: effective profile, endpoints, image
digest, model, input, process argv, deployment state, transport state, and
readiness remain unresolved.

The compiler also locks and validates empty authority, authorization-envelope,
completion-envelope, accepted/consumed receipt, admission-receipt, admitted,
and executable sets. Therefore neither an operator token nor predecessor
observer evidence can silently promote either candidate.

## Safety

Validation reads regular non-symlink repository files through descriptor-based
`O_NOFOLLOW` component traversal, checks source hashes and semantic anchors,
recompiles the overlay, validates Draft 2020-12 schema constraints, and checks
canonical bytes. Tests do not invoke Docker, services, sockets, network,
subprocesses, downloads, credentials, models, or the Warehouse sample.
