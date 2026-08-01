#!/usr/bin/env python3
"""Exact two-state adapter for Wave 3 candidate validators."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "bundle"
BASELINE = BUNDLE / "baseline"


class LifecycleError(ValueError):
    pass


def _merge_module() -> Any:
    path = BUNDLE / "merge_live.py"
    spec = importlib.util.spec_from_file_location("wave3_exact_merge", path)
    if spec is None or spec.loader is None:
        raise LifecycleError("cannot load exact Wave 3 lifecycle contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state() -> str:
    module = _merge_module()
    try:
        return module.lifecycle()
    except Exception as exc:
        raise LifecycleError(str(exc)) from exc


def validation_path(path: Path) -> Path:
    """Return a pinned premerge snapshot only after exact merged verification."""
    current = state()
    if current == "wholly_unmerged":
        return path
    names = {
        "official-capabilities.json",
        "manifest.json",
        "acceptance_inventory.json",
        "capability-oracles.json",
    }
    if path.name not in names:
        return path
    baseline = BASELINE / path.name
    if not baseline.is_file():
        raise LifecycleError(f"missing published baseline: {path.name}")
    return baseline
