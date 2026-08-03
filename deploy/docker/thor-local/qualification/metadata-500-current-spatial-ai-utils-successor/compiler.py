#!/usr/bin/env python3
"""Compile and optionally install the reviewed SpatialAI all-seven promotion."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]


sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
MAX_JSON_BYTES = 12_000_000
RECEIPT_HEAD = "f7ea82feef81739b6861f49e8a2eb5fea9583900"
RECEIPT_TREE = "d86ca3a4bffdc99c0693a135f5b3623f8b98edce"
UPSTREAM_COMMIT = "7732edf8fb38ef896b20f2a0a6a701a4db10dc57"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
EMPTY_TREE_SHA256 = hashlib.sha256(b"{}").hexdigest()

TARGET_IDS = tuple(
    f"manifest-entry.spatial-ai-utils.0{index}-{suffix}"
    for index, suffix in enumerate(
        (
            "calibration-and-camera-grouping",
            "3d-2d-geometry",
            "multiview-visualization",
            "detection-map",
            "tracking-hota-clear-identity-count",
            "nvschema-conversion",
            "video-frame-tools",
        )
    )
)
EXTERNAL_ID = "manifest-entry.spatial-ai-utils.07-aws-gcs-validation"
PRODUCT_CALLS = dict(zip(TARGET_IDS, (17, 15, 11, 37, 16, 9, 17), strict=True))
FINAL_GAP = (
    "No known gap: the reviewed clean all-seven Thor receipt proves two independent "
    "positive runs, five named adjacent negatives, deterministic output, exact "
    "cleanup, and locked imported-product execution without the Warehouse sample."
)
FINAL_FAMILY_GAP = (
    "No known provider-free gap: all seven local SpatialAI utilities passed the "
    "reviewed target-bound Thor contract. AWS/GCS remains an unchanged external "
    "optional boundary."
)

RAW_RECEIPT = (
    "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-successor/authoritative-integrated-receipt.json",
    "9ca6de79ac42605a80b5de9c2397ba4d303fdc423e9713a061a520f3a730fce7",
)
OUTER_MATERIALIZER = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/materializer.py",
    "00a74a1c824e8c2dfa6b2751de3eaed47a8d1717d36d82003048066b0d6b6c42",
)
OUTER_INTEGRATED_SCHEMA = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/integrated-receipt.schema.json",
    "907bbd439372ad89161cf42154e800be1c7571f39f2ec7aa4991c14e4e009a0b",
)
OUTER_LOCK = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/lock.json",
    "0f3035122fe04837eb0d9259969ca5c60f3639ef135db31d780dcf1d48c63d5a",
)
PRODUCER_LOCK = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/producer-lock.json",
    "ab623de8e6bcadd2a41086285e9f81f54bbb1174844279e8e18bf639fa9ab9b7",
)
PRODUCER_LOCK_SCHEMA = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-offline-env/producer-lock.schema.json",
    "7d60a599a99aed129062b9d0b537ce45663ebb175d5c4685aa9e8ade5ac2e73d",
)
PRODUCER_CONTRACT = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/contract.json",
    "029b17846f5e137d6aaad1e092abd444e7e17f112517841ce59fc960b096ec70",
)
PRODUCER_CONTRACT_SCHEMA = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/contract.schema.json",
    "beda5705dad3b6cdff0c9aa11ae3ecd716df1508e0f7042d503f3a87fde80553",
)
PRODUCER_EXECUTOR = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/executor.py",
    "6f3af563886565f2688f97472fa2e6d993f8dc47ed12215d2d02c77ac4f8066c",
)
PRODUCER_RESULT_SCHEMA = (
    "deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/result.schema.json",
    "c49f98b4ad1aea73b6c1938eb06b1218b252902d3f54d19b0b3c891c2fcbbf1b",
)
CURRENT_LEDGER = (
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "834bb40b576d9e9e546cecb3bdb866993b7be7fd3bf9d5e9e19a0d852d4e4e39",
)
CURRENT_ORACLES = (
    "deploy/docker/thor-local/parity/capability-oracles.json",
    "b8f03c0d949ae7c9bb6dd14f37142e4f723849125ec944eb9244bd0ad9b79a1a",
)
CURRENT_MANIFEST = (
    "deploy/docker/thor-local/parity/manifest.json",
    "629f3dbf69b42a73037d7dd5e8f8b369dd72885e9a82f3a59fcfa4f19cbc0744",
)
CURRENT_SELECTOR = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.json",
    "bee044866dc53c4c868fd37fd7c21b35e7b8fe6e7b4f7f31e81f3c2263f977c6",
)
SELECTED_LEDGER = (
    "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-rebind-successor/post-state-official-capabilities.json",
    "315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229",
)
SELECTED_ORACLES = (
    "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-rebind-successor/post-state-capability-oracles.json",
    "c2b8d584b4bb00f42d6337bbad31038d016fe02a7cfbf92ac747f42075bdc6c0",
)
SELECTED_MANIFEST = (
    "deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/post-state-manifest.json",
    "97d7801134de5022bce7636f47dd08a34df78d913e01a59a5faddb9376d5dc37",
)
OFFICIAL_SCHEMA = (
    "deploy/docker/thor-local/parity/official-capabilities.schema.json",
    "71f1e0f1d820c3809ea3b55abb504071321f61c6e36978226dd10108c7b2384b",
)
ROOT_ORACLE_SCHEMA = (
    "deploy/docker/thor-local/parity/capability-oracles.schema.json",
    "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1",
)
SELECTED_ORACLE_SCHEMA = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.schema.json",
    "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
)
METADATA_SCHEMA = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json",
    "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
)
SELECTOR_SCHEMA = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json",
    "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
)
ROOT_ACCEPTANCE = (
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
)
SELECTED_ACCEPTANCE = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-acceptance-inventory.json",
    "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
)
PACKAGE_README = (
    "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-successor/README.md",
    "c3ab64961b660cf4590826694a43d5ccf0ebff4f85cb5e30ab919f42933d54b4",
)
PACKAGE_EVIDENCE = (
    "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-successor/EVIDENCE.md",
    "97c58718c4eaed2d18a864170a565f63e4f7546156dc020a3493fa374742b846",
)

OUTPUT_PATHS = {
    "producer_receipt": PACKAGE / "producer-runtime-receipt.json",
    "ledger_500": PACKAGE / "post-state-official-capabilities.json",
    "oracle_500": PACKAGE / "post-state-capability-oracles.json",
    "manifest_500": PACKAGE / "post-state-manifest.json",
    "ledger_289": PACKAGE / "post-state-root-official-capabilities.json",
    "oracle_289": PACKAGE / "post-state-root-capability-oracles.json",
    "manifest_289": PACKAGE / "post-state-root-manifest.json",
    "descriptor_289": PACKAGE / "post-state-metadata-set-289.json",
    "descriptor_500": PACKAGE / "post-state-metadata-set-500.json",
    "selector": PACKAGE / "post-state-selector.json",
}
CANONICAL_PATHS = {
    "ledger_289": REPO_ROOT / CURRENT_LEDGER[0],
    "oracle_289": REPO_ROOT / CURRENT_ORACLES[0],
    "manifest_289": REPO_ROOT / CURRENT_MANIFEST[0],
    "descriptor_289": REPO_ROOT
    / "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-spatial-ai-utils-289.json",
    "descriptor_500": REPO_ROOT
    / "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-spatial-ai-utils-500.json",
    "selector": REPO_ROOT / CURRENT_SELECTOR[0],
}

EXPECTED_OUTPUT_SHA256 = {
    "producer_receipt": "9c0c9294b78bc5e01b8cc9500a70f050bb52d7b618399a13569b78064966d95a",
    "ledger_500": "c910f26b25749d39c8ab51e5b48b0174128c7b018bd0d9e1354bce31bed13162",
    "oracle_500": "4c122819bcc9057480e2fc98431f727f2a8b79681989ab95b80af27ad81be4f0",
    "manifest_500": "ec8c6c65bb8f95d81212e175c8c8eb4adf378bcaba91f8e04549a844ac3b5777",
    "ledger_289": "92e1c88c5ef9f2fc3f54a4ca2203f8b11e6f1e9b8a24517161c1d634c6a486de",
    "oracle_289": "cdccc9a21df79a6cb857b51b83c00d07d9e9da2d3a7a32b1c9b480328692821a",
    "manifest_289": "1040ba9806ead7050accec09e4be32cd3fb223c804782b49c81683cebbe89c62",
    "descriptor_289": "6ab007d5ba0056facdd560f737494eccbedfb224922c84af8c598dea9cd0d6d2",
    "descriptor_500": "ae9d66b08fc93fbd3b8f24f0b3e0b098a4f89e63bb723427880ced7f4ac5d80e",
    "selector": "1e7275bdf562aafe2957d4b9d05974be0cce253335cbb8ae86096cb7291e5d4c",
}
POST_PROMOTION_SOURCE_SHA256 = {
    CURRENT_LEDGER[0]: EXPECTED_OUTPUT_SHA256["ledger_289"],
    CURRENT_ORACLES[0]: EXPECTED_OUTPUT_SHA256["oracle_289"],
    CURRENT_MANIFEST[0]: EXPECTED_OUTPUT_SHA256["manifest_289"],
    CURRENT_SELECTOR[0]: EXPECTED_OUTPUT_SHA256["selector"],
}


class PromotionError(RuntimeError):
    """A source, receipt-authority, schema, or exact-delta invariant failed."""


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()


def relative(path: Path) -> str:
    return os.fspath(path.relative_to(REPO_ROOT))


def repo_file(relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise PromotionError(f"unsafe repository path: {relative_path}")
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise PromotionError(f"missing repository input: {relative_path}") from exc
        if stat.S_ISLNK(mode):
            raise PromotionError(f"repository input contains symlink: {relative_path}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise PromotionError(f"repository input is not regular: {relative_path}")
    current.resolve(strict=True).relative_to(REPO_ROOT)
    return current


def strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise PromotionError(f"oversized JSON input: {label}")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in rows:
            if key in output:
                raise PromotionError(f"duplicate JSON key in {label}: {key}")
            output[key] = value
        return output

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                PromotionError(f"non-finite JSON number in {label}: {value}")
            ),
        )
    except PromotionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid JSON in {label}: {exc}") from exc


def load_locked(source: tuple[str, str]) -> Any:
    relative_path, expected = source
    payload = repo_file(relative_path).read_bytes()
    allowed = {expected}
    if relative_path in POST_PROMOTION_SOURCE_SHA256:
        allowed.add(POST_PROMOTION_SOURCE_SHA256[relative_path])
    if sha256(payload) not in allowed:
        raise PromotionError(f"raw source digest drift: {relative_path}")
    return strict_json(payload, relative_path)


def load_receipt_head(source: tuple[str, str]) -> Any:
    """Load a pre-promotion canonical source from the authoritative checkout."""
    relative_path, expected = source
    payload = git_blob(RECEIPT_HEAD, relative_path)
    if sha256(payload) != expected:
        raise PromotionError(f"receipt-head canonical source drift: {relative_path}")
    return strict_json(payload, f"{RECEIPT_HEAD}:{relative_path}")


def schema_check(value: Any, schema: Any, label: str) -> None:
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        path = "/".join(map(str, errors[0].absolute_path)) or "<root>"
        raise PromotionError(f"{label} schema failure at {path}: {errors[0].message}")


def git_blob(commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise PromotionError(f"locked path absent at {commit}: {relative_path}")
    return result.stdout


def load_module(source: tuple[str, str], name: str) -> Any:
    relative_path, expected = source
    path = repo_file(relative_path)
    if sha256(path.read_bytes()) != expected:
        raise PromotionError(f"module source drift: {relative_path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PromotionError(f"cannot load module: {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_locked_source_graph(producer_lock: dict[str, Any]) -> None:
    binding_commit = producer_lock["producer_binding_commit"]
    if binding_commit != "0bd7fef7e1426f6a298ceb1c422aa38b76f383d8":
        raise PromotionError("producer binding commit drift")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", binding_commit, RECEIPT_HEAD],
        cwd=REPO_ROOT,
        check=False,
    )
    if ancestor.returncode:
        raise PromotionError("producer binding commit is not receipt-head ancestor")
    collections = (
        "producer_bundle",
        "canonical_controls",
        "metadata_controls",
        "fixture_controls",
        "product_source_controls",
        "product_root_manifest",
        "producer_root_manifest",
    )
    locked: dict[str, str] = {}
    rows = [row for key in collections for row in producer_lock[key]]
    if len(rows) != 315 or len({row["path"] for row in rows}) != 274:
        raise PromotionError("producer lock denominator drift")
    for row in rows:
        prior = locked.setdefault(row["path"], row["sha256"])
        if prior != row["sha256"]:
            raise PromotionError(f"conflicting source lock: {row['path']}")
    for relative_path, expected in locked.items():
        if sha256(git_blob(RECEIPT_HEAD, relative_path)) != expected:
            raise PromotionError(f"receipt-head source blob drift: {relative_path}")
    if producer_lock["expectations"]["product_function_calls"] != 122:
        raise PromotionError("producer lock accounting drift")


def validate_authority() -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = load_locked(RAW_RECEIPT)
    schema_check(receipt, load_locked(OUTER_INTEGRATED_SCHEMA), "integrated receipt")
    producer_lock = load_locked(PRODUCER_LOCK)
    schema_check(producer_lock, load_locked(PRODUCER_LOCK_SCHEMA), "producer lock")
    validate_locked_source_graph(producer_lock)
    contract = load_locked(PRODUCER_CONTRACT)
    schema_check(contract, load_locked(PRODUCER_CONTRACT_SCHEMA), "producer contract")
    schema_check(
        receipt["producer_receipt"],
        load_locked(PRODUCER_RESULT_SCHEMA),
        "producer receipt",
    )
    if (
        subprocess.run(
            ["git", "rev-parse", f"{RECEIPT_HEAD}^{{tree}}"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        != RECEIPT_TREE
    ):
        raise PromotionError("receipt checkout tree drift")
    merge_base = subprocess.run(
        ["git", "merge-base", UPSTREAM_COMMIT, RECEIPT_HEAD],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if merge_base != UPSTREAM_COMMIT:
        raise PromotionError("receipt checkout is not based on the selected upstream")
    outer = load_module(OUTER_MATERIALIZER, "spatial_ai_promotion_outer_validator")
    environment_lock = load_locked(OUTER_LOCK)
    old_checkout = outer._checkout_state
    old_merge_base = outer._merge_base
    try:
        outer._checkout_state = lambda: (RECEIPT_HEAD, RECEIPT_TREE, "")
        outer._merge_base = lambda ancestor, head: (
            UPSTREAM_COMMIT
            if (ancestor, head) == (UPSTREAM_COMMIT, RECEIPT_HEAD)
            else ""
        )
        outer.validate_integrated_receipt(
            receipt,
            environment_lock,
            producer_lock,
            expected_cache_scan=receipt["environment_receipt"]["cache_scan"],
            expected_temporary_root=receipt["cleanup"]["materializer_temporary_root"],
        )
    except Exception as exc:
        raise PromotionError(
            f"deep integrated authority validation failed: {exc}"
        ) from exc
    finally:
        outer._checkout_state = old_checkout
        outer._merge_base = old_merge_base
    nested = receipt["producer_receipt"]
    rendered_nested = encoded(nested)
    if (
        sha256(rendered_nested) != receipt["bindings"]["producer_receipt_sha256"]
        or receipt["bindings"]["producer_receipt_sha256"]
        != "9c0c9294b78bc5e01b8cc9500a70f050bb52d7b618399a13569b78064966d95a"
    ):
        raise PromotionError("nested producer raw binding drift")
    if receipt["accounting"] != {
        "capabilities_passed": 7,
        "bounded_capability_actions": 49,
        "requests": 49,
        "product_function_calls": 122,
        "independent_positive_runs": 14,
        "adjacent_negatives": 35,
    }:
        raise PromotionError("integrated accounting drift")
    if [row["capability_id"] for row in nested["capability_results"]] != list(
        TARGET_IDS
    ):
        raise PromotionError("nested result order drift")
    contract_rows = {row["capability_id"]: row for row in contract["capabilities"]}
    for row in nested["capability_results"]:
        capability_id = row["capability_id"]
        runtime = contract_rows[capability_id]
        if (
            row["status"] != "pass"
            or row["fixture_sha256"] != runtime["fixture_manifest"]["sha256"]
            or row["independent_runs"] != 2
            or row["bounded_capability_actions"] != 7
            or row["requests"] != 7
            or row["imported_product_function_invocations"]
            != PRODUCT_CALLS[capability_id]
            or row["deterministic_output"] is not True
            or len(row["adjacent_negatives"]) != 5
            or not all(item["rejected"] is True for item in row["adjacent_negatives"])
        ):
            raise PromotionError(f"nested result proof drift: {capability_id}")
        for control in runtime["source_controls"]:
            if sha256(git_blob(RECEIPT_HEAD, control["path"])) != control["sha256"]:
                raise PromotionError(f"runtime source lock drift: {control['path']}")
    return receipt, contract


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
            raise PromotionError(f"source has no claims: {source['id']}")
        canonical_claims = sorted(canonical_bytes(claim).decode() for claim in claims)
        source["claim_set_sha256"] = sha256(canonical_bytes(canonical_claims))


def evidence_ref(capability_id: str, index: int, producer_sha: str) -> dict[str, str]:
    return {
        "path": relative(OUTPUT_PATHS["producer_receipt"]),
        "sha256": producer_sha,
        "capability_id": capability_id,
        "json_pointer": f"/capability_results/{index}",
    }


def projected_contract(
    source_contract: dict[str, Any], runtime: dict[str, Any]
) -> dict[str, Any]:
    output = copy.deepcopy(source_contract)
    output["source_controls"] = copy.deepcopy(runtime["source_controls"])
    if "required_metrics" in output:
        output["required_metrics"] = copy.deepcopy(runtime["required_semantics"])
    elif "required_semantics" in output:
        output["required_semantics"] = copy.deepcopy(runtime["required_semantics"])
    else:
        raise PromotionError(f"target semantic key absent: {runtime['capability_id']}")
    return output


def promote_ledger(
    baseline: dict[str, Any], contract: dict[str, Any], producer_sha: str
) -> dict[str, Any]:
    output = copy.deepcopy(baseline)
    runtime = {row["capability_id"]: row for row in contract["capabilities"]}
    found: list[str] = []
    for row in output["capabilities"]:
        capability_id = row["id"]
        if capability_id not in TARGET_IDS:
            continue
        found.append(capability_id)
        row["contract"] = projected_contract(row["contract"], runtime[capability_id])
        row["thor_state"] = "wired"
        row["runtime_state"] = "passed_current"
        row["gap"] = FINAL_GAP
        row["runtime_evidence"] = [
            evidence_ref(capability_id, TARGET_IDS.index(capability_id), producer_sha)
        ]
    if found != list(TARGET_IDS):
        raise PromotionError("ledger target identity/order drift")
    refresh_claim_hashes(output)
    return output


def ledger_binding(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in row.items()
        if key not in {"id", "scenario_ids", "runtime_evidence"}
    }


def promote_oracles(
    baseline: dict[str, Any], ledger: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    output = copy.deepcopy(baseline)
    ledger_rows = {row["id"]: row for row in ledger["capabilities"]}
    runtime_rows = {row["capability_id"]: row for row in contract["capabilities"]}
    executor = PRODUCER_EXECUTOR[0]
    found: list[str] = []
    for row in output["oracles"]:
        capability_id = row["capability_id"]
        if capability_id not in TARGET_IDS:
            continue
        found.append(capability_id)
        runtime = runtime_rows[capability_id]
        namespace = f"spatial-ai-{capability_id.split('.')[2]}"
        contract_projection = copy.deepcopy(ledger_rows[capability_id]["contract"])
        row["ledger_binding"] = ledger_binding(ledger_rows[capability_id])
        row["fixture"]["input"]["contract"] = copy.deepcopy(contract_projection)
        row["fixture"]["input"]["namespace"] = namespace
        row["fixture"]["materialization"] = {
            "generator": executor,
            "path": runtime["fixture_manifest"]["path"],
            "sha256": runtime["fixture_manifest"]["sha256"],
        }
        for assertion in row["assertions"]:
            prefix = "contract_identity/contract/"
            observation = assertion["observation"]
            if observation.startswith(prefix):
                key = observation.removeprefix(prefix)
                if key in contract_projection:
                    assertion["expected"] = copy.deepcopy(contract_projection[key])
        row["execution_bounds"]["executor"] = executor
        row["execution_bounds"]["collectors"] = [executor]
        row["execution_bounds"]["max_actions"] = 7
        row["execution_bounds"]["max_requests"] = 7
        row["execution_bounds"]["workload"] = {
            "calculated_max_requests": 7,
            "overhead_requests": 0,
            "phases": ["positive_run_1", "positive_run_2", "adjacent_negative"],
            "requests_per_unit": 7,
            "units": 1,
        }
        row["cleanup"]["allowlist"] = [namespace]
        row["cleanup"]["targets"] = [namespace]
        row["cleanup"]["executor"] = executor
        row["cleanup"]["postcondition_collectors"] = [executor]
        row["acceptance_readiness"] = {
            "blockers": [],
            "classification": "executor_ready",
        }
        if row["current_state"] != "open_unexecuted" or row["evidence"] != []:
            raise PromotionError(
                f"oracle state/evidence convention drift: {capability_id}"
            )
    if found != list(TARGET_IDS):
        raise PromotionError("oracle target identity/order drift")
    return output


def promote_manifest(baseline: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(baseline)
    rows = [row for row in output["features"] if row["id"] == "spatial-ai-utils"]
    if len(rows) != 1:
        raise PromotionError("SpatialAI manifest family identity drift")
    row = rows[0]
    if row["thor_state"] != "partial" or row["runtime_state"] != "not_qualified":
        raise PromotionError("SpatialAI family aggregate-state convention drift")
    row["gap"] = FINAL_FAMILY_GAP
    additions = [
        RAW_RECEIPT[0],
        relative(OUTPUT_PATHS["producer_receipt"]),
        relative(PACKAGE / "EVIDENCE.md"),
    ]
    row["thor_evidence"] = list(dict.fromkeys([*row["thor_evidence"], *additions]))
    return output


def descriptor(
    *,
    set_id: str,
    count: int,
    manifest_path: str,
    manifest: dict[str, Any],
    ledger_path: str,
    ledger: dict[str, Any],
    oracle_path: str,
    oracle: dict[str, Any],
    acceptance: tuple[str, str],
    oracle_schema: tuple[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "set_id": set_id,
        "mode": "immutable_static_metadata_set",
        "lifecycle": "live_ready",
        "target": {"product_version": "3.2.1", "main_commit": UPSTREAM_COMMIT},
        "expected_counts": {
            "capabilities": count,
            "oracles": count,
            "feature_families": 55,
        },
        "documents": {
            "manifest": {
                "path": manifest_path,
                "raw_sha256": sha256(encoded(manifest)),
                "schema_version": 1,
            },
            "official_capabilities": {
                "path": ledger_path,
                "raw_sha256": sha256(encoded(ledger)),
                "schema_version": 1,
                "schema_id": "official_capabilities_schema",
            },
            "capability_oracles": {
                "path": oracle_path,
                "raw_sha256": sha256(encoded(oracle)),
                "schema_version": oracle["schema_version"],
                "schema_id": "capability_oracles_schema",
            },
            "acceptance_inventory": {
                "path": acceptance[0],
                "raw_sha256": acceptance[1],
                "schema_version": 1,
            },
        },
        "schemas": {
            "official_capabilities_schema": {
                "path": OFFICIAL_SCHEMA[0],
                "raw_sha256": OFFICIAL_SCHEMA[1],
                "dialect": "https://json-schema.org/draft/2020-12/schema",
                "document_id": "https://developer.nvidia.com/vss/thor-local/official-capabilities.schema.json",
            },
            "capability_oracles_schema": {
                "path": oracle_schema[0],
                "raw_sha256": oracle_schema[1],
                "dialect": "https://json-schema.org/draft/2020-12/schema",
                "document_id": (
                    "https://nvidia.com/vss/thor/capability-oracles.schema.json"
                    if count == 289
                    else "https://developer.nvidia.com/vss/thor-local/live-capability-oracles-v2.schema.json"
                ),
            },
        },
    }


def changed_ids(
    before: list[dict[str, Any]], after: list[dict[str, Any]], key: str
) -> set[str]:
    old = {row[key]: row for row in before}
    new = {row[key]: row for row in after}
    if list(old) != list(new):
        raise PromotionError("metadata row identity/order drift")
    return {
        identity
        for identity in old
        if canonical_bytes(old[identity]) != canonical_bytes(new[identity])
    }


def derive() -> tuple[dict[str, Any], dict[str, bytes], dict[str, int]]:
    # Reject live canonical drift independently of the immutable receipt-head
    # baseline used to make derivation idempotent after publication.
    for source in (CURRENT_LEDGER, CURRENT_ORACLES, CURRENT_MANIFEST, CURRENT_SELECTOR):
        load_locked(source)
    for source in (PACKAGE_README, PACKAGE_EVIDENCE):
        relative_path, expected = source
        if sha256(repo_file(relative_path).read_bytes()) != expected:
            raise PromotionError(f"package documentation drift: {relative_path}")
    receipt, contract = validate_authority()
    producer_payload = encoded(receipt["producer_receipt"])
    producer_sha = sha256(producer_payload)
    current_ledger = load_receipt_head(CURRENT_LEDGER)
    current_oracles = load_receipt_head(CURRENT_ORACLES)
    current_manifest = load_receipt_head(CURRENT_MANIFEST)
    selected_ledger = load_locked(SELECTED_LEDGER)
    selected_oracles = load_locked(SELECTED_ORACLES)
    selected_manifest = load_locked(SELECTED_MANIFEST)
    if (
        selected_ledger["capabilities"][:289] != current_ledger["capabilities"]
        or selected_oracles["oracles"][:289] != current_oracles["oracles"]
    ):
        raise PromotionError("selected Metadata-500 prefix is not current root")
    ledger_289 = promote_ledger(current_ledger, contract, producer_sha)
    ledger_500 = promote_ledger(selected_ledger, contract, producer_sha)
    oracle_289 = promote_oracles(current_oracles, ledger_289, contract)
    oracle_500 = promote_oracles(selected_oracles, ledger_500, contract)
    manifest_289 = promote_manifest(current_manifest)
    manifest_500 = promote_manifest(selected_manifest)
    if (
        ledger_500["capabilities"][:289] != ledger_289["capabilities"]
        or oracle_500["oracles"][:289] != oracle_289["oracles"]
        or ledger_500["capabilities"][289:] != selected_ledger["capabilities"][289:]
        or oracle_500["oracles"][289:] != selected_oracles["oracles"][289:]
    ):
        raise PromotionError("promoted prefix or preserved 211-row suffix drift")
    if (
        changed_ids(current_ledger["capabilities"], ledger_289["capabilities"], "id")
        != set(TARGET_IDS)
        or changed_ids(
            current_oracles["oracles"], oracle_289["oracles"], "capability_id"
        )
        != set(TARGET_IDS)
        or changed_ids(current_manifest["features"], manifest_289["features"], "id")
        != {"spatial-ai-utils"}
    ):
        raise PromotionError("canonical delta changed outside SpatialAI 00-06/family")
    old_ledger = {row["id"]: row for row in current_ledger["capabilities"]}
    new_ledger = {row["id"]: row for row in ledger_289["capabilities"]}
    old_oracles = {row["capability_id"]: row for row in current_oracles["oracles"]}
    new_oracles = {row["capability_id"]: row for row in oracle_289["oracles"]}
    if (
        old_ledger[EXTERNAL_ID] != new_ledger[EXTERNAL_ID]
        or old_oracles[EXTERNAL_ID] != new_oracles[EXTERNAL_ID]
    ):
        raise PromotionError("external provider row 07 changed")
    row05 = new_ledger[TARGET_IDS[5]]["contract"]
    runtime05 = next(
        row for row in contract["capabilities"] if row["capability_id"] == TARGET_IDS[5]
    )
    if (
        row05["required_semantics"] != runtime05["required_semantics"]
        or len(row05["required_semantics"]) != 13
        or row05["source_controls"] != runtime05["source_controls"]
        or row05["source_controls"][0]["sha256"]
        != "e433d69e7561e304cff99925122b7c44822ee1a279b29ce62607ac439cfec060"
    ):
        raise PromotionError("SpatialAI row05 current-source/semantic rebind drift")
    schema_check(ledger_289, load_locked(OFFICIAL_SCHEMA), "root ledger")
    schema_check(ledger_500, load_locked(OFFICIAL_SCHEMA), "Metadata-500 ledger")
    schema_check(oracle_289, load_locked(ROOT_ORACLE_SCHEMA), "root oracle")
    schema_check(oracle_500, load_locked(SELECTED_ORACLE_SCHEMA), "Metadata-500 oracle")

    def out(name: str) -> str:
        return relative(OUTPUT_PATHS[name])

    descriptor_289 = descriptor(
        set_id="thor-vss-3.2.1-current-spatial-ai-utils-289",
        count=289,
        manifest_path=CURRENT_MANIFEST[0],
        manifest=manifest_289,
        ledger_path=CURRENT_LEDGER[0],
        ledger=ledger_289,
        oracle_path=CURRENT_ORACLES[0],
        oracle=oracle_289,
        acceptance=ROOT_ACCEPTANCE,
        oracle_schema=ROOT_ORACLE_SCHEMA,
    )
    descriptor_500 = descriptor(
        set_id="thor-vss-3.2.1-current-spatial-ai-utils-500",
        count=500,
        manifest_path=out("manifest_500"),
        manifest=manifest_500,
        ledger_path=out("ledger_500"),
        ledger=ledger_500,
        oracle_path=out("oracle_500"),
        oracle=oracle_500,
        acceptance=SELECTED_ACCEPTANCE,
        oracle_schema=SELECTED_ORACLE_SCHEMA,
    )
    schema_check(descriptor_289, load_locked(METADATA_SCHEMA), "289 descriptor")
    schema_check(descriptor_500, load_locked(METADATA_SCHEMA), "500 descriptor")
    selector = {
        "schema_version": 1,
        "selected_set": descriptor_500["set_id"],
        "available_sets": [
            {
                "set_id": descriptor_289["set_id"],
                "descriptor_path": relative(CANONICAL_PATHS["descriptor_289"]),
                "descriptor_raw_sha256": sha256(encoded(descriptor_289)),
            },
            {
                "set_id": descriptor_500["set_id"],
                "descriptor_path": relative(CANONICAL_PATHS["descriptor_500"]),
                "descriptor_raw_sha256": sha256(encoded(descriptor_500)),
            },
        ],
    }
    schema_check(selector, load_locked(SELECTOR_SCHEMA), "selector")
    documents = {
        "ledger_500": ledger_500,
        "oracle_500": oracle_500,
        "manifest_500": manifest_500,
        "ledger_289": ledger_289,
        "oracle_289": oracle_289,
        "manifest_289": manifest_289,
        "descriptor_289": descriptor_289,
        "descriptor_500": descriptor_500,
        "selector": selector,
    }
    payloads = {name: encoded(value) for name, value in documents.items()}
    payloads["producer_receipt"] = producer_payload
    counts = {
        "root_capabilities": 289,
        "metadata_500_capabilities": 500,
        "promoted_capabilities": 7,
        "preserved_root_capabilities": 282,
        "preserved_metadata_500_capabilities": 493,
        "preserved_suffix": 211,
        "promoted_manifest_families": 1,
        "product_function_calls": 122,
        "external_provider_rows_changed": 0,
    }
    return documents, payloads, counts


def canonical_state(payloads: dict[str, bytes], *, allow_repair: bool) -> str:
    old_sources = {
        "ledger_289": CURRENT_LEDGER[1],
        "oracle_289": CURRENT_ORACLES[1],
        "manifest_289": CURRENT_MANIFEST[1],
        "selector": CURRENT_SELECTOR[1],
    }
    observed = {
        name: safe_canonical_bytes(path) for name, path in CANONICAL_PATHS.items()
    }
    is_old = all(
        observed[name] is not None and sha256(observed[name] or b"") == digest
        for name, digest in old_sources.items()
    ) and all(observed[name] is None for name in ("descriptor_289", "descriptor_500"))
    is_new = all(observed[name] == payloads[name] for name in CANONICAL_PATHS)
    if is_old:
        return "pre_promotion"
    if is_new:
        return "post_promotion"
    if allow_repair:
        for name, payload in observed.items():
            if payload is None:
                continue
            allowed = {payloads[name]}
            if name in old_sources:
                source_digest = old_sources[name]
                if sha256(payload) == source_digest:
                    continue
            if payload not in allowed:
                raise PromotionError(f"unrecognized canonical drift: {name}")
        return "repairable_partial_promotion"
    raise PromotionError(
        "canonical metadata is a mixed or unrecognized publication state"
    )


def safe_canonical_bytes(path: Path) -> bytes | None:
    """Read a canonical target without following symlinks or special files."""
    try:
        relative_path = path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise PromotionError(f"canonical target escapes repository: {path}") from exc
    current = REPO_ROOT
    for part in relative_path.parts[:-1]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise PromotionError(f"canonical parent is missing: {current}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise PromotionError(f"canonical parent is unsafe: {current}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PromotionError(f"cannot inspect canonical target: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise PromotionError(f"canonical target is unsafe: {path}")
    return path.read_bytes()


def atomic_install(path: Path, payload: bytes) -> None:
    safe_canonical_bytes(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        safe_canonical_bytes(path)
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        finally:
            raise


def write_or_check(write: bool, install_canonical: bool) -> dict[str, int]:
    _, payloads, counts = derive()
    state = canonical_state(payloads, allow_repair=install_canonical)
    if set(payloads) != set(OUTPUT_PATHS):
        raise PromotionError("promotion output set drift")
    for name, payload in payloads.items():
        path = OUTPUT_PATHS[name]
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        else:
            expected = EXPECTED_OUTPUT_SHA256.get(name)
            if not expected or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
                raise PromotionError(f"unfinalized checked output digest: {name}")
            if path.read_bytes() != payload or sha256(payload) != expected:
                raise PromotionError(f"checked promotion output differs: {name}")
    if install_canonical:
        if not write:
            for name, path in CANONICAL_PATHS.items():
                atomic_install(path, payloads[name])
            if canonical_state(payloads, allow_repair=False) != "post_promotion":
                raise PromotionError("canonical publication did not complete exactly")
        else:
            raise PromotionError("--write and --install-canonical are separate steps")
    counts["canonical_state_pre_install"] = state
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--install-canonical", action="store_true")
    args = parser.parse_args(argv)
    try:
        counts = write_or_check(args.write, args.install_canonical)
        print(json.dumps({"status": "pass", **counts}, sort_keys=True))
        return 0
    except (PromotionError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
