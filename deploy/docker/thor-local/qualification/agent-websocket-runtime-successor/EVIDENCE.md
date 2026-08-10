# Retained evidence

Status: `passed_current` for `protocol.agent.websocket`.

The current Thor run proved:

- an HTTP 101 WebSocket upgrade through the mounted loopback HAProxy route;
- one UTF-8 JSON Agent request using the locked current UI `chat_stream` default;
- three correlated response frames in order: two `in_progress`, then exactly one `complete` terminal;
- non-empty semantic response content, retained only as a SHA-256 digest;
- normal client close code 1000 with no frame after terminal completion;
- rejection of an inbound response missing `conversation_id` by the actual checked-in validator after temporary SWC compilation;
- exact pre/post identity, health, start time, and restart-count equality for Agent, gateway, and UI containers;
- no change to the Agent report tree and complete removal of temporary compilation output.

The receipt contains no raw prompt, response, request ID, conversation ID, session value, endpoint URL, or credential. The first unretained attempt also identified why the historical empty-schema template is not directly executable on the current runtime; the retained passing run records the current-UI-default materialization rather than concealing it.

Focused NVIDIA UI WebSocket tests passed 110/110. The vendored package-wide TypeScript check remains red for many unrelated pre-existing files, so it is not used as proof for this narrowly bound protocol capability.

Report HITL command recovery is not inferred from this transport proof. It remains tracked separately as `runtime.agent.base-hitl`.
