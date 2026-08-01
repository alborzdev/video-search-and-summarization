#!/usr/bin/env python3
"""Inert audio-entry plan and read-only future evidence validator."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
EVIDENCE_SCHEMA_PATH = HERE / "evidence.schema.json"
PLAN_SCHEMA_PATH = HERE / "plan.schema.json"
VALIDATION_RESULT_SCHEMA_PATH = HERE / "validation-result.schema.json"
EXPECTED_PACKAGE_HASHES = {
    "contract.json": "d181a2f7e2029b6902f41605730642c95d477e87ae3514fefb73ed89359cb493",
    "contract.schema.json": "e690285d507f0b35537970cb06281d4cbb4c1e03b7c5fcff15a9c844f93119ee",
    "evidence.schema.json": "b555b626e0865cc68508126194712d0e2822fd8b1af4b4dc7b026749706a2ac2",
    "plan.schema.json": "1605d3b3c6f48279ecceaaa401b727798692017bab464ceaab6c782917b3f112",
    "validation-result.schema.json": "44b7878ea00935ded1699a3d139dece56a9f8d69426093526bdfe39bc4c079f1",
}
MAX_JSON_BYTES = 5_000_000
MAX_ARTIFACT_BYTES = 2_000_000
GIB = 1024**3
PHRASE = "Attention operator. The blue crate is ready."
PHRASE_TOKENS = ("attention", "operator", "the", "blue", "crate", "is", "ready")
CORE_TOKENS = ("blue", "crate", "is", "ready")
EXPECTED_ORACLES = {
    "manifest-gap.audio-understanding.00-audio-aware-base-workflow": (
        "audio-aware Base workflow",
        "oracle.manifest-entry.audio-understanding.00",
        "9fc78ad68e479a3aaa9eddcb4f2e1c8481205b1e630c86d30314749af1fabc6c",
    ),
    "manifest-gap.audio-understanding.01-audio-transcript-per-rt-vlm-chunk": (
        "audio transcript per RT-VLM chunk",
        "oracle.manifest-entry.audio-understanding.01",
        "4e54f3a8bf32fbc34c572f72a012ded20b3a0b88e7e6c9b9b5748edede31ddfa",
    ),
    "manifest-gap.audio-understanding.02-audio-aware-summarization-and-alerts": (
        "audio-aware summarization and alerts",
        "oracle.manifest-entry.audio-understanding.02",
        "b9df559c2c45ce08133185aa1757ac1805562051cf8d1d544ff538b2a65171e2",
    ),
}
EXPECTED_SOURCE_PATHS = {
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/inventory.json",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/inventory.schema.json",
    "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "deploy/docker/thor-local/parity/manifest.json",
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "deploy/docker/thor-local/parity/capability-oracles.json",
    "deploy/docker/thor-local/qualification/tiny-audio-fixture/fixture.py",
    "deploy/docker/thor-local/qualification/tiny-audio-fixture/receipt.schema.json",
    "deploy/docker/thor-local/qualification/tiny-audio-fixture/README.md",
    "deploy/docker/thor-local/qualification/tiny-audio-fixture/EVIDENCE.md",
    "services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py",
    "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py",
    "services/agent/src/vss_agents/tools/video_report_gen.py",
    "services/agent/src/vss_agents/tools/video_understanding.py",
    "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml",
    "deploy/docker/developer-profiles/dev-profile-thor-full/.env",
    "deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml",
    "deploy/docker/thor-local/audio/README.md",
    "deploy/docker/thor-local/audio/omni.compose.yml",
    "deploy/docker/thor-local/audio/thor-omni-audio.sh",
    "deploy/docker/thor-local/audio/omni_snapshot.py",
    "deploy/docker/thor-local/rt-vlm/memory_budget.py",
}


class QualificationError(RuntimeError):
    """A static lock, schema, provenance, or semantic evidence check failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    )


def _strict_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise QualificationError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {label}")
    return value


def _validate(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), str(schema_path))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            instance
        ),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(part) for part in first.absolute_path)
        raise QualificationError(
            f"{label} schema violation at {location}: {first.message}"
        )


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise QualificationError(f"symlinked repository path: {relative}")
    try:
        resolved = (REPO_ROOT / path).resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise QualificationError(f"repository source is absent: {relative}") from exc
    if not resolved.is_file():
        raise QualificationError(f"repository source is not a file: {relative}")
    return resolved


def _external_file(raw: str, label: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise QualificationError(f"{label} path must be absolute")
    try:
        mode = path.lstat().st_mode
        resolved = path.resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        pass
    except OSError as exc:
        raise QualificationError(f"cannot resolve {label}: {path}") from exc
    else:
        raise QualificationError(f"{label} must remain outside repository")
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise QualificationError(f"{label} must be a regular non-symlink file")
    size = path.stat().st_size
    if size < 1 or size > MAX_ARTIFACT_BYTES:
        raise QualificationError(f"{label} size is outside the bounded range")
    return path


def _external_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    checked = _external_file(str(path), label)
    raw = checked.read_bytes()
    return _strict_json_bytes(raw, label), raw


def _load_contract() -> dict[str, Any]:
    for name, expected in EXPECTED_PACKAGE_HASHES.items():
        if _sha256((HERE / name).read_bytes()) != expected:
            raise QualificationError(f"package identity drift: {name}")
    contract = _strict_json_bytes(CONTRACT_PATH.read_bytes(), str(CONTRACT_PATH))
    _validate(contract, CONTRACT_SCHEMA_PATH, "contract")
    locks = contract["source_locks"]
    if len({item["path"] for item in locks}) != len(locks):
        raise QualificationError("duplicate source lock path")
    if {item["path"] for item in locks} != EXPECTED_SOURCE_PATHS:
        raise QualificationError("exact 23-file source lock set drifted")
    assertions = contract["source_assertions"]
    if len({item["path"] for item in assertions}) != len(assertions):
        raise QualificationError("duplicate source assertion path")
    if not {item["path"] for item in assertions} <= EXPECTED_SOURCE_PATHS:
        raise QualificationError("source assertion is not raw-locked")
    observed = {
        item["entry_id"]: (
            item["advertised"],
            item["oracle_id"],
            item["required_oracle_canonical_sha256"],
        )
        for item in contract["advertised_oracles"]
    }
    if observed != EXPECTED_ORACLES:
        raise QualificationError("exact three audio oracle bindings drifted")
    return contract


def _check_sources(contract: dict[str, Any]) -> list[dict[str, Any]]:
    assertions = {
        item["path"]: item["fragments"] for item in contract["source_assertions"]
    }
    checks = []
    for lock in contract["source_locks"]:
        raw = _repo_file(lock["path"]).read_bytes()
        digest_match = _sha256(raw) == lock["sha256"]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        fragments_match = all(
            fragment in text for fragment in assertions.get(lock["path"], [])
        )
        checks.append(
            {
                "path": lock["path"],
                "sha256_match": digest_match,
                "assertions_match": fragments_match,
            }
        )
    failed = [
        item["path"]
        for item in checks
        if not item["sha256_match"] or not item["assertions_match"]
    ]
    if failed:
        raise QualificationError(f"source lock or assertion mismatch: {failed}")
    return checks


def _verify_live_bindings() -> None:
    plan = _strict_json_bytes(
        _repo_file(
            "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json"
        ).read_bytes(),
        "advertised-entry plan",
    )
    entries = {item["entry_id"]: item for item in plan["entries"]}
    for entry_id, (advertised, oracle_id, digest) in EXPECTED_ORACLES.items():
        entry = entries.get(entry_id)
        if entry is None or entry["advertised"] != advertised:
            raise QualificationError(f"live advertised entry drift: {entry_id}")
        oracle = entry["required_oracle"]
        if oracle["id"] != oracle_id or _canonical_sha256(oracle) != digest:
            raise QualificationError(f"live required oracle drift: {entry_id}")
        if (
            entry["coverage_state"] != "open_missing_entry_capability_and_oracle"
            or entry["runtime_evidence"] != []
            or oracle["status"] != "open_unexecuted"
            or oracle["runtime_evidence"] != []
            or entry["warehouse_scope"]["sample_bundle_required"] is not False
        ):
            raise QualificationError(f"live audio oracle is no longer open: {entry_id}")

    wave7 = _strict_json_bytes(
        _repo_file(
            "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/inventory.json"
        ).read_bytes(),
        "Wave 7 advertised-entry inventory",
    )
    rows = {item["entry_id"]: item for item in wave7["cases"]}
    if not set(EXPECTED_ORACLES) <= set(rows):
        raise QualificationError("Wave 7 audio candidates are incomplete")
    for entry_id, (advertised, _, digest) in EXPECTED_ORACLES.items():
        row = rows[entry_id]
        if (
            row["advertised"] != advertised
            or row["required_oracle_canonical_sha256"] != digest
            or "no " not in row["evidence_scope"].lower()
        ):
            raise QualificationError(f"Wave 7 audio candidate drift: {entry_id}")

    capability_ids = {
        item["id"]
        for item in _strict_json_bytes(
            _repo_file(
                "deploy/docker/thor-local/parity/official-capabilities.json"
            ).read_bytes(),
            "official capabilities",
        )["capabilities"]
    }
    oracle_ids = {
        item["capability_id"]
        for item in _strict_json_bytes(
            _repo_file(
                "deploy/docker/thor-local/parity/capability-oracles.json"
            ).read_bytes(),
            "capability oracles",
        )["oracles"]
    }
    proposed = {
        f"manifest-entry.audio-understanding.0{index}-{suffix}"
        for index, suffix in (
            (0, "audio-aware-base-workflow"),
            (1, "audio-transcript-per-rt-vlm-chunk"),
            (2, "audio-aware-summarization-and-alerts"),
        )
    }
    if proposed & capability_ids or proposed & oracle_ids:
        raise QualificationError(
            "audio advertised entry was unexpectedly promoted live"
        )


def build_plan() -> dict[str, Any]:
    contract = _load_contract()
    source_checks = _check_sources(contract)
    _verify_live_bindings()
    result = {
        "schema_version": 1,
        "mode": "inert_read_only_audio_admission_plan",
        "writes": False,
        "subprocesses": False,
        "docker": False,
        "network": False,
        "lifecycle": False,
        "model_load": False,
        "downloads": False,
        "credentials": False,
        "warehouse_sample_bundle": "excluded",
        "contract_sha256": _sha256(CONTRACT_PATH.read_bytes()),
        "source_checks": source_checks,
        "oracle_count": 3,
        "runtime_evidence": [],
        "lanes": {
            "native_audio": (
                "semantic Base/LVS/alert proof only; ASR transcript claim forbidden"
            ),
            "separate_asr": (
                "timed nonempty audio_transcript proof only; "
                "VLM_MODEL_SUPPORTS_AUDIO must be false"
            ),
        },
        "next_action": "operator_review_then_separate_explicit_runtime_execution",
    }
    _validate(result, PLAN_SCHEMA_PATH, "plan result")
    return result


def _timestamp(raw: str, label: str) -> datetime:
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        value = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise QualificationError(f"invalid timestamp: {label}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise QualificationError(f"timestamp lacks timezone: {label}")
    return value


def _contains_sequence(text: str, sequence: tuple[str, ...]) -> bool:
    tokens = tuple(re.findall(r"[a-z0-9]+", text.casefold()))
    width = len(sequence)
    return any(
        tokens[index : index + width] == sequence for index in range(len(tokens))
    )


def _walk_artifacts(value: Any) -> list[dict[str, Any]]:
    artifacts = []
    if isinstance(value, dict):
        if "artifact_id" in value:
            artifacts.append(value)
        else:
            for item in value.values():
                artifacts.extend(_walk_artifacts(item))
    elif isinstance(value, list):
        for item in value:
            artifacts.extend(_walk_artifacts(item))
    return artifacts


def _check_artifacts(
    evidence: dict[str, Any],
) -> tuple[dict[str, bytes], dict[str, str]]:
    artifacts = _walk_artifacts(evidence)
    ids = [item["artifact_id"] for item in artifacts]
    paths = [item["path"] for item in artifacts]
    if len(ids) != len(set(ids)):
        raise QualificationError("duplicate artifact_id")
    if len(paths) != len(set(paths)):
        raise QualificationError("artifact path reused across evidence roles")
    raw_by_id: dict[str, bytes] = {}
    text_by_id: dict[str, str] = {}
    for item in artifacts:
        path = _external_file(item["path"], f"artifact {item['artifact_id']}")
        raw = path.read_bytes()
        if len(raw) != item["size_bytes"] or _sha256(raw) != item["sha256"]:
            raise QualificationError(
                f"artifact size or digest mismatch: {item['artifact_id']}"
            )
        raw_by_id[item["artifact_id"]] = raw
        try:
            text_by_id[item["artifact_id"]] = raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return raw_by_id, text_by_id


def _require_artifact_text(
    artifact: dict[str, Any],
    text_by_id: dict[str, str],
    tokens: list[str],
    label: str,
) -> None:
    text = text_by_id.get(artifact["artifact_id"])
    if text is None or any(token not in text for token in tokens):
        raise QualificationError(f"{label} artifact is not correlated to its claim")


def _validate_models_response(
    artifact: dict[str, Any],
    raw_by_id: dict[str, bytes],
    observed_model_id: str,
    expected_audio_support: bool,
    label: str,
) -> None:
    document = _strict_json_bytes(raw_by_id[artifact["artifact_id"]], label)
    if set(document) != {"id", "audio_support"}:
        raise QualificationError(f"{label} must contain exact id/audio_support fields")
    if (
        document["id"] != observed_model_id
        or document["audio_support"] is not expected_audio_support
    ):
        raise QualificationError(f"{label} identity or audio_support differs")


def _validate_snapshot_files(manifest: dict[str, Any]) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise QualificationError("native model snapshot provenance is incomplete")
    paths: list[str] = []
    total = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise QualificationError("native snapshot file entry is invalid")
        path = item["path"]
        digest = item["sha256"]
        size = item["size"]
        path_value = Path(path) if isinstance(path, str) else Path("/")
        if (
            not isinstance(path, str)
            or not path
            or path_value.is_absolute()
            or ".." in path_value.parts
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in path
            )
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise QualificationError("native snapshot file entry is invalid")
        paths.append(path)
        total += size
    if len(paths) != len(set(paths)):
        raise QualificationError("native snapshot file paths are not unique")
    if manifest.get("file_count") != len(files) or manifest.get("total_bytes") != total:
        raise QualificationError("native snapshot file count or size sum differs")


def _validate_fixture(
    evidence: dict[str, Any], raw_by_id: dict[str, bytes]
) -> dict[str, Any]:
    fixture = evidence["fixture"]
    receipt_artifact = fixture["receipt"]
    media_artifact = fixture["media"]
    receipt = _strict_json_bytes(
        raw_by_id[receipt_artifact["artifact_id"]], "fixture receipt"
    )
    _validate(
        receipt,
        _repo_file(
            "deploy/docker/thor-local/qualification/tiny-audio-fixture/receipt.schema.json"
        ),
        "tiny audio fixture receipt",
    )
    if (
        receipt["fixture_id"] != fixture["fixture_id"]
        or receipt["phrase"]["text"] != fixture["phrase"]
        or receipt["phrase"]["utf8_sha256"] != fixture["phrase_utf8_sha256"]
    ):
        raise QualificationError("fixture identity or known phrase drifted")
    media_path = Path(media_artifact["path"])
    if (
        receipt["media"]["filename"] != media_path.name
        or receipt["media"]["sha256"] != media_artifact["sha256"]
        or receipt["media"]["size_bytes"] != media_artifact["size_bytes"]
    ):
        raise QualificationError("fixture media does not match its locked receipt")
    if receipt["safety"]["warehouse_data_used"] is not False:
        raise QualificationError("Warehouse fixture evidence is forbidden")
    return receipt


def _validate_endpoints(evidence: dict[str, Any]) -> None:
    for label in ("native_audio_run", "transcript_run"):
        endpoint = evidence[label]["endpoint"]
        if endpoint["models_url"] != endpoint["base_url"] + "/v1/models":
            raise QualificationError(f"{label} models endpoint is not locally bound")
        if int(endpoint["base_url"].rsplit(":", 1)[1]) > 65535:
            raise QualificationError(f"{label} loopback port is invalid")
    if int(evidence["transcript_run"]["asr"]["endpoint"].rsplit(":", 1)[1]) > 65535:
        raise QualificationError("ASR loopback port is invalid")


def _validate_models_and_resources(
    evidence: dict[str, Any],
    raw_by_id: dict[str, bytes],
    text_by_id: dict[str, str],
) -> None:
    native = evidence["native_audio_run"]
    model = native["model"]
    if model["configured_model_id"] != model["observed_model_id"]:
        raise QualificationError(
            "native configured and observed model identities differ"
        )
    _validate_models_response(
        model["models_response"],
        raw_by_id,
        model["observed_model_id"],
        True,
        "native /v1/models",
    )
    _require_artifact_text(
        model["launch_capture"],
        text_by_id,
        [
            model["configured_model_id"],
            "VLM_MODEL_SUPPORTS_AUDIO=true",
            "ENABLE_AUDIO=true",
            "127.0.0.1",
            "snapshot-verified=true",
            model["repository"],
            model["revision"],
        ],
        "native launch",
    )
    manifest = _strict_json_bytes(
        raw_by_id[model["snapshot_manifest"]["artifact_id"]],
        "native model snapshot manifest",
    )
    if (
        manifest.get("repository") != model["repository"]
        or manifest.get("revision") != model["revision"]
    ):
        raise QualificationError("native model snapshot provenance is incomplete")
    _validate_snapshot_files(manifest)

    memory = native["memory"]
    required = max(
        80 * GIB,
        (memory["total_bytes"] * 65 + 99) // 100,
    )
    reserve = (memory["total_bytes"] * 20 + 99) // 100
    if (
        memory["available_before_bytes"] < required
        or memory["available_before_bytes"] > memory["total_bytes"]
        or memory["available_during_bytes"] > memory["total_bytes"]
        or memory["available_after_bytes"] > memory["total_bytes"]
        or memory["available_during_bytes"] < reserve
        or memory["available_after_bytes"] < reserve
        or memory["available_after_bytes"] < memory["available_during_bytes"]
    ):
        raise QualificationError("native Omni memory gate or recovery check failed")
    _require_artifact_text(
        memory["capture"],
        text_by_id,
        [
            f"total_bytes={memory['total_bytes']}",
            f"available_before_bytes={memory['available_before_bytes']}",
            f"available_during_bytes={memory['available_during_bytes']}",
            f"available_after_bytes={memory['available_after_bytes']}",
            "gate_passed=true",
            "oom_events=0",
        ],
        "native memory",
    )

    transcript = evidence["transcript_run"]
    transcript_model = transcript["model"]
    if transcript_model["configured_model_id"] != transcript_model["observed_model_id"]:
        raise QualificationError(
            "transcript configured and observed model identities differ"
        )
    _validate_models_response(
        transcript_model["models_response"],
        raw_by_id,
        transcript_model["observed_model_id"],
        False,
        "transcript /v1/models",
    )
    asr = transcript["asr"]
    if asr["creation_capture"]["source_service"] != "rtvi-vlm":
        raise QualificationError("ASR creation capture must originate from RT-VLM")
    _require_artifact_text(
        asr["creation_capture"],
        text_by_id,
        [
            "Creating ASR process for audio transcription",
            "VLM_MODEL_SUPPORTS_AUDIO=false",
            asr["model_id"],
        ],
        "ASR creation",
    )
    creation_text = text_by_id[asr["creation_capture"]["artifact_id"]]
    if "Skipping ASR process" in creation_text:
        raise QualificationError(
            "native Omni ASR-skip evidence cannot prove audio_transcript"
        )
    resources = transcript["resources"]
    if (
        resources["peak_memory_bytes"] > resources["memory_limit_bytes"]
        or resources["peak_cpu_cores"] > resources["cpu_limit_cores"]
    ):
        raise QualificationError(
            "transcript lane exceeded its declared resource budget"
        )
    _require_artifact_text(
        resources["capture"],
        text_by_id,
        [
            f"memory_limit_bytes={resources['memory_limit_bytes']}",
            f"peak_memory_bytes={resources['peak_memory_bytes']}",
            f"cpu_limit_cores={resources['cpu_limit_cores']}",
            f"peak_cpu_cores={resources['peak_cpu_cores']}",
            "within_declared_budget=true",
            "oom_events=0",
        ],
        "transcript resources",
    )


def _validate_times(evidence: dict[str, Any]) -> None:
    native = evidence["native_audio_run"]
    transcript = evidence["transcript_run"]
    native_start = _timestamp(native["started_at"], "native run start")
    native_end = _timestamp(native["ended_at"], "native run end")
    transcript_start = _timestamp(transcript["started_at"], "transcript run start")
    transcript_end = _timestamp(transcript["ended_at"], "transcript run end")
    if native_start >= native_end:
        raise QualificationError("native run timestamps are not increasing")
    if transcript_start >= transcript_end:
        raise QualificationError("transcript run timestamps are not increasing")
    if (
        native["run_id"] == transcript["run_id"]
        or native["authorization_id"] == transcript["authorization_id"]
        or native_end > transcript_start
    ):
        raise QualificationError("native-audio and separate-ASR runs must be distinct")
    completed = _timestamp(evidence["cleanup"]["completed_at"], "cleanup completion")
    if completed < max(native_end, transcript_end):
        raise QualificationError("cleanup completed before a runtime lane ended")

    base, transcript_oracle, summary = evidence["oracle_evidence"]
    native_artifacts = [
        native["model"]["models_response"],
        native["model"]["launch_capture"],
        native["memory"]["capture"],
        base["response_capture"],
        base["control_capture"],
        summary["summary_capture"],
        summary["summary_control_capture"],
        summary["alert_capture"],
        summary["alert_control_capture"],
    ]
    transcript_artifacts = [
        transcript["model"]["models_response"],
        transcript["asr"]["creation_capture"],
        transcript["resources"]["capture"],
        *(chunk["response_capture"] for chunk in transcript_oracle["chunks"]),
    ]
    for artifact in native_artifacts:
        captured = _timestamp(artifact["captured_at"], artifact["artifact_id"])
        if not native_start <= captured <= native_end:
            raise QualificationError("native artifact timestamp is outside its run")
    for artifact in transcript_artifacts:
        captured = _timestamp(artifact["captured_at"], artifact["artifact_id"])
        if not transcript_start <= captured <= transcript_end:
            raise QualificationError("transcript artifact timestamp is outside its run")
    cleanup_capture = _timestamp(
        evidence["cleanup"]["capture"]["captured_at"], "cleanup capture"
    )
    if not max(native_end, transcript_end) <= cleanup_capture <= completed:
        raise QualificationError("cleanup capture timestamp is outside cleanup")


def _validate_oracles(
    evidence: dict[str, Any],
    receipt: dict[str, Any],
    text_by_id: dict[str, str],
) -> None:
    base, transcript, summary_alert = evidence["oracle_evidence"]
    native_run_id = evidence["native_audio_run"]["run_id"]
    transcript_run_id = evidence["transcript_run"]["run_id"]
    cleanup_id = evidence["cleanup"]["cleanup_evidence_id"]
    if (
        base["run_id"] != native_run_id
        or summary_alert["run_id"] != native_run_id
        or transcript["run_id"] != transcript_run_id
        or any(
            item["cleanup_evidence_id"] != cleanup_id
            for item in (base, transcript, summary_alert)
        )
    ):
        raise QualificationError("oracle evidence is bound to the wrong run or cleanup")

    for text, label in (
        (base["response_text"], "Base response"),
        (summary_alert["summary_text"], "LVS summary"),
        (summary_alert["alert_text"], "alert"),
    ):
        if not _contains_sequence(text, PHRASE_TOKENS):
            raise QualificationError(f"{label} lacks full known-phrase correlation")
    for text, label in (
        (base["audio_disabled_control_text"], "Base control"),
        (summary_alert["summary_audio_disabled_control_text"], "summary control"),
        (summary_alert["alert_audio_disabled_control_text"], "alert control"),
    ):
        if _contains_sequence(text, PHRASE_TOKENS) or _contains_sequence(
            text, CORE_TOKENS
        ):
            raise QualificationError(f"{label} leaks audio-only phrase semantics")

    bindings = (
        (base["response_capture"], base["response_text"], "Base response"),
        (base["control_capture"], base["audio_disabled_control_text"], "Base control"),
        (
            summary_alert["summary_capture"],
            summary_alert["summary_text"],
            "LVS summary",
        ),
        (
            summary_alert["summary_control_capture"],
            summary_alert["summary_audio_disabled_control_text"],
            "summary control",
        ),
        (summary_alert["alert_capture"], summary_alert["alert_text"], "alert"),
        (
            summary_alert["alert_control_capture"],
            summary_alert["alert_audio_disabled_control_text"],
            "alert control",
        ),
    )
    for artifact, text, label in bindings:
        _require_artifact_text(artifact, text_by_id, [text], label)
    if (
        base["response_capture"]["source_service"] != "vss-agent"
        or summary_alert["summary_capture"]["source_service"] != "lvs-server"
        or summary_alert["alert_capture"]["source_service"] != "alert-bridge"
    ):
        raise QualificationError("semantic output came from the wrong workflow service")

    chunks = transcript["chunks"]
    duration = receipt["probe"]["duration_ms"]
    phrase_chunks = 0
    prior_end = 0
    for expected_index, chunk in enumerate(chunks):
        if chunk["chunk_index"] != expected_index:
            raise QualificationError("chunk indices are not exact and ordered")
        if chunk["start_ms"] < prior_end or chunk["start_ms"] - prior_end > 100:
            raise QualificationError("chunk media timing has an overlap or large gap")
        if (
            chunk["end_ms"] <= chunk["start_ms"]
            or chunk["end_ms"] > duration
            or chunk["asr_ended_ms"] <= chunk["asr_started_ms"]
            or chunk["asr_started_ms"] < chunk["start_ms"]
            or chunk["asr_ended_ms"] > chunk["end_ms"]
        ):
            raise QualificationError("chunk or ASR timing is invalid")
        if chunk["response_capture"]["source_service"] != "rtvi-vlm":
            raise QualificationError("chunk transcript was not captured from RT-VLM")
        _require_artifact_text(
            chunk["response_capture"],
            text_by_id,
            ["audio_transcript", chunk["audio_transcript"]],
            f"chunk {expected_index}",
        )
        phrase_chunks += _contains_sequence(chunk["audio_transcript"], PHRASE_TOKENS)
        prior_end = chunk["end_ms"]
    if chunks[0]["start_ms"] != 0 or abs(prior_end - duration) > 100:
        raise QualificationError("chunk timing does not span the locked fixture")
    if phrase_chunks != 1:
        raise QualificationError(
            "exactly one timed chunk must contain the full known phrase"
        )


def _validate_cleanup(evidence: dict[str, Any], text_by_id: dict[str, str]) -> None:
    cleanup = evidence["cleanup"]
    if set(cleanup["created_resource_ids"]) != set(cleanup["removed_resource_ids"]):
        raise QualificationError(
            "cleanup did not remove exactly executor-owned resources"
        )
    if any(
        not item.startswith(cleanup["ownership_prefix"])
        for item in cleanup["created_resource_ids"]
    ):
        raise QualificationError(
            "cleanup ownership prefix does not cover every resource"
        )
    for run_id in (
        evidence["native_audio_run"]["run_id"],
        evidence["transcript_run"]["run_id"],
    ):
        if not any(run_id in item for item in cleanup["created_resource_ids"]):
            raise QualificationError("cleanup resources are not bound to both run ids")
    _require_artifact_text(
        cleanup["capture"],
        text_by_id,
        [*cleanup["removed_resource_ids"], "cleanup-complete"],
        "cleanup",
    )


def validate_evidence(path: Path) -> dict[str, Any]:
    contract = _load_contract()
    _check_sources(contract)
    _verify_live_bindings()
    evidence, evidence_raw = _external_json(path, "candidate evidence receipt")
    _validate(evidence, EVIDENCE_SCHEMA_PATH, "candidate evidence")
    raw_by_id, text_by_id = _check_artifacts(evidence)
    receipt = _validate_fixture(evidence, raw_by_id)
    _validate_endpoints(evidence)
    _validate_models_and_resources(evidence, raw_by_id, text_by_id)
    _validate_times(evidence)
    _validate_oracles(evidence, receipt, text_by_id)
    _validate_cleanup(evidence, text_by_id)
    result = {
        "schema_version": 1,
        "mode": "read_only_future_evidence_validation",
        "evidence_sha256": _sha256(evidence_raw),
        "candidate_status": "validated_for_review_not_admitted",
        "can_mark_passed_current": False,
        "live_ledger_mutation": False,
        "warehouse_sample_bundle": "excluded",
        "checks": {
            "fixture_receipt_and_media": True,
            "native_audio_semantics": True,
            "separate_asr_transcript": True,
            "chunk_timing": True,
            "model_identity_and_provenance": True,
            "loopback_endpoints": True,
            "memory_and_resources": True,
            "cleanup": True,
        },
        "oracle_observations": [
            {
                "entry_id": "manifest-gap.audio-understanding.00-audio-aware-base-workflow",
                "observation": "candidate_semantics_matched_not_admitted",
                "lane": "native_audio",
            },
            {
                "entry_id": "manifest-gap.audio-understanding.01-audio-transcript-per-rt-vlm-chunk",
                "observation": "candidate_transcript_matched_not_admitted",
                "lane": "separate_asr",
            },
            {
                "entry_id": "manifest-gap.audio-understanding.02-audio-aware-summarization-and-alerts",
                "observation": "candidate_semantics_matched_not_admitted",
                "lane": "native_audio",
            },
        ],
        "runtime_evidence_admitted": [],
        "limitations": [
            (
                "validator authenticates bounded receipt structure, raw artifacts, "
                "and cross-correlations but does not execute or independently observe "
                "the runtime"
            ),
            (
                "candidate evidence still requires human review and explicit "
                "live-ledger integration"
            ),
            (
                "native Omni audio semantics do not prove a nonempty "
                "audio_transcript because RT-VLM skips the ASR process for "
                "native-audio models"
            ),
        ],
    }
    _validate(result, VALIDATION_RESULT_SCHEMA_PATH, "validation result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate-evidence",
        type=Path,
        help="absolute external candidate receipt; validation is read-only",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            validate_evidence(args.validate_evidence)
            if args.validate_evidence is not None
            else build_plan()
        )
    except QualificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            result,
            sort_keys=args.json,
            separators=(",", ":") if args.json else None,
            indent=None if args.json else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
