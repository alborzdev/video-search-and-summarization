#!/usr/bin/env python3
"""Project the Global-Chat-qualified 289-row prefix into 500 rows."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PREDECESSOR = (
    HERE.parent / "metadata-500-current-agent-websocket-runtime-successor" / "project.py"
)
SPEC = importlib.util.spec_from_file_location(
    "metadata_500_agent_websocket_predecessor_for_ui_global_chat",
    PREDECESSOR,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load the reviewed Agent WebSocket predecessor")
base = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = base
SPEC.loader.exec_module(base)

CURRENT_LEDGER = base.CURRENT_LEDGER
CURRENT_ORACLES = base.CURRENT_ORACLES
CURRENT_MANIFEST = base.CURRENT_MANIFEST
CURRENT_ACCEPTANCE = base.CURRENT_ACCEPTANCE
CURRENT_ORACLE_SCHEMA = base.CURRENT_ORACLE_SCHEMA
PRIOR_LEDGER_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-agent-websocket-runtime-successor/"
    "post-state-official-capabilities.json"
)
PRIOR_ORACLES_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-agent-websocket-runtime-successor/"
    "post-state-capability-oracles.json"
)
PRIOR_MANIFEST_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-agent-websocket-runtime-successor/post-state-manifest.json"
)
PRIOR_ORACLE_SCHEMA_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-agent-websocket-runtime-successor/"
    "post-state-capability-oracles.schema.json"
)
OUTPUT_LEDGER_500 = str(
    HERE.relative_to(REPO) / "post-state-official-capabilities.json"
)
OUTPUT_ORACLES_500 = str(HERE.relative_to(REPO) / "post-state-capability-oracles.json")
OUTPUT_MANIFEST_500 = str(HERE.relative_to(REPO) / "post-state-manifest.json")
OUTPUT_ORACLE_SCHEMA_500 = str(
    HERE.relative_to(REPO) / "post-state-capability-oracles.schema.json"
)
SET_ID_289 = "thor-vss-3.2.1-current-ui-global-chat-runtime-289"
SET_ID_500 = "thor-vss-3.2.1-current-ui-global-chat-runtime-500"
DESCRIPTOR_289 = f"deploy/docker/thor-local/parity/metadata_sets/sets/{SET_ID_289}.json"
DESCRIPTOR_500 = f"deploy/docker/thor-local/parity/metadata_sets/sets/{SET_ID_500}.json"
SELECTOR = base.SELECTOR


OVERRIDES = (
    "CURRENT_LEDGER",
    "CURRENT_ORACLES",
    "CURRENT_MANIFEST",
    "CURRENT_ACCEPTANCE",
    "CURRENT_ORACLE_SCHEMA",
    "PRIOR_LEDGER_500",
    "PRIOR_ORACLES_500",
    "PRIOR_MANIFEST_500",
    "PRIOR_ORACLE_SCHEMA_500",
    "OUTPUT_LEDGER_500",
    "OUTPUT_ORACLES_500",
    "OUTPUT_MANIFEST_500",
    "OUTPUT_ORACLE_SCHEMA_500",
    "SET_ID_289",
    "SET_ID_500",
    "DESCRIPTOR_289",
    "DESCRIPTOR_500",
    "SELECTOR",
)

module = base
seen: set[int] = set()
while id(module) not in seen:
    seen.add(id(module))
    for name in OVERRIDES:
        setattr(module, name, globals()[name])
    nested = getattr(module, "base", None)
    if nested is None:
        break
    module = nested


def build_outputs() -> dict[str, bytes]:
    return base.build_outputs()


def main(argv: list[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
