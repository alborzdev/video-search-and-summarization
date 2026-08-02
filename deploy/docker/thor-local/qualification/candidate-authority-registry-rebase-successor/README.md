# Candidate authority registry rebase successor

This immutable sibling rebases the exact empty candidate-authority registry onto the finalized execution-binding registry, admission index, and empty receipt set.

Finalized admission inputs are pinned at:

- admission index `74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff`, schema `54cef2f2dc7879f817ff21c2b2472b19629d23c028fc25c3cee04fe9f09926d7`
- empty receipt set `e3d3d918bb392d903c00d82687efbf24d7c834019761929304019bbd4930132f`, schema `63dfd032bb3625fd1d5002f19a10e25f72f1c775c9f2c5ce6ee1121531449c10`

The execution-binding registry artifact (`af3927c…5b6b5`), schema (`8c2f7fa…a1f61`), locator artifact (`d1882d4…b69a0`), locator schema, compiler, and tests are all raw-locked.

The derivation preserves every historical empty authority, key, revocation, policy, not-required-edge, and spent-ledger collection; exact cryptographic/action/closure design fields; and zero trusted roots, accepted/consumed receipts, authorization, execution, and promotion semantics. The Warehouse sample remains excluded.

Validation and tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-authority-registry-rebase-successor/tests
```

The compiler performs no runtime, network, Docker, signing, verification, receipt consumption, or file-write action.
