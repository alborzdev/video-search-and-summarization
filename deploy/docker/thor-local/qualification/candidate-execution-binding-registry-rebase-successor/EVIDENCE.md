# Candidate execution-binding registry rebase evidence

## Control-source locks

The compiler directly locks the checked artifact, strict schema, and producer
for each projection input plus the complete Wave1 chain and 16-bundle approval
DAG: 28 current control files total. It separately locks all eight files in the
historical registry package.

| Source artifact | Raw SHA-256 |
| --- | --- |
| Candidate approval mapping rebase v2 | `cb9bea95b4cfeab7c44441854e331a7093667d6b379fe0555692e5105ce4507f` |
| Candidate oracle adapter | `59359d95ec768ab79f9c7a99404f2a7304addb018bbc3c591900d6ee7e9540b0` |
| Remaining-entry workloads | `ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312` |
| Protocol-v2 candidates | `cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7` |
| Runtime-lane plan | `bf863fac268d1247eda71b9edbfd497580453c52cd3ced7fcdb333386efa25c9` |
| Guarded adapter receipt | `acfe8215c0666a990109e2e1d34a531ba5c2b3c2fa415f7cf901c5e7bddec99c` |
| Wave1 contract | `fae464894d7d565a1078f852776bb005e0426c4280473d551bbec3e727e2d53c` |
| Wave1 production-subset receipt | `ab07eac3e5c240f55d2480fe34aa5128be0cd62b3a64027e3ae689cb27bd0396` |
| Wave1 successor annotation index | `1a066029a04bc67bcefd4571f24fce1cda1df275ab48aed48f99ea7e274f10b5` |
| Runtime approval-bundle rebase successor | `415931c48a231c150c62d90e134da5f60a75adb8bed653dcef45251ef6caf194` |

All associated schema/compiler or producer files and their raw hashes are
enumerated in `registry.json.source_locks`.

## Projection-source locks

The checked locator artifact directly hashes current regular files rather than
trusting locator strings:

| Lock group | Occurrences | Unique locators/files |
| --- | ---: | ---: |
| Semantic implementation surfaces | 389 | 269 locators / 235 base files |
| Active lane profile and Compose paths | 45 | 26 files |

`locator-locks.json` raw SHA-256:
`d1882d4811bd661fd011f8cf91894951cc8af806c56968218ef0100b500b69a0`.

## Checked registry

| Measurement | Value |
| --- | --- |
| Registry rows | 208 |
| Canonical binding-row SHA-256 | `0d8b334e25330d8f5142a6fff91cc13fc3ebf0c013a371e1f6b41334530c0924` |
| Registry raw SHA-256 | `af3927c15f9e5c1efb67690ee7ca3f3e6ee9fb77e720767db2264d68a935b6b5` |
| Preserved binding-semantics SHA-256 | `5e8038dda61af51fb8bf1ced95ad133879048493c587a75d19354fd85a5f6448` |
| Admission-grade bindings | 0 |
| Authoritative executable bindings | 0 |
| Runtime evidence records | 0 |
| Executable bindings / promotions | 0 / 0 |

The four exact external IDs are Slack notification, remote OpenAI-compatible
RT-VLM, Enterprise RAG report generation, and FRAG retrieval integration. They
remain external-only and cannot promote a local candidate.

## Reproducible validation

```text
compiler.py --check: status ok
pytest: 22 passed
ruff check: all checks passed
ruff format --check: 2 files already formatted
JSON and strict schema validation: passed
git diff --check: passed
cache hygiene: passed
```

Validation used only repository reads and deterministic in-process processing.
It performed no historical executor invocation, runtime/network request,
Docker or service lifecycle action, host inspection, download, model access,
credential access, or Warehouse sample action. No runtime state was promoted.
