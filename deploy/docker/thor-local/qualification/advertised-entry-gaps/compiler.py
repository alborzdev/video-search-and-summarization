#!/usr/bin/env python3
"""Compile and validate the exact uncovered advertised-entry planning set."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
MANIFEST_PATH = REPO_ROOT / "deploy/docker/thor-local/parity/manifest.json"
OFFICIAL_CAPABILITIES_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/parity/official-capabilities.json"
)
RULES_PATH = LANE / "classification-rules.json"
RULES_SCHEMA_PATH = LANE / "classification-rules.schema.json"
PLAN_SCHEMA_PATH = LANE / "plan.schema.json"
PLAN_PATH = LANE / "plan.json"

MANIFEST_RAW_SHA256 = "879d683f9ad22ace194f5c818361418bc9027d7011cb4fa9d6f9a4af738cacba"
MANIFEST_CANONICAL_SHA256 = (
    "9b955d9f68fdf5f413e48b92653861b0d56933b1803e84d145e1eafff93f7e6c"
)
OFFICIAL_CAPABILITIES_RAW_SHA256 = (
    "65241b3ad56f5d9bb817ba040c06abdbfe034701be645c845d94e4f065514f0e"
)
OFFICIAL_CAPABILITIES_CANONICAL_SHA256 = (
    "792dde11c6d6b8f75e5323250a75c5743fe47e6500c80cb27673a3c1d6b2c5c3"
)
RULES_RAW_SHA256 = "8b32b2fcfa8e669d1b45408c7a8e04c238e54c590be2b5bc24b3506ae1449314"
RULES_CANONICAL_SHA256 = (
    "631cccf7d20b68f82bdb384f36b2c409e26abe26fe4c1425b740bad1f2ba77d6"
)
RULES_SCHEMA_RAW_SHA256 = (
    "ad5e7c6c5d2a6760aee0909ea805bbcbceb4adcd8bce600429e0b67ab7126c0b"
)
PLAN_SCHEMA_RAW_SHA256 = (
    "17dff277b38f1a0ca30055c94e0d96f7a8ee3087bfb4aa2de428065ebebd818c"
)
EXPECTED_PLAN_PAYLOAD_SHA256 = (
    "a50231e6de3b97cd551a46c32a317e83c71cff2ca27eb22a0363d92e756587d4"
)
EXPECTED_PLAN_RAW_SHA256 = (
    "9ea23d0e84c22f913024035b92633c173e46bce61e7b80ddc6af376d0e389239"
)
EXPECTED_FAMILY_IDS = {
    "video-summarization-live",
    "search-scale",
    "alert-notifications-slack",
    "rt-vlm-media",
    "rt-vlm-api",
    "rt-vlm-models",
    "rt-vlm-performance-observability",
    "rt-cv-3d-sparse4d",
    "rt-cv-3d-mv3dt",
    "vios-codecs-audio",
    "audio-understanding",
    "vios-ui",
    "agent-and-mcp-apis",
    "spatial-ai-utils",
    "synthetic-data-tools",
    "enterprise-rag",
}
MIGRATED_ENTRY_CAPABILITY_IDS = {
    "manifest-entry.vios-codecs-audio.05-cpu-multimedia-support",
}
CUSTOM_DATA_FAMILIES = {"rt-cv-3d-sparse4d", "rt-cv-3d-mv3dt"}
EXCLUDED_SAMPLE_MARKERS = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
)


class CompileError(RuntimeError):
    """Fail-closed input, schema, denominator, or output error."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _strict_json(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CompileError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompileError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _load_locked_json(
    path: Path, raw_sha256: str | None = None, canonical_sha256: str | None = None
) -> Any:
    if path.is_symlink() or not path.is_file():
        raise CompileError(f"not a regular package/source file: {path}")
    payload = path.read_bytes()
    if raw_sha256 is not None and _sha_bytes(payload) != raw_sha256:
        raise CompileError(f"raw digest drift: {path}")
    value = _strict_json(payload, str(path))
    if canonical_sha256 is not None and _sha_json(value) != canonical_sha256:
        raise CompileError(f"canonical digest drift: {path}")
    return value


def _schema_errors(instance: Any, schema: Any) -> list[str]:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    return [
        f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in errors
    ]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:56].rstrip("-") or "entry"


def _literal_success_condition(
    advertised: str, oracle_type: str, executor_class: str
) -> str:
    if oracle_type == "external_optional_boundary":
        return (
            f'Observe and correlate the literal advertised behavior "{advertised}" '
            "against the user-managed external system with explicit authorization; "
            "a local mock, source presence, or family-lane pass is not sufficient."
        )
    if oracle_type == "runtime_scale_benchmark":
        return (
            f'Execute the exact advertised scale claim "{advertised}" on Thor and '
            "capture per-stream correctness plus latency and resource measurements; "
            "a configuration value or NVIDIA reference row alone is not sufficient."
        )
    if oracle_type == "runtime_custom_data_multicamera":
        return (
            f'Execute and semantically verify "{advertised}" with tiny '
            "operator-supplied custom multiview data and matching calibration; the "
            "excluded Warehouse sample bundle and family-lane status are not evidence."
        )
    if oracle_type == "offline_tool_execution":
        return (
            f'Run the tool path for "{advertised}" on a digest-bound tiny input and '
            "semantically validate its output; importability or source presence alone "
            "is not sufficient."
        )
    if oracle_type == "runtime_browser_interaction":
        return (
            f'Complete the browser interaction for "{advertised}" and correlate the '
            "rendered result with backend state; route presence or a screenshot alone "
            "is not sufficient."
        )
    return (
        f'Directly execute and semantically verify "{advertised}" through '
        f"{executor_class}; source presence or a family-lane pass is not sufficient."
    )


def _entry_rule(family_rule: dict[str, Any], advertised: str) -> dict[str, Any]:
    result = {
        key: family_rule[key]
        for key in (
            "capability_kind",
            "oracle_type",
            "executor_class",
            "required_evidence",
            "setup_requirements",
            "cleanup_policy",
        )
    }
    override = family_rule.get("entry_overrides", {}).get(advertised)
    if override:
        result.update(override)
    return result


def compile_plan() -> dict[str, Any]:
    manifest = _load_locked_json(
        MANIFEST_PATH, MANIFEST_RAW_SHA256, MANIFEST_CANONICAL_SHA256
    )
    official = _load_locked_json(
        OFFICIAL_CAPABILITIES_PATH,
        OFFICIAL_CAPABILITIES_RAW_SHA256,
        OFFICIAL_CAPABILITIES_CANONICAL_SHA256,
    )
    rules = _load_locked_json(RULES_PATH, RULES_RAW_SHA256, RULES_CANONICAL_SHA256)
    rules_schema = _load_locked_json(RULES_SCHEMA_PATH, RULES_SCHEMA_RAW_SHA256)
    rule_errors = _schema_errors(rules, rules_schema)
    if rule_errors:
        raise CompileError(
            f"classification rules schema failed: {'; '.join(rule_errors[:5])}"
        )
    if len(manifest.get("features", [])) != 55:
        raise CompileError("manifest feature denominator drift")

    capabilities = official.get("capabilities")
    if not isinstance(capabilities, list):
        raise CompileError("official capability ledger is malformed")
    capability_by_id = {
        item.get("id"): item for item in capabilities if isinstance(item, dict)
    }
    if len(capability_by_id) != len(capabilities):
        raise CompileError("official capability identity denominator drift")

    uncovered: list[tuple[int, dict[str, Any], list[tuple[int, str]]]] = []
    for family_index, feature in enumerate(manifest["features"]):
        ids = feature.get("official_capability_ids", [])
        if not isinstance(ids, list):
            raise CompileError(
                f"official_capability_ids is not a list: {feature.get('id')}"
            )
        if any(capability_id not in capability_by_id for capability_id in ids):
            raise CompileError(
                f"manifest capability binding is absent from ledger: {feature.get('id')}"
            )
        if ids and not set(ids) <= MIGRATED_ENTRY_CAPABILITY_IDS:
            continue
        canonical_titles = {
            capability_by_id[capability_id].get("title") for capability_id in ids
        }
        missing = [
            (advertised_index, advertised)
            for advertised_index, advertised in enumerate(feature.get("advertised", []))
            if advertised not in canonical_titles
        ]
        if missing:
            uncovered.append((family_index, feature, missing))
    if len(uncovered) != 16:
        raise CompileError("uncovered family denominator drift")
    uncovered_ids = {feature["id"] for _, feature, _ in uncovered}
    if uncovered_ids != EXPECTED_FAMILY_IDS:
        raise CompileError("uncovered family identity drift")
    if set(rules["family_rules"]) != uncovered_ids:
        raise CompileError(
            "classification rules do not exactly cover uncovered families"
        )

    entries: list[dict[str, Any]] = []
    families: list[dict[str, Any]] = []
    used_overrides: set[tuple[str, str]] = set()
    for family_index, feature, missing_entries in uncovered:
        family_id = feature["id"]
        official_capability_ids = feature.get("official_capability_ids", [])
        official_state = "partial" if official_capability_ids else "absent"
        family_pointer = f"/features/{family_index}"
        family_hash = _sha_json(feature)
        family_rule = rules["family_rules"][family_id]
        entry_ids: list[str] = []
        for advertised_index, advertised in missing_entries:
            if not isinstance(advertised, str) or not advertised:
                raise CompileError(f"invalid advertised entry: {family_pointer}")
            entry_id = (
                f"manifest-gap.{family_id}.{advertised_index:02d}-{_slug(advertised)}"
            )
            entry_pointer = f"{family_pointer}/advertised/{advertised_index}"
            selected = _entry_rule(family_rule, advertised)
            if advertised in family_rule.get("entry_overrides", {}):
                used_overrides.add((family_id, advertised))
            acceptance_class = feature["acceptance_class"]
            if selected["oracle_type"] == "external_optional_boundary":
                acceptance_class = "external_optional"
            custom_data = family_id in CUSTOM_DATA_FAMILIES
            entry_ids.append(entry_id)
            entries.append(
                {
                    "entry_id": entry_id,
                    "manifest_pointer": entry_pointer,
                    "family_pointer": family_pointer,
                    "family_index": family_index,
                    "advertised_index": advertised_index,
                    "family_id": family_id,
                    "advertised": advertised,
                    "advertised_utf8_sha256": _sha_bytes(advertised.encode("utf-8")),
                    "advertised_canonical_sha256": _sha_json(advertised),
                    "family_canonical_sha256": family_hash,
                    "family_acceptance_class": feature["acceptance_class"],
                    "family_category": feature["category"],
                    "family_runtime_state_snapshot": feature["runtime_state"],
                    "family_thor_state_snapshot": feature["thor_state"],
                    "official_capability_ids_state": official_state,
                    "family_lane_binding_is_semantic_coverage": False,
                    "coverage_state": "open_missing_entry_capability_and_oracle",
                    "proposed_capability": {
                        "id": f"manifest-entry.{family_id}.{advertised_index:02d}-{_slug(advertised)}",
                        "kind": selected["capability_kind"],
                        "acceptance_class": acceptance_class,
                        "literal_scope": advertised,
                    },
                    "required_oracle": {
                        "id": f"oracle.manifest-entry.{family_id}.{advertised_index:02d}",
                        "type": selected["oracle_type"],
                        "executor_class": selected["executor_class"],
                        "status": "open_unexecuted",
                        "setup_requirements": selected["setup_requirements"],
                        "required_evidence": selected["required_evidence"],
                        "literal_success_condition": _literal_success_condition(
                            advertised,
                            selected["oracle_type"],
                            selected["executor_class"],
                        ),
                        "cleanup_policy": selected["cleanup_policy"],
                        "runtime_evidence": [],
                    },
                    "warehouse_scope": {
                        "sample_bundle_required": False,
                        "custom_data_capability_in_scope": custom_data,
                    },
                    "runtime_evidence": [],
                }
            )
        families.append(
            {
                "family_id": family_id,
                "manifest_pointer": family_pointer,
                "family_index": family_index,
                "family_canonical_sha256": family_hash,
                "advertised_entry_count": len(feature["advertised"]),
                "uncovered_advertised_entry_count": len(missing_entries),
                "covered_advertised_entry_count": (
                    len(feature["advertised"]) - len(missing_entries)
                ),
                "official_capability_ids": official_capability_ids,
                "official_capability_ids_state": official_state,
                "family_lane_binding_is_semantic_coverage": False,
                "family_runtime_state_snapshot": feature["runtime_state"],
                "family_thor_state_snapshot": feature["thor_state"],
                "entry_ids": entry_ids,
            }
        )

    declared_overrides = {
        (family_id, advertised)
        for family_id, family_rule in rules["family_rules"].items()
        for advertised in family_rule.get("entry_overrides", {})
    }
    if used_overrides != declared_overrides:
        raise CompileError(
            "one or more entry overrides do not bind an exact manifest string"
        )
    if len(entries) != 86 or len({item["entry_id"] for item in entries}) != 86:
        raise CompileError("advertised entry denominator or identity drift")
    if len({item["manifest_pointer"] for item in entries}) != 86:
        raise CompileError("manifest entry pointers are not unique")

    acceptance_counts = Counter(
        item["proposed_capability"]["acceptance_class"] for item in entries
    )
    oracle_counts = Counter(item["required_oracle"]["type"] for item in entries)
    plan: dict[str, Any] = {
        "schema_version": 1,
        "mode": "isolated_advertised_entry_gap_planning",
        "source_locks": {
            "manifest": {
                "path": "deploy/docker/thor-local/parity/manifest.json",
                "raw_sha256": MANIFEST_RAW_SHA256,
                "canonical_sha256": MANIFEST_CANONICAL_SHA256,
            },
            "classification_rules": {
                "path": "deploy/docker/thor-local/qualification/advertised-entry-gaps/classification-rules.json",
                "raw_sha256": RULES_RAW_SHA256,
                "canonical_sha256": RULES_CANONICAL_SHA256,
            },
            "official_capabilities": {
                "path": "deploy/docker/thor-local/parity/official-capabilities.json",
                "raw_sha256": OFFICIAL_CAPABILITIES_RAW_SHA256,
                "canonical_sha256": OFFICIAL_CAPABILITIES_CANONICAL_SHA256,
            },
        },
        "policy": {
            "planning_only": True,
            "family_lane_binding_is_semantic_coverage": False,
            "runtime_evidence": [],
            "can_mark_passed_current": False,
            "warehouse_sample_bundle": "excluded",
            "custom_data_warehouse_capability": "in_scope",
        },
        "summary": {
            "manifest_family_count": 55,
            "families_with_uncovered_advertised_entries": len(families),
            "families_without_official_capability_ids": sum(
                item["official_capability_ids_state"] == "absent" for item in families
            ),
            "families_with_partial_official_capability_ids": sum(
                item["official_capability_ids_state"] == "partial" for item in families
            ),
            "advertised_entries_without_official_capability_ids": len(entries),
            "open_unverified_entries": len(entries),
            "runtime_evidence_count": 0,
            "acceptance_class_counts": dict(sorted(acceptance_counts.items())),
            "oracle_type_counts": dict(sorted(oracle_counts.items())),
        },
        "families": families,
        "entries": entries,
    }
    plan["plan_payload_sha256"] = _sha_json(plan)
    return plan


def validate_plan(plan: dict[str, Any], *, enforce_pins: bool = True) -> None:
    schema = _load_locked_json(PLAN_SCHEMA_PATH, PLAN_SCHEMA_RAW_SHA256)
    errors = _schema_errors(plan, schema)
    if errors:
        raise CompileError(f"plan schema failed: {'; '.join(errors[:5])}")
    payload = dict(plan)
    observed_payload_sha = payload.pop("plan_payload_sha256")
    if _sha_json(payload) != observed_payload_sha:
        raise CompileError("plan payload digest mismatch")
    if enforce_pins and EXPECTED_PLAN_PAYLOAD_SHA256 != "TO_BE_PINNED":
        if observed_payload_sha != EXPECTED_PLAN_PAYLOAD_SHA256:
            raise CompileError("checked plan payload digest drift")
    if any(item["runtime_evidence"] for item in plan["entries"]):
        raise CompileError("runtime evidence is forbidden in gap planning")
    if any(
        item["family_lane_binding_is_semantic_coverage"] for item in plan["entries"]
    ):
        raise CompileError(
            "family lane binding was misrepresented as semantic coverage"
        )
    for item in plan["entries"]:
        if item["advertised"] != item["proposed_capability"]["literal_scope"]:
            raise CompileError("literal advertised scope drift")


def check_checked_plan() -> dict[str, Any]:
    if not PLAN_PATH.is_file() or PLAN_PATH.is_symlink():
        raise CompileError("checked plan.json is missing or unsafe")
    payload = PLAN_PATH.read_bytes()
    if EXPECTED_PLAN_RAW_SHA256 != "TO_BE_PINNED":
        if _sha_bytes(payload) != EXPECTED_PLAN_RAW_SHA256:
            raise CompileError("checked plan raw digest drift")
    checked = _strict_json(payload, str(PLAN_PATH))
    validate_plan(checked)
    fresh = compile_plan()
    if checked != fresh:
        raise CompileError("checked plan differs from deterministic compilation")
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--output", type=Path)
    subparsers.add_parser("validate")
    subparsers.add_parser("check")
    args = parser.parse_args()
    try:
        if args.command == "compile":
            plan = compile_plan()
            validate_plan(plan, enforce_pins=False)
            rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
            if args.output:
                args.output.write_text(rendered, encoding="utf-8")
            else:
                print(rendered, end="")
        else:
            plan = check_checked_plan()
            print(
                "PASS: exact 16-family / 86-entry advertised gap plan "
                f"validated ({plan['plan_payload_sha256']})"
            )
    except (CompileError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
