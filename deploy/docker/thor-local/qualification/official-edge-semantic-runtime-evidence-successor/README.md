# Official Edge semantic runtime evidence successor

This package is the reviewed, non-promoting collector for the exact VSS 3.2.1
Thor official-edge model pair. It excludes the Warehouse sample and does not
download media, models, images, or artifacts.

The default command is a static `plan`. It validates source locks but creates no
network opener, performs no request, and changes no service. Runtime execution
requires all of the following:

- the exact acknowledgement `I_ACK_OFFICIAL_EDGE_SEMANTIC_RUNTIME`;
- a manifest that passes `manifest.schema.json` and binds an authorization-token
  digest;
- a fresh, digest-bound `read_only_host` official-edge readiness receipt in
  `prelaunch_ready_not_runtime_qualified` state;
- the exact source-locked artifact trees, image references and IDs, served model
  IDs, selector, loopback endpoints, release commits, and no-cloud Agent wiring;
- a local, digest-pinned visual fixture no larger than 1 MiB.

Execution makes exactly seven bounded numeric-loopback requests: both exact
`/v1/models` identities, positive and negative LLM tool semantics, positive and
absent-negative VLM visual semantics, and one Agent workflow that must exhibit
both visual consumption and the final LLM sentinel. Proxy-enabled openers,
redirects, hostname aliases, cloud targets, Qwen/older-Edge substitutions,
over-budget runs, and incomplete cleanup fail closed.

Freshness comes only from `captured_at_utc` inside the digest-bound readiness
receipt. The manifest supplies no capture time and receipt file modification
time is ignored. The positive visual oracle is never placed in its VLM prompt;
it must be recovered from the pinned visual bytes. The positive LLM tool call
uses `thor-tool-<run_id>` as an explicit per-run argument and binds its digest in
the receipt.

```bash
python3 executor.py
python3 executor.py plan
python3 executor.py execute \
  --manifest /absolute/path/to/manifest.json \
  --acknowledgement I_ACK_OFFICIAL_EDGE_SEMANTIC_RUNTIME \
  --authorization-token 'operator-supplied-token'
python3 executor.py validate-receipt \
  --receipt /absolute/path/to/receipt.json \
  --sha256 RECEIPT_SHA256
```

The successful receipt contains hashes, byte counts, public exact model
identities, stable assertions, counters, and cleanup state only. It excludes
raw media, authorization values, prompts, response bodies, and local paths. Its
status is `passed_candidate_non_promoting`; it cannot modify canonical state.

The canonical Thor requirements gate recognizes only the exact approved hashes
of `contract.json`, `contract.schema.json`, `executor.py`,
`manifest.schema.json`, and `receipt.schema.json`, then invokes this package's
strict receipt validator. A
valid receipt removes only the semantic-runtime-receipt blocker. Existing exact
artifact-tree and image blockers remain until independently satisfied.

## Fake-only verification

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_executor.py
ruff check executor.py test_executor.py
mypy --strict executor.py
```

The tests use inert fake openers and temporary fake bytes. They never contact a
service, Docker, a registry, or a model endpoint.
