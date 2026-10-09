# Development priorities

This is an actively evolving internal prototype. Shipping/distribution is not planned anytime soon. Optimize for fast, visible iteration and useful user testing.

For UI edits, starting the site, or switching runtime modes, read [the fast UI development workflow](docs/ui-development.md). Use its source-mounted hot reload workflow by default. Scope checks to the affected app; use full image builds when validating packaging or deliberately refreshing the built fallback.

Thor shares memory between CPU and GPU workloads. Keep the memory guard active and respect the explicitly selected reserve in `.thor/settings.json`. On October 9 the user selected **10 GiB** for the Anvil T5 demo; do not silently restore the historical 36/48 GiB floors. For service configuration, consult `tools/thor/README.md` and `artifacts/thor-memory-2026-09-09/` before changing model or runtime budgets.

For live ingestion or full-stack startup, first read `tools/runtime/README.md`: the September 9 reboot invalidated sustained-ingestion readiness. The user's 10 GiB reserve selection does not extend the workloads qualified by historical receipts.
