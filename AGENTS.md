# Development priorities

This is an actively evolving internal prototype. Shipping/distribution is not planned anytime soon. Optimize for fast, visible iteration and useful user testing.

For UI edits, starting the site, or switching runtime modes, read [the fast UI development workflow](docs/ui-development.md). Use its source-mounted hot reload workflow by default. Scope checks to the affected app; use full image builds when validating packaging or deliberately refreshing the built fallback.

Thor shares memory between CPU and GPU workloads. Preserve the existing 36 GiB runtime reserve and memory guard while iterating. For service configuration, consult `artifacts/thor-memory-2026-09-09/` and its management tooling before changing model or runtime budgets.

For live ingestion or full-stack startup, first read `tools/runtime/README.md`: the September 9 reboot invalidated sustained-ingestion readiness. Keep the current 48 GiB diagnostic reserve until staged validation supports another budget.
