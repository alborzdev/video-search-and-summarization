"""Deterministic Stage-2 promotion projection for MV3DT config-utils evidence."""

from __future__ import annotations

from collections import Counter
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
TARGET_IDS = (
    "tool.mv3dt.cam-info-generator",
    "tool.mv3dt.pub-sub-generator",
)
AGGREGATE = (
    "deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/aggregate-runtime-receipt.json",
    "7fb004dd62139c3d738e5c2b4bfcf7430ec0c1e3000efa664f4cfb12b1406cf2",
)
CURRENT_LEDGER = (
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "e94599599f8442f884aa4b184deafe3c5ce59aae310dd91ad0552133740c29e7",
)
CURRENT_ORACLES = (
    "deploy/docker/thor-local/parity/capability-oracles.json",
    "c45bc270163b2369b1650d638f5fa0e3f53aa327e4b0375e6773246ca35fbbf5",
)
SELECTED_LEDGER = (
    "deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/post-state-official-capabilities.json",
    "6698f904f93fbefa7c2bc9c7512ccf4765d3ba27200843a86ea1e6522375ae73",
)
CURRENT_MANIFEST = (
    "deploy/docker/thor-local/parity/manifest.json",
    "0e1bb1fedbc3184e0e86cad4c6bf943e62d325fafbc21638df0b67f2483abcf7",
)
SELECTED_MANIFEST = (
    "deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/post-state-manifest.json",
    "b2fa6b72ca756b37103178cb3d40aeed9e8d4d5c137883812ff0600f62168fb8",
)
OFFICIAL_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/official-capabilities.schema.json"
)
EXECUTOR = (
    "deploy/docker/thor-local/qualification/mv3dt-config-utils-runtime-evidence-successor/executor.py",
    "650894ecc69baa518a92d8315c2d11c356b815a299ee50dc1e7b21737a87d567",
)
RESULT_SCHEMA = (
    "deploy/docker/thor-local/qualification/mv3dt-config-utils-runtime-evidence-successor/result.schema.json",
    "0cf0bb117d42df0bd01c00c10da31928e3467948a682ae9dffbafeff9fb80e09",
)
ROOT_ORACLE_SCHEMA = (
    "deploy/docker/thor-local/parity/capability-oracles.schema.json",
    "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1",
)
SELECTED_ORACLE_SCHEMA = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.schema.json",
    "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
)
ROOT_ACCEPTANCE = (
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
)
SELECTED_ACCEPTANCE = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-acceptance-inventory.json",
    "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
)
METADATA_SCHEMA = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json",
    "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
)
SELECTOR_SCHEMA = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json",
    "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
)
FINAL_GAP = (
    "No known gap: a current target-bound offline runtime receipt covers the exact "
    "MV3DT configuration generator contract twice, including adjacent-negative "
    "behavior, determinism, and exact cleanup without the Warehouse sample bundle."
)
FINAL_FAMILY_GAP = (
    "No known gap: both MV3DT configuration generators passed the current target-bound "
    "offline runtime contract twice, including adjacent-negative behavior, determinism, "
    "and exact cleanup without the Warehouse sample bundle."
)
RECEIPT_PATHS = {
    TARGET_IDS[0]: PACKAGE / "receipts/00-cam-info-generator.json",
    TARGET_IDS[1]: PACKAGE / "receipts/01-pub-sub-generator.json",
}
OUTPUT_PATHS = {
    "official_schema": PACKAGE / "post-state-official-capabilities.schema.json",
    "ledger_500": PACKAGE / "post-state-official-capabilities.json",
    "manifest_500": PACKAGE / "post-state-manifest.json",
    "ledger_289": PACKAGE / "post-state-root-official-capabilities.json",
    "oracle_289": PACKAGE / "post-state-root-capability-oracles.json",
    "manifest_289": PACKAGE / "post-state-root-manifest.json",
    "descriptor_289": PACKAGE / "post-state-metadata-set-289.json",
    "descriptor_500": PACKAGE / "post-state-metadata-set-500.json",
    "selector": PACKAGE / "post-state-selector.json",
}
# Filled only after a reviewed --write derivation; check mode rejects unlocked output.
EXPECTED_OUTPUT_SHA256: dict[str, str] = {
    "official_schema": "71f1e0f1d820c3809ea3b55abb504071321f61c6e36978226dd10108c7b2384b",
    "ledger_500": "315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229",
    "manifest_500": "97d7801134de5022bce7636f47dd08a34df78d913e01a59a5faddb9376d5dc37",
    "ledger_289": "834bb40b576d9e9e546cecb3bdb866993b7be7fd3bf9d5e9e19a0d852d4e4e39",
    "oracle_289": "856a93bf11bbe4cb77b315fe5ae1884ccedb7dc83107f4142c6721e78688308c",
    "manifest_289": "629f3dbf69b42a73037d7dd5e8f8b369dd72885e9a82f3a59fcfa4f19cbc0744",
    "descriptor_289": "f78ad2adbb93b0966318c365c00d0ddd7fe84e59a37d9d4cf061a99a73d9a1ef",
    "descriptor_500": "2c13a744a2cbb5dd143f72be5872dc18b24653aca7d17f2e45e2b9c06f3dd0ae",
    "selector": "809e6aad4ad0b319f50b548132b7a288ca0d8a8281281c542085bdd58c10d125",
    "receipt:tool.mv3dt.cam-info-generator": "8e657734a2bfb511115e45dd58e372c68012969f5d0ead726f5cf27e8f5e7044",
    "receipt:tool.mv3dt.pub-sub-generator": "f7a1c4c0c93122a2f884c7454720ae75b61c4533ba2d7001fd38bf58d7962a4a",
}
POST_PROMOTION_SOURCE_SHA256 = {
    CURRENT_LEDGER[0]: EXPECTED_OUTPUT_SHA256["ledger_289"],
    CURRENT_MANIFEST[0]: EXPECTED_OUTPUT_SHA256["manifest_289"],
    CURRENT_ORACLES[0]: EXPECTED_OUTPUT_SHA256["oracle_289"],
}


class PromotionError(RuntimeError):
    """A receipt binding or exact promotion delta failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_locked(source: tuple[str, str]) -> Any:
    path, expected = source
    payload = (REPO_ROOT / path).read_bytes()
    if digest(payload) not in {expected, POST_PROMOTION_SOURCE_SHA256.get(path)}:
        raise PromotionError(f"raw source digest drift: {path}")
    return json.loads(payload)


def schema_check(document: Any, schema: Any, label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        path = "/".join(map(str, errors[0].absolute_path))
        raise PromotionError(f"{label} schema failure at {path}: {errors[0].message}")


def _load_executor() -> Any:
    path, expected = EXECUTOR
    source = REPO_ROOT / path
    if digest(source.read_bytes()) != expected:
        raise PromotionError("runtime executor source binding drift")
    spec = importlib.util.spec_from_file_location("mv3dt_promotion_executor", source)
    if spec is None or spec.loader is None:
        raise PromotionError("cannot load runtime executor validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_aggregate(aggregate: dict[str, Any], oracle_500: dict[str, Any]) -> None:
    schema_check(aggregate, load_locked(RESULT_SCHEMA), "aggregate receipt")
    try:
        _load_executor().validate_result_exact(
            aggregate, development=False, oracle_registry=oracle_500
        )
    except Exception as exc:
        raise PromotionError(
            f"deep aggregate receipt validation failed: {exc}"
        ) from exc
    promotion = aggregate["promotion"]
    if promotion != {
        "aggregate_is_promotable": True,
        "dependency_pin_parity_claimed": False,
        "development_smoke_only": False,
        "eligible_capability_ids": list(TARGET_IDS),
        "family_id": "mv3dt-config-utils",
        "ledger_mutation_performed": False,
        "receipt_is_runtime_evidence": True,
        "requires_separate_reviewed_metadata_integration": True,
    }:
        raise PromotionError("aggregate promotion envelope drift")
    environment = aggregate["environment"]
    if (
        environment["declared_versions_match_observed"] is not False
        or environment["normative_scope"] != "observed_current_thor_behavior_only"
        or "does not claim exact dependency-pin parity"
        not in environment["dependency_caveat"]
    ):
        raise PromotionError("aggregate dependency caveat drift")
    if aggregate["bindings"] != {
        **aggregate["bindings"],
        "checkout_clean": True,
        "checkout_head": "537b3e1fd0b5104de5a09515a53bade8ef5e9a79",
        "checkout_tree": "8de1c2f0108c5531e8f1c05acab6aaae640809ce",
        "checkout_status_porcelain_sha256": digest(b""),
    }:
        raise PromotionError("aggregate clean-checkout provenance drift")


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
        source["claim_set_sha256"] = digest(canonical_bytes(canonical_claims))


def aggregate_ref(capability_id: str, index: int) -> dict[str, str]:
    return {
        "path": AGGREGATE[0],
        "sha256": AGGREGATE[1],
        "capability_id": capability_id,
        "json_pointer": f"/capability_results/{index}",
    }


def promote_ledger(baseline: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(baseline)
    found: list[str] = []
    for row in output["capabilities"]:
        if row["id"] not in TARGET_IDS:
            continue
        index = TARGET_IDS.index(row["id"])
        found.append(row["id"])
        row["thor_state"] = "wired"
        row["runtime_state"] = "passed_current"
        row["gap"] = FINAL_GAP
        row["runtime_evidence"] = [aggregate_ref(row["id"], index)]
    if found != list(TARGET_IDS):
        raise PromotionError("ledger target identity/order drift")
    refresh_claim_hashes(output)
    return output


def promote_manifest(baseline: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(baseline)
    rows = [row for row in output["features"] if row["id"] == "mv3dt-config-utils"]
    if len(rows) != 1:
        raise PromotionError("MV3DT family identity drift")
    row = rows[0]
    row["thor_state"] = "wired"
    row["runtime_state"] = "passed_current"
    row["gap"] = FINAL_FAMILY_GAP
    additions = [
        AGGREGATE[0],
        *(relative(RECEIPT_PATHS[capability_id]) for capability_id in TARGET_IDS),
        relative(PACKAGE / "post-state-capability-oracles.json"),
        relative(PACKAGE / "EVIDENCE.md"),
    ]
    row["thor_evidence"] = [*row["thor_evidence"], *additions]
    if len(set(row["thor_evidence"])) != len(row["thor_evidence"]):
        raise PromotionError("MV3DT family evidence is not unique")
    return output


def validate_receipts(
    aggregate: dict[str, Any], oracle_500: dict[str, Any], ledger_500: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    oracle_rows = {row["capability_id"]: row for row in oracle_500["oracles"]}
    ledger_rows = {row["id"]: row for row in ledger_500["capabilities"]}
    results = aggregate["capability_results"]
    if [row["capability_id"] for row in results] != list(TARGET_IDS):
        raise PromotionError("aggregate capability result order drift")
    receipts: dict[str, dict[str, Any]] = {}
    for index, (capability_id, result) in enumerate(
        zip(TARGET_IDS, results, strict=True)
    ):
        receipt = result["official_receipt"]
        binding = result["runtime_evidence_binding"]
        oracle = oracle_rows[capability_id]
        if (
            receipt["capability_id"] != capability_id
            or receipt["oracle_sha256"] != digest(canonical_bytes(oracle))
            or binding["official_receipt_sha256"] != digest(canonical_bytes(receipt))
            or binding["oracle_sha256"] != digest(canonical_bytes(oracle))
            or binding["oracle_document_sha256"] != digest(encoded(oracle_500))
            or binding["capability_evidence_sha256"]
            != digest(
                canonical_bytes(
                    {
                        key: value
                        for key, value in result.items()
                        if key not in {"official_receipt", "runtime_evidence_binding"}
                    }
                )
            )
            or ledger_rows[capability_id]["runtime_evidence"]
            != [aggregate_ref(capability_id, index)]
        ):
            raise PromotionError(f"nested receipt/outer binding drift: {capability_id}")
        if (
            receipt["assertions"][5]["observed"] is not False
            or receipt["assertions"][6]["observed"] is not False
        ):
            raise PromotionError(f"wave3 semantics changed: {capability_id}")
        receipts[capability_id] = copy.deepcopy(receipt)
    return receipts


def validate_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    key: str,
    targets: set[str],
    label: str,
) -> None:
    old = {row[key]: row for row in before["capabilities"]}
    new = {row[key]: row for row in after["capabilities"]}
    changed = {
        row_id
        for row_id in old
        if canonical_bytes(old[row_id]) != canonical_bytes(new[row_id])
    }
    if list(old) != list(new) or changed != targets:
        raise PromotionError(f"{label} did not change exactly the target rows")


def validate_manifest_delta(before: dict[str, Any], after: dict[str, Any]) -> None:
    old = {row["id"]: row for row in before["features"]}
    new = {row["id"]: row for row in after["features"]}
    changed = {
        row_id
        for row_id in old
        if canonical_bytes(old[row_id]) != canonical_bytes(new[row_id])
    }
    if list(old) != list(new) or changed != {"mv3dt-config-utils"}:
        raise PromotionError("manifest did not change exactly one family")


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
    official_schema_sha: str,
    oracle_schema: tuple[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "set_id": set_id,
        "mode": "immutable_static_metadata_set",
        "lifecycle": "live_ready",
        "target": {
            "product_version": "3.2.1",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
        },
        "expected_counts": {
            "capabilities": count,
            "oracles": count,
            "feature_families": 55,
        },
        "documents": {
            "manifest": {
                "path": manifest_path,
                "raw_sha256": digest(encoded(manifest)),
                "schema_version": 1,
            },
            "official_capabilities": {
                "path": ledger_path,
                "raw_sha256": digest(encoded(ledger)),
                "schema_version": 1,
                "schema_id": "official_capabilities_schema",
            },
            "capability_oracles": {
                "path": oracle_path,
                "raw_sha256": digest(encoded(oracle)),
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
                "path": OFFICIAL_SCHEMA_PATH,
                "raw_sha256": official_schema_sha,
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


def derive(
    oracle_500: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, int]]:
    aggregate = load_locked(AGGREGATE)
    validate_aggregate(aggregate, oracle_500)
    current_ledger = load_locked(CURRENT_LEDGER)
    selected_ledger = load_locked(SELECTED_LEDGER)
    if [row["id"] for row in current_ledger["capabilities"]] != [
        row["id"] for row in selected_ledger["capabilities"][:289]
    ]:
        raise PromotionError("current ledger is not selected Metadata-500 prefix")
    current_ledger_baseline = copy.deepcopy(current_ledger)
    selected_ledger_rows = {
        row["id"]: row for row in selected_ledger["capabilities"][:289]
    }
    for index, row in enumerate(current_ledger_baseline["capabilities"]):
        if row["id"] in TARGET_IDS:
            current_ledger_baseline["capabilities"][index] = copy.deepcopy(
                selected_ledger_rows[row["id"]]
            )
    refresh_claim_hashes(current_ledger_baseline)
    baseline_500 = copy.deepcopy(selected_ledger)
    baseline_500["capabilities"][:289] = copy.deepcopy(
        current_ledger_baseline["capabilities"]
    )
    refresh_claim_hashes(baseline_500)
    ledger_500 = promote_ledger(baseline_500)
    ledger_289 = promote_ledger(current_ledger_baseline)
    if (
        ledger_500["capabilities"][:289] != ledger_289["capabilities"]
        or ledger_500["capabilities"][289:] != selected_ledger["capabilities"][289:]
    ):
        raise PromotionError("promoted 289 prefix or preserved 211 suffix drift")

    current_manifest = load_locked(CURRENT_MANIFEST)
    selected_manifest = load_locked(SELECTED_MANIFEST)
    current_manifest_baseline = copy.deepcopy(current_manifest)
    selected_family = next(
        row
        for row in selected_manifest["features"]
        if row["id"] == "mv3dt-config-utils"
    )
    for index, row in enumerate(current_manifest_baseline["features"]):
        if row["id"] == "mv3dt-config-utils":
            current_manifest_baseline["features"][index] = copy.deepcopy(
                selected_family
            )
    manifest_289 = promote_manifest(current_manifest_baseline)
    manifest_500 = promote_manifest(selected_manifest)
    current_oracles = load_locked(CURRENT_ORACLES)
    oracle_289 = copy.deepcopy(current_oracles)
    promoted_oracles = {
        row["capability_id"]: row for row in oracle_500["oracles"][:289]
    }
    for index, row in enumerate(oracle_289["oracles"]):
        if row["capability_id"] in TARGET_IDS:
            oracle_289["oracles"][index] = copy.deepcopy(
                promoted_oracles[row["capability_id"]]
            )
    schema_check(oracle_289, load_locked(ROOT_ORACLE_SCHEMA), "root oracle")
    receipts = validate_receipts(aggregate, oracle_500, ledger_500)

    official_schema_payload = (REPO_ROOT / OFFICIAL_SCHEMA_PATH).read_bytes()
    official_schema = json.loads(official_schema_payload)
    official_schema_sha = digest(official_schema_payload)
    schema_check(ledger_289, official_schema, "root official ledger")
    schema_check(ledger_500, official_schema, "Metadata-500 official ledger")
    validate_delta(
        baseline_500, ledger_500, "id", set(TARGET_IDS), "Metadata-500 ledger"
    )
    validate_delta(
        current_ledger_baseline,
        ledger_289,
        "id",
        set(TARGET_IDS),
        "root ledger",
    )
    validate_manifest_delta(current_manifest_baseline, manifest_289)
    validate_manifest_delta(selected_manifest, manifest_500)

    def path(name: str) -> str:
        return relative(OUTPUT_PATHS[name])

    descriptor_289 = descriptor(
        set_id="thor-vss-3.2.1-current-mv3dt-config-utils-289",
        count=289,
        manifest_path="deploy/docker/thor-local/parity/manifest.json",
        manifest=manifest_289,
        ledger_path="deploy/docker/thor-local/parity/official-capabilities.json",
        ledger=ledger_289,
        oracle_path="deploy/docker/thor-local/parity/capability-oracles.json",
        oracle=oracle_289,
        acceptance=ROOT_ACCEPTANCE,
        official_schema_sha=official_schema_sha,
        oracle_schema=ROOT_ORACLE_SCHEMA,
    )
    descriptor_500 = descriptor(
        set_id="thor-vss-3.2.1-current-mv3dt-config-utils-500",
        count=500,
        manifest_path=path("manifest_500"),
        manifest=manifest_500,
        ledger_path=path("ledger_500"),
        ledger=ledger_500,
        oracle_path=relative(PACKAGE / "post-state-capability-oracles.json"),
        oracle=oracle_500,
        acceptance=SELECTED_ACCEPTANCE,
        official_schema_sha=official_schema_sha,
        oracle_schema=SELECTED_ORACLE_SCHEMA,
    )
    schema_check(descriptor_289, load_locked(METADATA_SCHEMA), "289 descriptor")
    schema_check(descriptor_500, load_locked(METADATA_SCHEMA), "500 descriptor")
    future_descriptor_paths = {
        289: "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-mv3dt-config-utils-289.json",
        500: "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-mv3dt-config-utils-500.json",
    }
    selector = {
        "schema_version": 1,
        "selected_set": descriptor_500["set_id"],
        "available_sets": [
            {
                "set_id": descriptor_289["set_id"],
                "descriptor_path": future_descriptor_paths[289],
                "descriptor_raw_sha256": digest(encoded(descriptor_289)),
            },
            {
                "set_id": descriptor_500["set_id"],
                "descriptor_path": future_descriptor_paths[500],
                "descriptor_raw_sha256": digest(encoded(descriptor_500)),
            },
        ],
    }
    schema_check(selector, load_locked(SELECTOR_SCHEMA), "selector")
    documents = {
        "ledger_500": ledger_500,
        "manifest_500": manifest_500,
        "ledger_289": ledger_289,
        "oracle_289": oracle_289,
        "manifest_289": manifest_289,
        "descriptor_289": descriptor_289,
        "descriptor_500": descriptor_500,
        "selector": selector,
    }
    payloads = {name: encoded(value) for name, value in documents.items()}
    payloads["official_schema"] = official_schema_payload
    for capability_id, receipt in receipts.items():
        payloads[f"receipt:{capability_id}"] = encoded(receipt)
    states = Counter(row["runtime_state"] for row in ledger_500["capabilities"])
    counts = {
        "official_capabilities": 500,
        "root_capabilities": 289,
        "official_receipts": 2,
        "manifest_features": 55,
        "passed_current": states["passed_current"],
        "preserved_ledger_rows": 498,
        "preserved_manifest_features": 54,
        "selected_suffix": 211,
    }
    return documents, payloads, counts


def write_or_check(oracle_500: dict[str, Any], write: bool) -> dict[str, int]:
    _, payloads, counts = derive(oracle_500)
    destinations = {
        **OUTPUT_PATHS,
        **{f"receipt:{key}": value for key, value in RECEIPT_PATHS.items()},
    }
    if set(payloads) != set(destinations):
        raise PromotionError("promotion output set drift")
    for name, payload in payloads.items():
        path = destinations[name]
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            continue
        expected = EXPECTED_OUTPUT_SHA256.get(name)
        if expected is None or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise PromotionError(f"unfinalized checked output digest: {name}")
        if path.read_bytes() != payload or digest(payload) != expected:
            raise PromotionError(f"checked promotion output differs: {name}")
    return counts
