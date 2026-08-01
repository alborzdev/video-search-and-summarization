#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate the isolated VSS curated prerelease candidate watchlist offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[5]
MANIFEST_PATH = HERE / "manifest.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"

UPSTREAM_REPOSITORY = (
    "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization"
)
STABLE_MAIN_SHA = "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
STABLE_RELEASE_SHA = "7640d917047cf7b0fd3085eefb8282754b56bc94"
PRERELEASE_SHA = "708dac2ff071c76971d5cc8cab24f3879e6aac63"
EXPECTED_MANIFEST_CANONICAL_SHA256 = (
    "cc0c9be534b3a3db1d72a5768cc416d17740a1fe922198dd649c1cbd6de46b70"
)

EXPECTED_POINTERS: dict[str, tuple[tuple[str, str], ...]] = {
    "build-vision-agent": (
        (
            "skills/vss-build-vision-agent/SKILL.md",
            "e740d35f2f90af386dcf706c68fc06c132d87934",
        ),
        (
            "skills/vss-build-vision-agent/references/composition.md",
            "e740d35f2f90af386dcf706c68fc06c132d87934",
        ),
        (
            "skills/vss-build-vision-agent/references/edge.md",
            "e740d35f2f90af386dcf706c68fc06c132d87934",
        ),
    ),
    "search-architecture": (
        (
            "skills/vss-search-archive/SKILL.md",
            "381926e7f87340fa201b6bff5f77caa136bd13ed",
        ),
        (
            "deploy/docker/developer-profiles/dev-profile-search/overrides.env",
            "fef33284139da3a99443683fb4079221a0700dfa",
        ),
        (
            "deploy/docker/developer-profiles/dev-profile-search/vss-agent/configs/config.yml",
            "53ce65d0b79606ece2237713291922db8600e5dc",
        ),
    ),
    "graph-rag": (
        (
            "services/agent/packages/vss_core/src/vss_core/knowledge/adapters/arango_graph.py",
            "27d9d2736142226805a184f9b325ca64793c1882",
        ),
        (
            "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config_rag.yml",
            "27d9d2736142226805a184f9b325ca64793c1882",
        ),
    ),
    "alerts-workflows": (
        (
            "services/alert/src/realtime/services/incident_service.py",
            "2748aaa312394388fdeabe2bbbd2c00bec4aa94a",
        ),
        (
            "services/alert/src/handlers/event_loop_pipeline_mixin.py",
            "2561a206734dd83de63902956782127b347eed61",
        ),
        (
            "services/alert/src/metrics/prometheus_metrics.py",
            "1634f43741542e2ef7a4818801fe28dc39840e52",
        ),
        (
            "skills/vss-manage-alerts/SKILL.md",
            "ad68ee6ebd706a5678194bd4e75905bbbc6f01bf",
        ),
    ),
    "behavior-analytics": (
        (
            "services/analytics/behavior-analytics/apps/uber/main_uber_app.py",
            "ba9309b459068972cc15f2c701c0303485767987",
        ),
        (
            "services/analytics/behavior-analytics/configs/uber_config.json",
            "ba9309b459068972cc15f2c701c0303485767987",
        ),
        (
            "skills/vss-setup-behavior-analytics/SKILL.md",
            "9d9f4ca59e36f3452c6aac12960a53de22edf895",
        ),
    ),
    "vios-webrtc-ui": (
        (
            "services/vios/configs/notification_config.json",
            "2aadf9548c696f069a89e7596946a5785b28a95b",
        ),
        (
            "services/vios/src/framework/media/media_pipelines/gstnvaudiodecoder.cpp",
            "e91788f6198793c15098fa3db808c00a0332ea74",
        ),
        (
            "services/vios/ui/vios-ui/src/components/videoPlayer/VideoPlayer.tsx",
            "743a0ee14fabe393f0bada12b9d16b6f887edb81",
        ),
        (
            "deploy/docker/services/vios/scripts/apply_turn_config.sh",
            "3e2ac404591d0657f1bfb3a826215d90fc4db88d",
        ),
    ),
    "reports-sop": (
        (
            "skills/vss-generate-video-report/SKILL.md",
            "6c114839ddfec31e4cded8854b2e1952308381ed",
        ),
        (
            "skills/vss-build-vision-agent/references/services/sop.md",
            "b982b2680ed3f316f544a5694f8bcaef60f73274",
        ),
        (
            "skills/vss-generate-video-report/references/report-templates/sop-compliance-report.md",
            "b982b2680ed3f316f544a5694f8bcaef60f73274",
        ),
    ),
    "lvs-index-api": (
        (
            "services/video-summarization/src/via_server.py",
            "13e1dda785140bcc6231d950dc6bfa66e7a4572b",
        ),
        (
            "services/video-summarization/src/vss_api_models.py",
            "13e1dda785140bcc6231d950dc6bfa66e7a4572b",
        ),
    ),
    "agent-ui-vlm-verification": (
        (
            "services/ui/packages/nv-metropolis-bp-vss-ui/alerts/lib-src/AlertsComponent.tsx",
            "30283056fd838748f81a54ec8eeed2bebe774438",
        ),
        (
            "services/ui/packages/nv-metropolis-bp-vss-ui/alerts/lib-src/components/AlertsTable.tsx",
            "30283056fd838748f81a54ec8eeed2bebe774438",
        ),
    ),
    "profile-compose-inversion": (
        ("deploy/docker/containers.env", "2dad5db7bb14311450cd381c4278ac56e9d85ca8"),
        (
            "deploy/docker/developer-profiles/dev-profile-base/overrides.env",
            "2dad5db7bb14311450cd381c4278ac56e9d85ca8",
        ),
        (
            "deploy/docker/services/rtvi/rtvi-cv/download-models.sh",
            "cb366e72fde3984def9f958642bdf87f1c1f4923",
        ),
    ),
    "thor-aarch64-multiarch": (
        (
            "services/vios/cicd_files/aarch64/Dockerfile.app",
            "91cc11e3b8d6dc7cbd31bd65a0ee55b5da632099",
        ),
        ("services/vios/build.sh", "781d88f9806b6314b3940186955f05fc274f10ee"),
    ),
    "sdrc-configurator": (
        ("services/sdrc/README.md", "01384d0ae20c153cb0742c3f464c1b0b25c9f753"),
        (
            "services/analytics/vss-configurator/README.md",
            "01384d0ae20c153cb0742c3f464c1b0b25c9f753",
        ),
        (
            "services/analytics/vss-rt-config-adaptor/README.md",
            "01384d0ae20c153cb0742c3f464c1b0b25c9f753",
        ),
    ),
    "kubernetes-helm": (
        (
            "skills/vss-build-vision-agent/references/deployment_resolution.md",
            "42d92840ac9ced25d561d8053d446c9a77cbdce3",
        ),
        (
            "deploy/helm/industry-profiles/warehouse-operations/warehouse-2d-app/values.yaml",
            "ee50193cbb47ec3ccbe20a86865b8ff942943093",
        ),
        (
            "deploy/helm/developer-profiles/dev-profile-search/values.yaml",
            "e58288a0ad06e0a2baec64410312fe6b4ff94fa0",
        ),
    ),
    "nemoclaw-mcp-orchestration": (
        (
            "deploy/docker/scripts/deploy_nemoclaw.ipynb",
            "11f73ac2acca6e988b9bd2a2759a38a143787700",
        ),
        (
            "deploy/docker/scripts/deploy_vss_orchestrator.ipynb",
            "11f73ac2acca6e988b9bd2a2759a38a143787700",
        ),
        (
            "services/agent/packages/vss_agents/src/vss_agents/orchestrator/mcp_ssl_worker.py",
            "74f88bb2cbe77d5abf4e44bd78908f0718c3ffb5",
        ),
    ),
}

EXPECTED_EXCEPTIONS = {
    "build-vision-agent": (
        "deprecated-thor-edge-4b",
        "conflict",
    ),
    "sdrc-configurator": (
        "warehouse-sample-bundle",
        "excluded",
    ),
}


class WatchlistError(RuntimeError):
    """The prerelease watchlist is malformed or has drifted."""


def _load(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise WatchlistError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WatchlistError(f"cannot load JSON {path}: {exc}") from exc


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _load(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise WatchlistError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise WatchlistError(
            f"{label} schema validation failed at {location}: {error.message}"
        )


def _safe_source_path(raw: str) -> None:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or raw.startswith("./"):
        raise WatchlistError(f"unsafe upstream source path: {raw}")


def _assert_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise WatchlistError(f"duplicate {label}")


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _contains_forbidden_status(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_forbidden_status(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_status(item) for item in value)
    return value == "passed_current"


def validate_manifest() -> dict[str, Any]:
    manifest = _load(MANIFEST_PATH)
    _validate_schema(manifest, MANIFEST_SCHEMA_PATH, "manifest")

    upstream = manifest["upstream_locks"]
    expected_upstream = {
        "repository": UPSTREAM_REPOSITORY,
        "stable_main_sha": STABLE_MAIN_SHA,
        "stable_release_tag": "v3.2.1",
        "stable_release_peeled_sha": STABLE_RELEASE_SHA,
        "prerelease_branch": "develop",
        "prerelease_sha": PRERELEASE_SHA,
        "nightly_tag": "nightly-20260801",
        "nightly_sha": PRERELEASE_SHA,
        "declared_prerelease_version": "3.3.0",
        "merge_base_sha": STABLE_RELEASE_SHA,
        "compare_url": f"{UPSTREAM_REPOSITORY}/compare/{STABLE_MAIN_SHA}...{PRERELEASE_SHA}",
    }
    if upstream != expected_upstream:
        raise WatchlistError("upstream ref lock set drifted")

    policies = manifest["policies"]
    if any(
        policies[key]
        for key in (
            "official_baseline",
            "live_ledger_mutation_allowed",
            "runtime_evidence_allowed",
            "promotion_allowed",
            "passed_current_allowed",
            "network_required",
            "local_develop_checkout_required",
            "warehouse_sample_required",
        )
    ):
        raise WatchlistError("nonadvancing policy must remain false")

    families = manifest["families"]
    family_ids = [item["family_id"] for item in families]
    if family_ids != list(EXPECTED_POINTERS):
        raise WatchlistError("14-family order or identity set drifted")
    _assert_unique(family_ids, "family_id")

    all_evidence_ids: list[str] = []
    all_paths: list[str] = []
    observed_exceptions: dict[str, tuple[str, str]] = {}
    for family in families:
        family_id = family["family_id"]
        if family["static_disposition"] != "candidate_static":
            raise WatchlistError(f"static disposition drifted for {family_id}")
        if family["runtime_disposition"] != "runtime_watchlist":
            raise WatchlistError(f"runtime disposition drifted for {family_id}")

        pointers = family["source_pointers"]
        for pointer in pointers:
            _safe_source_path(pointer["path"])
        observed = tuple(
            (pointer["path"], pointer["introducing_commit"]) for pointer in pointers
        )
        if observed != EXPECTED_POINTERS[family_id]:
            raise WatchlistError(f"source pointer set drifted for {family_id}")
        for pointer in pointers:
            expected_source_url = (
                f"{UPSTREAM_REPOSITORY}/blob/{PRERELEASE_SHA}/{pointer['path']}"
            )
            expected_commit_url = (
                f"{UPSTREAM_REPOSITORY}/commit/{pointer['introducing_commit']}"
            )
            if pointer["source_ref"] != PRERELEASE_SHA:
                raise WatchlistError(f"source ref drifted for {pointer['evidence_id']}")
            if pointer["source_url"] != expected_source_url:
                raise WatchlistError(f"source URL drifted for {pointer['evidence_id']}")
            if pointer["introducing_commit_url"] != expected_commit_url:
                raise WatchlistError(f"commit URL drifted for {pointer['evidence_id']}")
            all_evidence_ids.append(pointer["evidence_id"])
            all_paths.append(pointer["path"])

        exceptions = family["exceptions"]
        if exceptions:
            if len(exceptions) != 1:
                raise WatchlistError(f"exception cardinality drifted for {family_id}")
            exception = exceptions[0]
            observed_exceptions[family_id] = (
                exception["exception_id"],
                exception["disposition"],
            )

    _assert_unique(all_evidence_ids, "evidence_id")
    _assert_unique(all_paths, "upstream source path")
    if observed_exceptions != EXPECTED_EXCEPTIONS:
        raise WatchlistError("excluded/conflict exception set drifted")
    if _contains_forbidden_status(families):
        raise WatchlistError("prerelease family cannot claim passed_current")
    if _canonical_sha256(manifest) != EXPECTED_MANIFEST_CANONICAL_SHA256:
        raise WatchlistError("canonical manifest lock drifted")

    result = {
        "schema_version": 1,
        "scope": "isolated_prerelease_watchlist",
        "upstream_prerelease_sha": PRERELEASE_SHA,
        "qualification_ceiling": "locked_remote_pointers_only",
        "official_baseline_status": "unchanged",
        "coverage_limit": {
            "selection_basis": "curated_prerelease_candidate_watchlist",
            "authoritative_full_diff_denominator": None,
            "exhaustive_develop_coverage_claimed": False,
            "coverage_fraction": "not_computable",
        },
        "counts": {
            "families": len(families),
            "candidate_static": sum(
                item["static_disposition"] == "candidate_static" for item in families
            ),
            "runtime_watchlist": sum(
                item["runtime_disposition"] == "runtime_watchlist" for item in families
            ),
            "source_pointers": len(all_evidence_ids),
            "excluded_exceptions": sum(
                disposition == "excluded"
                for _, disposition in observed_exceptions.values()
            ),
            "conflict_exceptions": sum(
                disposition == "conflict"
                for _, disposition in observed_exceptions.values()
            ),
            "passed_current_promotions": 0,
        },
        "family_results": [
            {
                "family_id": family["family_id"],
                "static_status": "pointer_locked_candidate",
                "runtime_status": "watchlist_not_executed",
                "source_pointer_count": len(family["source_pointers"]),
                "runtime_evidence": [],
            }
            for family in families
        ],
        "runtime_evidence": [],
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the result JSON")
    args = parser.parse_args()
    try:
        result = validate_manifest()
    except WatchlistError as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            "PASS: prerelease watchlist locks "
            f"{result['counts']['families']} selected candidate families"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
