from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest

HERE = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "runtime_approval_bundle_test", HERE / "compiler.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def contract() -> dict:
    return json.loads((HERE / "contract.json").read_text())


def test_default_compiles_only_inert_unapproved_plan(capsys):
    assert MODULE.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "inert_nonexecuting_approval_plan"
    assert result["bundle_count"] == 13
    assert result["approval_count"] == 0
    assert result["default_policy"] == {
        "host_inspection": False,
        "subprocess": False,
        "network": False,
        "docker": False,
        "writes": False,
        "downloads": False,
        "credentials": False,
        "lifecycle": False,
        "destructive": False,
        "approvals_granted": False,
        "warehouse_sample_bundle": "excluded",
    }


def test_exact_bundle_denominator_unique_noninheriting_placeholders():
    result = MODULE.compile_plan()
    bundles = result["ordered_bundles"]
    assert [item["id"] for item in bundles] == MODULE.EXPECTED_BUNDLE_IDS
    placeholders = [item["approval_placeholder"] for item in bundles]
    assert len(placeholders) == len(set(placeholders)) == 13
    assert all(value.startswith("<APPROVE_ONLY_") for value in placeholders)
    policy = result["approval_policy"]
    assert policy["approval_inheritance"] is False
    assert policy["dependency_completion_is_not_approval"] is True
    assert policy["placeholder_is_not_approval"] is True
    assert policy["compiler_can_grant_approval"] is False


def test_precedence_is_exact_acyclic_and_dependencies_precede_dependents():
    bundles = MODULE.compile_plan()["ordered_bundles"]
    positions = {item["id"]: index for index, item in enumerate(bundles)}
    assert {
        item["id"]: item["depends_on"] for item in bundles
    } == MODULE.EXPECTED_DEPENDENCIES
    for bundle in bundles:
        assert all(
            positions[item] < positions[bundle["id"]] for item in bundle["depends_on"]
        )


def test_download_review_preserves_exact_unknown_and_disk_boundaries():
    review = MODULE.compile_plan()["download_review"]
    exact = [
        item for item in review["artifacts"] if item["size_state"] == "exact_known"
    ]
    unknown = [item for item in review["artifacts"] if item["size_state"] == "unknown"]
    documented = [
        item
        for item in review["artifacts"]
        if item["size_state"] == "documented_floor_only"
    ]
    assert sum(item["exact_remote_bytes"] for item in exact) == 19_871_036_871
    assert (
        sum(item["planning_floor_bytes"] or 0 for item in review["artifacts"])
        == 49_871_036_871
    )
    assert len(unknown) == 6 and len(documented) == 1
    assert review["all_missing_download_bytes_known"] is False
    assert review["all_installed_or_unpacked_bytes_known"] is False
    assert review["disk_review_required_after_exact_missing_set_is_known"] is True


def test_stable_audio_package_is_raw_locked_and_split_by_authorization():
    result = MODULE.compile_plan()
    boundary = result["audio_dependency_boundary"]
    assert boundary["active_audio_package_relied_on"] is True
    assert "tiny-audio-fixture" in boundary["stable_fixture_path"]
    assert "wave7" in boundary["wave7_identity_path"]
    assert {
        item["path"]
        for item in result["source_checks"]
        if "audio-entry-oracles" in item["path"]
    } == {
        "deploy/docker/thor-local/qualification/audio-entry-oracles/contract.json",
        "deploy/docker/thor-local/qualification/audio-entry-oracles/oracle.py",
    }
    audio_ids = {
        item["id"]
        for item in result["ordered_bundles"]
        if item["id"].startswith("audio-")
    }
    assert audio_ids == {"audio-native-runtime", "audio-asr-transcript-runtime"}


def test_search_100_and_audio_lanes_have_separate_noninheriting_scopes():
    bundles = {item["id"]: item for item in MODULE.compile_plan()["ordered_bundles"]}
    progressive = bundles["search-scale-progressive-2-4-8-16"]
    hundred = bundles["search-scale-100"]
    assert progressive["approval_placeholder"] != hundred["approval_placeholder"]
    assert "search-scale-progressive-2-4-8-16" in hundred["depends_on"]
    native = bundles["audio-native-runtime"]
    asr = bundles["audio-asr-transcript-runtime"]
    assert native["approval_placeholder"] != asr["approval_placeholder"]
    assert any("distinct from ASR" in item for item in native["required_inputs"])
    assert any("distinct from native Omni" in item for item in asr["required_inputs"])


def test_strict_schemas_and_raw_package_hashes():
    instances = {
        "contract.schema.json": contract(),
        "plan.schema.json": MODULE.compile_plan(),
    }
    for filename, instance in instances.items():
        schema = json.loads((HERE / filename).read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(instance)
        assert (
            hashlib.sha256((HERE / filename).read_bytes()).hexdigest()
            == MODULE.EXPECTED_PACKAGE_HASHES[filename]
        )
    assert (
        hashlib.sha256((HERE / "contract.json").read_bytes()).hexdigest()
        == MODULE.EXPECTED_PACKAGE_HASHES["contract.json"]
    )


def test_all_source_locks_are_exact_and_current():
    loaded = MODULE._load_contract()
    checks = MODULE._check_sources(loaded)
    assert {item["path"] for item in checks} == MODULE.EXPECTED_SOURCE_PATHS
    assert len(checks) == 25
    assert all(item["sha256_match"] for item in checks)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c: c["bundles"].reverse(), "ordered bundle denominator"),
        (
            lambda c: c["bundles"][1].update(
                approval_placeholder=c["bundles"][0]["approval_placeholder"]
            ),
            "placeholders must be unique",
        ),
        (
            lambda c: c["bundles"][5].update(depends_on=[]),
            "dependency precedence drift",
        ),
        (
            lambda c: c["bundles"][3]["flags"].update(network=False),
            "download flags must disclose",
        ),
        (
            lambda c: c["bundles"][4]["flags"].update(lifecycle=False),
            "destructive flags must disclose",
        ),
        (
            lambda c: c["download_review"].update(known_exact_remote_bytes=1),
            "known exact download byte total",
        ),
        (
            lambda c: c["download_review"]["artifacts"][0].update(
                planning_floor_bytes=1
            ),
            "known planning-floor byte total",
        ),
        (
            lambda c: c["audio_dependency_boundary"].update(
                active_audio_package_relied_on=False
            ),
            "stable audio package must be relied on",
        ),
        (
            lambda c: c["source_locks"].__setitem__(
                slice(None),
                [
                    item
                    for item in c["source_locks"]
                    if not item["path"].endswith("audio-entry-oracles/oracle.py")
                ],
            ),
            "stable audio contract/oracle lock set",
        ),
    ],
)
def test_semantic_drift_fails_closed(mutate, message):
    value = contract()
    mutate(value)
    with pytest.raises(MODULE.BundleError, match=message):
        MODULE._validate_semantics(value)


def test_contract_schema_rejects_unknown_fields_and_actual_approvals():
    value = contract()
    value["unexpected"] = True
    with pytest.raises(MODULE.BundleError, match="schema violation"):
        MODULE._validate_schema(value, HERE / "contract.schema.json", "contract")

    plan = MODULE.compile_plan()
    plan["ordered_bundles"][0]["unexpected"] = True
    with pytest.raises(MODULE.BundleError, match="schema violation"):
        MODULE._validate_schema(plan, HERE / "plan.schema.json", "plan")
    value = contract()
    value["default_policy"]["approvals_granted"] = True
    with pytest.raises(MODULE.BundleError, match="schema violation"):
        MODULE._validate_schema(value, HERE / "contract.schema.json", "contract")


def test_duplicate_nonfinite_package_and_source_drift_fail(tmp_path, monkeypatch):
    with pytest.raises(MODULE.BundleError, match="duplicate JSON key"):
        MODULE._strict_json(b'{"schema_version":1,"schema_version":1}', "duplicate")
    with pytest.raises(MODULE.BundleError, match="non-finite"):
        MODULE._strict_json(b'{"value":NaN}', "nan")
    with monkeypatch.context() as scoped:
        scoped.setitem(MODULE.EXPECTED_PACKAGE_HASHES, "contract.json", "0" * 64)
        with pytest.raises(MODULE.BundleError, match="package identity drift"):
            MODULE.compile_plan()
    loaded = MODULE._load_contract()
    bad = tmp_path / "bad-source"
    bad.write_text("drift", encoding="utf-8")
    original = MODULE._repo_file
    with monkeypatch.context() as scoped:
        scoped.setattr(
            MODULE,
            "_repo_file",
            lambda relative: (
                bad
                if relative == loaded["source_locks"][0]["path"]
                else original(relative)
            ),
        )
        with pytest.raises(MODULE.BundleError, match="source lock mismatch"):
            MODULE._check_sources(loaded)


def test_each_bundle_discloses_inputs_blockers_cleanup_rollback_and_flags():
    for bundle in MODULE.compile_plan()["ordered_bundles"]:
        assert len(bundle["required_inputs"]) >= 2
        assert len(bundle["current_blockers"]) >= 2
        assert bundle["cleanup"]
        assert bundle["rollback"]
        assert set(bundle["flags"]) == {
            "host_inspection",
            "subprocess",
            "network",
            "docker",
            "writes",
            "downloads",
            "credentials",
            "lifecycle",
            "destructive",
        }


def test_compiler_ast_has_no_action_write_network_or_approval_facility():
    tree = ast.parse((HERE / "compiler.py").read_text())
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports.intersection(
        {
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "docker",
            "shutil",
            "tempfile",
            "os",
        }
    )
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not attributes.intersection(
        {
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
            "mkdir",
            "rmdir",
            "link",
            "symlink_to",
            "run",
            "Popen",
            "request",
            "urlopen",
        }
    )
