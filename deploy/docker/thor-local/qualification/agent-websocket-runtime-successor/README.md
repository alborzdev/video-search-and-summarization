# Thor Agent WebSocket runtime qualification

This package qualifies `protocol.agent.websocket` against the current VSS 3.2.1 Thor deployment. It is inert by default, uses only the IPv4 loopback gateway, sends one bounded Agent chat frame, compiles the checked-in NVIDIA UI validator into a temporary directory for the adjacent-negative test, and retains no chat text or raw request, conversation, or session identifier.

The immutable protocol-case template carries an empty `schema_type`, while the current NVIDIA UI declares `chat_stream` as its default and the deployed 3.2.1 Agent rejects an empty value. The executor therefore materializes only that field from the locked current UI source. It hashes both the template and wire frame so this compatibility decision is explicit and reproducible.

Run the read-only preflight:

```bash
python3 deploy/docker/thor-local/qualification/agent-websocket-runtime-successor/execute.py
```

Run the bounded qualification deliberately:

```bash
python3 deploy/docker/thor-local/qualification/agent-websocket-runtime-successor/execute.py \
  --execute \
  --ack I_AUTHORIZE_AGENT_WEBSOCKET_RUNTIME_QUALIFICATION
```

Verify the retained receipt and official projection offline:

```bash
python3 deploy/docker/thor-local/qualification/agent-websocket-runtime-successor/verify.py
```

This package does not call the Agent `/generate` endpoint, restart a service, mutate VIOS or RT-CV, access the Warehouse sample bundle, or use an external network endpoint. The separate `runtime.agent.base-hitl` capability remains open until its report command/recovery state machine is exercised independently.
