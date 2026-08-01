# Thor runtime approval bundles

This isolated package compiles the remaining operator-authorized work into 13 explicit, non-executing approval bundles. It grants no approval and performs no host inspection, subprocess, network request, Docker call, write, download, credential access, lifecycle change, or cleanup.

Run the default inert compiler from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/runtime-approval-bundles/compiler.py
```

`--check` compiles and validates the same plan. There is no execute mode.

## Approval isolation and precedence

Every bundle has a unique `<APPROVE_ONLY_...>` placeholder. A placeholder is not an acknowledgement. Completing a dependency is not approval for its dependent, and approval never inherits across bundles.

| Bundle | Must follow | Material action flags |
|---|---|---|
| Read-only Docker/runtime inspection | — | host inspection, subprocess, loopback network, Docker |
| cgroupfs remediation | inspection | writes, Docker lifecycle, destructive interruption/restoration |
| tiny audio fixture generation | — | local subprocess, two outside-repository writes |
| model/artifact downloads | inspection | network, Docker, writes, downloads, credentials |
| profile lifecycle | inspection, cgroup remediation, downloads | Docker/network/writes/credentials/lifecycle/destructive |
| Search scale 2/4/8/16 | profile lifecycle | runtime/lifecycle/destructive |
| Search scale 100 | profile lifecycle, completed progressive lane | separate runtime/lifecycle/destructive approval |
| MV3DT custom data | profile lifecycle | runtime/lifecycle/destructive |
| Sparse4D custom data/models | profile lifecycle, downloads | runtime/lifecycle/destructive |
| native-Omni audio runtime | fixture, downloads, profile lifecycle | native semantics only; runtime/lifecycle/destructive |
| local-ASR transcript runtime | fixture, downloads, profile lifecycle | per-chunk transcript only; separate runtime/lifecycle/destructive approval |
| official Edge staging | inspection, downloads | Docker and filesystem writes; no profile start |
| external attestations | — | provider network, credentials, sanitized evidence write |

The contract records required inputs, current planning blockers, cleanup, rollback, and nine boolean action disclosures for every bundle. A dependency can be satisfied by that bundle's separate receipt or by a reviewed determination that no action is required—for example, cgroupfs already being correct or an artifact already being present. Neither result grants the dependent approval. Blocker language is deliberately non-observational: the compiler does not infer current memory, disk, cgroup, container, port, endpoint, image, model, or credential state.

## Download and disk review

Reviewed exact remote bytes currently cover only:

- official Edge Nemotron tree: `5,284,569,483` bytes;
- official Edge arm64 vLLM image manifest payload: `14,586,467,388` bytes.

Their exact total is `19,871,036,871` bytes. Cosmos3 has only a documented 30 GB planning floor, producing a `49,871,036,871`-byte planning floor; its exact transfer size remains unknown. vLLM installed/unpacked size, the RT-VLM image transfer size, MV3DT assets, Sparse4D ONNX and anchor, and the native-audio model size also remain unknown. These figures are not current free-space evidence. The download bundle requires a fresh exact missing-set and disk-headroom review before authorization.

## Audio authorization boundary

The reviewed `audio-entry-oracles` contract and validator are raw-locked alongside the tiny-audio fixture and Wave 7 identities. Native Omni can support Base, summary, and alert semantics but cannot prove the ASR transcript entry. The native and local-ASR bundles therefore have distinct non-inheriting approval placeholders and require distinct authorization IDs.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/runtime-approval-bundles/tests
```

The tests are static and temporary-file-only. They validate package/source locks, schema strictness, the exact denominator, unique approval placeholders, precedence, download arithmetic and unknown-size retention, the audio boundary, and absence of action facilities.
