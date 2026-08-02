#!/usr/bin/env python3
"""Compile the inert Search fixture-provisioning blocker/adapter contract.

This program reads source-locked repository files only.  It has no execution,
HTTP, Docker, credential, subprocess, or filesystem-write path.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
PLAN_SCHEMA_PATH = HERE / "plan.schema.json"
MAX_BYTES = 32 * 1024 * 1024


class ContractError(RuntimeError):
    """Stable, non-sensitive compiler failure."""

    CODES = {"configuration_error", "source_drift", "contract_mismatch"}

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _read(path: Path, maximum: int = MAX_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ContractError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ContractError("configuration_error")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in stable
        ):
            raise ContractError("configuration_error")
        return raw
    finally:
        os.close(descriptor)


def _decode(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ContractError("configuration_error")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ContractError("configuration_error")
            ),
        )
    except ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("configuration_error") from exc
    if not isinstance(value, dict):
        raise ContractError("configuration_error")
    return value


def _json(path: Path) -> dict[str, Any]:
    return _decode(_read(path))


def _validate(value: Any, schema_path: Path) -> None:
    try:
        schema = _json(schema_path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise ContractError("contract_mismatch")
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError("configuration_error") from exc


def _repo_path(relative: Any) -> Path:
    if not isinstance(relative, str):
        raise ContractError("configuration_error")
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise ContractError("configuration_error")
    current = ROOT
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ContractError("configuration_error")
        except OSError as exc:
            raise ContractError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise ContractError("configuration_error") from exc
    return current


def _locked_sources(contract: Mapping[str, Any]) -> dict[str, bytes]:
    sources: dict[str, bytes] = {}
    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != 18:
        raise ContractError("contract_mismatch")
    for lock in locks:
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in sources
        ):
            raise ContractError("contract_mismatch")
        raw = _read(_repo_path(lock["path"]))
        if hashlib.sha256(raw).hexdigest() != lock["sha256"]:
            raise ContractError("source_drift")
        sources[lock["path"]] = raw
    return sources


def _text(sources: Mapping[str, bytes], path: str) -> str:
    try:
        return sources[path].decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise ContractError("contract_mismatch") from exc


def _require_fragments(value: str, fragments: Sequence[str]) -> None:
    if any(fragment not in value for fragment in fragments):
        raise ContractError("contract_mismatch")


def _class_fields(source: str, class_name: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ContractError("contract_mismatch") from exc
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(matches) != 1:
        raise ContractError("contract_mismatch")
    return {
        node.target.id
        for node in matches[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _selected_oracle(sources: Mapping[str, bytes]) -> None:
    path = (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
        "post-state-capability-oracles.json"
    )
    selected = _decode(sources[path])
    rows = selected.get("oracles")
    if not isinstance(rows, list) or len(rows) != 500:
        raise ContractError("contract_mismatch")
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("oracle_id") == "oracle.runtime.agent.search-profile"
    ]
    if len(matches) != 1:
        raise ContractError("contract_mismatch")
    row = matches[0]
    bounds = row.get("execution_bounds", {})
    if (
        row.get("capability_id") != "runtime.agent.search-profile"
        or row.get("current_state") != "open_unexecuted"
        or row.get("evidence") != []
        or bounds.get("max_requests") != 14
        or bounds.get("max_actions") != 14
        or bounds.get("executor") is not None
        or bounds.get("collectors") != []
    ):
        raise ContractError("contract_mismatch")


def _production_semantics(sources: Mapping[str, bytes]) -> None:
    ingest = _text(sources, "services/agent/src/vss_agents/api/video_ingest.py")
    deprecated_ingest = _text(
        sources, "services/agent/src/vss_agents/api/video_search_ingest.py"
    )
    delete = _text(sources, "services/agent/src/vss_agents/api/video_delete.py")
    search = _text(sources, "services/agent/src/vss_agents/tools/search.py")
    attribute = _text(
        sources, "services/agent/src/vss_agents/tools/attribute_search.py"
    )
    embed = _text(sources, "services/agent/src/vss_agents/tools/embed_search.py")
    predecessor = _decode(
        sources[
            "deploy/docker/thor-local/qualification/"
            "search-semantic-runtime-evidence-successor/contract.json"
        ]
    )

    _require_fragments(
        ingest,
        [
            "VST returns",
            "``sensorId`` on the final-chunk response",
            "except httpx.ConnectError as exc:",
            "except httpx.TimeoutException as exc:",
            'result.get("usage", {}).get("total_chunks_processed", 0)',
            '"/api/v1/videos/{sensor_id}/complete"',
        ],
    )
    _require_fragments(
        deprecated_ingest,
        [
            "VST will return its own sensorId on success",
            'vst_sensor_id = vst_result.get("sensorId")',
        ],
    )
    _require_fragments(
        delete,
        [
            "Best-effort: continues even if individual steps fail",
            "delete_by_query(",
            'status = "partial"',
            'status = "failure"',
        ],
    )
    _require_fragments(
        attribute,
        [
            "stream_id = await get_stream_id(result.metadata.sensor_id",
            "# Skip result if VST conversion fails",
            "valid_results = attr_results",
        ],
    )
    _require_fragments(
        embed,
        [
            '"field": "llm.visionEmbeddings.vector"',
            "query_embedding = await _generate_query_embedding(query_input, embed_client)",
            "search_index: str | list[str] = config.es_index",
        ],
    )
    expected_search_fields = {
        "query",
        "source_type",
        "reference_object",
        "video_sources",
        "description",
        "timestamp_start",
        "timestamp_end",
        "top_k",
        "min_cosine_similarity",
        "agent_mode",
        "use_critic",
    }
    if _class_fields(search, "SearchInput") != expected_search_fields:
        raise ContractError("contract_mismatch")
    if _class_fields(search, "ReferenceObject") != {
        "object_id",
        "sensor_name",
        "sensor_id",
        "timestamp",
    }:
        raise ContractError("contract_mismatch")
    _require_fragments(search, ['model_config = ConfigDict(extra="forbid")'])

    auth = predecessor.get("authorization", {})
    evidence = predecessor.get("evidence", {})
    if (
        predecessor.get("package_id") != "search-semantic-runtime-evidence-successor"
        or predecessor.get("execution_bounds", {}).get("max_requests") != 14
        or predecessor.get("execution_bounds", {}).get("max_actions") != 14
        or auth.get("ownership_attestation")
        != "I_ATTEST_THIS_EXACT_RUN_NAMESPACE_IS_PREPROVISIONED_FOR_THIS_RUN_AND_MAY_BE_DELETED"
        or predecessor.get("workflow", [{}])[0].get("id") != "capture-pre-state"
        or evidence.get("promotion_eligible") is not False
        or evidence.get("canonical_state_advanced") is not False
    ):
        raise ContractError("contract_mismatch")

    for config_path in (
        "deploy/docker/developer-profiles/dev-profile-search/vss-agent/configs/config.yml",
        "deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml",
    ):
        _require_fragments(
            _text(sources, config_path),
            [
                "es_index: ${ELASTIC_SEARCH_INDEX}",
                "behavior_index: mdx-behavior-2025-01-01",
                "frames_index: mdx-raw-2025-01-01",
            ],
        )
    template = _text(
        sources,
        "deploy/docker/services/infra/elk/elasticsearch/init-scripts/"
        "elasticsearch-template-creation.sh",
    )
    _require_fragments(
        template,
        [
            '"index_patterns": ["mdx-behavior-*"]',
            '"index_patterns": ["mdx-raw-*"]',
            '"index_patterns": ["mdx-embed-filtered-*"]',
            '"type": "dense_vector"',
        ],
    )
    _require_fragments(
        _text(sources, "skills/vss-search-archive/SKILL.md"),
        [
            "For a source to be searchable it must be ingested **through the VSS agent backend**",
            "Delete through the agent backend, not bare VIOS",
        ],
    )


def compile_plan() -> dict[str, Any]:
    contract = _json(CONTRACT_PATH)
    _validate(contract, CONTRACT_SCHEMA_PATH)
    sources = _locked_sources(contract)
    _selected_oracle(sources)
    _production_semantics(sources)

    decision = contract["decision"]
    adapter = contract["maximal_public_api_adapter"]
    actions = adapter.get("actions")
    expected_ids = [
        "validate-local-media",
        "capture-vst-and-es-prestate",
        "request-upload-url",
        "upload-one-owned-file",
        "complete-search-ingest",
        "reconcile-runtime-identities",
        "run-search-semantic-candidate",
        "delete-owned-video",
        "verify-cross-system-postconditions",
    ]
    blocker_ids = [row.get("id") for row in contract["blocking_findings"]]
    expected_blockers = [
        "sensor-identity-not-requestable",
        "selected-object-identity-fixed",
        "rtvi-cv-registration-best-effort",
        "attribute-vst-enrichment-required",
        "model-vectors-not-in-search-input",
        "profile-index-binding-mismatch",
        "delete-is-best-effort",
        "fixed-envelope-has-no-setup",
    ]
    if (
        contract.get("default_execution_enabled") is not False
        or contract.get("runtime_transport_implemented") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or decision.get("safe_exact_full_fixture_creation_proven") is not False
        or decision.get("operator_preprovisioned_fixture_gap_closed") is not False
        or decision.get("predecessor_executor_binding_permitted") is not False
        or decision.get("promotion_eligible") is not False
        or decision.get("canonical_state_advanced") is not False
        or not isinstance(actions, list)
        or len(actions) != 9
        or adapter.get("planned_action_count") != 9
        or [row.get("order") for row in actions] != list(range(1, 10))
        or [row.get("id") for row in actions] != expected_ids
        or [row.get("status") for row in actions]
        != [
            "implementable",
            "implementable",
            "implementable",
            "partial",
            "partial",
            "partial",
            "blocked",
            "partial",
            "blocked",
        ]
        or blocker_ids != expected_blockers
        or contract.get("implementable_exact_subset", {}).get(
            "sufficient_for_full_search_fixture"
        )
        is not False
    ):
        raise ContractError("contract_mismatch")

    plan = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_source_locked_blocker_valid",
        "default_execution_enabled": False,
        "runtime_transport_implemented": False,
        "runtime_requests": 0,
        "runtime_actions": 0,
        "selected_metadata_rows": 500,
        "selected_search_state": "open_unexecuted_null_bound",
        "predecessor_preserved": True,
        "safe_exact_full_fixture_creation_proven": False,
        "operator_preprovisioned_fixture_gap_closed": False,
        "predecessor_executor_binding_permitted": False,
        "maximal_adapter_planned_action_count": 9,
        "implementable_exact_subset": (
            "elasticsearch_document_lifecycle_only_not_a_functional_search_fixture"
        ),
        "blocking_finding_ids": blocker_ids,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }
    _validate(plan, PLAN_SCHEMA_PATH)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments not in ([], ["plan"]):
        print(
            json.dumps({"status": "error", "code": "configuration_error"}),
            file=sys.stderr,
        )
        return 2
    try:
        print(json.dumps(compile_plan(), indent=2, sort_keys=True))
        return 0
    except ContractError as exc:
        print(
            json.dumps({"status": "error", "code": exc.code}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
