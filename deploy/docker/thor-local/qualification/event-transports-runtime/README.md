# Thor event-transport runtime qualification

This package proves the VSS 3.2.1 Kafka NvSchema and Redis Streams transport
contracts on the local Thor. It mounts the pinned NVIDIA source read-only into
already-present arm64 runtime images and uses only fixed qualifier-owned broker
namespaces.

Run the live qualifier:

```bash
python3 deploy/docker/thor-local/qualification/event-transports-runtime/execute.py
```

The run performs four semantic actions: Kafka positive/negative and Redis
positive/negative. It does not call the VSS Agent, mutate VIOS/RT-CV streams,
or access the Warehouse sample bundle. The executor fails closed unless its
topic, groups, stream, and runner containers are absent before the run. It
removes only those exact resources and proves non-owned broker name sets and
broker health match afterward.

Verify the retained result and official projections without contacting either
broker:

```bash
python3 deploy/docker/thor-local/qualification/event-transports-runtime/verify.py
```
