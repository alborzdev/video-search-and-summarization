from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import socket
import tempfile
import time
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[4]


def load_executor() -> ModuleType:
    path = PACKAGE / "executor.py"
    spec = importlib.util.spec_from_file_location(
        "spatial_ai_runtime_executor_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


@pytest.fixture(scope="module")
def current_execution() -> dict:
    return EXECUTOR.execute(
        EXECUTOR.load_contract(),
        set(EXECUTOR.EXPECTED_CAPABILITIES),
        allow_dirty_development=True,
    )


def test_contract_schema_exact_scope_and_bounds() -> None:
    contract = EXECUTOR.load_contract()
    Draft202012Validator(
        EXECUTOR.strict_json(PACKAGE / "contract.schema.json")
    ).validate(contract)
    assert [
        row["capability_id"] for row in contract["capabilities"]
    ] == EXECUTOR.EXPECTED_CAPABILITIES
    assert contract["policy"]["external_provider_entry"].endswith(
        "07-aws-gcs-validation"
    )
    assert (
        contract["policy"]["external_provider_treatment"]
        == "excluded_external_optional_not_applicable"
    )
    assert contract["policy"]["independent_positive_runs"] == 2
    assert contract["policy"]["adjacent_negative_count_per_capability"] == 5
    assert contract["policy"]["target_case_actions_per_capability"] == 7
    assert contract["policy"]["aggregate_bounded_capability_actions"] == 49
    assert contract["policy"]["aggregate_requests"] == 49
    assert contract["policy"]["warehouse_sample_bundle"] == "excluded"
    for key in (
        "network_allowed",
        "docker_allowed",
        "service_lifecycle_allowed",
        "model_access_allowed",
        "downloads_allowed",
        "credentials_allowed",
    ):
        assert contract["policy"][key] is False


def test_inert_plan_selection_is_schema_valid_and_nonpromoting() -> None:
    contract = EXECUTOR.load_contract()
    selected = EXECUTOR._resolve_selection(["01", "04", "05"])
    result = EXECUTOR.plan(contract, selected)
    Draft202012Validator(EXECUTOR.strict_json(PACKAGE / "result.schema.json")).validate(
        result
    )
    EXECUTOR.validate_result(result, contract)
    assert result["status"] == "plan"
    assert [row["status"] for row in result["capability_results"]] == [
        "not_selected",
        "plan",
        "not_selected",
        "not_selected",
        "plan",
        "plan",
        "not_selected",
    ]
    assert result["promotion"]["aggregate_is_promotable"] is False
    assert result["confinement"]["bounded_capability_actions"] == 0


def test_static_fixture_and_source_locks_match() -> None:
    contract = EXECUTOR.load_contract()
    EXECUTOR.verify_static_locks(contract)
    for row in contract["capabilities"]:
        assert (
            EXECUTOR.sha_file(REPO_ROOT / row["fixture_manifest"]["path"])
            == row["fixture_manifest"]["sha256"]
        )
        for lock in row["source_controls"]:
            assert EXECUTOR.sha_file(REPO_ROOT / lock["path"]) == lock["sha256"]


def test_current_canonical_bindings_and_external_boundary_are_exact() -> None:
    bindings = EXECUTOR.verify_bindings(EXECUTOR.load_contract(), require_clean=False)
    assert bindings["canonical_rows_are_planning_only"] is True
    assert bindings["checkout_head"]


def test_all_capability_execution_is_local_and_independent(
    current_execution: dict,
) -> None:
    result = current_execution
    EXECUTOR.validate_result(result, EXECUTOR.load_contract())
    by_short = {
        row["capability_id"].split(".")[2][:2]: row
        for row in result["capability_results"]
    }
    assert result["status"] == "partial"
    assert {key for key, row in by_short.items() if row["status"] == "pass"} == {
        "01",
        "04",
        "05",
    }
    assert {key for key, row in by_short.items() if row["status"] == "blocked"} == {
        "00",
        "02",
        "03",
        "06",
    }
    assert result["promotion"]["individual_receipt_candidates"] == [
        EXECUTOR.SHORT_IDS["01"],
        EXECUTOR.SHORT_IDS["04"],
        EXECUTOR.SHORT_IDS["05"],
    ]
    assert result["promotion"]["receipt_is_runtime_evidence"] is False
    assert result["promotion"]["aggregate_is_promotable"] is False
    assert result["promotion"]["external_provider_entry_touched"] is False
    for key in (
        "network_calls",
        "docker_calls",
        "service_lifecycle_calls",
        "model_accesses",
        "downloads",
        "warehouse_sample_accesses",
        "product_subprocess_calls",
    ):
        assert result["confinement"][key] == 0


def test_passing_rows_have_exact_actions_requests_negatives_and_cleanup(
    current_execution: dict,
) -> None:
    passing = [
        row
        for row in current_execution["capability_results"]
        if row["status"] == "pass"
    ]
    assert passing
    for row in passing:
        assert row["independent_runs"] == 2
        assert row["bounded_capability_actions"] == row["requests"] == 7
        assert len(row["adjacent_negatives"]) == 5
        assert all(case["rejected"] is True for case in row["adjacent_negatives"])
        assert row["run_output_sha256"][0] == row["run_output_sha256"][1]
        assert row["imported_product_function_invocations"] == sum(
            row["imported_product_function_counts"].values()
        )
        assert row["cleanup"]["pre_state_captured"] == "absent"
        assert row["cleanup"]["removed"] is True
        assert row["cleanup"]["siblings_unchanged"] is True


def test_literal_imported_product_function_counts_are_exact(
    current_execution: dict,
) -> None:
    by_short = {
        row["capability_id"].split(".")[2][:2]: row
        for row in current_execution["capability_results"]
    }
    assert by_short["01"]["imported_product_function_counts"] == {
        "boxes.box3d_to_corners": 4,
        "projection.project_boxes_3d_to_2d": 4,
        "projection.project_points_3d_to_image": 1,
    }
    assert by_short["04"]["imported_product_function_counts"] == {
        "tracking.CLEAR.eval_sequence": 4,
        "tracking.Count.eval_sequence": 4,
        "tracking.HOTA.eval_sequence": 4,
        "tracking.Identity.eval_sequence": 4,
    }
    assert by_short["05"]["imported_product_function_counts"] == {
        "nvschema.convert_sparse4d_to_nvschema": 5,
        "nvschema.load_nvschema": 4,
    }


def test_blocked_rows_retain_capability_local_preflight(
    current_execution: dict,
) -> None:
    blocked = [
        row
        for row in current_execution["capability_results"]
        if row["status"] == "blocked"
    ]
    assert blocked
    for row in blocked:
        preflight = row["positive_observations"]["preflight"]
        assert preflight["ready"] is False
        assert preflight["missing_modules"] or preflight["import_failures"]
        assert row["bounded_capability_actions"] == row["requests"] == 0
        assert row["imported_product_function_invocations"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "top-injection",
        "missing-requests",
        "wrong-actions",
        "delete-negative",
        "bad-call-total",
        "claims-promotion",
    ],
)
def test_deep_result_validation_rejects_drift(
    current_execution: dict, mutation: str
) -> None:
    value = copy.deepcopy(current_execution)
    passing = next(
        row for row in value["capability_results"] if row["status"] == "pass"
    )
    if mutation == "top-injection":
        value["unexpected"] = True
    elif mutation == "missing-requests":
        del passing["requests"]
    elif mutation == "wrong-actions":
        passing["bounded_capability_actions"] = 6
    elif mutation == "delete-negative":
        passing["adjacent_negatives"].pop()
    elif mutation == "bad-call-total":
        passing["imported_product_function_invocations"] += 1
    elif mutation == "claims-promotion":
        value["promotion"]["ledger_mutation_performed"] = True
    with pytest.raises(EXECUTOR.EvidenceError):
        EXECUTOR.validate_result(value, EXECUTOR.load_contract())


@pytest.mark.parametrize(
    "mutation",
    [
        "nested-binding-injection",
        "aggregate-promotable",
        "forged-candidates",
        "runtime-binding-hash",
        "observation-injection",
        "redistributed-function-counts",
        "external-activity-count",
        "wrong-environment",
        "determinism-flag",
        "third-output-hash",
        "blocked-request-count",
        "aggregate-action-count",
        "mode-status-mismatch",
        "cleanup-claim",
        "target-action-id",
    ],
)
def test_audit_mutations_are_rejected(current_execution: dict, mutation: str) -> None:
    value = copy.deepcopy(current_execution)
    passing = next(
        row for row in value["capability_results"] if row["status"] == "pass"
    )
    blocked = next(
        row for row in value["capability_results"] if row["status"] == "blocked"
    )
    if mutation == "nested-binding-injection":
        value["bindings"]["forged"] = {"accepted": True}
    elif mutation == "aggregate-promotable":
        value["promotion"]["aggregate_is_promotable"] = True
    elif mutation == "forged-candidates":
        value["promotion"]["individual_receipt_candidates"] = [blocked["capability_id"]]
    elif mutation == "runtime-binding-hash":
        passing["runtime_evidence_binding"]["executor_sha256"] = "0" * 64
    elif mutation == "observation-injection":
        passing["positive_observations"]["forged"] = True
        forged_hash = EXECUTOR.sha_bytes(
            EXECUTOR.canonical_bytes(passing["positive_observations"])
        )
        passing["run_output_sha256"] = [forged_hash, forged_hash]
        passing["runtime_evidence_binding"]["capability_evidence_sha256"] = forged_hash
    elif mutation == "redistributed-function-counts":
        counts = passing["imported_product_function_counts"]
        first, second = list(counts)[:2]
        counts[first] += 1
        counts[second] -= 1
        passing["runtime_evidence_binding"][
            "imported_product_function_counts_sha256"
        ] = EXECUTOR.sha_bytes(EXECUTOR.canonical_bytes(counts))
    elif mutation == "external-activity-count":
        value["confinement"]["network_calls"] = 99
    elif mutation == "wrong-environment":
        value["environment"]["platform"] = "linux-x86_64"
    elif mutation == "determinism-flag":
        passing["deterministic_output"] = False
    elif mutation == "third-output-hash":
        passing["run_output_sha256"].append(passing["run_output_sha256"][0])
    elif mutation == "blocked-request-count":
        blocked["requests"] = 999
        value["confinement"]["requests"] += 999
    elif mutation == "aggregate-action-count":
        value["confinement"]["bounded_capability_actions"] += 1
    elif mutation == "mode-status-mismatch":
        value["status"] = "plan"
    elif mutation == "cleanup-claim":
        passing["cleanup"]["siblings_unchanged"] = False
    elif mutation == "target-action-id":
        passing["target_action_ids"][0] = "forged-action"
        passing["runtime_evidence_binding"]["target_action_ids_sha256"] = (
            EXECUTOR.sha_bytes(EXECUTOR.canonical_bytes(passing["target_action_ids"]))
        )
    with pytest.raises(EXECUTOR.EvidenceError):
        EXECUTOR.validate_result(value, EXECUTOR.load_contract())


def test_zero_product_call_adapter_cannot_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def zero_call_adapter(_root: Path, _fixture: dict) -> tuple[dict, list]:
        action_ids = [
            "positive-run-1",
            "positive-run-2",
            *EXECUTOR.EXPECTED_NEGATIVE_CASE_IDS["01"],
        ]
        for action_id in action_ids:
            EXECUTOR._target_action(action_id, lambda: None)
        return {}, []

    monkeypatch.setitem(EXECUTOR.ADAPTERS, "geometry_projection", zero_call_adapter)
    with pytest.raises(EXECUTOR.EvidenceError, match="product-function count drift"):
        EXECUTOR.execute(
            EXECUTOR.load_contract(),
            {EXECUTOR.SHORT_IDS["01"]},
            allow_dirty_development=True,
        )


def test_sibling_escape_is_denied_and_executor_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_parent = Path(tempfile.gettempdir())
    before = {path.name for path in temp_parent.glob("vss-spatial-ai-runtime.*")}

    def escaping_adapter(root: Path, _fixture: dict) -> tuple[dict, list]:
        EXECUTOR._target_action(
            "positive-run-1",
            lambda: (root.parent / "escaped-sibling").write_text(
                "escape", encoding="utf-8"
            ),
        )
        return {}, []

    monkeypatch.setitem(EXECUTOR.ADAPTERS, "geometry_projection", escaping_adapter)
    with pytest.raises(EXECUTOR.ConfinementError, match="escaped owned namespace"):
        EXECUTOR.execute(
            EXECUTOR.load_contract(),
            {EXECUTOR.SHORT_IDS["01"]},
            allow_dirty_development=True,
        )
    after = {path.name for path in temp_parent.glob("vss-spatial-ai-runtime.*")}
    assert after == before


def test_combined_fifo_spawn_and_socket_alias_bypass_is_denied_and_cleaned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_adapter = EXECUTOR.ADAPTERS["geometry_projection"]
    prebound_posix_spawn = EXECUTOR.os.posix_spawn
    prebound_socket_type = socket.SocketType
    escaped_paths: list[Path] = []
    denied: list[str] = []

    def attacking_adapter(root: Path, fixture: dict) -> tuple[dict, list]:
        escaped_fifo = root.parent / "escaped-sibling.fifo"
        escaped_paths.append(escaped_fifo)
        attacks = (
            lambda: EXECUTOR.os.mkfifo(escaped_fifo),
            lambda: prebound_posix_spawn(
                "/bin/true", ["true"], dict(EXECUTOR.os.environ)
            ),
            lambda: prebound_socket_type(),
        )
        for attack in attacks:
            try:
                value = attack()
            except EXECUTOR.ConfinementError as exc:
                denied.append(str(exc))
            else:
                if hasattr(value, "close"):
                    value.close()
        return original_adapter(root, fixture)

    monkeypatch.setitem(EXECUTOR.ADAPTERS, "geometry_projection", attacking_adapter)
    try:
        with pytest.raises(
            EXECUTOR.ConfinementError, match="prohibited external activity"
        ):
            EXECUTOR.execute(
                EXECUTOR.load_contract(),
                {EXECUTOR.SHORT_IDS["01"]},
                allow_dirty_development=True,
            )
    finally:
        for escaped_fifo in escaped_paths:
            if escaped_fifo.exists():
                escaped_fifo.unlink()
    assert len(denied) == 3
    assert escaped_paths and all(not path.exists() for path in escaped_paths)


def test_every_present_os_process_entrypoint_and_mknod_is_wrapped_and_restored(
    tmp_path: Path,
) -> None:
    process_originals = {
        name: getattr(EXECUTOR.os, name) for name in EXECUTOR.OS_PROCESS_ENTRYPOINTS
    }
    mknod_original = EXECUTOR.os.mknod
    counters = {key: 0 for key in EXECUTOR.EXTERNAL_ACTIVITY_KEYS}
    with EXECUTOR.external_activity_denied(counters):
        for name in EXECUTOR.OS_PROCESS_ENTRYPOINTS:
            with pytest.raises(EXECUTOR.ConfinementError, match="subprocess"):
                getattr(EXECUTOR.os, name)()
        with pytest.raises(EXECUTOR.ConfinementError, match="owned namespace"):
            EXECUTOR.os.mknod(tmp_path / "escaped-node")
    assert counters["product_subprocess_calls"] == len(EXECUTOR.OS_PROCESS_ENTRYPOINTS)
    assert counters["filesystem_escape_attempts"] == 1
    assert all(
        getattr(EXECUTOR.os, name) is function
        for name, function in process_originals.items()
    )
    assert EXECUTOR.os.mknod is mknod_original
    assert not (tmp_path / "escaped-node").exists()


def test_confinement_error_is_not_swallowed_as_a_negative() -> None:
    counters = {key: 0 for key in EXECUTOR.EXTERNAL_ACTIVITY_KEYS}
    EXECUTOR._ACTIVE_ACTION_COUNTS = {}
    try:
        with EXECUTOR.external_activity_denied(counters):
            with pytest.raises(EXECUTOR.ConfinementError, match="network access"):
                EXECUTOR._expect_exception("network-negative", socket.socketpair)
    finally:
        EXECUTOR._ACTIVE_ACTION_COUNTS = None
    assert counters["network_calls"] == 1
    assert counters["downloads"] == 1


@pytest.mark.parametrize(
    ("system", "machine", "python_version", "message"),
    [
        ("Linux", "x86_64", ("3", "12", "0"), "runtime target mismatch"),
        ("Darwin", "aarch64", ("3", "12", "0"), "runtime target mismatch"),
        ("Linux", "aarch64", ("3", "11", "9"), "runtime Python mismatch"),
    ],
)
def test_wrong_runtime_target_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    python_version: tuple[str, str, str],
    message: str,
) -> None:
    monkeypatch.setattr(EXECUTOR.platform, "system", lambda: system)
    monkeypatch.setattr(EXECUTOR.platform, "machine", lambda: machine)
    monkeypatch.setattr(
        EXECUTOR.platform, "python_version_tuple", lambda: python_version
    )
    with pytest.raises(EXECUTOR.EvidenceError, match=message):
        EXECUTOR.verify_target_environment(EXECUTOR.load_contract())


def test_selection_rejects_unknown_and_accepts_full_id() -> None:
    assert EXECUTOR._resolve_selection(["01"]) == {EXECUTOR.SHORT_IDS["01"]}
    assert EXECUTOR._resolve_selection([EXECUTOR.SHORT_IDS["05"]]) == {
        EXECUTOR.SHORT_IDS["05"]
    }
    with pytest.raises(EXECUTOR.EvidenceError, match="unknown capability"):
        EXECUTOR._resolve_selection(["07"])


def test_repo_file_rejects_symlink_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "payload.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(EXECUTOR, "REPO_ROOT", tmp_path)
    with pytest.raises(EXECUTOR.EvidenceError, match="symlink component"):
        EXECUTOR.repo_file("alias/payload.json")


def test_network_denial_restores_socket() -> None:
    original = socket.socket
    with EXECUTOR.network_denied():
        with pytest.raises(EXECUTOR.EvidenceError, match="network access"):
            socket.socket()
    assert socket.socket is original


def test_product_deadline_interrupts() -> None:
    with pytest.raises(EXECUTOR.EvidenceError, match="exceeded 0.01-second deadline"):
        with EXECUTOR.product_execution_deadline(0.01):
            time.sleep(0.1)


def test_receipt_writer_is_exclusive_and_mode_0600(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    EXECUTOR.publish_receipt_exclusive(output, "{}\n")
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(EXECUTOR.EvidenceError, match="already exists"):
        EXECUTOR.publish_receipt_exclusive(output, "{}\n")


def test_alternate_contract_is_rejected(tmp_path: Path) -> None:
    alternate = tmp_path / "contract.json"
    alternate.write_bytes((PACKAGE / "contract.json").read_bytes())
    with pytest.raises(EXECUTOR.EvidenceError, match="canonical contract"):
        EXECUTOR.require_default_contract(alternate)
