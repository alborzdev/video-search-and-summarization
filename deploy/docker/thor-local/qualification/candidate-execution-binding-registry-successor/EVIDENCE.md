# Candidate execution-binding registry evidence

## Control-source locks

The compiler directly locks the checked artifact, strict schema, and producer
for each of the seven projection inputs plus the 16-bundle approval DAG: 24
control files total.

| Source artifact | Raw SHA-256 |
| --- | --- |
| Candidate approval mapping v2 | `751fd28d59744a709a18eaa6d347e293bb6a665502636e26aaeff65c340f9844` |
| Candidate oracle adapter | `6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235` |
| Remaining-entry workloads | `ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312` |
| Protocol-v2 candidates | `886151fee9ce27b24601499011151e827c4742b32d400c609c8c0b149851db62` |
| Runtime-lane plan | `bf863fac268d1247eda71b9edbfd497580453c52cd3ced7fcdb333386efa25c9` |
| Guarded adapter receipt | `acfe8215c0666a990109e2e1d34a531ba5c2b3c2fa415f7cf901c5e7bddec99c` |
| Wave8 production-subset receipt | `0bf0167de20896260a7ca962665d5088385866ed6d272cf62f51d05c6c18b3f9` |
| Runtime approval-bundle successor | `74ba837f9e87923ddd48c635a067aeca9929bbf7cd9b3cff5f26157560aa3c0e` |

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
`c8311f1dc9eca330a186c43e15766e2daf5418649e41258eb50baa6445a31708`.

## Checked registry

| Measurement | Value |
| --- | --- |
| Registry rows | 208 |
| Canonical binding-row SHA-256 | `25b6dc3b2046895b926df837b93560e8f367cc672afdd479eb31438e94cea96c` |
| Registry raw SHA-256 | `59600e64e818b553039dd3d623d1a174714f6f51563da08251560c2994c7f544` |
| Admission-grade bindings | 0 |
| Authoritative executable bindings | 0 |
| Runtime evidence records | 0 |

The four exact external IDs are Slack notification, remote OpenAI-compatible
RT-VLM, Enterprise RAG report generation, and FRAG retrieval integration. They
remain external-only and cannot promote a local candidate.

## Reproducible validation

```text
compiler.py --check: status ok
pytest: 20 passed
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
