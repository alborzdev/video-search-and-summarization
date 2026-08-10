# Thor Alert Bridge WebSocket runtime qualification

This package proves the VSS 3.2.1 real-time alert-delivery WebSocket contract
on the local Thor. It runs the pinned NVIDIA Alert Bridge source from a
read-only mount in an isolated loopback-only container and uses only fixed
qualifier-owned Redis resources.

Run the live qualifier:

```bash
python3 deploy/docker/thor-local/qualification/alert-websocket-runtime/execute.py
```

The run performs two semantic actions: one positive delivery path and one
non-JSON adjacent negative. It does not call the VSS Agent, mutate the normal
alert streams or service, change VIOS/RT-CV streams, use Warehouse data, or
make external requests. It fails closed unless its container, port, and Redis
streams are absent before execution, then removes only its exact allowlist and
proves the normal service and non-owned Redis key set match pre-state.

Verify the retained result and official projection without contacting Redis or
starting a container:

```bash
python3 deploy/docker/thor-local/qualification/alert-websocket-runtime/verify.py
```
