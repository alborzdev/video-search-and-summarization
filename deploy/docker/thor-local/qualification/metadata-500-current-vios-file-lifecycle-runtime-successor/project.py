#!/usr/bin/env python3
"""Build and validate the current 500-row metadata successor atomically."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(PARITY))

import capability_oracles_v2  # noqa: E402
import verify_official_capabilities  # noqa: E402


CURRENT_LEDGER = "deploy/docker/thor-local/parity/official-capabilities.json"
CURRENT_ORACLES = "deploy/docker/thor-local/parity/capability-oracles.json"
CURRENT_MANIFEST = "deploy/docker/thor-local/parity/manifest.json"
CURRENT_ACCEPTANCE = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
CURRENT_ORACLE_SCHEMA = "deploy/docker/thor-local/parity/capability-oracles.schema.json"
CURRENT_OFFICIAL_SCHEMA = "deploy/docker/thor-local/parity/official-capabilities.schema.json"
PRIOR_LEDGER_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-vios-codecs-runtime-successor/"
    "post-state-official-capabilities.json"
)
PRIOR_ORACLES_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-vios-codecs-runtime-successor/"
    "post-state-capability-oracles.json"
)
PRIOR_MANIFEST_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-vios-codecs-runtime-successor/post-state-manifest.json"
)
ACCEPTANCE_500 = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-migration-rebase-successor/"
    "post-state-acceptance-inventory.json"
)
PRIOR_ORACLE_SCHEMA_500 = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-vios-codecs-runtime-successor/"
    "post-state-capability-oracles.schema.json"
)
OUTPUT_LEDGER_500 = str(HERE.relative_to(REPO) / "post-state-official-capabilities.json")
OUTPUT_ORACLES_500 = str(HERE.relative_to(REPO) / "post-state-capability-oracles.json")
OUTPUT_MANIFEST_500 = str(HERE.relative_to(REPO) / "post-state-manifest.json")
OUTPUT_ORACLE_SCHEMA_500 = str(
    HERE.relative_to(REPO) / "post-state-capability-oracles.schema.json"
)
SET_ID_289 = "thor-vss-3.2.1-current-vios-file-lifecycle-runtime-289"
SET_ID_500 = "thor-vss-3.2.1-current-vios-file-lifecycle-runtime-500"
DESCRIPTOR_289 = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    f"{SET_ID_289}.json"
)
DESCRIPTOR_500 = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    f"{SET_ID_500}.json"
)
SELECTOR = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
VSS_CODEC_FEATURE = "vios-codecs-audio"
VSS_CODEC_500_GAP = (
    "The canonical Thor receipt passes CPU multimedia, B-frame handling, HEVC "
    "multislice/RFC7798, H.264/H.265, and bounded AAC RTSP republish with its "
    "documented transcode substitute. In this 500-row planning overlay, the four "
    "non-CPU passed results remain candidate rows until separately evidence-bound; "
    "main-VIOS audio recording remains approval-gated and unqualified."
)


class ProjectionError(RuntimeError):
    """The current or predecessor metadata cannot form the exact successor."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProjectionError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ProjectionError(f"non-finite JSON value in {label}: {value}")
            ),
        )
    except ProjectionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(f"invalid JSON: {label}") from exc


def _read(relative: str) -> bytes:
    path = REPO / relative
    if path.is_symlink() or not path.is_file():
        raise ProjectionError(f"missing regular source: {relative}")
    return path.read_bytes()


def _load(relative: str) -> dict[str, Any]:
    value = _strict_json(_read(relative), relative)
    if not isinstance(value, dict):
        raise ProjectionError(f"JSON source is not an object: {relative}")
    return value


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _claim_digest(source_id: str, capabilities: list[dict[str, Any]]) -> str:
    claims = []
    for capability in capabilities:
        for claim in capability["source_claims"]:
            if claim["source_id"] == source_id:
                claims.append(
                    {
                        "capability_id": capability["id"],
                        "locator": claim["locator"],
                        "contract": capability["contract"],
                    }
                )
    if not claims:
        raise ProjectionError(f"source has no capability claims: {source_id}")
    canonical = sorted(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in claims
    )
    return _sha(json.dumps(canonical, separators=(",", ":")).encode())


def _project_documents() -> tuple[dict[str, Any], ...]:
    current_ledger = _load(CURRENT_LEDGER)
    current_oracles = _load(CURRENT_ORACLES)
    current_manifest = _load(CURRENT_MANIFEST)
    ledger_500 = _load(PRIOR_LEDGER_500)
    oracles_500 = _load(PRIOR_ORACLES_500)
    prior_manifest = _load(PRIOR_MANIFEST_500)
    acceptance_500 = _load(ACCEPTANCE_500)
    oracle_schema_500 = _load(PRIOR_ORACLE_SCHEMA_500)

    current_capabilities = current_ledger.get("capabilities")
    capabilities_500 = ledger_500.get("capabilities")
    current_oracle_rows = current_oracles.get("oracles")
    oracle_rows_500 = oracles_500.get("oracles")
    if not all(
        isinstance(value, list)
        for value in (
            current_capabilities,
            capabilities_500,
            current_oracle_rows,
            oracle_rows_500,
        )
    ):
        raise ProjectionError("capability or oracle collections are malformed")
    if (
        len(current_capabilities) != 289
        or len(capabilities_500) != 500
        or len(current_oracle_rows) != 289
        or len(oracle_rows_500) != 500
    ):
        raise ProjectionError("289/500 metadata count contract drifted")
    if [item["id"] for item in current_capabilities] != [
        item["id"] for item in capabilities_500[:289]
    ]:
        raise ProjectionError("500-capability predecessor no longer has the current ID prefix")
    if [item["capability_id"] for item in current_oracle_rows] != [
        item["capability_id"] for item in oracle_rows_500[:289]
    ]:
        raise ProjectionError("500-oracle predecessor no longer has the current ID prefix")

    ledger_500["capabilities"][:289] = copy.deepcopy(current_capabilities)
    ledger_500["sources"] = copy.deepcopy(current_ledger["sources"])
    for source in ledger_500["sources"]:
        source["claim_set_sha256"] = _claim_digest(
            source["id"], ledger_500["capabilities"]
        )

    oracles_500["oracles"][:289] = copy.deepcopy(current_oracle_rows)

    prior_features = {item["id"]: item for item in prior_manifest["features"]}
    projected_features = []
    for feature in current_manifest["features"]:
        feature_id = feature["id"]
        if feature_id not in prior_features:
            raise ProjectionError(f"500-manifest predecessor lacks family: {feature_id}")
        projected = copy.deepcopy(feature)
        projected["official_capability_ids"] = copy.deepcopy(
            prior_features[feature_id]["official_capability_ids"]
        )
        group = [
            item
            for item in ledger_500["capabilities"]
            if item["feature_id"] == feature_id
        ]
        aggregate = verify_official_capabilities._aggregate_family_status(group)
        projected.update(aggregate)
        if projected.get("unqualified_advertised"):
            projected["runtime_state"] = "not_qualified"
        if feature_id == VSS_CODEC_FEATURE:
            projected["gap"] = VSS_CODEC_500_GAP
        projected_features.append(projected)
    manifest_500 = copy.deepcopy(current_manifest)
    manifest_500["features"] = projected_features

    runtime_state_schema = oracle_schema_500["$defs"]["live_oracle"]["allOf"][0][
        "then"
    ]["properties"]["ledger_binding"]["properties"]["runtime_state"]
    if runtime_state_schema != {"enum": ["not_qualified", "passed_current"]}:
        raise ProjectionError("predecessor runtime-state schema drifted")

    verify_official_capabilities.validate(
        ledger=ledger_500,
        manifest=manifest_500,
        acceptance=acceptance_500,
        oracle_plan=oracles_500,
        oracle_schema=oracle_schema_500,
        repo_root=REPO,
    )
    capability_oracles_v2.validate(
        oracles_500,
        ledger_500,
        acceptance_500,
        oracle_schema_500,
    )
    return ledger_500, oracles_500, manifest_500, oracle_schema_500


def _member(
    path: str,
    raw: bytes,
    *,
    schema_version: int | None = None,
    schema_id: str | None = None,
    dialect: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"path": path, "raw_sha256": _sha(raw)}
    if schema_version is not None:
        value["schema_version"] = schema_version
    if schema_id is not None:
        value["schema_id"] = schema_id
    if dialect is not None:
        value["dialect"] = dialect
    if document_id is not None:
        value["document_id"] = document_id
    return value


def _descriptor(
    *,
    set_id: str,
    count: int,
    manifest: tuple[str, bytes],
    ledger: tuple[str, bytes],
    oracles: tuple[str, bytes],
    acceptance: tuple[str, bytes],
    oracle_schema: tuple[str, bytes, str],
) -> dict[str, Any]:
    target = _load(CURRENT_LEDGER)["target"]
    return {
        "documents": {
            "acceptance_inventory": _member(
                acceptance[0], acceptance[1], schema_version=1
            ),
            "capability_oracles": _member(
                oracles[0],
                oracles[1],
                schema_version=1 if count == 289 else 2,
                schema_id="capability_oracles_schema",
            ),
            "manifest": _member(manifest[0], manifest[1], schema_version=1),
            "official_capabilities": _member(
                ledger[0],
                ledger[1],
                schema_version=1,
                schema_id="official_capabilities_schema",
            ),
        },
        "expected_counts": {
            "capabilities": count,
            "feature_families": 55,
            "oracles": count,
        },
        "lifecycle": "live_ready",
        "mode": "immutable_static_metadata_set",
        "schema_version": 1,
        "schemas": {
            "capability_oracles_schema": _member(
                oracle_schema[0],
                oracle_schema[1],
                dialect="https://json-schema.org/draft/2020-12/schema",
                document_id=oracle_schema[2],
            ),
            "official_capabilities_schema": _member(
                CURRENT_OFFICIAL_SCHEMA,
                _read(CURRENT_OFFICIAL_SCHEMA),
                dialect="https://json-schema.org/draft/2020-12/schema",
                document_id=(
                    "https://developer.nvidia.com/vss/thor-local/"
                    "official-capabilities.schema.json"
                ),
            ),
        },
        "set_id": set_id,
        "target": {
            "main_commit": target["main_commit"],
            "product_version": target["product_version"],
        },
    }


def build_outputs() -> dict[str, bytes]:
    ledger_500, oracles_500, manifest_500, schema_500 = _project_documents()
    outputs = {
        OUTPUT_LEDGER_500: _encoded(ledger_500),
        OUTPUT_ORACLES_500: _encoded(oracles_500),
        OUTPUT_MANIFEST_500: _encoded(manifest_500),
        OUTPUT_ORACLE_SCHEMA_500: _encoded(schema_500),
    }
    descriptor_289 = _descriptor(
        set_id=SET_ID_289,
        count=289,
        manifest=(CURRENT_MANIFEST, _read(CURRENT_MANIFEST)),
        ledger=(CURRENT_LEDGER, _read(CURRENT_LEDGER)),
        oracles=(CURRENT_ORACLES, _read(CURRENT_ORACLES)),
        acceptance=(CURRENT_ACCEPTANCE, _read(CURRENT_ACCEPTANCE)),
        oracle_schema=(
            CURRENT_ORACLE_SCHEMA,
            _read(CURRENT_ORACLE_SCHEMA),
            "https://nvidia.com/vss/thor/capability-oracles.schema.json",
        ),
    )
    descriptor_500 = _descriptor(
        set_id=SET_ID_500,
        count=500,
        manifest=(OUTPUT_MANIFEST_500, outputs[OUTPUT_MANIFEST_500]),
        ledger=(OUTPUT_LEDGER_500, outputs[OUTPUT_LEDGER_500]),
        oracles=(OUTPUT_ORACLES_500, outputs[OUTPUT_ORACLES_500]),
        acceptance=(ACCEPTANCE_500, _read(ACCEPTANCE_500)),
        oracle_schema=(
            OUTPUT_ORACLE_SCHEMA_500,
            outputs[OUTPUT_ORACLE_SCHEMA_500],
            (
                "https://developer.nvidia.com/vss/thor-local/"
                "live-capability-oracles-v2.schema.json"
            ),
        ),
    )
    outputs[DESCRIPTOR_289] = _encoded(descriptor_289)
    outputs[DESCRIPTOR_500] = _encoded(descriptor_500)
    selector = {
        "available_sets": [
            {
                "descriptor_path": DESCRIPTOR_289,
                "descriptor_raw_sha256": _sha(outputs[DESCRIPTOR_289]),
                "set_id": SET_ID_289,
            },
            {
                "descriptor_path": DESCRIPTOR_500,
                "descriptor_raw_sha256": _sha(outputs[DESCRIPTOR_500]),
                "set_id": SET_ID_500,
            },
        ],
        "schema_version": 1,
        "selected_set": SET_ID_500,
    }
    outputs[SELECTOR] = _encoded(selector)
    return outputs


def _write_atomic(relative: str, raw: bytes) -> None:
    target = REPO / relative
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ProjectionError(f"refusing unsafe output target: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="atomically write the exact projection"
    )
    args = parser.parse_args(argv)
    try:
        outputs = build_outputs()
        if args.write:
            for relative, raw in outputs.items():
                _write_atomic(relative, raw)
            mode = "written"
        else:
            drift = [
                relative
                for relative, raw in outputs.items()
                if not (REPO / relative).is_file()
                or (REPO / relative).read_bytes() != raw
            ]
            if drift:
                raise ProjectionError(f"projection drift: {', '.join(drift)}")
            mode = "verified"
    except (KeyError, OSError, TypeError, ValueError, ProjectionError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "mode": mode,
                "selected_set": SET_ID_500,
                "output_count": len(outputs),
                "output_sha256": {
                    relative: _sha(raw) for relative, raw in sorted(outputs.items())
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
