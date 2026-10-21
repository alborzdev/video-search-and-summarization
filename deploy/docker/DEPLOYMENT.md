# Docker deployment map

Spark and Thor use the same application branch and the hardware-selected
entry points in `tools/runtime`. See [shared setup](../../docs/device-setup.md)
and [runtime qualification](../../tools/runtime/README.md).

```sh
python3 tools/runtime/bootstrap.py doctor
python3 tools/runtime/desktop.py check --no-open
python3 tools/runtime/desktop.py start --no-open
python3 tools/runtime/bootstrap.py stop
```

Render, staging and startup are separate operations. Preserve the saved local
reserve and cached model choices. The memory guard remains active, including
while unrelated training runs. UI development uses the
[source-mounted workflow](../../docs/ui-development.md).

The 3.3 source and its default upstream Compose deployment are described in
[edge deployment](../../docs/edge-deployment.mdx). Our measured device adapters
select only the services they need through `edge-demo/compose.yml`, then apply
local network, model and memory settings. This does not qualify an untested
upstream model or a new Thor inference engine.

`containers.env` and `container-inventory.json` are the upstream image catalog.
Local 3.3 source derivatives in `thor-local/Dockerfile.*33` pin their dependency
base images by digest. The former hand-maintained 3.2 image declaration mirror
and its duplicate validator have been removed. Actual offline readiness comes
from the selected device's cache verification and real workflow checks.

Keep `.spark/`, `.thor/`, recordings, indexes, credentials and compiled engines
local. A normal source update never replaces these directories. Retain the
[historical official-edge safety rules](thor-local/official-edge/README.md) for
that separate legacy launcher. The shared bootstrap does not override its fuse.
