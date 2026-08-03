from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "spatial_ai_promotion_compiler", PACKAGE / "compiler.py"
)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def digest(value: object) -> str:
    return hashlib.sha256(compiler.canonical_bytes(value)).hexdigest()


def test_checked_derivation_is_exact_and_idempotent() -> None:
    first_documents, first_payloads, counts = compiler.derive()
    second_documents, second_payloads, _ = compiler.derive()
    assert first_documents == second_documents
    assert first_payloads == second_payloads
    assert counts["promoted_capabilities"] == 7
    assert counts["preserved_metadata_500_capabilities"] == 493
    assert counts["product_function_calls"] == 122
    assert {
        name: compiler.sha256(payload) for name, payload in first_payloads.items()
    } == compiler.EXPECTED_OUTPUT_SHA256


def test_exact_delta_suffix_external_row_and_family_state() -> None:
    documents, _, _ = compiler.derive()
    old_ledger = compiler.load_receipt_head(compiler.CURRENT_LEDGER)
    old_oracle = compiler.load_receipt_head(compiler.CURRENT_ORACLES)
    selected_ledger = compiler.load_locked(compiler.SELECTED_LEDGER)
    selected_oracle = compiler.load_locked(compiler.SELECTED_ORACLES)
    new_ledger = documents["ledger_289"]
    new_oracle = documents["oracle_289"]
    assert compiler.changed_ids(
        old_ledger["capabilities"], new_ledger["capabilities"], "id"
    ) == set(compiler.TARGET_IDS)
    assert compiler.changed_ids(
        old_oracle["oracles"], new_oracle["oracles"], "capability_id"
    ) == set(compiler.TARGET_IDS)
    old_caps = {row["id"]: row for row in old_ledger["capabilities"]}
    new_caps = {row["id"]: row for row in new_ledger["capabilities"]}
    old_oracles = {row["capability_id"]: row for row in old_oracle["oracles"]}
    new_oracles = {row["capability_id"]: row for row in new_oracle["oracles"]}
    assert new_caps[compiler.EXTERNAL_ID] == old_caps[compiler.EXTERNAL_ID]
    assert new_oracles[compiler.EXTERNAL_ID] == old_oracles[compiler.EXTERNAL_ID]
    assert (
        digest(new_caps[compiler.EXTERNAL_ID])
        == "317d4d9b346832c17f7a4052d3a36ab673ae8727112deaf16fbc20f87afd4602"
    )
    assert (
        digest(new_oracles[compiler.EXTERNAL_ID])
        == "8aa110783776a7edbc4369efbf3b8c286b109a9b5edcabb4f6710f2c1fe9926c"
    )
    assert (
        documents["ledger_500"]["capabilities"][289:]
        == selected_ledger["capabilities"][289:]
    )
    assert documents["oracle_500"]["oracles"][289:] == selected_oracle["oracles"][289:]
    assert (
        digest(documents["ledger_500"]["capabilities"][289:])
        == "658f7972440b80eb6302c9ca6a64eb231ebaa41fc4d5ce7b633df020a55d69d9"
    )
    assert (
        digest(documents["oracle_500"]["oracles"][289:])
        == "3b579c6abded078f2bc4ddd8fdca34f4f577171463c02f7ecca797ce2f2789ab"
    )
    family = next(
        row
        for row in documents["manifest_289"]["features"]
        if row["id"] == "spatial-ai-utils"
    )
    assert (family["thor_state"], family["runtime_state"]) == (
        "partial",
        "not_qualified",
    )


def test_row05_exact_current_contract_and_oracle_projection() -> None:
    documents, _, _ = compiler.derive()
    capability_id = compiler.TARGET_IDS[5]
    ledger = next(
        row
        for row in documents["ledger_289"]["capabilities"]
        if row["id"] == capability_id
    )
    oracle = next(
        row
        for row in documents["oracle_289"]["oracles"]
        if row["capability_id"] == capability_id
    )
    contract = ledger["contract"]
    assert len(contract["source_controls"]) == 3
    assert [row["path"] for row in contract["source_controls"]] == [
        "libs/analytics/spatialai-data-utils/spatialai_data_utils/converters/nusc_results_to_nvschema.py",
        "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/geometry/rotation.py",
        "libs/analytics/spatialai-data-utils/spatialai_data_utils/loaders/nvschema.py",
    ]
    assert [row["sha256"] for row in contract["source_controls"]] == [
        "e433d69e7561e304cff99925122b7c44822ee1a279b29ce62607ac439cfec060",
        "c284a70fbdcc116a9310cfb568d34256ff3516235080571a38fbda05a5de9f32",
        "81faba50eaf2a239e0bbc7b9022c33baeea123ccae49812ca95a0ca060dc6f3e",
    ]
    assert len(contract["required_semantics"]) == 13
    assert contract["required_semantics"] == [
        "convert_sparse4d_to_nvschema",
        "version_4_0",
        "class",
        "confidence",
        "rotation",
        "dimensions",
        "embedding",
        "bbox3d",
        "quaternion_rotation",
        "non_identity_quaternion_rotation",
        "strict_loader_round_trip",
        "gt_json_aicity_flattened_semantics",
        "top_and_bbox_confidence",
    ]
    assert oracle["ledger_binding"]["contract"] == contract
    assert oracle["fixture"]["input"]["contract"] == contract
    assert (
        oracle["fixture"]["materialization"]["sha256"]
        == "f5172225171daef63dc35f79392c5f9a715bb729facb9a7566970ed9dc51a20f"
    )
    assert oracle["current_state"] == "open_unexecuted"
    assert oracle["evidence"] == []
    assert oracle["acceptance_readiness"] == {
        "blockers": [],
        "classification": "executor_ready",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["accounting"].update(product_function_calls=121),
        lambda value: value["promotion"].update(canonical_parity_mutated=True),
        lambda value: value["producer_receipt"]["capability_results"][0].update(
            status="partial"
        ),
    ],
)
def test_authority_mutations_are_rejected(
    monkeypatch: pytest.MonkeyPatch, mutate
) -> None:
    original_loader = compiler.load_locked
    authority = copy.deepcopy(original_loader(compiler.RAW_RECEIPT))
    mutate(authority)

    def load(source):
        return authority if source == compiler.RAW_RECEIPT else original_loader(source)

    monkeypatch.setattr(compiler, "load_locked", load)
    with pytest.raises(compiler.PromotionError):
        compiler.validate_authority()


def test_nonancestor_checkout_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = subprocess.run

    def run(args, *positional, **kwargs):
        if (
            args[:2] == ["git", "merge-base"]
            and args[-2:] == [compiler.UPSTREAM_COMMIT, compiler.RECEIPT_HEAD]
            and "--is-ancestor" not in args
        ):
            return subprocess.CompletedProcess(
                args, 0, stdout="0" * 40 + "\n", stderr=""
            )
        return original(args, *positional, **kwargs)

    monkeypatch.setattr(compiler.subprocess, "run", run)
    with pytest.raises(compiler.PromotionError, match="not based"):
        compiler.validate_authority()


def test_safe_canonical_paths_reject_target_and_parent_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    real = real_parent / "value.json"
    real.write_text("{}\n")
    target_link = tmp_path / "target.json"
    target_link.symlink_to(real)
    with pytest.raises(compiler.PromotionError, match="target is unsafe"):
        compiler.safe_canonical_bytes(target_link)
    parent_link = tmp_path / "linked"
    parent_link.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(compiler.PromotionError, match="parent is unsafe"):
        compiler.safe_canonical_bytes(parent_link / "value.json")


def test_canonical_state_classification_and_atomic_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    names = tuple(compiler.CANONICAL_PATHS)
    paths = {name: tmp_path / f"{name}.json" for name in names}
    monkeypatch.setattr(compiler, "CANONICAL_PATHS", paths)
    old_payloads = {name: f"old-{name}\n".encode() for name in names}
    new_payloads = {name: f"new-{name}\n".encode() for name in names}
    for name in ("ledger_289", "oracle_289", "manifest_289", "selector"):
        paths[name].write_bytes(old_payloads[name])
    monkeypatch.setattr(
        compiler,
        "CURRENT_LEDGER",
        ("ledger", compiler.sha256(old_payloads["ledger_289"])),
    )
    monkeypatch.setattr(
        compiler,
        "CURRENT_ORACLES",
        ("oracle", compiler.sha256(old_payloads["oracle_289"])),
    )
    monkeypatch.setattr(
        compiler,
        "CURRENT_MANIFEST",
        ("manifest", compiler.sha256(old_payloads["manifest_289"])),
    )
    monkeypatch.setattr(
        compiler,
        "CURRENT_SELECTOR",
        ("selector", compiler.sha256(old_payloads["selector"])),
    )
    assert compiler.canonical_state(new_payloads, allow_repair=False) == "pre_promotion"
    compiler.atomic_install(paths["ledger_289"], new_payloads["ledger_289"])
    assert paths["ledger_289"].read_bytes() == new_payloads["ledger_289"]
    assert (
        compiler.canonical_state(new_payloads, allow_repair=True)
        == "repairable_partial_promotion"
    )
    with pytest.raises(compiler.PromotionError, match="mixed"):
        compiler.canonical_state(new_payloads, allow_repair=False)
    for name, path in paths.items():
        compiler.atomic_install(path, new_payloads[name])
    assert (
        compiler.canonical_state(new_payloads, allow_repair=False) == "post_promotion"
    )
    paths["selector"].write_bytes(b"unrecognized\n")
    with pytest.raises(compiler.PromotionError, match="unrecognized"):
        compiler.canonical_state(new_payloads, allow_repair=True)


def test_outer_lock_symlink_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = compiler.repo_file

    def reject(relative_path: str):
        if relative_path == compiler.OUTER_LOCK[0]:
            raise compiler.PromotionError("repository input contains symlink")
        return original(relative_path)

    monkeypatch.setattr(compiler, "repo_file", reject)
    with pytest.raises(compiler.PromotionError, match="symlink"):
        compiler.validate_authority()
