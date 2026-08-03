#!/usr/bin/env python3
"""Compile and safely publish the reviewed Agent evaluation contract correction."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
import yaml


sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
BASE_HEAD = "a41c34c5bcd57f9da49f6a08758fd440064624b5"
BASE_TREE = "878148101b38324ee8e956fb3b020848946458d4"
UPSTREAM = "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
TARGET_ID = "evaluation.agent.report"
CONFIG_PATH = (
    "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml"
)
CONFIG_SHA256 = "e89664e421bac7b8869b9dfa1e4149930e11b935bf6dc01351392a6557bb4c79"
EVALUATOR_PATH = "services/agent/src/vss_agents/evaluators/report_evaluator/evaluate.py"
EVALUATOR_SHA256 = "e36fccd2f36e9ea0eceacc49c623eb868b41c68215eac9293e2d6ac15fb4d684"
SOURCE_ID = "main-repository-7732edf8"
SOURCE_CLAIM = {
    "source_id": SOURCE_ID,
    "locator": (
        f"{CONFIG_PATH} at {UPSTREAM}, "
        "eval.evaluators.report_evaluator.metric_configs.llm_judge."
        "llm_name=eval_llm_judge and llms.eval_llm_judge; "
        f"{EVALUATOR_PATH} ReportEvaluatorConfig"
    ),
}
PROFILE = {
    "config_path": CONFIG_PATH,
    "config_raw_sha256": CONFIG_SHA256,
    "llm_profile": "eval_llm_judge",
    "max_tokens": 4096,
    "temperature": 0.0,
    "upstream_commit": UPSTREAM,
}

ROOT_LEDGER = "deploy/docker/thor-local/parity/official-capabilities.json"
ROOT_ORACLE = "deploy/docker/thor-local/parity/capability-oracles.json"
ROOT_MANIFEST = "deploy/docker/thor-local/parity/manifest.json"
SELECTOR = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
WAVE2 = "deploy/docker/thor-local/parity/candidates/wave2/candidate.json"
SELECTED_BASE = "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-successor"
SELECTED_LEDGER = f"{SELECTED_BASE}/post-state-official-capabilities.json"
SELECTED_ORACLE = f"{SELECTED_BASE}/post-state-capability-oracles.json"
SELECTED_MANIFEST = f"{SELECTED_BASE}/post-state-manifest.json"
OFFICIAL_SCHEMA = "deploy/docker/thor-local/parity/official-capabilities.schema.json"
ROOT_ORACLE_SCHEMA = "deploy/docker/thor-local/parity/capability-oracles.schema.json"
V2_ORACLE_SCHEMA = "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.schema.json"
METADATA_SCHEMA = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
SELECTOR_SCHEMA = "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
ROOT_ACCEPTANCE = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
V2_ACCEPTANCE = "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-acceptance-inventory.json"

BASE_SHA256 = {
    ROOT_LEDGER: "92e1c88c5ef9f2fc3f54a4ca2203f8b11e6f1e9b8a24517161c1d634c6a486de",
    ROOT_ORACLE: "cdccc9a21df79a6cb857b51b83c00d07d9e9da2d3a7a32b1c9b480328692821a",
    ROOT_MANIFEST: "1040ba9806ead7050accec09e4be32cd3fb223c804782b49c81683cebbe89c62",
    SELECTOR: "1e7275bdf562aafe2957d4b9d05974be0cce253335cbb8ae86096cb7291e5d4c",
    WAVE2: "db42abe49cd2be32b63a54a7a7a1a5c628ae58e0aa36edaf65fc83600a617384",
    SELECTED_LEDGER: "c910f26b25749d39c8ab51e5b48b0174128c7b018bd0d9e1354bce31bed13162",
    SELECTED_ORACLE: "4c122819bcc9057480e2fc98431f727f2a8b79681989ab95b80af27ad81be4f0",
    SELECTED_MANIFEST: "ec8c6c65bb8f95d81212e175c8c8eb4adf378bcaba91f8e04549a844ac3b5777",
    OFFICIAL_SCHEMA: "71f1e0f1d820c3809ea3b55abb504071321f61c6e36978226dd10108c7b2384b",
    ROOT_ORACLE_SCHEMA: "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1",
    V2_ORACLE_SCHEMA: "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    METADATA_SCHEMA: "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
    SELECTOR_SCHEMA: "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
    ROOT_ACCEPTANCE: "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    V2_ACCEPTANCE: "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
}

OUTPUTS = {
    "ledger_289": PACKAGE / "post-state-root-official-capabilities.json",
    "oracle_289": PACKAGE / "post-state-root-capability-oracles.json",
    "ledger_500": PACKAGE / "post-state-official-capabilities.json",
    "oracle_500": PACKAGE / "post-state-capability-oracles.json",
    "wave2": PACKAGE / "post-state-wave2-candidate.json",
    "descriptor_289": PACKAGE / "post-state-metadata-set-289.json",
    "descriptor_500": PACKAGE / "post-state-metadata-set-500.json",
    "selector": PACKAGE / "post-state-selector.json",
}
CANONICAL = {
    "ledger_289": REPO_ROOT / ROOT_LEDGER,
    "oracle_289": REPO_ROOT / ROOT_ORACLE,
    "wave2": REPO_ROOT / WAVE2,
    "descriptor_289": REPO_ROOT
    / "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-agent-evaluation-contract-289.json",
    "descriptor_500": REPO_ROOT
    / "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-agent-evaluation-contract-500.json",
    "selector": REPO_ROOT / SELECTOR,
}
EXPECTED_OUTPUT_SHA256 = {
    "ledger_289": "b014d103771d630814ca2110ac4d32e108b004d83bbd85b7974b8e9d6b5d69ae",
    "oracle_289": "cff157f7cba86fb62fafb6cbc1ce9f919815e2602ea15f2dbfcc3f2a04d3e647",
    "ledger_500": "0d1acb94ff7cd4913a4469d5244b2fa2b0dcbae0a0b9bc39556603c60f7d3e06",
    "oracle_500": "9c79ce33432c6e1da8ce9c45b21632b881407e3887eb712350794aeac017526a",
    "wave2": "bd8f5e1edd7f41f65a84363420447ee0f2c19754344edb1468aa4d4efba4eac0",
    "descriptor_289": "69f61af1302d284989e66fb5c7287a3fee44e658b517817b7df6672fb8b3dc72",
    "descriptor_500": "c3289aca4fced64a517111f59ed6680566398ec008c0422c50bab0b8e9b8e43a",
    "selector": "43df03877878d6f42dce45a4b403b6a503d8a7500b2176226985d0b600241d6a",
}


class PromotionError(RuntimeError):
    pass


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()


def encode_wave2_minimal(before: dict[str, Any], after: dict[str, Any]) -> bytes:
    """Preserve the locked Wave 2 formatting outside the reviewed row/hash delta."""
    payload = git_blob(BASE_HEAD, WAVE2)
    if sha(payload) != BASE_SHA256[WAVE2] or strict_json(payload, WAVE2) != before:
        raise PromotionError("Wave 2 minimal-encoding baseline differs")

    old_sources = {row["id"]: row for row in before["sources"]}
    new_sources = {row["id"]: row for row in after["sources"]}
    changed_sources = {
        source_id
        for source_id in old_sources
        if old_sources[source_id]["claim_set_sha256"]
        != new_sources[source_id]["claim_set_sha256"]
    }
    if changed_sources != {
        "agent-eval-detail-doc-3.2.1",
        "main-repository-wave2-7732edf8",
    }:
        raise PromotionError("unexpected Wave 2 source hash delta")
    for source_id in sorted(changed_sources):
        old_hash = old_sources[source_id]["claim_set_sha256"].encode()
        new_hash = new_sources[source_id]["claim_set_sha256"].encode()
        if payload.count(old_hash) != 1:
            raise PromotionError(f"Wave 2 source hash is not unique: {source_id}")
        payload = payload.replace(old_hash, new_hash)

    target_prefix = b'    {\n      "target_id": "evaluation.agent.report",'
    start = payload.find(target_prefix)
    if start < 0:
        raise PromotionError("Wave 2 target row is missing")
    end_marker = b"\n    },\n    {"
    end = payload.find(end_marker, start)
    if end < 0:
        raise PromotionError("Wave 2 target row boundary is missing")
    new_row = next(row for row in after["enrichments"] if row["target_id"] == TARGET_ID)
    claims = ",\n        ".join(
        json.dumps(claim, ensure_ascii=True, separators=(", ", ": "))
        for claim in new_row["source_claims_add"]
    )
    replacement = (
        "    {\n"
        f'      "target_id": {json.dumps(TARGET_ID)},\n'
        '      "source_claims_add": [\n'
        f"        {claims}\n"
        "      ],\n"
        '      "contract_merge": '
        f"{json.dumps(new_row['contract_merge'], ensure_ascii=True, separators=(', ', ': '))},\n"
        '      "merge_note": '
        f"{json.dumps(new_row['merge_note'], ensure_ascii=True)}\n"
        "    }"
    ).encode()
    payload = payload[:start] + replacement + payload[end + len(b"\n    }") :]
    if strict_json(payload, "minimal Wave 2 output") != after:
        raise PromotionError("minimal Wave 2 output differs from derived document")
    return payload


def strict_json(payload: bytes, label: str) -> Any:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise PromotionError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode(),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                PromotionError(f"non-finite JSON in {label}: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid JSON in {label}: {exc}") from exc


def git_blob(commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise PromotionError(f"missing locked Git blob: {commit}:{path}")
    listing = subprocess.run(
        ["git", "ls-tree", commit, "--", path],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.split(None, 3)
    if (
        len(listing) != 4
        or listing[0] not in {"100644", "100755"}
        or listing[1] != "blob"
    ):
        raise PromotionError(f"locked Git path is not a regular blob: {path}")
    return result.stdout


def baseline(path: str) -> Any:
    payload = git_blob(BASE_HEAD, path)
    if sha(payload) != BASE_SHA256[path]:
        raise PromotionError(f"baseline digest drift: {path}")
    return strict_json(payload, f"{BASE_HEAD}:{path}")


def locked(path: str) -> Any:
    payload = (REPO_ROOT / path).read_bytes()
    if sha(payload) != BASE_SHA256[path]:
        raise PromotionError(f"locked source digest drift: {path}")
    return strict_json(payload, path)


def refresh_claim_hashes(ledger: dict[str, Any]) -> None:
    for source in ledger["sources"]:
        claims = []
        for capability in ledger["capabilities"]:
            for claim in capability["source_claims"]:
                if claim["source_id"] == source["id"]:
                    claims.append(
                        {
                            "capability_id": capability["id"],
                            "locator": claim["locator"],
                            "contract": capability["contract"],
                        }
                    )
        if not claims:
            raise PromotionError(f"source without claims: {source['id']}")
        source["claim_set_sha256"] = sha(
            canonical(sorted(canonical(row).decode() for row in claims))
        )


def corrected_contract(old: dict[str, Any]) -> dict[str, Any]:
    if old.get("judge_defaults") != {"max_tokens": 2048, "temperature": 0}:
        raise PromotionError("stale report evaluator judge_defaults baseline differs")
    result = copy.deepcopy(old)
    del result["judge_defaults"]
    result["judge_profile_config"] = copy.deepcopy(PROFILE)
    return result


def transform_ledger(document: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(document)
    rows = [row for row in output["capabilities"] if row["id"] == TARGET_ID]
    if len(rows) != 1:
        raise PromotionError("report evaluator capability denominator differs")
    row = rows[0]
    row["contract"] = corrected_contract(row["contract"])
    if SOURCE_CLAIM not in row["source_claims"]:
        row["source_claims"].append(copy.deepcopy(SOURCE_CLAIM))
    refresh_claim_hashes(output)
    return output


def contract_assertions(
    contract: dict[str, Any], observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                visit(
                    value[key], f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}"
                )
        else:
            result.append(
                {
                    "id": f"contract-{len(result) + 1:02d}",
                    "observation": f"contract_identity{pointer}",
                    "operator": "equals",
                    "expected": copy.deepcopy(value),
                }
            )

    visit(contract, "/contract")
    for index, observation in enumerate(observations, 1):
        if observation["id"] == "contract_identity":
            continue
        result.append(
            {
                "id": f"observation-{index:02d}",
                "observation": observation["id"],
                "operator": "recorded_pass",
                "expected": True,
            }
        )
    return result


def ledger_binding(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(row[key])
        for key in (
            "feature_id",
            "kind",
            "title",
            "source_claims",
            "acceptance_class",
            "thor_state",
            "runtime_state",
            "contract",
            "gap",
        )
    }


def transform_oracle(
    document: dict[str, Any], ledger: dict[str, Any]
) -> dict[str, Any]:
    output = copy.deepcopy(document)
    capability = next(row for row in ledger["capabilities"] if row["id"] == TARGET_ID)
    rows = [row for row in output["oracles"] if row["capability_id"] == TARGET_ID]
    if len(rows) != 1:
        raise PromotionError("report evaluator oracle denominator differs")
    row = rows[0]
    row["ledger_binding"] = ledger_binding(capability)
    row["fixture"]["input"]["contract"] = copy.deepcopy(capability["contract"])
    row["assertions"] = contract_assertions(
        capability["contract"], row["expected_observations"]
    )
    return output


def transform_wave2(document: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(document)
    rows = [row for row in output["enrichments"] if row["target_id"] == TARGET_ID]
    if len(rows) != 1:
        raise PromotionError("Wave 2 report enrichment denominator differs")
    row = rows[0]
    row["contract_merge"] = corrected_contract(row["contract_merge"])
    claim = {
        "source_id": "main-repository-wave2-7732edf8",
        "locator": SOURCE_CLAIM["locator"],
    }
    if claim not in row["source_claims_add"]:
        row["source_claims_add"].append(claim)
    row["merge_note"] = (
        "Bind evaluator semantics to the exact upstream dev-base eval_llm_judge "
        "profile selected by report_evaluator.metric_configs.llm_judge; "
        "ReportEvaluatorConfig itself has no max_tokens default. Retain "
        "required_local/source_only/not_qualified."
    )
    for source in output["sources"]:
        claims = []
        for capability in output["new_capabilities"]:
            for claim_row in capability["source_claims"]:
                if claim_row["source_id"] == source["id"]:
                    claims.append(
                        {
                            "record_type": "new_capability",
                            "record_id": capability["id"],
                            "locator": claim_row["locator"],
                            "contract": capability["contract"],
                        }
                    )
        for enrichment in output["enrichments"]:
            for claim_row in enrichment["source_claims_add"]:
                if claim_row["source_id"] == source["id"]:
                    claims.append(
                        {
                            "record_type": "enrichment",
                            "record_id": enrichment["target_id"],
                            "locator": claim_row["locator"],
                            "contract": enrichment["contract_merge"],
                        }
                    )
        for discrepancy in output["discrepancies_and_boundaries"]:
            for claim_row in discrepancy["source_claims"]:
                if claim_row["source_id"] == source["id"]:
                    claims.append(
                        {
                            "record_type": "discrepancy_or_boundary",
                            "record_id": discrepancy["id"],
                            "locator": claim_row["locator"],
                            "contract": {
                                "category": discrepancy["category"],
                                "resolution": discrepancy["resolution"],
                                "must_not_claim": discrepancy["must_not_claim"],
                            },
                        }
                    )
        source["claim_set_sha256"] = sha(
            canonical(sorted(canonical(item).decode() for item in claims))
        )
    return output


def changed(
    before: list[dict[str, Any]], after: list[dict[str, Any]], key: str
) -> set[str]:
    if [row[key] for row in before] != [row[key] for row in after]:
        raise PromotionError("row identity/order drift")
    return {old[key] for old, new in zip(before, after, strict=True) if old != new}


def descriptor(
    set_id: str,
    count: int,
    ledger: dict[str, Any],
    oracle: dict[str, Any],
    ledger_path: str,
    oracle_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "set_id": set_id,
        "mode": "immutable_static_metadata_set",
        "lifecycle": "live_ready",
        "target": {"product_version": "3.2.1", "main_commit": UPSTREAM},
        "expected_counts": {
            "capabilities": count,
            "oracles": count,
            "feature_families": 55,
        },
        "documents": {
            "manifest": {
                "path": ROOT_MANIFEST if count == 289 else SELECTED_MANIFEST,
                "raw_sha256": BASE_SHA256[ROOT_MANIFEST]
                if count == 289
                else BASE_SHA256[SELECTED_MANIFEST],
                "schema_version": 1,
            },
            "official_capabilities": {
                "path": ledger_path,
                "raw_sha256": sha(encoded(ledger)),
                "schema_version": 1,
                "schema_id": "official_capabilities_schema",
            },
            "capability_oracles": {
                "path": oracle_path,
                "raw_sha256": sha(encoded(oracle)),
                "schema_version": 1 if count == 289 else 2,
                "schema_id": "capability_oracles_schema",
            },
            "acceptance_inventory": {
                "path": ROOT_ACCEPTANCE if count == 289 else V2_ACCEPTANCE,
                "raw_sha256": BASE_SHA256[ROOT_ACCEPTANCE]
                if count == 289
                else BASE_SHA256[V2_ACCEPTANCE],
                "schema_version": 1,
            },
        },
        "schemas": {
            "official_capabilities_schema": {
                "path": OFFICIAL_SCHEMA,
                "raw_sha256": BASE_SHA256[OFFICIAL_SCHEMA],
                "dialect": "https://json-schema.org/draft/2020-12/schema",
                "document_id": "https://developer.nvidia.com/vss/thor-local/official-capabilities.schema.json",
            },
            "capability_oracles_schema": {
                "path": ROOT_ORACLE_SCHEMA if count == 289 else V2_ORACLE_SCHEMA,
                "raw_sha256": BASE_SHA256[ROOT_ORACLE_SCHEMA]
                if count == 289
                else BASE_SHA256[V2_ORACLE_SCHEMA],
                "dialect": "https://json-schema.org/draft/2020-12/schema",
                "document_id": "https://nvidia.com/vss/thor/capability-oracles.schema.json"
                if count == 289
                else "https://developer.nvidia.com/vss/thor-local/live-capability-oracles-v2.schema.json",
            },
        },
    }


def schema_check(value: Any, schema_path: str, label: str) -> None:
    schema = locked(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        raise PromotionError(f"{label} schema failure: {errors[0].message}")


def derive() -> tuple[dict[str, Any], dict[str, bytes], dict[str, int]]:
    if (
        subprocess.run(
            ["git", "rev-parse", f"{BASE_HEAD}^{{tree}}"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        != BASE_TREE
    ):
        raise PromotionError("base checkpoint tree differs")
    config_raw = git_blob(UPSTREAM, CONFIG_PATH)
    evaluator_raw = git_blob(UPSTREAM, EVALUATOR_PATH)
    if sha(config_raw) != CONFIG_SHA256 or sha(evaluator_raw) != EVALUATOR_SHA256:
        raise PromotionError("upstream Agent source binding differs")
    config = yaml.safe_load(config_raw)
    selected_profile = config["eval"]["evaluators"]["report_evaluator"][
        "metric_configs"
    ]["llm_judge"].get("llm_name")
    if selected_profile != "eval_llm_judge":
        raise PromotionError("report evaluator judge profile selection differs")
    if (
        config["llms"][selected_profile].get("max_tokens") != 4096
        or config["llms"][selected_profile].get("temperature") != 0.0
    ):
        raise PromotionError("upstream dev-base judge profile differs")
    evaluator_text = evaluator_raw.decode()
    section = evaluator_text[
        evaluator_text.index("class ReportEvaluatorConfig") : evaluator_text.index(
            "class ReportEvaluator",
            evaluator_text.index("class ReportEvaluatorConfig") + 1,
        )
    ]
    if "max_tokens" in section:
        raise PromotionError("ReportEvaluatorConfig unexpectedly defines max_tokens")

    old_289 = baseline(ROOT_LEDGER)
    old_o289 = baseline(ROOT_ORACLE)
    old_500 = baseline(SELECTED_LEDGER)
    old_o500 = baseline(SELECTED_ORACLE)
    ledger_289 = transform_ledger(old_289)
    oracle_289 = transform_oracle(old_o289, ledger_289)
    ledger_500 = transform_ledger(old_500)
    oracle_500 = transform_oracle(old_o500, ledger_500)
    old_wave2 = baseline(WAVE2)
    wave2 = transform_wave2(old_wave2)
    if (
        ledger_500["capabilities"][:289] != ledger_289["capabilities"]
        or oracle_500["oracles"][:289] != oracle_289["oracles"]
    ):
        raise PromotionError("289/500 corrected prefix differs")
    if (
        ledger_500["capabilities"][289:] != old_500["capabilities"][289:]
        or oracle_500["oracles"][289:] != old_o500["oracles"][289:]
    ):
        raise PromotionError("211-row suffix changed")
    if changed(old_289["capabilities"], ledger_289["capabilities"], "id") != {
        TARGET_ID
    } or changed(old_o289["oracles"], oracle_289["oracles"], "capability_id") != {
        TARGET_ID
    }:
        raise PromotionError("correction changed an unrelated root row")
    schema_check(ledger_289, OFFICIAL_SCHEMA, "root ledger")
    schema_check(oracle_289, ROOT_ORACLE_SCHEMA, "root oracle")
    schema_check(ledger_500, OFFICIAL_SCHEMA, "500 ledger")
    schema_check(oracle_500, V2_ORACLE_SCHEMA, "500 oracle")
    d289 = descriptor(
        "thor-vss-3.2.1-current-agent-evaluation-contract-289",
        289,
        ledger_289,
        oracle_289,
        ROOT_LEDGER,
        ROOT_ORACLE,
    )
    d500 = descriptor(
        "thor-vss-3.2.1-current-agent-evaluation-contract-500",
        500,
        ledger_500,
        oracle_500,
        str(OUTPUTS["ledger_500"].relative_to(REPO_ROOT)),
        str(OUTPUTS["oracle_500"].relative_to(REPO_ROOT)),
    )
    schema_check(d289, METADATA_SCHEMA, "289 descriptor")
    schema_check(d500, METADATA_SCHEMA, "500 descriptor")
    selector = {
        "schema_version": 1,
        "selected_set": d500["set_id"],
        "available_sets": [
            {
                "set_id": d289["set_id"],
                "descriptor_path": str(
                    CANONICAL["descriptor_289"].relative_to(REPO_ROOT)
                ),
                "descriptor_raw_sha256": sha(encoded(d289)),
            },
            {
                "set_id": d500["set_id"],
                "descriptor_path": str(
                    CANONICAL["descriptor_500"].relative_to(REPO_ROOT)
                ),
                "descriptor_raw_sha256": sha(encoded(d500)),
            },
        ],
    }
    schema_check(selector, SELECTOR_SCHEMA, "selector")
    docs = {
        "ledger_289": ledger_289,
        "oracle_289": oracle_289,
        "ledger_500": ledger_500,
        "oracle_500": oracle_500,
        "wave2": wave2,
        "descriptor_289": d289,
        "descriptor_500": d500,
        "selector": selector,
    }
    payloads = {name: encoded(value) for name, value in docs.items()}
    payloads["wave2"] = encode_wave2_minimal(old_wave2, wave2)
    return (
        docs,
        payloads,
        {
            "root_capabilities": 289,
            "selected_capabilities": 500,
            "corrected_capabilities": 1,
            "preserved_suffix": 211,
        },
    )


def safe_bytes(path: Path) -> bytes | None:
    rel = path.relative_to(REPO_ROOT)
    current = REPO_ROOT
    for part in rel.parts[:-1]:
        current /= part
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise PromotionError(f"unsafe canonical parent: {current}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise PromotionError(f"unsafe canonical target: {path}")
    return path.read_bytes()


def atomic_install(path: Path, payload: bytes) -> None:
    safe_bytes(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temporary)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        safe_bytes(path)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def publication_state(payloads: dict[str, bytes], repair: bool) -> str:
    old = {
        "ledger_289": BASE_SHA256[ROOT_LEDGER],
        "oracle_289": BASE_SHA256[ROOT_ORACLE],
        "wave2": BASE_SHA256[WAVE2],
        "selector": BASE_SHA256[SELECTOR],
    }
    observed = {name: safe_bytes(path) for name, path in CANONICAL.items()}
    if (
        all(
            observed[name] is not None and sha(observed[name] or b"") == digest
            for name, digest in old.items()
        )
        and observed["descriptor_289"] is None
        and observed["descriptor_500"] is None
    ):
        return "pre_promotion"
    if all(observed[name] == payloads[name] for name in CANONICAL):
        return "post_promotion"
    if repair:
        for name, value in observed.items():
            if (
                value is None
                or value == payloads[name]
                or (name in old and sha(value) == old[name])
            ):
                continue
            raise PromotionError(f"unrecognized canonical drift: {name}")
        return "repairable_partial_promotion"
    raise PromotionError("mixed canonical publication state")


def run(write: bool, install: bool) -> dict[str, Any]:
    _, payloads, counts = derive()
    state = publication_state(payloads, repair=install or write)
    for name, payload in payloads.items():
        path = OUTPUTS[name]
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        else:
            expected = EXPECTED_OUTPUT_SHA256.get(name)
            if (
                expected is None
                or path.read_bytes() != payload
                or sha(payload) != expected
            ):
                raise PromotionError(f"checked output differs: {name}")
    if install:
        if write:
            raise PromotionError("--write and --install-canonical are separate")
        for name, path in CANONICAL.items():
            atomic_install(path, payloads[name])
        if publication_state(payloads, repair=False) != "post_promotion":
            raise PromotionError("canonical publication incomplete")
    return {**counts, "canonical_state_pre_install": state}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--install-canonical", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(
                {"status": "pass", **run(args.write, args.install_canonical)},
                sort_keys=True,
            )
        )
        return 0
    except (OSError, KeyError, TypeError, ValueError, PromotionError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
