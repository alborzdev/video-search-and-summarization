# Thor VA-MCP read-only runtime qualification

This qualifier exercises the live VSS 3.2.1 VA-MCP server at loopback port
9901. It verifies the JSON-RPC-over-SSE handshake, response-header session
contract, exact nine-tool inventory, and all eight read-only analytics tools.
Each tool call receives a fresh MCP session as required by the released server.

`react_agent` is inventoried but intentionally not invoked: this package proves
the read-only analytics MCP boundary without making an Agent/LLM call. It does
not modify VIOS, RT-CV, Docker, Elasticsearch, or alert configuration.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/va-mcp-runtime-successor/harness.py plan
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/va-mcp-runtime-successor/harness.py execute
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/va-mcp-runtime-successor/harness.py check
```
