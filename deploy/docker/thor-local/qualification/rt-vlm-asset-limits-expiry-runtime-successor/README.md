# RT-VLM asset limits and expiry runtime successor

This package binds official capability 364 to current-Thor production runtime
evidence. It runs the mounted production `AssetManager` in two isolated child
processes inside the healthy RT-VLM container. Tiny temporary files prove
pressure eviction, in-use protection, hard-cap rejection, and TTL expiry
without mutating the main RT-VLM asset catalog.

The default command is inert. The acknowledged command makes four read-only
loopback API calls and runs two sequential, bounded container-local probes. It
makes no model, Agent, VIOS, RT-CV, stream, or service-lifecycle request.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 execute.py plan
PYTHONDONTWRITEBYTECODE=1 python3 execute.py execute \
  --ack I_ACK_ISOLATED_RT_VLM_ASSET_LIMIT_AND_TTL_RUNTIME_PROOF
```
