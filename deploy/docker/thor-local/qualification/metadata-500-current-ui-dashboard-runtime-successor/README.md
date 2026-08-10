# Current UI Dashboard runtime metadata successor

This deterministic successor projects the reviewed 289-row current ledger,
oracle plan, and manifest after `runtime.ui.dashboard-tab` received fresh
desktop/mobile rendered-browser evidence. It preserves rows 290-500 byte for
byte from the selected RT-Embed predecessor, then emits matching 289-row and
500-row metadata descriptors and advances the selector atomically.

The selected set is
`thor-vss-3.2.1-current-ui-dashboard-runtime-500`; the explicit current-prefix
set is `thor-vss-3.2.1-current-ui-dashboard-runtime-289`. The projection is
deterministic and fails closed if any canonical input or retained predecessor
member drifts.

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-ui-dashboard-runtime-successor/project.py
pytest -q deploy/docker/thor-local/qualification/metadata-500-current-ui-dashboard-runtime-successor/tests
```

The projection does not reinterpret the separate unauthenticated-network
boundary. The Dashboard capability is qualified for its rendered behavior;
host firewall acceptance remains an independent pending capability.

```bash
python3 project.py
python3 project.py --write
pytest -q tests
```
