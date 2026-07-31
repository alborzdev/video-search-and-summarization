# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Find and optionally label box-like meshes in an OpenUSD stage.

The original helper was intended to be pasted into the Isaac Sim Script Editor.
It now retains that mode while also providing a headless OpenUSD CLI, which is
the mode used on Jetson Thor.
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple

from pxr import Usd, UsdGeom, Vt

try:
    from pxr import UsdSemantics
except ImportError:  # Isaac Sim releases before the current LabelsAPI schema.
    UsdSemantics = None

try:
    from pxr import Semantics as LegacySemantics
except ImportError:  # Plain OpenUSD does not include NVIDIA's deprecated schema.
    LegacySemantics = None


USER_OUTPUT_PATH = ""

PATTERNS = {
    "printersbox": re.compile(r"printersbox.*body", re.IGNORECASE),
    "flatbox": re.compile(r"flatbox.*body", re.IGNORECASE),
    "officepaperbox": re.compile(r"officepaperbox.*_box_\d+", re.IGNORECASE),
    "cardbox": None,
    "largecardboardbox": re.compile(r"largecardboardboxe.*/merged$", re.IGNORECASE),
    "cubebox": re.compile(r"cubebox.*body", re.IGNORECASE),
    "whitecorrugatedbox": re.compile(r"whitecorrugatedbox.*body", re.IGNORECASE),
    "multidepthbox": re.compile(r"multidepthbox.*body", re.IGNORECASE),
    "longbox": re.compile(r"longbox.*body", re.IGNORECASE),
    "woodencrate": None,
}
EXCLUDED_CRATE_PATTERN = re.compile(r"heavydutypackingtable_\w+")


def enable_semantics(
    prim: Usd.Prim, semantic_label: str, semantic_class: str = "class"
) -> None:
    """Author a current OpenUSD ``LabelsAPI`` label on ``prim``."""

    if UsdSemantics is not None:
        labels = UsdSemantics.LabelsAPI.Get(prim, semantic_class)
        if not labels:
            if not UsdSemantics.LabelsAPI.CanApply(prim, semantic_class):
                raise ValueError(
                    f"LabelsAPI taxonomy {semantic_class!r} cannot be applied to {prim.GetPath()}"
                )
            labels = UsdSemantics.LabelsAPI.Apply(prim, semantic_class)
        labels.CreateLabelsAttr().Set(Vt.TokenArray([semantic_label]))
        return
    if LegacySemantics is None:
        raise RuntimeError("No OpenUSD semantic-label schema is available")
    labels = LegacySemantics.SemanticsAPI.Get(prim, "Semantics")
    if not labels:
        labels = LegacySemantics.SemanticsAPI.Apply(prim, "Semantics")
        labels.CreateSemanticTypeAttr()
        labels.CreateSemanticDataAttr()
    labels.GetSemanticTypeAttr().Set(semantic_class)
    labels.GetSemanticDataAttr().Set(semantic_label)


def get_stage(stage_path: Optional[str] = None) -> Usd.Stage:
    """Open ``stage_path`` or return the current Isaac Sim stage."""

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


def is_prim_visible(prim: Usd.Prim) -> bool:
    """Return false when ``prim`` or one of its ancestors is invisible."""

    while prim and not prim.IsPseudoRoot():
        if UsdGeom.Imageable(prim).GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible:
            return False
        prim = prim.GetParent()
    return True


def _category_for_path(path: str) -> Optional[str]:
    lower_path = path.lower()
    if "box" in lower_path:
        for category, pattern in PATTERNS.items():
            if pattern is not None and pattern.search(lower_path):
                return category
            if pattern is None and category in lower_path:
                return category
        return "other"
    if (
        "crate" in lower_path
        and "woodencrate" not in lower_path
        and not EXCLUDED_CRATE_PATTERN.search(lower_path)
    ):
        return "basket"
    return None


def categorize_boxes(
    stage: Usd.Stage,
    *,
    apply_labels: bool = False,
    semantic_class: str = "class",
    include_hidden: bool = False,
) -> Tuple[Dict[str, List[str]], List[str]]:
    """Return categorized mesh paths and hidden matching paths."""

    categorized: DefaultDict[str, List[str]] = defaultdict(list)
    hidden: List[str] = []
    for prim in stage.Traverse():
        if prim.GetTypeName() != "Mesh":
            continue
        category = _category_for_path(str(prim.GetPath()))
        if category is None:
            continue
        if not is_prim_visible(prim):
            hidden.append(str(prim.GetPath()))
            if not include_hidden:
                continue
        categorized[category].append(str(prim.GetPath()))
        if apply_labels:
            enable_semantics(prim, category, semantic_class)
    return dict(categorized), hidden


def write_report(
    output_path: str, categorized: Dict[str, Iterable[str]], hidden: Iterable[str]
) -> Path:
    """Write the human-readable categorization report and return its path."""

    resolved = Path(output_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    hidden_paths = list(hidden)
    with resolved.open("w", encoding="utf-8") as report:
        report.write("Box Sanity Check Summary (Visible Boxes)\n\n")
        for category, paths_iter in categorized.items():
            paths = list(paths_iter)
            report.write(f"{category}: {len(paths)} boxes\n")
            for path in paths:
                report.write(f"  - {path}\n")
            report.write("\n")
        if hidden_paths:
            report.write(f"Hidden Boxes: {len(hidden_paths)}\n")
            for path in hidden_paths:
                report.write(f"  - {path}\n")
    return resolved


def run(
    *,
    output_path: str,
    stage_path: Optional[str] = None,
    apply_labels: bool = False,
    semantic_class: str = "class",
    include_hidden: bool = False,
) -> Tuple[Dict[str, List[str]], List[str]]:
    """Run categorization against a file-backed or current Isaac Sim stage."""

    stage = get_stage(stage_path)
    categorized, hidden = categorize_boxes(
        stage,
        apply_labels=apply_labels,
        semantic_class=semantic_class,
        include_hidden=include_hidden,
    )
    report = write_report(output_path, categorized, hidden)
    if apply_labels and stage_path:
        stage.GetRootLayer().Save()
    for category, paths in categorized.items():
        print(f"{category}: {len(paths)} boxes")
    print(f"Hidden Boxes: {len(hidden)}")
    print(f"Report written to: {report}")
    return categorized, hidden


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", help="USD file to inspect; omit only inside Isaac Sim Script Editor"
    )
    parser.add_argument(
        "--output",
        default=USER_OUTPUT_PATH,
        help="report path (required unless USER_OUTPUT_PATH is set)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="author LabelsAPI labels and save a file-backed stage in place",
    )
    parser.add_argument("--semantic-class", default="class")
    parser.add_argument("--include-hidden", action="store_true")
    args = parser.parse_args()
    if not args.output:
        parser.error("--output is required unless USER_OUTPUT_PATH is set")
    run(
        output_path=args.output,
        stage_path=args.stage,
        apply_labels=args.apply,
        semantic_class=args.semantic_class,
        include_hidden=args.include_hidden,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
