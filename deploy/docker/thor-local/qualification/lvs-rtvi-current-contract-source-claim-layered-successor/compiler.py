#!/usr/bin/env python3
"""Validate the layered LVS/RT-VLM current-contract transition read-only."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT = HERE / "layered-current-contract.json"
SCHEMA = HERE / "layered-current-contract.schema.json"
MAX_BYTES = 96_000_000

OFFICIAL = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLES = "deploy/docker/thor-local/parity/capability-oracles.json"
MANIFEST = "deploy/docker/thor-local/parity/manifest.json"
ACCEPTANCE = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
PRIOR_DIR = (
    "deploy/docker/thor-local/qualification/"
    "alerts-source-claim-layered-observation-successor"
)
SOURCE_RECEIPT = (
    "deploy/docker/thor-local/qualification/"
    "source-claim-hash-repair-successor/live-integration-receipt.json"
)
ALERTS_RECEIPT = (
    "deploy/docker/thor-local/qualification/"
    "alerts-current-contract-successor/live-integration-receipt.json"
)

PREDECESSOR_HASHES = {
    OFFICIAL: "61c2a4c0bc9d23940d954311f93824dc55c18cfc58caca002162cc1ef6808098",
    ORACLES: "24214553cbd669eb80efa7b4a602ac52328e00bd43241c839b43b10d05e22e8e",
}
PREDECESSOR_CANONICAL_HASHES = {
    OFFICIAL: "e4b99eb1809f7ce9d82d20872377dfa5e23f20d06ccd06ab8741916003c9a81c",
    ORACLES: "9be4281e11b6ba122f6004b19942bdd8935258202a3d7dc84654c4ff11ac3df6",
}
CURRENT_HASHES = {
    OFFICIAL: "fb80c2a96cc0951fc770b59a77c96d303fcf7c359e27201e16b1923e1a54a371",
    ORACLES: "4cfaa1996b6a46a1888035af773f444e505324c9edada2fee387c0399d9788ec",
}
PRESERVED_HASHES = {
    MANIFEST: "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    ACCEPTANCE: "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
}
PRIOR_LAYER_HASHES = {
    f"{PRIOR_DIR}/layered-observation.json": (
        "5014c7338ab2f003e818302015d10448a7509db4cdfc23ad5f345ad847e43ae9"
    ),
    f"{PRIOR_DIR}/compiler.py": (
        "ca4f0209deaa165a5a1469da7551745be8ea5951ad29846b3fe72628227f75af"
    ),
    f"{PRIOR_DIR}/layered-observation.schema.json": (
        "b22646fb90ecdc3e1c24893d70cd7f23e8c7b014c0b12dfe546cd6bf6e5414e6"
    ),
    SOURCE_RECEIPT: (
        "edc3c30ef79a720551fb16682555dc66d01533efd11a3ee40a6386883cde680d"
    ),
    ALERTS_RECEIPT: (
        "ad4e461066e658b1cbc016a4ab5bc209a7c4e1c3246306367bb6c4aeca32c8e9"
    ),
}
CURRENT_INPUT_HASHES = {
    "deploy/docker/thor-local/qualification/expected/lvs-mcp.json": (
        "6979727420bd3a6d0a58c4edd5ca07566fcbf3423f7a66198e12847bdd3d4d8a"
    ),
    "deploy/docker/thor-local/qualification/expected/lvs.json": (
        "d1ed1fef7a40b1459722bcdefa766919705fd546d77074da087d5a2791ebd4f0"
    ),
    "deploy/docker/thor-local/qualification/expected/rt-vlm.json": (
        "51d2c0b107fd12fb7a498c416541724edbbd01bf930f5a6b2cb37f6199d4a5ff"
    ),
    "deploy/docker/thor-local/qualification/api_inventory.json": (
        "e621f0b8a9e8be6fa04535965bdefc17910c6d88284779fc95daafeb4f66c482"
    ),
    "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py": (
        "24f6f968cbfac481dd1d310f4fe278b9db2311ec16f3f613c0525e8b77834a0d"
    ),
    "services/video-summarization/src/lvs_mcp.py": (
        "c31da08ff5847051732f08ab62344fbc898f40598bc69375910892bd35cdab2a"
    ),
    "services/video-summarization/src/via_server.py": (
        "d4bd721cc0030f49875ef56f7c07a24aea3dd895d23fd405399a9c2ebf25856c"
    ),
}

ABSENT = object()
GENERATED = object()
OLD_RT_ASSERTIONS = [
    {
        "id": "contract-01",
        "observation": "contract_identity/contract/auth",
        "operator": "equals",
        "expected": "bearer",
    },
    {
        "id": "contract-02",
        "observation": "contract_identity/contract/base_url",
        "operator": "equals",
        "expected": "http://<host>:8000",
    },
    {
        "id": "contract-03",
        "observation": "contract_identity/contract/expected_manifest",
        "operator": "equals",
        "expected": "deploy/docker/thor-local/qualification/expected/rt-vlm.json",
    },
    {
        "id": "contract-04",
        "observation": "contract_identity/contract/expected_manifest_sha256",
        "operator": "equals",
        "expected": "2f64f1e9bb208ea3fd9a4b0aaa581bee852cbd819a3b753e53eb6325c6d1121b",
    },
    {
        "id": "contract-05",
        "observation": "contract_identity/contract/operation_count",
        "operator": "equals",
        "expected": 27,
    },
    {
        "id": "contract-06",
        "observation": "contract_identity/contract/prefix",
        "operator": "equals",
        "expected": "/v1",
    },
    {
        "id": "observation-02",
        "observation": "semantic_result",
        "operator": "recorded_pass",
        "expected": True,
    },
    {
        "id": "observation-03",
        "observation": "api_contract",
        "operator": "recorded_pass",
        "expected": True,
    },
]

OFFICIAL_CHANGES = {
    "/sources/14/claim_set_sha256": (
        "2982c0ec931af90b830c27fe30d3f9e3a01627cd645dc77978b5fcbce89cb3b3",
        "e4d4a14a821f65cefe27e686ce2857c36a5869f596f7e3e7411317ff0f2f7a80",
    ),
    "/sources/17/claim_set_sha256": (
        "03c398b054ce2acf6fcf74fb0f93cb2b61a5d7a946137743696b58943606e065",
        "330d42bbd7bd19c6f136c00ac97410b66476a771f13d451597ba5f85daee9e79",
    ),
    "/sources/18/claim_set_sha256": (
        "dd5748aa7a58bc774ed46f8553709dcfbffddcff8907d265898bf63060b36145",
        "eb0abf0fbd7c796ccbe854e060900dddfe4dfdfe634510cbc7a643469d5c4554",
    ),
    "/sources/32/claim_set_sha256": (
        "d0b3c9f0811df7a07f1bf5255d0c86b9ff3e4b530b45424009628ebcc821d65c",
        "661c4f3f6b86963096727c760134d702cb75891ba4d97af83d02e64665c9bf48",
    ),
    "/capabilities/114/contract/operation_count": (27, 28),
    "/capabilities/114/contract/documented_operation_count": (ABSENT, 27),
    "/capabilities/114/contract/thor_local_operation_count": (ABSENT, 28),
    "/capabilities/114/contract/thor_local_extension": (
        ABSENT,
        {
            "method": "DELETE",
            "path": "/v1/generate_captions/requests/{request_id}",
        },
    ),
    "/capabilities/114/contract/expected_manifest_sha256": (
        "2f64f1e9bb208ea3fd9a4b0aaa581bee852cbd819a3b753e53eb6325c6d1121b",
        "51d2c0b107fd12fb7a498c416541724edbbd01bf930f5a6b2cb37f6199d4a5ff",
    ),
    "/capabilities/117/contract/expected_manifest_sha256": (
        "dcc3b500384bdc57868f018e03baad46ff9f2692f690bbb07a308bcb200dad17",
        "d1ed1fef7a40b1459722bcdefa766919705fd546d77074da087d5a2791ebd4f0",
    ),
    "/capabilities/127/contract/expected_manifest_sha256": (
        "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
        "6979727420bd3a6d0a58c4edd5ca07566fcbf3423f7a66198e12847bdd3d4d8a",
    ),
}

ORACLE_CHANGES = {
    "/oracles/114/ledger_binding/contract/operation_count": (27, 28),
    "/oracles/114/ledger_binding/contract/documented_operation_count": (ABSENT, 27),
    "/oracles/114/ledger_binding/contract/thor_local_operation_count": (ABSENT, 28),
    "/oracles/114/ledger_binding/contract/thor_local_extension": (
        ABSENT,
        {
            "method": "DELETE",
            "path": "/v1/generate_captions/requests/{request_id}",
        },
    ),
    "/oracles/114/ledger_binding/contract/expected_manifest_sha256": (
        "2f64f1e9bb208ea3fd9a4b0aaa581bee852cbd819a3b753e53eb6325c6d1121b",
        "51d2c0b107fd12fb7a498c416541724edbbd01bf930f5a6b2cb37f6199d4a5ff",
    ),
    "/oracles/114/fixture/input/contract/operation_count": (27, 28),
    "/oracles/114/fixture/input/contract/documented_operation_count": (ABSENT, 27),
    "/oracles/114/fixture/input/contract/thor_local_operation_count": (ABSENT, 28),
    "/oracles/114/fixture/input/contract/thor_local_extension": (
        ABSENT,
        {
            "method": "DELETE",
            "path": "/v1/generate_captions/requests/{request_id}",
        },
    ),
    "/oracles/114/fixture/input/contract/expected_manifest_sha256": (
        "2f64f1e9bb208ea3fd9a4b0aaa581bee852cbd819a3b753e53eb6325c6d1121b",
        "51d2c0b107fd12fb7a498c416541724edbbd01bf930f5a6b2cb37f6199d4a5ff",
    ),
    "/oracles/114/assertions": (OLD_RT_ASSERTIONS, GENERATED),
    "/oracles/114/execution_bounds/max_requests": (109, 113),
    "/oracles/114/execution_bounds/workload/units": (27, 28),
    "/oracles/114/execution_bounds/workload/calculated_max_requests": (109, 113),
    "/oracles/114/execution_bounds/max_actions": (109, 113),
    "/oracles/117/ledger_binding/contract/expected_manifest_sha256": (
        "dcc3b500384bdc57868f018e03baad46ff9f2692f690bbb07a308bcb200dad17",
        "d1ed1fef7a40b1459722bcdefa766919705fd546d77074da087d5a2791ebd4f0",
    ),
    "/oracles/117/fixture/input/contract/expected_manifest_sha256": (
        "dcc3b500384bdc57868f018e03baad46ff9f2692f690bbb07a308bcb200dad17",
        "d1ed1fef7a40b1459722bcdefa766919705fd546d77074da087d5a2791ebd4f0",
    ),
    "/oracles/117/assertions/3/expected": (
        "dcc3b500384bdc57868f018e03baad46ff9f2692f690bbb07a308bcb200dad17",
        "d1ed1fef7a40b1459722bcdefa766919705fd546d77074da087d5a2791ebd4f0",
    ),
    "/oracles/127/ledger_binding/contract/expected_manifest_sha256": (
        "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
        "6979727420bd3a6d0a58c4edd5ca07566fcbf3423f7a66198e12847bdd3d4d8a",
    ),
    "/oracles/127/fixture/input/contract/expected_manifest_sha256": (
        "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
        "6979727420bd3a6d0a58c4edd5ca07566fcbf3423f7a66198e12847bdd3d4d8a",
    ),
    "/oracles/127/assertions/2/expected": (
        "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
        "6979727420bd3a6d0a58c4edd5ca07566fcbf3423f7a66198e12847bdd3d4d8a",
    ),
}

RECORDS = (
    {
        "capability_id": "api.core.rt-vlm-27",
        "capability_index": 114,
        "oracle_index": 114,
        "expected_manifest": "deploy/docker/thor-local/qualification/expected/rt-vlm.json",
        "expected_manifest_sha256": CURRENT_INPUT_HASHES[
            "deploy/docker/thor-local/qualification/expected/rt-vlm.json"
        ],
        "source_ids": ["rt-vlm-api-doc-3.2.1"],
    },
    {
        "capability_id": "api.core.lvs-17",
        "capability_index": 117,
        "oracle_index": 117,
        "expected_manifest": "deploy/docker/thor-local/qualification/expected/lvs.json",
        "expected_manifest_sha256": CURRENT_INPUT_HASHES[
            "deploy/docker/thor-local/qualification/expected/lvs.json"
        ],
        "source_ids": ["lvs-api-doc-3.2.1"],
    },
    {
        "capability_id": "api.core.lvs-mcp-doc-13-repo-9",
        "capability_index": 127,
        "oracle_index": 127,
        "expected_manifest": "deploy/docker/thor-local/qualification/expected/lvs-mcp.json",
        "expected_manifest_sha256": CURRENT_INPUT_HASHES[
            "deploy/docker/thor-local/qualification/expected/lvs-mcp.json"
        ],
        "source_ids": ["lvs-doc-3.2.1", "main-repository-7732edf8"],
    },
)


class ContractError(RuntimeError):
    """A locked input, layered transition, or boundary invariant failed."""


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    )


def _repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(p in {"", ".", ".."} for p in pure.parts)
    ):
        raise ContractError(f"unsafe repository path: {relative}")
    path = REPO_ROOT.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"not a regular non-symlink file: {relative}")
    return path


def regular_bytes(relative: str) -> bytes:
    path = _repo_path(relative)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
        raise ContractError(f"invalid source type or size: {relative}")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        payload = os.read(descriptor, metadata.st_size + 1)
    finally:
        os.close(descriptor)
    if len(payload) != metadata.st_size:
        raise ContractError(f"short or long read: {relative}")
    return payload


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ContractError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode(),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ContractError(f"non-finite JSON value in {label}: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON root is not an object: {label}")
    return value


def _parts(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ContractError(f"invalid pointer: {pointer}")
    return [
        part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")
    ]


def _get(value: Any, pointer: str) -> Any:
    current = value
    for part in _parts(pointer):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _lookup(value: Any, pointer: str) -> Any:
    current = value
    for part in _parts(pointer):
        if isinstance(current, list):
            index = int(part)
            if index >= len(current):
                return ABSENT
            current = current[index]
        else:
            if part not in current:
                return ABSENT
            current = current[part]
    return current


def _set(value: Any, pointer: str, replacement: Any) -> None:
    parts = _parts(pointer)
    current = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    leaf = parts[-1]
    if isinstance(current, list):
        current[int(leaf)] = replacement
    else:
        current[leaf] = replacement


def _delete(value: Any, pointer: str) -> None:
    parts = _parts(pointer)
    current = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    leaf = parts[-1]
    if isinstance(current, list):
        del current[int(leaf)]
    else:
        del current[leaf]


def leaf_diffs(before: Any, after: Any, pointer: str = "") -> list[str]:
    if type(before) is not type(after):
        return [pointer]
    if isinstance(before, dict):
        result: list[str] = []
        for key in before.keys() | after.keys():
            escaped = key.replace("~", "~0").replace("/", "~1")
            child = f"{pointer}/{escaped}"
            if key not in before or key not in after:
                result.append(child)
            else:
                result.extend(leaf_diffs(before[key], after[key], child))
        return result
    if isinstance(before, list):
        if len(before) != len(after):
            return [pointer]
        result = []
        for index, (old, new) in enumerate(zip(before, after, strict=True)):
            result.extend(leaf_diffs(old, new, f"{pointer}/{index}"))
        return result
    return [] if before == after else [pointer]


def transition(relative: str) -> tuple[dict[str, Any], dict[str, Any]]:
    changes = OFFICIAL_CHANGES if relative == OFFICIAL else ORACLE_CHANGES
    live_bytes = regular_bytes(relative)
    if sha256(live_bytes) != CURRENT_HASHES[relative]:
        raise ContractError(
            f"live target is not the locked current successor: {relative}"
        )
    live = strict_json(live_bytes, relative)
    predecessor = copy.deepcopy(live)
    for pointer, (old, new) in changes.items():
        actual = _lookup(live, pointer)
        if new is not GENERATED and actual != new:
            raise ContractError(f"current value drift at {pointer}")
        if old is ABSENT:
            _delete(predecessor, pointer)
        else:
            _set(predecessor, pointer, old)
    if canonical_sha256(predecessor) != PREDECESSOR_CANONICAL_HASHES[relative]:
        raise ContractError(
            f"transition does not reverse to the prior layered semantic state: {relative}"
        )
    if sorted(leaf_diffs(predecessor, live)) != sorted(changes):
        raise ContractError(f"semantic pointer allowlist drift: {relative}")
    return predecessor, live


def derived_claim_hashes(ledger: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in ledger["sources"]:
        claims = []
        for capability in ledger["capabilities"]:
            for claim in capability.get("source_claims", []):
                if claim.get("source_id") == source["id"]:
                    claims.append(
                        {
                            "capability_id": capability["id"],
                            "locator": claim["locator"],
                            "contract": capability["contract"],
                        }
                    )
        canonical = sorted(
            json.dumps(item, sort_keys=True, separators=(",", ":")) for item in claims
        )
        result[source["id"]] = sha256(
            json.dumps(canonical, separators=(",", ":")).encode()
        )
    return result


def _validate_prior_layers() -> None:
    for relative, expected in PRIOR_LAYER_HASHES.items():
        if sha256(regular_bytes(relative)) != expected:
            raise ContractError(f"prior layer drift: {relative}")
    prior = strict_json(
        regular_bytes(f"{PRIOR_DIR}/layered-observation.json"), "prior observation"
    )
    if (
        prior.get("summary", {}).get("current_official_raw_sha256")
        != PREDECESSOR_HASHES[OFFICIAL]
    ):
        raise ContractError("prior source-claim terminal digest drift")
    if (
        prior.get("layers", [{}])[0].get("receipt_raw_sha256")
        != PRIOR_LAYER_HASHES[SOURCE_RECEIPT]
    ):
        raise ContractError("prior source-claim receipt binding drift")
    oracle_rows = [
        row
        for row in prior.get("layers", [])
        if row.get("layer_id") == "alerts-current-contract-oracles"
    ]
    if (
        len(oracle_rows) != 1
        or oracle_rows[0].get("input_raw_sha256") != PREDECESSOR_HASHES[ORACLES]
    ):
        raise ContractError("prior Alerts oracle terminal digest drift")


def _validate_current_inputs() -> None:
    for relative, expected in {**CURRENT_INPUT_HASHES, **PRESERVED_HASHES}.items():
        if sha256(regular_bytes(relative)) != expected:
            raise ContractError(f"current input drift: {relative}")
    rt = strict_json(
        regular_bytes("deploy/docker/thor-local/qualification/expected/rt-vlm.json"),
        "RT-VLM expected manifest",
    )
    operations = {(row["method"], row["path"]) for row in rt["operations"]}
    exact_abort = ("DELETE", "/v1/generate_captions/requests/{request_id}")
    if (
        rt.get("declared_operation_count") != 28
        or rt.get("normalized_unique_operation_count") != 28
    ):
        raise ContractError("RT-VLM expected operation count is not 28")
    if exact_abort not in operations or len(operations) != 28:
        raise ContractError(
            "exact RT-VLM request abort route is not uniquely inventoried"
        )


def _validate_boundaries(official: dict[str, Any], oracles: dict[str, Any]) -> None:
    for record in RECORDS:
        capability = official["capabilities"][record["capability_index"]]
        oracle = oracles["oracles"][record["oracle_index"]]
        if capability.get("id") != record["capability_id"]:
            raise ContractError("capability identity drift")
        if oracle.get("capability_id") != record["capability_id"]:
            raise ContractError("oracle identity drift")
        if (
            capability["contract"]["expected_manifest_sha256"]
            != record["expected_manifest_sha256"]
        ):
            raise ContractError("capability manifest binding drift")
    derived = derived_claim_hashes(official)
    if any(
        source["claim_set_sha256"] != derived[source["id"]]
        for source in official["sources"]
    ):
        raise ContractError("official source claim-set hashes are not verifier-derived")
    if any(row.get("evidence") for row in oracles["oracles"]):
        raise ContractError("runtime evidence addition is forbidden")
    if any(row.get("current_state") == "passed_current" for row in oracles["oracles"]):
        raise ContractError("passed_current promotion is forbidden")
    if (
        oracles.get("policy", {}).get("warehouse_sample_bundle")
        != "excluded; custom-data fixtures remain in scope"
    ):
        raise ContractError("Warehouse exclusion drift")


def build_expected() -> dict[str, Any]:
    _validate_prior_layers()
    _validate_current_inputs()
    _old_official, official = transition(OFFICIAL)
    _old_oracles, oracles = transition(ORACLES)
    _validate_boundaries(official, oracles)
    records = []
    for record in RECORDS:
        capability_prefix = f"/capabilities/{record['capability_index']}/"
        oracle_prefix = f"/oracles/{record['oracle_index']}/"
        records.append(
            {
                **record,
                "official_semantic_pointers": sorted(
                    pointer
                    for pointer in OFFICIAL_CHANGES
                    if pointer.startswith(capability_prefix)
                ),
                "oracle_semantic_pointers": sorted(
                    pointer
                    for pointer in ORACLE_CHANGES
                    if pointer.startswith(oracle_prefix)
                ),
            }
        )
    return {
        "schema_version": 1,
        "observation_id": "thor-vss-3.2.1-lvs-rtvi-current-contract-source-claim-layered-successor",
        "mode": "read_only_layered_current_contract_observation_no_writes",
        "predecessor_layers": {
            "layered_observation_path": f"{PRIOR_DIR}/layered-observation.json",
            "layered_observation_raw_sha256": PRIOR_LAYER_HASHES[
                f"{PRIOR_DIR}/layered-observation.json"
            ],
            "source_claim_receipt_path": SOURCE_RECEIPT,
            "source_claim_receipt_raw_sha256": PRIOR_LAYER_HASHES[SOURCE_RECEIPT],
            "alerts_receipt_path": ALERTS_RECEIPT,
            "alerts_receipt_raw_sha256": PRIOR_LAYER_HASHES[ALERTS_RECEIPT],
            "official_raw_sha256": PREDECESSOR_HASHES[OFFICIAL],
            "oracles_raw_sha256": PREDECESSOR_HASHES[ORACLES],
        },
        "current_contract_inputs": [
            {"path": relative, "raw_sha256": digest}
            for relative, digest in sorted(CURRENT_INPUT_HASHES.items())
        ],
        "preserved_live_identities": [
            {"path": relative, "raw_sha256": digest}
            for relative, digest in sorted(PRESERVED_HASHES.items())
        ],
        "changed_records": records,
        "transitions": [
            {
                "path": OFFICIAL,
                "predecessor_raw_sha256": PREDECESSOR_HASHES[OFFICIAL],
                "current_raw_sha256": CURRENT_HASHES[OFFICIAL],
                "semantic_leaf_count": len(OFFICIAL_CHANGES),
                "semantic_pointers": sorted(OFFICIAL_CHANGES),
            },
            {
                "path": ORACLES,
                "predecessor_raw_sha256": PREDECESSOR_HASHES[ORACLES],
                "current_raw_sha256": CURRENT_HASHES[ORACLES],
                "semantic_leaf_count": len(ORACLE_CHANGES),
                "semantic_pointers": sorted(ORACLE_CHANGES),
            },
        ],
        "policy": {
            "writes_performed": False,
            "network_allowed": False,
            "docker_allowed": False,
            "services_allowed": False,
            "runtime_evidence_added": False,
            "passed_current_promotions": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "summary": {
            "changed_capability_records": 3,
            "changed_oracle_records": 3,
            "official_semantic_leaf_count": len(OFFICIAL_CHANGES),
            "oracle_semantic_leaf_count": len(ORACLE_CHANGES),
            "total_semantic_leaf_count": len(OFFICIAL_CHANGES) + len(ORACLE_CHANGES),
            "rt_vlm_operation_count": 28,
            "lvs_operation_count": 18,
            "lvs_mcp_tool_count": 13,
            "runtime_evidence_records": 0,
            "promotions": 0,
        },
    }


def validate() -> dict[str, Any]:
    expected = build_expected()
    observed = strict_json(ARTIFACT.read_bytes(), "layered current-contract artifact")
    schema = strict_json(SCHEMA.read_bytes(), "layered current-contract schema")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(observed),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        raise ContractError(f"artifact schema violation: {errors[0].message}")
    if observed != expected:
        raise ContractError("checked layered current-contract artifact drift")
    if sha256(regular_bytes(OFFICIAL)) != CURRENT_HASHES[OFFICIAL]:
        raise ContractError("live official ledger is not the current successor")
    if sha256(regular_bytes(ORACLES)) != CURRENT_HASHES[ORACLES]:
        raise ContractError("live oracle ledger is not the current successor")
    return {
        "status": "valid",
        "writes_performed": False,
        **expected["summary"],
        "warehouse_sample_bundle": expected["policy"]["warehouse_sample_bundle"],
    }


def review() -> dict[str, Any]:
    expected = build_expected()
    return {
        "status": "reviewed",
        "writes_performed": False,
        "artifact_raw_sha256": sha256(encoded(expected)),
        **expected["summary"],
    }


def rollback_plan() -> dict[str, Any]:
    build_expected()
    return {
        "status": "rollback_plan_only",
        "writes_performed": False,
        "targets": [
            {"path": path, "restore_raw_sha256": digest}
            for path, digest in PREDECESSOR_HASHES.items()
        ],
        "semantic_leaf_count": len(OFFICIAL_CHANGES) + len(ORACLE_CHANGES),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("plan", "review", "validate", "rollback-plan")
    )
    args = parser.parse_args()
    result = (
        rollback_plan()
        if args.command == "rollback-plan"
        else review()
        if args.command in {"plan", "review"}
        else validate()
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
