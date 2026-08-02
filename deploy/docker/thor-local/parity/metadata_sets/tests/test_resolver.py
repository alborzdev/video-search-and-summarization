from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE.parent))

from metadata_sets import resolver  # noqa: E402


COMMIT = "a" * 40
SET_ID = "test-metadata-set"
DESCRIPTOR_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/test-metadata-set.json"
)


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write(root: Path, relative: str, payload: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _member_schema(document_id: str, collection: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": document_id,
        "type": "object",
        "required": ["schema_version", "target", collection],
        "properties": {
            "schema_version": {"const": 1},
            "target": {"type": "object"},
            collection: {"type": "array"},
        },
    }


def _build_repo(root: Path) -> None:
    for name in ("selector.schema.json", "metadata-set.schema.json"):
        _write(
            root,
            f"deploy/docker/thor-local/parity/metadata_sets/{name}",
            (PACKAGE / name).read_bytes(),
        )
    documents = {
        "manifest": {
            "schema_version": 1,
            "upstream": {"latest_ga": "v3.2.1", "target_commit": COMMIT},
            "features": [
                {
                    "id": "feature",
                    "official_capability_ids": ["cap"],
                    "acceptance_class": "required_local",
                    "thor_state": "wired",
                    "runtime_state": "not_qualified",
                }
            ],
        },
        "official_capabilities": {
            "schema_version": 1,
            "target": {"product_version": "3.2.1", "main_commit": COMMIT},
            "capabilities": [
                {
                    "id": "cap",
                    "feature_id": "feature",
                    "kind": "runtime_behavior",
                    "title": "capability",
                    "source_claims": [],
                    "acceptance_class": "required_local",
                    "thor_state": "wired",
                    "runtime_state": "not_qualified",
                    "contract": {},
                    "scenario_ids": ["scenario"],
                    "gap": "not qualified",
                }
            ],
        },
        "capability_oracles": {
            "schema_version": 1,
            "target": {"product_version": "3.2.1", "main_commit": COMMIT},
            "oracles": [
                {
                    "capability_id": "cap",
                    "ledger_binding": {
                        "feature_id": "feature",
                        "kind": "runtime_behavior",
                        "title": "capability",
                        "source_claims": [],
                        "acceptance_class": "required_local",
                        "thor_state": "wired",
                        "runtime_state": "not_qualified",
                        "contract": {},
                        "gap": "not qualified",
                    },
                }
            ],
        },
        "acceptance_inventory": {
            "schema_version": 1,
            "scenarios": [{"id": "scenario"}],
            "coverage": {
                "features": [{"feature_id": "feature", "scenario_ids": ["scenario"]}]
            },
        },
    }
    document_paths = {
        "manifest": "deploy/docker/thor-local/parity/manifest.json",
        "official_capabilities": (
            "deploy/docker/thor-local/parity/official-capabilities.json"
        ),
        "capability_oracles": (
            "deploy/docker/thor-local/parity/capability-oracles.json"
        ),
        "acceptance_inventory": (
            "deploy/docker/thor-local/qualification/acceptance_inventory.json"
        ),
    }
    schema_values = {
        "official_capabilities_schema": _member_schema(
            "https://example.test/official.schema.json", "capabilities"
        ),
        "capability_oracles_schema": _member_schema(
            "https://example.test/oracles.schema.json", "oracles"
        ),
    }
    schema_paths = {
        "official_capabilities_schema": (
            "deploy/docker/thor-local/parity/official-capabilities.schema.json"
        ),
        "capability_oracles_schema": (
            "deploy/docker/thor-local/parity/capability-oracles.schema.json"
        ),
    }
    for document_id, value in documents.items():
        _write(root, document_paths[document_id], _encoded(value))
    for schema_id, value in schema_values.items():
        _write(root, schema_paths[schema_id], _encoded(value))

    descriptor = {
        "schema_version": 1,
        "set_id": SET_ID,
        "mode": "immutable_static_metadata_set",
        "lifecycle": "live_ready",
        "target": {"product_version": "3.2.1", "main_commit": COMMIT},
        "expected_counts": {
            "capabilities": 1,
            "oracles": 1,
            "feature_families": 1,
        },
        "documents": {
            document_id: {
                "path": path,
                "raw_sha256": _sha((root / path).read_bytes()),
                "schema_version": 1,
                **(
                    {"schema_id": f"{document_id}_schema"}
                    if document_id in {"official_capabilities", "capability_oracles"}
                    else {}
                ),
            }
            for document_id, path in document_paths.items()
        },
        "schemas": {
            schema_id: {
                "path": path,
                "raw_sha256": _sha((root / path).read_bytes()),
                "dialect": "https://json-schema.org/draft/2020-12/schema",
                "document_id": schema_values[schema_id]["$id"],
            }
            for schema_id, path in schema_paths.items()
        },
    }
    _write(root, DESCRIPTOR_PATH, _encoded(descriptor))
    _write_selector(root)


def _write_selector(root: Path) -> None:
    descriptor_payload = (root / DESCRIPTOR_PATH).read_bytes()
    selector = {
        "schema_version": 1,
        "selected_set": SET_ID,
        "available_sets": [
            {
                "set_id": SET_ID,
                "descriptor_path": DESCRIPTOR_PATH,
                "descriptor_raw_sha256": _sha(descriptor_payload),
            }
        ],
    }
    _write(root, resolver.SELECTOR_PATH, _encoded(selector))


def _rewrite_descriptor(root: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    path = root / DESCRIPTOR_PATH
    value = json.loads(path.read_text())
    mutation(value)
    path.write_bytes(_encoded(value))
    _write_selector(root)


def _rewrite_member_and_relock(
    root: Path,
    document_id: str,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    descriptor = json.loads((root / DESCRIPTOR_PATH).read_text())
    member_path = root / descriptor["documents"][document_id]["path"]
    value = json.loads(member_path.read_text())
    mutation(value)
    member_path.write_bytes(_encoded(value))

    def relock(updated: dict[str, Any]) -> None:
        updated["documents"][document_id]["raw_sha256"] = _sha(member_path.read_bytes())

    _rewrite_descriptor(root, relock)


@pytest.fixture
def metadata_repo(tmp_path: Path) -> Path:
    _build_repo(tmp_path)
    return tmp_path


def test_checked_in_289_set_resolves_as_one_snapshot() -> None:
    snapshot = resolver.resolve_metadata_set()
    assert snapshot.set_id == "thor-vss-3.2.1-live-289"
    assert dict(snapshot.expected_counts) == {
        "capabilities": 289,
        "oracles": 289,
        "feature_families": 55,
    }
    first = snapshot.document("manifest")
    first["schema_version"] = 999
    assert snapshot.document("manifest")["schema_version"] == 1


def test_checked_in_staged_500_set_resolves_without_selecting_it() -> None:
    snapshot = resolver.resolve_metadata_set("thor-vss-3.2.1-metadata-500-staged")
    assert snapshot.set_id == "thor-vss-3.2.1-metadata-500-staged"
    assert dict(snapshot.expected_counts) == {
        "capabilities": 500,
        "oracles": 500,
        "feature_families": 55,
    }
    assert snapshot.document("capability_oracles")["schema_version"] == 2
    selected = resolver.resolve_metadata_set()
    assert selected.set_id == "thor-vss-3.2.1-live-289"


def test_unknown_set_and_document_fail_closed(metadata_repo: Path) -> None:
    with pytest.raises(resolver.MetadataSetError, match="unknown metadata set"):
        resolver.resolve_metadata_set("missing", repo_root=metadata_repo)
    snapshot = resolver.resolve_metadata_set(repo_root=metadata_repo)
    with pytest.raises(resolver.MetadataSetError, match="unknown document id"):
        snapshot.document("missing")


def test_duplicate_selector_key_is_rejected(metadata_repo: Path) -> None:
    selector = metadata_repo / resolver.SELECTOR_PATH
    selector.write_text(
        '{"schema_version":1,"selected_set":"test-metadata-set",'
        '"selected_set":"test-metadata-set","available_sets":[]}'
    )
    with pytest.raises(resolver.MetadataSetError, match="duplicate JSON key"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_duplicate_registry_id_is_rejected(metadata_repo: Path) -> None:
    selector_path = metadata_repo / resolver.SELECTOR_PATH
    selector = json.loads(selector_path.read_text())
    selector["available_sets"].append(selector["available_sets"][0])
    selector_path.write_bytes(_encoded(selector))
    with pytest.raises(resolver.MetadataSetError, match="duplicate set id"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_descriptor_and_member_hash_drift_are_rejected(metadata_repo: Path) -> None:
    descriptor = metadata_repo / DESCRIPTOR_PATH
    descriptor.write_bytes(descriptor.read_bytes() + b" ")
    with pytest.raises(resolver.MetadataSetError, match="descriptor.*raw hash differs"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)

    _build_repo(metadata_repo)
    manifest = metadata_repo / "deploy/docker/thor-local/parity/manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(resolver.MetadataSetError, match="documents.manifest: raw hash"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_parent_escape_and_member_symlink_are_rejected(metadata_repo: Path) -> None:
    _rewrite_descriptor(
        metadata_repo,
        lambda value: value["documents"]["manifest"].update(
            {"path": "deploy/docker/thor-local/../manifest.json"}
        ),
    )
    with pytest.raises(resolver.MetadataSetError, match="schema violation|unsafe"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)

    _build_repo(metadata_repo)
    manifest = metadata_repo / "deploy/docker/thor-local/parity/manifest.json"
    target = metadata_repo / "manifest-target.json"
    target.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(target)
    with pytest.raises(resolver.MetadataSetError, match="symlink"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_symlinked_path_component_is_rejected(metadata_repo: Path) -> None:
    parity = metadata_repo / "deploy/docker/thor-local/parity"
    moved = metadata_repo / "real-parity"
    parity.rename(moved)
    parity.symlink_to(moved, target_is_directory=True)
    with pytest.raises(resolver.MetadataSetError, match="symlink"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_mixed_ledger_oracle_set_is_rejected_after_valid_relock(
    metadata_repo: Path,
) -> None:
    oracle_path = (
        metadata_repo / "deploy/docker/thor-local/parity/capability-oracles.json"
    )
    oracle = json.loads(oracle_path.read_text())
    oracle["oracles"][0]["capability_id"] = "other"
    oracle_path.write_bytes(_encoded(oracle))

    def relock(value: dict[str, Any]) -> None:
        value["documents"]["capability_oracles"]["raw_sha256"] = _sha(
            oracle_path.read_bytes()
        )

    _rewrite_descriptor(metadata_repo, relock)
    with pytest.raises(resolver.MetadataSetError, match="id order differs"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_oracle_ledger_binding_substitution_is_rejected_after_valid_relock(
    metadata_repo: Path,
) -> None:
    _rewrite_member_and_relock(
        metadata_repo,
        "capability_oracles",
        lambda value: value["oracles"][0]["ledger_binding"].update(
            {"title": "substituted-but-schema-valid"}
        ),
    )
    with pytest.raises(resolver.MetadataSetError, match="binding differs"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_manifest_aggregate_overclaim_is_rejected_after_valid_relock(
    metadata_repo: Path,
) -> None:
    _rewrite_member_and_relock(
        metadata_repo,
        "manifest",
        lambda value: value["features"][0].update({"runtime_state": "passed"}),
    )
    with pytest.raises(resolver.MetadataSetError, match="aggregate differs"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


@pytest.mark.parametrize("scenario_ids", [[], ["invented-scenario"]])
def test_acceptance_coverage_attacks_are_rejected_after_valid_relock(
    metadata_repo: Path, scenario_ids: list[str]
) -> None:
    _rewrite_member_and_relock(
        metadata_repo,
        "acceptance_inventory",
        lambda value: value["coverage"]["features"][0].update(
            {"scenario_ids": scenario_ids}
        ),
    )
    with pytest.raises(
        resolver.MetadataSetError,
        match="coverage scenario ids|coverage omits capability scenarios",
    ):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_duplicate_acceptance_scenario_is_rejected_after_valid_relock(
    metadata_repo: Path,
) -> None:
    _rewrite_member_and_relock(
        metadata_repo,
        "acceptance_inventory",
        lambda value: value["scenarios"].append({"id": "scenario"}),
    )
    with pytest.raises(resolver.MetadataSetError, match="scenario ids.*unique"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_duplicate_capability_scenario_is_rejected_after_valid_relock(
    metadata_repo: Path,
) -> None:
    _rewrite_member_and_relock(
        metadata_repo,
        "official_capabilities",
        lambda value: value["capabilities"][0].update(
            {"scenario_ids": ["scenario", "scenario"]}
        ),
    )
    with pytest.raises(resolver.MetadataSetError, match="invalid scenario ids"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_validation_only_set_cannot_be_default_selected(
    metadata_repo: Path,
) -> None:
    _rewrite_descriptor(
        metadata_repo,
        lambda value: value.update({"lifecycle": "validation_only"}),
    )
    with pytest.raises(resolver.MetadataSetError, match="not live-ready"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)
    assert (
        resolver.resolve_metadata_set(SET_ID, repo_root=metadata_repo).set_id == SET_ID
    )


def test_schema_version_mismatch_is_rejected_after_valid_relock(
    metadata_repo: Path,
) -> None:
    acceptance_path = (
        metadata_repo
        / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
    )
    acceptance = json.loads(acceptance_path.read_text())
    acceptance["schema_version"] = 2
    acceptance_path.write_bytes(_encoded(acceptance))

    def relock(value: dict[str, Any]) -> None:
        value["documents"]["acceptance_inventory"]["raw_sha256"] = _sha(
            acceptance_path.read_bytes()
        )

    _rewrite_descriptor(metadata_repo, relock)
    with pytest.raises(resolver.MetadataSetError, match="schema_version differs"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_duplicate_and_nonfinite_member_json_are_rejected(metadata_repo: Path) -> None:
    ledger_path = (
        metadata_repo / "deploy/docker/thor-local/parity/official-capabilities.json"
    )
    ledger_path.write_text(
        '{"schema_version":1,"schema_version":1,"target":{},"capabilities":[]}'
    )

    def relock(value: dict[str, Any]) -> None:
        value["documents"]["official_capabilities"]["raw_sha256"] = _sha(
            ledger_path.read_bytes()
        )

    _rewrite_descriptor(metadata_repo, relock)
    with pytest.raises(resolver.MetadataSetError, match="duplicate JSON key"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)

    _build_repo(metadata_repo)
    ledger_path.write_text(
        '{"schema_version":1,"target":{},"capabilities":[],"bad":NaN}'
    )
    _rewrite_descriptor(metadata_repo, relock)
    with pytest.raises(resolver.MetadataSetError, match="non-finite"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)


def test_final_recheck_detects_toctou(
    metadata_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = resolver._read_repo_regular

    def racing_read(*args: Any, **kwargs: Any) -> resolver._ReadRecord:
        record = original(*args, **kwargs)
        if kwargs.get("label", "").startswith(
            "TOCTOU recheck"
        ) and record.path.endswith("/manifest.json"):
            identity = list(record.identity)
            identity[3] += 1
            return replace(record, identity=tuple(identity))
        return record

    monkeypatch.setattr(resolver, "_read_repo_regular", racing_read)
    with pytest.raises(resolver.MetadataSetError, match="changed during resolution"):
        resolver.resolve_metadata_set(repo_root=metadata_repo)
