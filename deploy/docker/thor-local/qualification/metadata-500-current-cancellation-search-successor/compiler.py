#!/usr/bin/env python3
"""Validate the current post-cancellation/post-Search Metadata-500 successor."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
LEDGER_OUTPUT = PACKAGE / "post-state-official-capabilities.json"
ORACLE_OUTPUT = PACKAGE / "post-state-capability-oracles.json"
MAX_JSON_BYTES = 96_000_000

BASE = "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor"
SOURCES: dict[str, tuple[str, str]] = {
    "current_ledger": (
        "deploy/docker/thor-local/parity/official-capabilities.json",
        "8639e39c636a2bd1682cf5b80063bb6d4a0545274e8f247c3cce580f30cef0bd",
    ),
    "current_oracles": (
        "deploy/docker/thor-local/parity/capability-oracles.json",
        "03da833f7a663fb170bedc9e7ebcc2e3caa8d8978beb9aaa2818526032577b7a",
    ),
    "base_ledger": (
        f"{BASE}/post-state-official-capabilities.json",
        "8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13",
    ),
    "base_oracles": (
        f"{BASE}/post-state-capability-oracles.json",
        "911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021",
    ),
    "manifest": (
        f"{BASE}/post-state-manifest.json",
        "f0efb35c49b2f6b5e23692203aa0e5e6588046927f35ab2725250e27a0d1faad",
    ),
    "acceptance": (
        f"{BASE}/post-state-acceptance-inventory.json",
        "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    ),
    "oracle_schema": (
        f"{BASE}/post-state-capability-oracles.schema.json",
        "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    ),
    "official_schema": (
        "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    ),
}

# Filled only after deterministic outputs and atomic selector descriptors exist.
EXPECTED_OUTPUTS = {
    "ledger": "bb03840d8ec05339758a9788f406d78b5c412eb1d56cdc90028bea5ad887d6a2",
    "oracles": "355679322116451972cb2366a61bfba23a72762863796aea84c93a7bb412db14",
}
ATOMIC = {
    "selector": (
        "deploy/docker/thor-local/parity/metadata_sets/selector.json",
        "2f3b5415b7a0ba082406af0ecdfdd03a53b74a91ae39e55262577d1f19241ddb",
    ),
    "descriptor_289": (
        "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-289.json",
        "a566d9f1d710964519b02cc9bc42a0bc0614fa8a40a8ec564a54b3e1fa8f3405",
    ),
    "descriptor_500": (
        "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-current-cancellation-search-500.json",
        "6dbe22f169f01a0e9866b7f24d0a9a8612774ff2e78eb51cac411aa354653f46",
    ),
}
HISTORICAL_LINEAGE = {
    "mapping_v1": (
        "deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor/mapping.json",
        "dd5be5e9a73245c3599309497b8b3d9e68c750656984fb0f166423730956722a",
    ),
    "sparse4d_repair": (
        "deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair-rebase-successor/repair.json",
        "099b89d6e0b75b01e768b71ebaa6b0a719153185cf7aba5e6d0e5eb50e3247d7",
    ),
    "mapping_v2": (
        "deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor-v2/mapping.json",
        "cb9bea95b4cfeab7c44441854e331a7093667d6b379fe0555692e5105ce4507f",
    ),
    "admission": (
        "deploy/docker/thor-local/qualification/candidate-admission-receipts-rebase-successor/admission-index.json",
        "74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff",
    ),
    "authority": (
        "deploy/docker/thor-local/qualification/candidate-authority-registry-rebase-successor/authority-registry.json",
        "954aa42541f715bdbb25148a322e2e3b3380f27fc4f958e8ba0e7378945acdd4",
    ),
}


class SuccessorError(RuntimeError):
    """A source identity, derivation, or non-promotion invariant failed."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SuccessorError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise SuccessorError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise SuccessorError(f"repository input contains symlink: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise SuccessorError(f"repository input is not regular: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SuccessorError(f"repository input escapes root: {relative}") from exc
    return current


def _strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise SuccessorError(f"oversized JSON input: {label}")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise SuccessorError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                SuccessorError(f"non-finite JSON number in {label}: {value}")
            ),
        )
    except SuccessorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuccessorError(f"invalid JSON in {label}: {exc}") from exc


def _load_locked(entries: dict[str, tuple[str, str]]) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for name, (relative, expected) in entries.items():
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise SuccessorError(f"unfinalized source lock: {name}")
        payload = _repo_file(relative).read_bytes()
        if _sha(payload) != expected:
            raise SuccessorError(f"raw source digest drift: {relative}")
        loaded[name] = _strict_json(payload, relative)
    return loaded


def _refresh_claim_hashes(ledger: dict[str, Any]) -> None:
    capabilities = ledger["capabilities"]
    for source in ledger["sources"]:
        claims = []
        for capability in capabilities:
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
            raise SuccessorError(f"source has no claims: {source['id']}")
        canonical_claims = sorted(_canonical(claim).decode() for claim in claims)
        source["claim_set_sha256"] = _sha(_canonical(canonical_claims))


def derive() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source = _load_locked(SOURCES)
    current_ledger = source["current_ledger"]
    current_oracles = source["current_oracles"]
    ledger = copy.deepcopy(source["base_ledger"])
    oracles = copy.deepcopy(source["base_oracles"])
    if len(current_ledger["capabilities"]) != 289 or len(ledger["capabilities"]) != 500:
        raise SuccessorError("ledger denominator drift")
    if len(current_oracles["oracles"]) != 289 or len(oracles["oracles"]) != 500:
        raise SuccessorError("oracle denominator drift")
    candidate_capabilities = copy.deepcopy(ledger["capabilities"][289:])
    candidate_oracles = copy.deepcopy(oracles["oracles"][289:])
    ledger["capabilities"][:289] = copy.deepcopy(current_ledger["capabilities"])
    _refresh_claim_hashes(ledger)
    oracles["policy"] = copy.deepcopy(current_oracles["policy"])
    oracles["oracles"][:289] = copy.deepcopy(current_oracles["oracles"])
    if ledger["capabilities"][289:] != candidate_capabilities:
        raise SuccessorError("candidate capability suffix changed")
    if oracles["oracles"][289:] != candidate_oracles:
        raise SuccessorError("candidate oracle suffix changed")
    return ledger, oracles, source


def _validate_invariants(
    ledger: dict[str, Any], oracles: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    official_errors = sorted(
        Draft202012Validator(source["official_schema"]).iter_errors(ledger),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    oracle_errors = sorted(
        Draft202012Validator(source["oracle_schema"]).iter_errors(oracles),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if official_errors:
        raise SuccessorError(f"official schema failure: {official_errors[0].message}")
    if oracle_errors:
        raise SuccessorError(f"oracle schema failure: {oracle_errors[0].message}")
    ids = [row["id"] for row in ledger["capabilities"]]
    oracle_ids = [row["capability_id"] for row in oracles["oracles"]]
    if len(ids) != 500 or ids != oracle_ids or len(set(ids)) != 500:
        raise SuccessorError("ledger/oracle order or identity drift")
    for capability, oracle in zip(
        ledger["capabilities"], oracles["oracles"], strict=True
    ):
        expected_binding = {
            key: copy.deepcopy(capability[key])
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
        if oracle["ledger_binding"] != expected_binding:
            raise SuccessorError(f"oracle binding drift: {capability['id']}")
    states = Counter(row["current_state"] for row in oracles["oracles"])
    evidence = sum(len(row.get("evidence", [])) for row in oracles["oracles"])
    executors = sum(
        row.get("execution_bounds", {}).get("executor") is not None
        for row in oracles["oracles"]
    )
    collectors = sum(
        bool(row.get("execution_bounds", {}).get("collectors"))
        for row in oracles["oracles"]
    )
    promotable = sum(
        row.get("can_promote_runtime_state") is True for row in oracles["oracles"]
    )
    candidate_oracles = oracles["oracles"][289:]
    candidate_capabilities = ledger["capabilities"][289:]
    candidate_evidence = sum(len(row.get("evidence", [])) for row in candidate_oracles)
    candidate_executor_ready = sum(
        row.get("readiness", {}).get("executor_ready") is True
        for row in candidate_oracles
    )
    if states != {"open_unexecuted": 464, "external_boundary_unexecuted": 36}:
        raise SuccessorError(f"runtime-state denominator drift: {dict(states)}")
    if any((evidence, executors, collectors, promotable)):
        raise SuccessorError("successor invented evidence, execution, or promotion")
    if any(
        row.get("fixture", {}).get("warehouse_sample_bundle") is not False
        for row in oracles["oracles"][:289]
    ) or any(
        row.get("contract", {}).get("warehouse_sample_bundle") != "excluded"
        for row in candidate_capabilities
    ):
        raise SuccessorError("Warehouse sample exclusion drift")
    if (
        len(ledger["sources"]) != 126
        or len(ledger["source_discrepancies"]) != 47
        or len(candidate_capabilities) != 211
        or candidate_evidence != 0
        or candidate_executor_ready != 0
    ):
        raise SuccessorError("authoritative count denominator drift")
    return {
        "capabilities": len(ids),
        "oracles": len(oracle_ids),
        "sources": len(ledger["sources"]),
        "discrepancies": len(ledger["source_discrepancies"]),
        "candidates": len(candidate_capabilities),
        "candidate_evidence": candidate_evidence,
        "candidate_executor_ready": candidate_executor_ready,
        "open_unexecuted": states["open_unexecuted"],
        "external_boundary_unexecuted": states["external_boundary_unexecuted"],
        "runtime_evidence": evidence,
        "executors": executors,
        "collectors": collectors,
        "promotable": promotable,
    }


def _validate_checked_output(path: Path, expected: str, derived: bytes) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise SuccessorError(f"unfinalized output lock: {path.name}")
    payload = _repo_file(str(path.relative_to(REPO_ROOT))).read_bytes()
    if payload != derived or _sha(payload) != expected:
        raise SuccessorError(f"checked output differs: {path.name}")


def _validate_atomic_selection(ledger_sha: str, oracle_sha: str) -> dict[str, Any]:
    atomic = _load_locked(ATOMIC)
    selector = atomic["selector"]
    descriptor_289 = atomic["descriptor_289"]
    descriptor_500 = atomic["descriptor_500"]
    selected = selector["selected_set"]
    registry = {row["set_id"]: row for row in selector["available_sets"]}
    expected_ids = [
        "thor-vss-3.2.1-current-289",
        "thor-vss-3.2.1-current-cancellation-search-500",
    ]
    if list(registry) != expected_ids or selected != expected_ids[1]:
        raise SuccessorError("atomic selector identity/order drift")
    descriptors = {
        expected_ids[0]: descriptor_289,
        expected_ids[1]: descriptor_500,
    }
    for set_id, descriptor in descriptors.items():
        record = registry[set_id]
        if descriptor["set_id"] != set_id:
            raise SuccessorError(f"selector/descriptor id drift: {set_id}")
        if (
            record["descriptor_raw_sha256"]
            != ATOMIC[
                "descriptor_289" if set_id == expected_ids[0] else "descriptor_500"
            ][1]
        ):
            raise SuccessorError(f"selector descriptor digest drift: {set_id}")
    if descriptor_500["documents"]["official_capabilities"]["raw_sha256"] != ledger_sha:
        raise SuccessorError("selected ledger digest drift")
    if descriptor_500["documents"]["capability_oracles"]["raw_sha256"] != oracle_sha:
        raise SuccessorError("selected oracle digest drift")
    return {"selected_set": selected, "available_sets": len(registry)}


def _validate_historical_lineage(
    ledger: dict[str, Any], oracles: dict[str, Any]
) -> dict[str, int]:
    historical = _load_locked(HISTORICAL_LINEAGE)
    candidate_capabilities = ledger["capabilities"][289:]
    candidate_oracles = oracles["oracles"][289:]
    candidate_ids = [row["id"] for row in candidate_capabilities]
    oracle_ids = [row["oracle_id"] for row in candidate_oracles]
    if len(candidate_ids) != 211 or len(set(candidate_ids)) != 211:
        raise SuccessorError("current candidate suffix identity drift")

    mapping_v1 = historical["mapping_v1"]
    mapping_v2 = historical["mapping_v2"]
    admission = historical["admission"]
    repair = historical["sparse4d_repair"]
    authority = historical["authority"]
    for name, mapping in (("mapping v1", mapping_v1), ("mapping v2", mapping_v2)):
        rows = mapping.get("mappings", [])
        if (
            [row.get("capability_id") for row in rows] != candidate_ids
            or [row.get("oracle_id") for row in rows] != oracle_ids
            or mapping.get("summary", {}).get("candidate_count") != 211
            or mapping.get("summary", {}).get("admitted_candidates") != 0
            or mapping.get("summary", {}).get("executable_candidates") != 0
            or mapping.get("summary", {}).get("receipt_count") != 0
            or mapping.get("policy", {}).get("approvals_granted") != 0
            or mapping.get("policy", {}).get("receipts_present") != 0
            or mapping.get("policy", {}).get("admitted_candidates") != 0
            or mapping.get("policy", {}).get("executable_candidates") != 0
            or any(
                row.get("approval_state") != "no_receipt_not_admitted_not_executable"
                for row in rows
            )
        ):
            raise SuccessorError(f"{name} lineage or zero-state drift")

    repaired_id = repair.get("repair", {}).get("capability_id")
    repaired_oracle_id = repair.get("repair", {}).get("oracle_id")
    repair_policy = repair.get("policy", {})
    repair_preservation = repair.get("preservation", {})
    if (
        repaired_id not in candidate_ids
        or repaired_oracle_id != f"oracle.{repaired_id}"
        or repair_policy.get("approval_granted") is not False
        or repair_policy.get("executor_present") is not False
        or repair_policy.get("runtime_evidence_created") != 0
        or repair_policy.get("runtime_state_promotion") is not False
        or repair_preservation.get("runtime_receipts") != 0
        or repair_preservation.get("runtime_qualification_claims") != 0
    ):
        raise SuccessorError("Sparse4D historical repair lineage drift")

    admissions = admission.get("admissions", [])
    admission_summary = admission.get("summary", {})
    if (
        [row.get("candidate_id") for row in admissions] != candidate_ids
        or [row.get("oracle_id") for row in admissions] != oracle_ids
        or any(row.get("runtime_admitted") is not False for row in admissions)
        or any(row.get("runtime_executable") is not False for row in admissions)
        or any(row.get("receipt_ids") != [] for row in admissions)
        or admission_summary.get("candidate_count") != 211
        or admission_summary.get("admitted_candidates") != 0
        or admission_summary.get("executable_candidates") != 0
        or admission_summary.get("receipt_count") != 0
    ):
        raise SuccessorError("historical admission lineage or zero-state drift")

    empty_authority_fields = (
        "active_keys",
        "authorities",
        "max_ttl_policies",
        "not_required_edge_policies",
        "revocations",
        "revoked_keys",
        "role_policies",
        "scope_policies",
        "spent_receipt_ledger",
        "threshold_policies",
        "trusted_roots",
    )
    authority_summary = authority.get("summary", {})
    if (
        authority.get("source_identity", {}).get("admission_index_raw_sha256")
        != HISTORICAL_LINEAGE["admission"][1]
        or authority.get("source_identity", {}).get("candidate_count") != 211
        or any(authority.get(field) != [] for field in empty_authority_fields)
        or any(value != 0 for value in authority_summary.values())
        or authority.get("policy", {}).get("compiler_can_accept") is not False
        or authority.get("policy", {}).get("compiler_can_consume") is not False
        or authority.get("policy", {}).get("compiler_can_execute") is not False
    ):
        raise SuccessorError("historical authority lineage or empty-state drift")

    if (
        any(row.get("evidence") != [] for row in candidate_oracles)
        or any(
            row.get("readiness", {}).get("executor_ready") is not False
            for row in candidate_oracles
        )
        or any(
            row.get("can_promote_runtime_state") is not False
            for row in candidate_oracles
        )
    ):
        raise SuccessorError("current candidate evidence/execution/promotion drift")
    return {
        "historical_artifacts_locked": len(historical),
        "historical_candidate_ids_aligned": len(candidate_ids),
        "historical_admissions": 0,
        "historical_authorities": 0,
    }


def check() -> dict[str, Any]:
    ledger, oracles, source = derive()
    summary = _validate_invariants(ledger, oracles, source)
    ledger_bytes = _encoded(ledger)
    oracle_bytes = _encoded(oracles)
    _validate_checked_output(LEDGER_OUTPUT, EXPECTED_OUTPUTS["ledger"], ledger_bytes)
    _validate_checked_output(ORACLE_OUTPUT, EXPECTED_OUTPUTS["oracles"], oracle_bytes)
    summary.update(_validate_atomic_selection(_sha(ledger_bytes), _sha(oracle_bytes)))
    summary.update(_validate_historical_lineage(ledger, oracles))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args(argv)
    del args
    try:
        summary = check()
    except (KeyError, OSError, SuccessorError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
