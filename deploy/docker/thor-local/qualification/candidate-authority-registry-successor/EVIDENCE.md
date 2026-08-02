# Candidate authority registry evidence

## Scope

This is static, read-only evidence. No authority, key, revocation, signature,
receipt, admission, execution, network request, dependency download, runtime
inspection, Docker action, host change, model access, secret access, or
Warehouse data access occurred.

## Locked inputs

| Input | Raw SHA-256 |
| --- | --- |
| Execution registry | `59600e64e818b553039dd3d623d1a174714f6f51563da08251560c2994c7f544` |
| Execution registry schema | `04eb378e9891a805069ad293a762c6e71c95498177baf0b5b21cf1db0c46ab7d` |
| Execution registry compiler | `fadfa7ff38585ce0604b0511113f12f1281016a3b39c08188022eda14144973d` |
| Locator locks | `c8311f1dc9eca330a186c43e15766e2daf5418649e41258eb50baa6445a31708` |
| Locator-lock schema | `3cad143f04ebb9a80b11e180aed9a6ccb573d247d52b617ea8caeb9805075cb2` |
| Admission index | `6dc6345f9b057c164929a1046b8ebcfb08fdfbedaa1b7a66180f344915d7d7eb` |
| Admission-index schema | `bc0603904f159a5759449cd4d6b54a94723cf26332611e25cb58432be6184c46` |
| Empty admission receipt set | `7bfeb7e70f9a7c3a2bbbb007c785286146dbfe70e4f63245168cf382b62ec805` |
| Admission receipt schema | `6cc3e19b809c48d23f8998908a2569d26dc4aad74a8ffdccfb8505914477764f` |
| Admission compiler | `8254bd9fe13fc7954ed3007f6fbdfb0247079b8f44147434ebed2048e5f27c67` |

The source execution registry contains 208 mapped rows with canonical row hash
`25b6dc3b2046895b926df837b93560e8f367cc672afdd479eb31438e94cea96c`.
Admission-grade bindings and all 13 authoritative action/service/profile/
Compose/cleanup/postcondition/evidence field total are exactly zero. The
admission source covers 211 candidates with zero admitted, zero executable, and
zero receipts.

Read-only source review also found candidate-inapplicable precedents; none is
imported or invoked by this package:

| Reviewed precedent | Raw SHA-256 | Why it is not candidate authority |
| --- | --- | --- |
| `.github/scripts/sign-agent-skill.sh` | `5e24a17b420134d97c0c2965b0055f5c43655694450655e6d1d0348dbb582b99` | Network/dependency-capable certificate workflow; no tracked offline candidate root |
| `.github/workflows/skills-signatures.yml` | `fd90f741cff30aaa0d2d405082488151985301e99fe9cd2837b998bb836f80cf` | Skill signing, not candidate receipt authority |
| `deploy/docker/thor-local/qualification/acceptance.py` | `673873746cb3f23fb35fd9dac445df4a181566ae320eb7e4090ac7837b7c024f` | Locally rewritable unsigned hash-chain primitive, not replay protection |
| `deploy/docker/thor-local/qualification/acceptance_executor.py` | `a02562c20489e05e73b692a83710645471dfe05eb23cc803d171789f7444651d` | Local acceptance helper without a trusted issuer or global spent ledger |
| `deploy/docker/thor-local/qualification/runtime-evidence-common/common.py` | `e89a4dedc5edf68a542b4d7de9c840821249d1121356676bc98e0d5fcc6e3627` | Caller-supplied token comparison and in-memory cleanup, not issuer/time/replay authority |

## Checked result

```json
{
  "authority_registry_raw_sha256": "4b3b806509d7dc0c50edcf8dadeec38b4b8aaab3a9d7404f3358922b029abcc2",
  "authorization_envelope_count": 0,
  "completion_receipt_envelope_count": 0,
  "signed_receipt_set_raw_sha256": "7d891821c71bf9bd3c12eff1913134882f4cf3d0dd656aba29c5de0eceff8ffc",
  "status": "ok",
  "trusted_root_count": 0
}
```

Focused validation passed 19 tests. Ruff lint and format checks passed. All
three JSON schemas passed Draft 2020-12 meta-schema validation. No Python byte
code or test cache is retained in the package.

## Security conclusion

The result is intentionally non-activating. SHA-256 is integrity, not
authority. Outer DSSE shape and future payload schema are not cryptographic
verification. Without independently pinned roots, a verifier, JCS/PAE,
trusted time, epoch rollback state, authenticated revocation, exact non-null
candidate executable bindings, and an atomic spent ledger, every nonempty
authority or receipt input fails closed. Warehouse remains excluded.
