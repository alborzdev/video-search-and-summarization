# Alerts current-contract successor

This offline successor changes exactly twelve JSON leaves: the
`api.core.alerts-19` expected-manifest digest and operation count in the live
capability; the three oracle digest copies; the three oracle operation-count
copies; and the four derived workload-budget values. The stable capability ID
and advertised title remain unchanged, while the bound contract truthfully
covers the current 21-operation manifest with an 85-request/action ceiling. It
preserves every unrelated parsed record, writes neither the manifest nor
acceptance aggregate, and creates no runtime evidence or `passed_current`
promotion.

```bash
python3 integrate_live.py plan
python3 integrate_live.py review
python3 integrate_live.py write
python3 integrate_live.py validate
python3 integrate_live.py rollback-plan
python3 -m unittest discover -s tests -p 'test*.py' -v
```

`rollback-plan` is read-only. The explicit `rollback` command reconstructs the
two exact predecessor byte streams by reversing only the twelve allowlisted
leaves; `validate-rollback` verifies that state. Normal validation is read-only.
