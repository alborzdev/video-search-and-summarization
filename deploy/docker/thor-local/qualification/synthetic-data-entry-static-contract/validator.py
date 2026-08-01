#!/usr/bin/env python3
"""Fail-closed, read-only validator for synthetic-data entry wiring."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
DEFAULT_CONTRACT = HERE / "contract.json"
CONTRACT_SCHEMA = HERE / "contract.schema.json"
MANIFEST_PATH = "deploy/docker/thor-local/parity/manifest.json"
CAPABILITIES_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLES_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
MAX_JSON_BYTES = 16 * 1024 * 1024
EXPECTED_CONTRACT_SHA256 = (
    "42eeddab5b20bdc5cd215f7ffd44f33df1f2c2cd738e22ff3bae4fad6731c14f"
)

EXPECTED_ENTRIES = [
    (
        "semantic label helpers",
        "manifest-gap.synthetic-data-tools.00-semantic-label-helpers",
        "manifest-entry.synthetic-data-tools.00-semantic-label-helpers",
        "oracle.manifest-entry.synthetic-data-tools.00-semantic-label-helpers",
        3,
    ),
    (
        "dataset checks",
        "manifest-gap.synthetic-data-tools.01-dataset-checks",
        "manifest-entry.synthetic-data-tools.01-dataset-checks",
        "oracle.manifest-entry.synthetic-data-tools.01-dataset-checks",
        10,
    ),
    (
        "RGB/depth/video conversion",
        "manifest-gap.synthetic-data-tools.02-rgb-depth-video-conversion",
        "manifest-entry.synthetic-data-tools.02-rgb-depth-video-conversion",
        "oracle.manifest-entry.synthetic-data-tools.02-rgb-depth-video-conversion",
        3,
    ),
    (
        "ground-truth conversion",
        "manifest-gap.synthetic-data-tools.03-ground-truth-conversion",
        "manifest-entry.synthetic-data-tools.03-ground-truth-conversion",
        "oracle.manifest-entry.synthetic-data-tools.03-ground-truth-conversion",
        2,
    ),
]
EXPECTED_OUTPUTS = [
    "ground_truth.json",
    "bounding_boxes.json",
    "rotation_keys_with_rot.json",
    "corners_comparison_dict.json",
]
EXPECTED_GROUND_TRUTH_SEMANTICS = (
    "--output is required; --calibration is required unless --skip-visualization "
    "is set; conversion-only mode uses a temporary alias workspace, does not "
    "mutate the input tree, and returns before demo image/video rendering"
)


class QualificationError(RuntimeError):
    """The static contract, source wiring, or canonical binding drifted."""


def canonical_bytes(value: Any) -> bytes:
    """Return stable JSON bytes for deterministic comparisons."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    """Return a lower-case SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(path: Path) -> dict[str, Any]:
    """Load a bounded regular JSON file with duplicate/non-finite rejection."""
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise QualificationError(f"not a regular non-symlink JSON file: {path}")
        if metadata.st_size > MAX_JSON_BYTES:
            raise QualificationError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise QualificationError(f"opened JSON is not regular: {path}")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_JSON_BYTES + 1)
        finally:
            os.close(descriptor)
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON number: {token}")
            ),
        )
    except QualificationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {path}")
    return value


def validate_schema(value: Any, schema_path: Path, label: str) -> None:
    """Validate with a checked Draft 2020-12 schema."""
    schema = strict_json(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {location}: {error.message}"
        )


def safe_repo_file(raw: str) -> Path:
    """Resolve a repository-relative regular file without following symlinks."""
    relative = Path(raw)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise QualificationError(f"unsafe repository path: {raw}")
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise QualificationError(f"missing repository source: {raw}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise QualificationError(f"symlinked repository source: {raw}")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError as exc:
        raise QualificationError(f"repository source escapes root: {raw}") from exc
    if not resolved.is_file():
        raise QualificationError(f"repository source is not a regular file: {raw}")
    return resolved


def _find_unique(rows: Any, key: str, expected: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise QualificationError(f"row set for {expected} is not an array")
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == expected]
    if len(matches) != 1:
        raise QualificationError(f"expected exactly one {key}={expected}")
    return matches[0]


def _source_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(contract["arm64_environment"]["source_controls"])
    for entry in contract["entries"]:
        rows.extend(entry["source_reviews"])
    return rows


def _verify_contract_denominators(contract: dict[str, Any]) -> None:
    observed = []
    for index, entry in enumerate(contract["entries"]):
        advertised, entry_id, capability_id, oracle_id, source_count = EXPECTED_ENTRIES[
            index
        ]
        observed.append(
            (
                entry["advertised"],
                entry["entry_id"],
                entry["capability"]["id"],
                entry["oracle"]["id"],
                len(entry["source_reviews"]),
            )
        )
        if entry["manifest_pointer"] != f"/features/30/advertised/{index}":
            raise QualificationError("manifest pointer/order drift")
        if entry["capability"] != {
            "id": capability_id,
            "kind": "tooling",
            "acceptance_class": "alternate_local_lane",
            "thor_state": "wired",
            "runtime_state": "not_qualified",
        }:
            raise QualificationError("canonical capability identity/state drift")
        if entry["oracle"] != {
            "id": oracle_id,
            "type": "offline_tool_execution",
            "current_state": "open_unexecuted",
            "runtime_evidence": [],
            "static_contract_is_full_semantic_proof": False,
        }:
            raise QualificationError("canonical oracle boundary drift")
    if observed != EXPECTED_ENTRIES:
        raise QualificationError("entry identity or source denominator drift")
    direct_paths = [row["path"] for entry in contract["entries"] for row in entry["source_reviews"]]
    if len(direct_paths) != 18 or len(set(direct_paths)) != 18:
        raise QualificationError("entry source-control denominator must be 18 unique paths")
    if contract["entries"][3]["deterministic_outputs"] != EXPECTED_OUTPUTS:
        raise QualificationError("ground-truth output denominator/order drift")


def _verify_manifest(contract: dict[str, Any]) -> None:
    manifest = strict_json(safe_repo_file(MANIFEST_PATH))
    features = manifest.get("features")
    if not isinstance(features, list) or len(features) <= 30:
        raise QualificationError("manifest feature index 30 is absent")
    feature = features[30]
    if not isinstance(feature, dict) or feature.get("id") != "synthetic-data-tools":
        raise QualificationError("manifest synthetic-data feature pointer drift")
    if feature.get("advertised") != [row[0] for row in EXPECTED_ENTRIES]:
        raise QualificationError("manifest advertised literal/order drift")
    if feature.get("acceptance_class") != "alternate_local_lane":
        raise QualificationError("manifest acceptance-class drift")
    if feature.get("thor_state") != "wired":
        raise QualificationError("manifest Thor wiring drift")
    # The family-level historical runtime state is deliberately not inherited by
    # these new entry-level contracts.


def _canonical_source_map(entry: dict[str, Any]) -> dict[str, str]:
    return {row["path"]: row["sha256"] for row in entry["source_reviews"]}


def _verify_ledgers(contract: dict[str, Any]) -> None:
    capabilities = strict_json(safe_repo_file(CAPABILITIES_PATH))
    oracles = strict_json(safe_repo_file(ORACLES_PATH))
    for entry in contract["entries"]:
        capability_id = entry["capability"]["id"]
        oracle_id = entry["oracle"]["id"]
        capability = _find_unique(capabilities.get("capabilities"), "id", capability_id)
        for field, expected in (
            ("feature_id", "synthetic-data-tools"),
            ("kind", "tooling"),
            ("title", entry["advertised"]),
            ("acceptance_class", "alternate_local_lane"),
            ("thor_state", "wired"),
            ("runtime_state", "not_qualified"),
        ):
            if capability.get(field) != expected:
                raise QualificationError(f"canonical capability {field} drift: {capability_id}")
        capability_contract = capability.get("contract")
        if not isinstance(capability_contract, dict):
            raise QualificationError(f"canonical capability contract absent: {capability_id}")
        controls = capability_contract.get("source_controls")
        if not isinstance(controls, list):
            raise QualificationError(f"canonical source controls absent: {capability_id}")
        ledger_sources = {
            row.get("path"): row.get("sha256") for row in controls if isinstance(row, dict)
        }
        if ledger_sources != _canonical_source_map(entry) or len(controls) != len(
            entry["source_reviews"]
        ):
            raise QualificationError(f"canonical source-control drift: {capability_id}")
        if capability_contract.get("warehouse_sample_bundle") != "excluded":
            raise QualificationError(f"Warehouse exclusion drift: {capability_id}")

        oracle = _find_unique(oracles.get("oracles"), "oracle_id", oracle_id)
        if oracle.get("capability_id") != capability_id:
            raise QualificationError(f"oracle/capability cross-map: {oracle_id}")
        binding = oracle.get("ledger_binding")
        if not isinstance(binding, dict):
            raise QualificationError(f"oracle ledger binding absent: {oracle_id}")
        for field in (
            "feature_id",
            "kind",
            "title",
            "acceptance_class",
            "thor_state",
            "runtime_state",
            "contract",
        ):
            if binding.get(field) != capability.get(field):
                raise QualificationError(f"oracle ledger binding drift: {oracle_id}/{field}")
        if oracle.get("current_state") != "open_unexecuted" or oracle.get("evidence") != []:
            raise QualificationError(f"oracle runtime promotion/evidence drift: {oracle_id}")


def _verify_source_reviews(contract: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    paths: set[str] = set()
    for row in _source_rows(contract):
        raw_path = row["path"]
        if raw_path in paths:
            raise QualificationError(f"duplicate source review: {raw_path}")
        paths.add(raw_path)
        path = safe_repo_file(raw_path)
        source_bytes = path.read_bytes()
        observed = sha256_bytes(source_bytes)
        if observed != row["sha256"]:
            raise QualificationError(f"source digest drift: {raw_path}")
        hashes[raw_path] = observed
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise QualificationError(f"source is not UTF-8: {raw_path}") from exc
        for fragment in row["text_fragments"]:
            if fragment not in source:
                raise QualificationError(f"missing source fragment in {raw_path}: {fragment}")
        if row["ast_symbols"]:
            try:
                tree = ast.parse(source, filename=raw_path)
            except SyntaxError as exc:
                raise QualificationError(f"source AST parse failed: {raw_path}") from exc
            symbols = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            missing = set(row["ast_symbols"]) - symbols
            if missing:
                raise QualificationError(
                    f"missing AST symbols in {raw_path}: {sorted(missing)}"
                )
    return hashes


def _verify_cli_contracts(contract: dict[str, Any]) -> None:
    source_paths = {row["path"] for row in _source_rows(contract)}
    for entry in contract["entries"]:
        for cli in entry["cli_contracts"]:
            if cli["path"] not in source_paths:
                raise QualificationError(f"CLI path lacks a source boundary: {cli['path']}")
            source = safe_repo_file(cli["path"]).read_text(encoding="utf-8")
            for argument in cli["arguments"]:
                if argument.startswith("--") and argument not in source:
                    raise QualificationError(
                        f"CLI argument absent from source {cli['path']}: {argument}"
                    )
    ground = contract["entries"][3]
    cli = ground["cli_contracts"][0]
    if "--skip-visualization" not in cli["arguments"]:
        raise QualificationError("bounded ground-truth CLI flag absent")
    if cli["semantics"] != EXPECTED_GROUND_TRUTH_SEMANTICS:
        raise QualificationError("ground-truth conversion-only semantics drift")
    source = safe_repo_file(cli["path"]).read_text(encoding="utf-8")
    required_fragments = [
        '"--output"',
        "required=True",
        '"--skip-visualization"',
        'action="store_true"',
        "if not args.skip_visualization and not args.calibration",
        "if args.skip_visualization:",
        "return",
        "enumerate(sorted(object_label_map)",
        "subfolders = sorted(",
        "for key in sorted(rotation_dict)",
    ]
    for fragment in required_fragments:
        if fragment not in source:
            raise QualificationError(f"ground-truth CLI/determinism drift: {fragment}")
    for output in EXPECTED_OUTPUTS:
        if output not in source:
            raise QualificationError(f"ground-truth output path absent: {output}")


def _verify_arm64_environment(contract: dict[str, Any]) -> dict[str, Any]:
    environment = contract["arm64_environment"]
    conda = environment["conda_lock"]
    pip_lock = environment["pip_requirements"]
    wheel = environment["wheel_lock"]
    for descriptor in (conda, pip_lock, wheel):
        actual = sha256_bytes(safe_repo_file(descriptor["path"]).read_bytes())
        if actual != descriptor["sha256"]:
            raise QualificationError(f"ARM64 lock digest drift: {descriptor['path']}")

    conda_lines = safe_repo_file(conda["path"]).read_text(encoding="utf-8").splitlines()
    urls = [line for line in conda_lines if line.startswith("https://")]
    if len(urls) != conda["artifact_count"]:
        raise QualificationError("ARM64 conda artifact denominator drift")
    if not all("conda.anaconda.org/conda-forge/" in line for line in urls):
        raise QualificationError("ARM64 conda source channel drift")
    if not all(re.search(r"#[0-9a-f]{64}$", line) for line in urls):
        raise QualificationError("ARM64 conda artifact hash fragment absent")
    for key in (
        "python_artifact_fragment",
        "openusd_artifact_fragment",
        "ffmpeg_artifact_fragment",
    ):
        if not any(conda[key] in line for line in urls):
            raise QualificationError(f"ARM64 conda identity absent: {conda[key]}")

    upstream = [
        line.strip()
        for line in safe_repo_file("tools/sdg-postprocessing/requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    thor = [
        line.strip()
        for line in safe_repo_file(pip_lock["path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    if len(thor) != pip_lock["requirement_count"]:
        raise QualificationError("ARM64 pip requirement denominator drift")
    if thor != [line for line in upstream if line != environment["upstream_usd_requirement"]]:
        raise QualificationError("ARM64 pip derivation drift")

    wheel_lines = [
        line
        for line in safe_repo_file(wheel["path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if len(wheel_lines) != wheel["wheel_count"]:
        raise QualificationError("ARM64 wheel denominator drift")
    wheel_pattern = re.compile(r"^[0-9a-f]{64}  wheels/[^/]+\.whl$")
    if not all(wheel_pattern.fullmatch(line) for line in wheel_lines):
        raise QualificationError("ARM64 wheel filename/bytes lock format drift")
    return {
        "platform": environment["platform"],
        "python": environment["python"],
        "openusd": environment["openusd"],
        "conda_artifacts": len(urls),
        "pip_requirements": len(thor),
        "locked_wheels": len(wheel_lines),
        "miniforge_filename": environment["miniforge"]["filename"],
        "miniforge_sha256": environment["miniforge"]["sha256"],
    }


def validate_contract(contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Validate static wiring and return deterministic non-runtime observations."""
    raw_contract_sha256 = sha256_bytes(contract_path.read_bytes())
    if raw_contract_sha256 != EXPECTED_CONTRACT_SHA256:
        raise QualificationError("exact contract digest drift")
    contract = strict_json(contract_path)
    validate_schema(contract, CONTRACT_SCHEMA, "contract")
    _verify_contract_denominators(contract)
    _verify_manifest(contract)
    _verify_ledgers(contract)
    source_hashes = _verify_source_reviews(contract)
    _verify_cli_contracts(contract)
    arm64 = _verify_arm64_environment(contract)
    return {
        "contract_sha256": raw_contract_sha256,
        "source_hashes": dict(sorted(source_hashes.items())),
        "unique_entry_source_count": 18,
        "arm64_environment": arm64,
        "entry_bindings": [
            {
                "entry_id": entry["entry_id"],
                "capability_id": entry["capability"]["id"],
                "oracle_id": entry["oracle"]["id"],
                "kind": entry["capability"]["kind"],
                "acceptance_class": entry["capability"]["acceptance_class"],
                "thor_state": entry["capability"]["thor_state"],
                "runtime_state": entry["capability"]["runtime_state"],
                "oracle_state": entry["oracle"]["current_state"],
                "source_count": len(entry["source_reviews"]),
                "runtime_evidence": [],
            }
            for entry in contract["entries"]
        ],
        "ground_truth_cli": {
            "flag": "--skip-visualization",
            "requires_output": True,
            "requires_calibration": False,
            "default_visualization_requires_calibration": True,
            "deterministic_outputs": EXPECTED_OUTPUTS,
        },
        "warehouse_sample_bundle": "excluded",
        "runtime_evidence": [],
        "full_semantic_execution_performed": False,
        "canonical_state_advanced": False,
    }
