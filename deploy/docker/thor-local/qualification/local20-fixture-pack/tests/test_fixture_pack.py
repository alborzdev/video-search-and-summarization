from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
import pytest

LANE = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "local20_fixture_pack_test", LANE / "fixture_pack.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PACK = load_module()


def loaded_manifest() -> dict:
    return json.loads((LANE / "manifest.json").read_text(encoding="utf-8"))


def loaded_fixture(name: str) -> dict:
    return json.loads((LANE / "fixtures" / name).read_text(encoding="utf-8"))


def recipes() -> dict[str, dict]:
    return {item["recipe_id"]: item for item in loaded_manifest()["media_recipes"]}


def test_default_is_inert_and_does_not_validate_or_resolve(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        PACK, "validate_pack", lambda: pytest.fail("default validated files")
    )
    monkeypatch.setattr(
        PACK, "_resolve_ffmpeg", lambda: pytest.fail("default resolved ffmpeg")
    )
    monkeypatch.setattr(
        PACK.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("default ran a subprocess"),
    )
    assert PACK.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "acknowledgement_required": PACK.ACKNOWLEDGEMENT,
        "mode": "inert_plan",
        "runtime_evidence": False,
        "subprocesses": False,
        "writes": False,
    }


def test_static_pack_validates_without_runtime_claims() -> None:
    result = PACK.validate_pack()
    assert result["requirements"] == 9
    assert result["media_recipes"] == 4
    assert result["json_fixtures"] == 4
    assert result["runtime_evidence"] is False
    assert result["capabilities_promoted"] is False


@pytest.mark.parametrize(
    "name",
    [
        "manifest.json",
        "manifest.schema.json",
        "fixture.schema.json",
        "generation-receipt.schema.json",
    ],
)
def test_package_sources_match_raw_hash_locks(name: str) -> None:
    raw = (LANE / name).read_bytes()
    assert PACK._sha256(raw) == PACK.PINNED_SOURCE_SHA256[name]


def test_all_fixture_payloads_match_manifest_hashes() -> None:
    for entry in loaded_manifest()["json_fixtures"]:
        raw = (LANE / entry["path"]).read_bytes()
        assert len(raw) <= entry["max_bytes"]
        assert PACK._sha256(raw) == entry["raw_sha256"]


@pytest.mark.parametrize(
    "schema_name",
    ["manifest.schema.json", "fixture.schema.json", "generation-receipt.schema.json"],
)
def test_schemas_are_valid_draft_2020_12(schema_name: str) -> None:
    Draft202012Validator.check_schema(
        json.loads((LANE / schema_name).read_text(encoding="utf-8"))
    )


def test_strict_json_rejects_duplicate_keys_and_non_object() -> None:
    with pytest.raises(PACK.FixturePackError, match="duplicate JSON key"):
        PACK._strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(PACK.FixturePackError, match="root must be an object"):
        PACK._strict_json(b"[]", "array")


def test_manifest_schema_rejects_unknown_property() -> None:
    manifest = loaded_manifest()
    manifest["unexpected"] = True
    schema = json.loads((LANE / "manifest.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(PACK.FixturePackError, match="schema violation"):
        PACK._validate_schema(manifest, schema, "manifest")


def test_fixture_schema_rejects_unknown_nested_property() -> None:
    fixture = loaded_fixture("search-documents-bboxes.json")
    fixture["documents"][0]["unexpected"] = True
    schema = json.loads((LANE / "fixture.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(PACK.FixturePackError, match="schema violation"):
        PACK._validate_schema(fixture, schema, "fixture")


def test_search_semantics_reject_route_drift_unknown_reference_and_bad_bbox() -> None:
    fixture = loaded_fixture("search-documents-bboxes.json")
    fixture["route_cases"].reverse()
    with pytest.raises(PACK.FixturePackError, match="exact ordered four-route"):
        PACK._semantic_fixture(fixture, recipes())
    fixture = loaded_fixture("search-documents-bboxes.json")
    fixture["route_cases"][0]["expected_document_id"] = "doc-unknown"
    with pytest.raises(PACK.FixturePackError, match="unknown document"):
        PACK._semantic_fixture(fixture, recipes())
    fixture = loaded_fixture("search-documents-bboxes.json")
    fixture["documents"][0]["bbox_xyxy_normalized"] = [0.7, 0.2, 0.4, 0.8]
    with pytest.raises(PACK.FixturePackError, match="x1 < x2"):
        PACK._semantic_fixture(fixture, recipes())


def test_alert_and_track_semantics_reject_verdict_or_event_drift() -> None:
    fixture = loaded_fixture("alerts-incidents-tracks.json")
    fixture["alerts"][0]["expected_publish"] = False
    with pytest.raises(PACK.FixturePackError, match="publish decision"):
        PACK._semantic_fixture(fixture, recipes())
    fixture = loaded_fixture("alerts-incidents-tracks.json")
    fixture["tracks"].reverse()
    with pytest.raises(PACK.FixturePackError, match="exact ordered event"):
        PACK._semantic_fixture(fixture, recipes())


def test_hitl_semantics_reject_transition_and_persistence_drift() -> None:
    fixture = loaded_fixture("hitl-state-transcript.json")
    fixture["steps"][3]["state_before"] = "idle"
    with pytest.raises(PACK.FixturePackError, match="exact state transitions"):
        PACK._semantic_fixture(fixture, recipes())
    fixture = loaded_fixture("hitl-state-transcript.json")
    fixture["persistence"]["retained_request_ids"].reverse()
    with pytest.raises(PACK.FixturePackError, match="ordered request identities"):
        PACK._semantic_fixture(fixture, recipes())


def test_vios_semantics_reject_wrong_bframe_pair() -> None:
    fixture = loaded_fixture("vios-remediation.json")
    mutated = copy.deepcopy(recipes())
    mutated["tiny-bframe-failing-mp4-v1"]["b_frames"] = 0
    with pytest.raises(PACK.FixturePackError, match="B-frame failing/reference"):
        PACK._semantic_fixture(fixture, mutated)


@pytest.mark.parametrize(
    "ack", ["", "yes", "I_ACKNOWLEDGE_GENERATING_BOUNDED_LOCAL20_MEDIA"]
)
def test_generation_requires_exact_ack_before_validation_or_tool_resolution(
    tmp_path, monkeypatch, ack: str
) -> None:
    monkeypatch.setattr(
        PACK, "validate_pack", lambda: pytest.fail("bad ack validated pack")
    )
    monkeypatch.setattr(
        PACK, "_resolve_ffmpeg", lambda: pytest.fail("bad ack resolved tool")
    )
    output = tmp_path / "media"
    with pytest.raises(
        PACK.FixturePackError, match="exact media-generation acknowledgement"
    ):
        PACK.generate_media(str(output), ack)
    assert not output.exists()


@pytest.mark.parametrize("raw", ["relative", ".", "unsafe name"])
def test_output_directory_requires_absolute_safe_new_path(tmp_path, raw: str) -> None:
    candidate = raw if raw == "relative" else str(tmp_path / raw)
    with pytest.raises(PACK.FixturePackError):
        PACK._outside_repo_output(candidate)


def test_output_directory_rejects_repository_and_existing_or_symlink(tmp_path) -> None:
    with pytest.raises(PACK.FixturePackError, match="outside the repository"):
        PACK._outside_repo_output(str(PACK.REPO_ROOT / "local20-output"))
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(PACK.FixturePackError, match="reuse or overwrite"):
        PACK._outside_repo_output(str(existing))
    linked = tmp_path / "linked"
    linked.symlink_to(existing, target_is_directory=True)
    with pytest.raises(PACK.FixturePackError, match="reuse or overwrite"):
        PACK._outside_repo_output(str(linked))


def install_mock_generator(
    monkeypatch,
    *,
    oversized: bool = False,
    fail_at: int | None = None,
    extra: bool = False,
) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(PACK, "_resolve_ffmpeg", lambda: Path("/usr/bin/ffmpeg"))
    real_read = PACK._read_regular

    def read(path: Path, maximum: int) -> bytes:
        if path == Path("/usr/bin/ffmpeg"):
            return b"trusted-fake-ffmpeg"
        return real_read(path, maximum)

    monkeypatch.setattr(PACK, "_read_regular", read)

    def run(argv, directory_fd):
        command = list(argv)
        calls.append(command)
        if fail_at == len(calls):
            raise PACK.FixturePackError("synthetic generation failure")
        payload = b"x" * (2_000_001 if oversized else 32)
        Path(command[-1]).write_bytes(payload)
        if extra and len(calls) == 1:
            descriptor = os.open(
                "operator-owned.txt",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                os.write(descriptor, b"keep")
            finally:
                os.close(descriptor)

    monkeypatch.setattr(PACK, "_run_ffmpeg", run)
    return calls


def test_mock_generation_is_confined_bounded_and_emits_strict_receipt(
    tmp_path, monkeypatch
) -> None:
    calls = install_mock_generator(monkeypatch)
    output = tmp_path / "local20-media"
    receipt = PACK.generate_media(str(output), PACK.ACKNOWLEDGEMENT)
    assert output.is_dir()
    assert sorted(item.name for item in output.iterdir()) == sorted(
        [item["filename"] for item in loaded_manifest()["media_recipes"]]
        + [PACK.RECEIPT_NAME]
    )
    assert receipt["purpose"] == "candidate_inputs_only_non_promoting"
    assert receipt["safety"]["network_used"] is False
    assert [
        item["recipe_id"] for item in receipt["artifacts"]
    ] == PACK.EXPECTED_RECIPE_IDS
    schema = json.loads(
        (LANE / "generation-receipt.schema.json").read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(receipt)) == []
    assert len(calls) == 4
    for command in calls:
        assert command[0] == "/usr/bin/ffmpeg"
        assert "-nostdin" in command and "-n" in command
        assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
        joined = " ".join(command).lower()
        assert (
            "docker" not in joined
            and "http:" not in joined
            and "https:" not in joined
            and "rtsp:" not in joined
        )


def test_generation_failure_cleans_only_owned_expected_paths(
    tmp_path, monkeypatch
) -> None:
    install_mock_generator(monkeypatch, fail_at=2)
    output = tmp_path / "failed"
    with pytest.raises(PACK.FixturePackError, match="synthetic generation failure"):
        PACK.generate_media(str(output), PACK.ACKNOWLEDGEMENT)
    assert not output.exists()


def test_oversized_generated_file_is_rejected_and_cleaned(
    tmp_path, monkeypatch
) -> None:
    install_mock_generator(monkeypatch, oversized=True)
    output = tmp_path / "oversized"
    with pytest.raises(PACK.FixturePackError, match="outside its bound"):
        PACK.generate_media(str(output), PACK.ACKNOWLEDGEMENT)
    assert not output.exists()


def test_unexpected_collision_is_preserved_not_recursively_deleted(
    tmp_path, monkeypatch
) -> None:
    install_mock_generator(monkeypatch, extra=True)
    output = tmp_path / "collision"
    with pytest.raises(PACK.FixturePackError, match="unexpected output"):
        PACK.generate_media(str(output), PACK.ACKNOWLEDGEMENT)
    assert output.is_dir()
    assert (output / "operator-owned.txt").read_bytes() == b"keep"
    assert sorted(item.name for item in output.iterdir()) == ["operator-owned.txt"]


def test_subprocess_wrapper_uses_no_shell_fixed_env_timeout_and_pinned_fd(
    monkeypatch,
) -> None:
    observed = {}

    def run(argv, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(PACK.subprocess, "run", run)
    PACK._run_ffmpeg(["/usr/bin/ffmpeg", "-version"], 17)
    assert observed["shell"] is False
    assert observed["env"] == PACK.SAFE_ENV
    assert observed["timeout"] == 30
    assert observed["pass_fds"] == (17,)
    assert observed["start_new_session"] is True
    assert observed["stdin"] == subprocess.DEVNULL
    assert observed["stdout"] == subprocess.DEVNULL
    assert observed["stderr"] == subprocess.DEVNULL


def test_subprocess_timeout_and_failure_are_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        PACK.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("ffmpeg", 30)
        ),
    )
    with pytest.raises(PACK.FixturePackError, match="timed out"):
        PACK._run_ffmpeg(["/usr/bin/ffmpeg"], 1)
    monkeypatch.setattr(
        PACK.subprocess, "run", lambda argv, **_k: subprocess.CompletedProcess(argv, 7)
    )
    with pytest.raises(PACK.FixturePackError, match="failed with 7"):
        PACK._run_ffmpeg(["/usr/bin/ffmpeg"], 1)


def test_receipt_schema_rejects_runtime_evidence_or_unknown_fields() -> None:
    receipt = {
        "schema_version": 1,
        "pack_id": "thor-local20-fixture-pack-v1",
        "purpose": "candidate_inputs_only_non_promoting",
        "output_directory": "/tmp/fixtures",
        "tool": {"name": "ffmpeg", "path": "/usr/bin/ffmpeg", "raw_sha256": "0" * 64},
        "artifacts": [
            {
                "recipe_id": item,
                "filename": loaded_manifest()["media_recipes"][index]["filename"],
                "raw_sha256": "1" * 64,
                "size_bytes": 1,
                "max_bytes": 2_000_000,
            }
            for index, item in enumerate(PACK.EXPECTED_RECIPE_IDS)
        ],
        "safety": {
            "warehouse_data_used": False,
            "network_used": False,
            "docker_used": False,
            "downloads_used": False,
            "service_lifecycle_used": False,
            "acknowledgement": PACK.ACKNOWLEDGEMENT,
        },
        "runtime_evidence": True,
    }
    schema = json.loads(
        (LANE / "generation-receipt.schema.json").read_text(encoding="utf-8")
    )
    with pytest.raises(PACK.FixturePackError, match="schema violation"):
        PACK._validate_schema(receipt, schema, "receipt")
