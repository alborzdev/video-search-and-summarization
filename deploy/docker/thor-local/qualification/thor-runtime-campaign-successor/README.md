# Thor runtime campaign successor

This Warehouse-free package is an inert composer for candidate Thor runtime
receipts. It does not start a profile, open a socket, inspect Docker, download
an artifact, call a model, grant authorization, write evidence, admit a
candidate, or promote canonical state.

The checked-in contract freezes the current ten-row semantic candidate overlay
and the strongest receipt surfaces for:

- official Thor LLM/VLM identity, backend image, no-cloud wiring, and live
  semantic behavior after fresh exact readiness admission;
- Base VQA/report semantics (`tiny-agent-media` and HITL state);
- integrated Search file lifecycle plus eleven semantic operations;
- Search RTSP archive lifecycle;
- rendered Video Management upload/RTSP behavior;
- LVS dependency/live-caption closure, Agent single/multi-report session,
  provider-free multi-video oracle, and focus matrix;
- Alerts terminal completion/cancellation; and
- the four read-only Thor host-prerequisite observations.

## Inert commands

`plan` is the default. It reads only checked-in regular files, validates all
32 direct raw source locks and nine additional transitive collector/verifier
locks (41 unique files), revalidates the selected ten-row overlay, and prints
the fixed campaign order and retained blockers.

```bash
python3 deploy/docker/thor-local/qualification/thor-runtime-campaign-successor/compiler.py
python3 deploy/docker/thor-local/qualification/thor-runtime-campaign-successor/compiler.py plan
```

`check` is also inert. It reads one reviewed campaign manifest, one receipt-set
index, and the twelve relative regular JSON receipt files named by that index.
It never imports or invokes their collectors.

```bash
python3 deploy/docker/thor-local/qualification/thor-runtime-campaign-successor/compiler.py check \
  --manifest /absolute/reviewed/campaign-manifest.json \
  --receipt-set /absolute/reviewed/receipt-set.json
```

Receipt paths are relative to the receipt-set directory. Absolute paths,
traversal, symlinks, duplicate paths, duplicate payloads, replacement after
review, and non-regular files fail closed. The compiler emits its validation
result to stdout and writes nothing.

## Frozen sequence

The exact phase order is:

1. read-only host prerequisites;
2. official-model live semantic admission;
3. Base tiny-media VQA/report;
4. Base HITL state/report;
5. integrated Search file lifecycle and semantics;
6. Search RTSP lifecycle;
7. rendered UI Video Management;
8. LVS identity/live-caption closure;
9. LVS Agent report session;
10. provider-free LVS multi-video static oracle;
11. LVS focus matrix; and
12. Alerts terminal completion/cancellation.

The profile transitions are exactly `none -> base -> search -> lvs -> alerts`.
Every mutating phase has a distinct campaign-prefixed run namespace and a
distinct executor-input digest. The host and provider-free static phases must
carry neither. Every phase after model admission, including the provider-free
static oracle, must carry the raw SHA-256 of that exact semantic model receipt.

## Identity contract

The manifest pins:

- commit `862bdcc46db9c81d920703d1ba14c9a4dfa21377` and the selected overlay;
- the resolved Compose and generated environment digest per profile;
- every required image role as an immutable `@sha256:` reference;
- every required model artifact, served model ID, and artifact-tree digest;
- all sixteen fixture/descriptor identities; and
- the input-manifest or reviewed-input digest for every runtime phase.

All inference placements are `local_thor`; the manifest schema admits no
remote endpoint and no Warehouse dependency. The current official Thor model
precedence is fixed to Nemotron 3 Nano 4B FP8 plus Cosmos3 Nano BF16. Their
release/main commits, artifact-lock digest, served IDs, loopback endpoints,
backend image references and IDs, and exact no-cloud configuration projection
are independently fixed. A model, served-name, image-reference, image-set,
model-set, fixture, phase, or source drift is rejected.

## Receipt composition

Every raw receipt is hash-checked and validated against its exact source-locked
schema. A readiness report cannot substitute for the official semantic model
receipt. That receipt must have the four exact collector hashes, seven ordered
semantic observations, exact release/artifact/image/served-model identities,
the exact no-cloud projection, and the campaign run/media identity. The
compiler additionally enforces available cross-receipt identity:

- Base, UI, and LVS manifest hashes must equal the phase input digest;
- raw or hashed run identities must equal the phase namespace;
- Search file, RTSP/control, UI media, LVS fixture readback, focus media, and
  Alerts descriptor identities must equal the campaign fixture pins;
- Search must prove its integrated semantic consumer shared the lifecycle
  budget/deadline;
- every downstream phase and descriptor must name the verified raw official
  semantic model receipt digest;
- host evidence must be an exact four-contract pass with a correct self-digest;
  and
- the LVS provenance record must hash-link the Agent receipt and static result
  while retaining `connected=false`.

The receipt-set maps 15 capability IDs: all ten selected semantic candidates,
the Alerts terminal capability, and four host prerequisites. It rejects the
standalone Search semantic receipt and weaker Base, Alerts, and LVS predecessor
receipts so one lifecycle is never counted twice.

## Deliberate incomplete boundary

A valid receipt set is
`campaign-receipt-set-valid-incomplete-nonpromoting`, never complete evidence.
Six blockers are mandatory:

- official-model staged-artifact/readiness evidence is scoped to the supplied
  non-promoting live receipt while the canonical artifact lock remains
  `incomplete_fail_closed`;
- the static LVS multi-video oracle did not consume live report bytes;
- Alerts exposes neither its authorized run namespace nor served-media digest;
- the UI receipt does not expose the reviewed RTSP descriptor digest;
- Search on Thor is a custom unsupported upstream boundary; and
- no canonical admission or promotion has occurred.

Removing a blocker, marking LVS provenance connected, claiming completeness,
or replacing a blocked mapping with a passing mapping is rejected. This is
intentional: a wrapper assertion cannot manufacture evidence absent from the
underlying receipt.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/thor-runtime-campaign-successor/tests
```

The tests generate only temporary synthetic JSON. They cover exact source and
schema validation, inert CLI shape, identity/set digests, cloud/Warehouse
rejection, phase ordering, disjoint namespaces, readiness-only model evidence,
wrong collector hashes, missing downstream model-receipt dependencies,
missing/duplicate/stale and cross-run receipts, conflicting Search evidence,
LVS overclaim prevention, Alerts descriptor drift, capability/blocker drift,
traversal, and symlinks.
