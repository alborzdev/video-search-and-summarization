# Current LVS REST runtime metadata successor

This immutable successor overlays the reviewed 289-row current Thor capability
ledger and oracle plan onto the unchanged 211-row candidate suffix from the
preceding LVS MCP successor.

The transition promotes `api.core.lvs-17` from static-only planning to
`passed_current` and `executor_ready`, bound to the sealed complete 18-operation
LVS REST qualification package. The family remains `not_qualified` because
other advertised API surfaces are still open.

Generate the immutable projection and selector:

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-lvs-rest-runtime-successor/project.py --write
```

The projector does not contact services or mutate runtime state.
