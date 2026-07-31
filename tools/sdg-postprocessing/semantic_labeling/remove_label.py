# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remove semantic labels from an OpenUSD stage or the current Isaac Sim stage."""

import argparse
from pathlib import Path
from typing import Optional

from pxr import Usd

try:
    from pxr import UsdSemantics
except ImportError:  # Isaac Sim releases before the current LabelsAPI schema.
    UsdSemantics = None

try:
    from pxr import Semantics as LegacySemantics
except ImportError:  # The deprecated NVIDIA schema is not part of plain OpenUSD.
    LegacySemantics = None


def get_stage(stage_path: Optional[str] = None) -> Usd.Stage:
    if stage_path:
        stage = Usd.Stage.Open(str(Path(stage_path).expanduser()))
        if not stage:
            raise ValueError(f"Unable to open USD stage: {stage_path}")
        return stage
    try:
        import omni.usd  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "No stage was supplied and Isaac Sim's omni.usd module is unavailable; "
            "pass --stage PATH."
        ) from exc
    stage = omni.usd.get_context().get_stage()
    if not stage:
        raise RuntimeError("Isaac Sim does not currently have an open USD stage")
    return stage


def remove_all_semantics(stage: Usd.Stage) -> int:
    """Remove current and, when available, deprecated semantic schemas."""

    removed = 0
    for prim in stage.Traverse():
        if UsdSemantics is not None:
            for taxonomy in list(UsdSemantics.LabelsAPI.GetDirectTaxonomies(prim)):
                if prim.RemoveAPI(UsdSemantics.LabelsAPI, taxonomy):
                    removed += 1
        if LegacySemantics is not None:
            for schema in list(prim.GetAppliedSchemas()):
                prefix = "SemanticsAPI:"
                if schema.startswith(prefix) and prim.RemoveAPI(
                    LegacySemantics.SemanticsAPI, schema[len(prefix) :]
                ):
                    removed += 1
    return removed


def run(stage_path: Optional[str] = None) -> int:
    stage = get_stage(stage_path)
    removed = remove_all_semantics(stage)
    if stage_path:
        stage.GetRootLayer().Save()
    print(f"Removed {removed} semantic label instance(s)")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        help="USD file to modify in place; omit only inside Isaac Sim Script Editor",
    )
    args = parser.parse_args()
    run(args.stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
