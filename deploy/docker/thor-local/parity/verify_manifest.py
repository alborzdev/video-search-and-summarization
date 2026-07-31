#!/usr/bin/env python3

"""Validate and report the Thor VSS feature-parity acceptance ledger."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
MANIFEST = SCRIPT_DIR / "manifest.json"


def fail(message: str) -> None:
    raise ValueError(message)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def validate() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        fail("schema_version must be 1")

    target = data.get("upstream", {}).get("target_commit", "")
    if len(target) != 40 or any(char not in "0123456789abcdef" for char in target):
        fail("upstream.target_commit must be a lowercase 40-character Git SHA")
    ancestor = git("merge-base", "--is-ancestor", target, "HEAD")
    if ancestor.returncode != 0:
        fail(f"target upstream commit {target} is not an ancestor of HEAD")

    profile_env = (
        REPO_ROOT / "deploy/docker/developer-profiles/dev-profile-thor-full/.env"
    ).read_text(encoding="utf-8").splitlines()
    required_release_pins = {
        "PERCEPTION_TAG=3.2.1",
        "RTVI_EMBED_TAG=3.2.1",
        "RTVI_VLM_IMAGE_TAG=3.2.1",
        "VST_STREAM_PROCESSOR_IMAGE_TAG=3.2.1",
        "VST_SENSOR_IMAGE_TAG=3.2.1",
        "NVSTREAMER_IMAGE_TAG=3.2.1",
        "VST_INGRESS_IMAGE_TAG=3.2.1",
        "VSS_AGENT_VERSION=3.2.1",
        "LVS_TAG=3.2.1",
        "LVS_ENABLE_MCP=true",
    }
    missing_pins = required_release_pins - set(profile_env)
    if missing_pins:
        fail(f"Thor profile is missing current release pins: {sorted(missing_pins)}")

    lvs_source = (REPO_ROOT / "services/video-summarization/src/via_server.py").read_text(
        encoding="utf-8"
    )
    if "purpose: Annotated[\n                Purpose," not in lvs_source:
        fail("the current upstream LVS invalid-purpose 422 fix is absent")

    allowed_thor = set(data["status_contract"]["thor_state"])
    allowed_runtime = set(data["status_contract"]["runtime_state"])
    allowed_acceptance = set(data["status_contract"]["acceptance_class"])
    features = data.get("features", [])
    if len(features) < 30:
        fail("the advertised feature ledger must contain at least 30 feature families")

    seen: set[str] = set()
    for feature in features:
        feature_id = feature.get("id", "")
        if not feature_id or feature_id in seen:
            fail(f"feature id is empty or duplicated: {feature_id!r}")
        seen.add(feature_id)
        if not feature.get("advertised"):
            fail(f"{feature_id}: advertised feature list is empty")
        if feature.get("thor_state") not in allowed_thor:
            fail(f"{feature_id}: invalid thor_state {feature.get('thor_state')!r}")
        if feature.get("runtime_state") not in allowed_runtime:
            fail(f"{feature_id}: invalid runtime_state {feature.get('runtime_state')!r}")
        acceptance_class = feature.get("acceptance_class")
        if acceptance_class not in allowed_acceptance:
            fail(f"{feature_id}: invalid acceptance_class {acceptance_class!r}")
        if acceptance_class == "external_optional":
            if feature["thor_state"] != "external_optional":
                fail(f"{feature_id}: external_optional must use thor_state=external_optional")
            if feature["runtime_state"] != "not_applicable":
                fail(f"{feature_id}: external_optional must use runtime_state=not_applicable")
            if not feature.get("external_dependency"):
                fail(f"{feature_id}: external_optional requires external_dependency")
            if not feature.get("boundary_reason"):
                fail(f"{feature_id}: external_optional requires boundary_reason")
        elif feature["thor_state"] == "external_optional" or feature["runtime_state"] == "not_applicable":
            fail(
                f"{feature_id}: local acceptance classes cannot use "
                "external_optional/not_applicable states"
            )
        if not feature.get("source_evidence"):
            fail(f"{feature_id}: source_evidence is empty")
        for evidence_type in ("source_evidence", "thor_evidence"):
            for relative in feature.get(evidence_type, []):
                if Path(relative).is_absolute() or ".." in Path(relative).parts:
                    fail(f"{feature_id}: unsafe {evidence_type} path {relative!r}")
                if not (REPO_ROOT / relative).exists():
                    fail(f"{feature_id}: missing {evidence_type} path {relative!r}")
        if feature["thor_state"] in {"partial", "source_only", "blocked_upstream"} and not feature.get("gap"):
            fail(f"{feature_id}: open work requires a non-empty gap")

    skills = data.get("skills", [])
    if len(skills) != 16:
        fail(f"expected the complete 16-skill catalog, found {len(skills)}")
    skill_ids = {skill.get("id", "") for skill in skills}
    if len(skill_ids) != 16:
        fail("skill ids must be non-empty and unique")
    disk_skills = {
        path.parent.name for path in (REPO_ROOT / "skills").glob("*/SKILL.md")
    }
    if skill_ids != disk_skills:
        fail(
            "manifest skill catalog differs from the checkout: "
            f"missing={sorted(disk_skills - skill_ids)}, extra={sorted(skill_ids - disk_skills)}"
        )
    for skill in skills:
        if skill.get("thor_state") not in allowed_thor:
            fail(f"{skill['id']}: invalid thor_state")
        if skill.get("runtime_state") not in allowed_runtime:
            fail(f"{skill['id']}: invalid runtime_state")

    return data


def report(data: dict) -> None:
    features = data["features"]
    thor_counts = Counter(feature["thor_state"] for feature in features)
    runtime_counts = Counter(feature["runtime_state"] for feature in features)
    acceptance_counts = Counter(feature["acceptance_class"] for feature in features)
    advertised_count = sum(len(feature["advertised"]) for feature in features)
    print(
        f"Target: {data['upstream']['latest_ga']} + upstream/main "
        f"{data['upstream']['target_commit'][:12]}"
    )
    print(
        f"Ledger: {len(features)} families, {advertised_count} advertised capabilities, "
        f"{len(data['skills'])} skills"
    )
    print("Thor state: " + ", ".join(f"{key}={value}" for key, value in sorted(thor_counts.items())))
    print("Runtime: " + ", ".join(f"{key}={value}" for key, value in sorted(runtime_counts.items())))
    print(
        "Acceptance: "
        + ", ".join(f"{key}={value}" for key, value in sorted(acceptance_counts.items()))
    )
    print("\nOpen parity work:")
    for feature in features:
        if feature["acceptance_class"] == "external_optional":
            continue
        if feature["thor_state"] != "wired" or feature["runtime_state"] != "passed_current":
            print(
                f"- {feature['id']}: {feature['thor_state']}/{feature['runtime_state']} — "
                f"{feature['gap']}"
            )
    print("\nExternal optional boundaries:")
    for feature in features:
        if feature["acceptance_class"] == "external_optional":
            print(
                f"- {feature['id']}: {feature['thor_state']}/{feature['runtime_state']} — "
                f"{feature['boundary_reason']} Dependency: {feature['external_dependency']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print status counts and all open gaps")
    args = parser.parse_args()
    try:
        data = validate()
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: Thor VSS parity manifest is structurally complete and matches this checkout")
    if args.report:
        report(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
