# Rebase successor v2 evidence boundary

The scaffold directly locks the finalized mapping-rebase and runtime-bundle-rebase artifact/schema/compiler/test files and the rebased 500-oracle artifact/schema. It separately byte-locks all six files in the historical v2 package plus the canonical selector and staged descriptor.

The finalized Sparse4D source identities are:

- `sparse4d-candidate-dependency-repair-rebase-successor/repair.json` = `099b89d6e0b75b01e768b71ebaa6b0a719153185cf7aba5e6d0e5eb50e3247d7`
- `sparse4d-candidate-dependency-repair-rebase-successor/repair.schema.json` = `162e203bd62efbfacf3fda95e43a43a14bad9a23753dca9e1c53edc33bd22e87`
- compiler = `49274a7cc3843097099fedcabe4bc879c79a4b8e45d2f67b1ff2a08fadacb294`
- tests = `f288992eec5520c78984e8bcf202def71d42c943a2348740d76f607f1ad65524`

The checked mapping hash is `cb9bea95b4cfeab7c44441854e331a7093667d6b379fe0555692e5105ce4507f`; its schema hash is `78c118cc062eee15992ad3fcd4fa2d3585e6b80dc5bea7e32806ade1f11ccaba`. Exact comparison to the rebased predecessor proves only Sparse4D and firewall rows changed, while 209 rows remain equal. Success does not prove approval, admission, execution, runtime evidence, or Warehouse deployment.
