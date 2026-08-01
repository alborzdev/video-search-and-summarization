from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cgroup_remediate", HERE / "remediate.py")
assert SPEC and SPEC.loader
remediate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = remediate
SPEC.loader.exec_module(remediate)
SCHEMA = json.loads((HERE / "evidence.schema.json").read_text())


def cid(character: str) -> str:
    return character * 64


def container(
    character: str,
    *,
    running: bool,
    policy: str = "no",
    auto_remove: bool = False,
    paused: bool = False,
    restarting: bool = False,
    health: str | None = None,
    started_at: str = "2026-01-01T00:00:00Z",
) -> remediate.ContainerState:
    return remediate.ContainerState(
        id=cid(character),
        name=f"container-{character}",
        status="running" if running else "exited",
        running=running,
        paused=paused,
        restarting=restarting,
        dead=False,
        restart_policy=policy,
        auto_remove=auto_remove,
        started_at=started_at,
        health=health,
    )


def snapshot(
    *,
    driver: str = "systemd",
    containers: tuple[remediate.ContainerState, ...] | None = None,
    config: bytes = b'{"runtimes":{"nvidia":{"path":"nvidia-container-runtime","args":[]}}}\n',
    live_restore: bool = False,
    swarm: str = "inactive",
    rootless: bool = False,
    drop_ins: str = "",
    exec_start: str = "/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock",
) -> remediate.HostSnapshot:
    if containers is None:
        containers = (
            container("a", running=True, policy="unless-stopped", health="healthy"),
            container("b", running=True, started_at="2026-01-01T00:00:01Z"),
            container("c", running=False),
        )
    return remediate.HostSnapshot(
        driver=driver,
        live_restore=live_restore,
        swarm=swarm,
        rootless=rootless,
        unit_exec_start=exec_start,
        unit_drop_ins=drop_ins,
        config=remediate.FileState(True, config, 0o640, 0, 44, (("user.test", b"x"),)),
        containers=containers,
    )


class FakeRuntime:
    def __init__(self, before: remediate.HostSnapshot | None = None) -> None:
        self.before = before or snapshot()
        parsed = remediate.parse_daemon_config(
            self.before.config.content, exists=self.before.config.exists
        )
        candidate_config, candidate = remediate.merge_cgroupfs(parsed)
        self.inspection = remediate.Inspection(
            self.before,
            candidate,
            candidate_config,
            True,
            tuple(remediate.admission_blockers(self.before)),
            False,
        )
        self.current = self.before
        self.events: list[tuple[str, str]] = []
        self.active: (
            tuple[remediate.Transaction, remediate.HostSnapshot, str] | None
        ) = None
        self.fail_install = False
        self.restart_failures: list[str] = []
        self.force_driver: str | None = None
        self.add_unknown_after_restart = False
        self.signal_during_install: int | None = None
        self.signal_during_restore: int | None = None
        self.fail_restore = False

    @contextlib.contextmanager
    def lock(self):
        self.events.append(("lock", "acquired"))
        yield

    def inspect(self):
        self.events.append(("inspect", "host"))
        return replace(self.inspection, active_recovery=self.active is not None)

    def prepare(self, inspection):
        transaction = remediate.Transaction("1" * 32)
        self.active = (transaction, inspection.snapshot, "initializing")
        self.events.append(("prepare", transaction.id))
        return transaction

    def phase(self, transaction, phase):
        assert self.active
        self.active = (transaction, self.active[1], phase)
        self.events.append(("phase", phase))

    def install_candidate(self, transaction, inspection):
        self.events.append(("install", transaction.id))
        if self.fail_install:
            raise remediate.RemediationError("install_failed")
        self.current = replace(
            self.current,
            config=replace(self.current.config, content=inspection.candidate),
        )
        if self.signal_during_install is not None:
            os.kill(os.getpid(), self.signal_during_install)

    def restart_docker(self, expected_driver):
        self.events.append(("restart", expected_driver))
        if self.restart_failures:
            raise remediate.RemediationError(self.restart_failures.pop(0))
        restarted = []
        for item in self.current.containers:
            should_run = item.running and item.restart_policy == "unless-stopped"
            restarted.append(
                replace(
                    item,
                    running=should_run,
                    status="running" if should_run else "exited",
                    health="healthy" if should_run and item.health else None,
                )
            )
        if self.add_unknown_after_restart:
            restarted.append(container("d", running=True))
        self.current = replace(
            self.current,
            driver=self.force_driver or expected_driver,
            containers=tuple(restarted),
        )

    def snapshot(self):
        return self.current

    def start_container(self, container_id):
        self.events.append(("start", container_id))
        items = []
        found = False
        for item in self.current.containers:
            if item.id == container_id:
                found = True
                items.append(
                    replace(
                        item,
                        running=True,
                        status="running",
                        health="healthy"
                        if item.id in self.before.healthy_ids
                        else item.health,
                    )
                )
            else:
                items.append(item)
        if not found:
            raise remediate.RemediationError("container_missing")
        self.current = replace(self.current, containers=tuple(items))

    def wait_healthy(self, container_ids):
        self.events.append(("healthy", str(len(container_ids))))

    def restore_original(self, transaction):
        self.events.append(("restore", transaction.id))
        if self.fail_restore:
            raise remediate.RemediationError("restore_failed")
        self.current = replace(self.current, config=self.before.config)
        if self.signal_during_restore is not None:
            os.kill(os.getpid(), self.signal_during_restore)

    def complete(self, transaction, evidence):
        self.events.append(("complete", evidence["status"]))
        self.active = None

    def active_transaction(self):
        return self.active


def validate_schema(value: dict) -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(value)


def test_plan_is_inert_and_schema_valid() -> None:
    value = remediate.plan()
    assert value["status"] == "planned"
    assert value["writes_or_lifecycle_actions"] is False
    validate_schema(value)


def test_main_plan_never_touches_injected_runtime(capsys) -> None:
    class ForbiddenRuntime:
        def __getattribute__(self, name):
            raise AssertionError("plan must not touch runtime")

    assert remediate.main([], runtime=ForbiddenRuntime(), effective_uid=1000) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"


@pytest.mark.parametrize(
    "argv,failure",
    [
        (["execute"], "exact_acknowledgement_required"),
        (["execute", "--ack", "yes"], "exact_acknowledgement_required"),
        (["recover"], "exact_recovery_acknowledgement_required"),
        (
            ["plan", "--ack", remediate.ACKNOWLEDGEMENT],
            "acknowledgement_without_mutating_mode",
        ),
    ],
)
def test_bad_ack_is_rejected_before_runtime(argv, failure, capsys) -> None:
    class ForbiddenRuntime:
        def __getattribute__(self, name):
            raise AssertionError("runtime must not be touched")

    assert remediate.main(argv, runtime=ForbiddenRuntime(), effective_uid=0) == 1
    assert json.loads(capsys.readouterr().out)["failure"] == failure


def test_execute_requires_euid_zero_before_runtime(capsys) -> None:
    class ForbiddenRuntime:
        def __getattribute__(self, name):
            raise AssertionError("runtime must not be touched")

    assert (
        remediate.main(
            ["execute", "--ack", remediate.ACKNOWLEDGEMENT],
            runtime=ForbiddenRuntime(),
            effective_uid=1000,
        )
        == 1
    )
    assert (
        json.loads(capsys.readouterr().out)["failure"] == "effective_uid_zero_required"
    )


def test_merge_preserves_every_other_value() -> None:
    before = {
        "runtimes": {"nvidia": {"path": "nvidia-container-runtime", "args": []}},
        "features": {"containerd-snapshotter": False},
        "exec-opts": ["native.cgroupdriver=systemd", "native.umask=0022"],
    }
    after, encoded = remediate.merge_cgroupfs(before)
    assert after["runtimes"] == before["runtimes"]
    assert after["features"] == before["features"]
    assert after["exec-opts"] == ["native.umask=0022", "native.cgroupdriver=cgroupfs"]
    assert remediate.parse_daemon_config(encoded) == after
    assert before["exec-opts"][0] == "native.cgroupdriver=systemd"


@pytest.mark.parametrize(
    "content,code",
    [
        (b'{"x":1,"x":2}', "daemon_json_duplicate_key"),
        (b"[]", "daemon_json_not_object"),
        (b"{", "daemon_json_invalid"),
    ],
)
def test_strict_daemon_parser_rejects_ambiguous_input(content, code) -> None:
    with pytest.raises(remediate.RemediationError, match=code):
        remediate.parse_daemon_config(content)


@pytest.mark.parametrize(
    "value,code",
    [
        ({"exec-opts": "bad"}, "daemon_exec_opts_not_string_array"),
        ({"exec-opts": [1]}, "daemon_exec_opts_not_string_array"),
        (
            {
                "exec-opts": [
                    "native.cgroupdriver=systemd",
                    "native.cgroupdriver=cgroupfs",
                ]
            },
            "daemon_multiple_cgroup_driver_options",
        ),
        (
            {"exec-opts": ["native.cgroupdriver"]},
            "daemon_malformed_cgroup_driver_option",
        ),
    ],
)
def test_merge_rejects_unsafe_exec_opts(value, code) -> None:
    with pytest.raises(remediate.RemediationError, match=code):
        remediate.merge_cgroupfs(value)


@pytest.mark.parametrize(
    "changed,code",
    [
        ({"live_restore": True}, "docker_live_restore_must_be_disabled"),
        ({"swarm": "active"}, "docker_swarm_must_be_inactive"),
        ({"rootless": True}, "rootless_docker_not_supported"),
        (
            {"drop_ins": "/etc/systemd/system/docker.service.d/x.conf"},
            "docker_unit_drop_ins_require_review",
        ),
        (
            {"exec_start": "/usr/bin/dockerd --exec-opt native.cgroupdriver=systemd"},
            "docker_unit_conflicting_daemon_option",
        ),
    ],
)
def test_admission_is_fail_closed(changed, code) -> None:
    assert code in remediate.admission_blockers(snapshot(**changed))


def test_admission_rejects_unrestorable_container_states() -> None:
    cases = [
        (
            container("a", running=True, auto_remove=True),
            "running_container_state_not_restorable",
        ),
        (
            container("a", running=True, paused=True),
            "running_container_state_not_restorable",
        ),
        (
            container("a", running=True, restarting=True),
            "running_container_state_not_restorable",
        ),
        (
            container("a", running=False, policy="always"),
            "nonrunning_container_may_autostart",
        ),
    ]
    for item, code in cases:
        assert code in remediate.admission_blockers(snapshot(containers=(item,)))


def test_inspect_reports_hashes_not_config_values() -> None:
    value = remediate.inspection_evidence(FakeRuntime().inspection)
    serialized = json.dumps(value)
    assert value["status"] == "ready"
    assert "nvidia-container-runtime" not in serialized
    assert value["containers"]["running_before_count"] == 2
    validate_schema(value)
    remediate.validate_evidence(value)


def test_system_runtime_container_inventory_accepts_missing_healthcheck() -> None:
    class StubRuntime(remediate.SystemRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, ...]] = []

        def _docker_text(self, *args: str) -> str:
            self.calls.append(args)
            if args[:4] == ("container", "ls", "-aq", "--no-trunc"):
                return cid("a")
            assert args[:3] == ("container", "inspect", "--format")
            assert ".State.Health" not in args[3]
            assert "{{json .HostConfig}}" not in args[3]
            return " ".join(
                json.dumps(value)
                for value in (
                    cid("a"),
                    "/no-healthcheck",
                    {
                        "Status": "running",
                        "Running": True,
                        "Paused": False,
                        "Restarting": False,
                        "Dead": False,
                        "StartedAt": "2026-01-01T00:00:00Z",
                    },
                    "unless-stopped",
                    False,
                )
            )

    runtime = StubRuntime()
    inventory = runtime._containers()
    assert len(inventory) == 1
    assert inventory[0].name == "no-healthcheck"
    assert inventory[0].health is None


def test_system_runtime_accepts_dockerd_success_message_on_stderr() -> None:
    class StderrValidationRuntime(remediate.SystemRuntime):
        def snapshot(self) -> remediate.HostSnapshot:
            return snapshot()

        def _run(self, argv, **kwargs):
            assert argv == (
                remediate.DOCKERD,
                "--validate",
                "--config-file=/dev/stdin",
            )
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=b"",
                stderr=b"configuration OK\n",
            )

    inspection = StderrValidationRuntime().inspect()
    assert inspection.candidate_validated is True
    assert "dockerd_candidate_validation_failed" not in inspection.blockers


def test_unvalidated_candidate_is_never_ready_or_executed() -> None:
    runtime = FakeRuntime()
    runtime.inspection = replace(runtime.inspection, candidate_validated=False)
    inspected = remediate.inspection_evidence(runtime.inspection)
    assert inspected["status"] == "blocked"
    assert "dockerd_candidate_validation_failed" in inspected["blockers"]
    executed = remediate.execute_transaction(runtime)
    assert executed["failure"] == "dockerd_candidate_validation_failed"
    assert not any(kind == "prepare" for kind, _ in runtime.events)


def test_success_restarts_and_starts_only_snapshot_target() -> None:
    runtime = FakeRuntime()
    value = remediate.execute_transaction(runtime)
    assert value["status"] == "passed"
    assert value["docker"]["driver_after"] == "cgroupfs"
    assert value["containers"]["exact_set_restored"] is True
    assert [(kind, target) for kind, target in runtime.events if kind == "start"] == [
        ("start", cid("b"))
    ]
    assert (
        value["containers"]["running_before_sha256"]
        == value["containers"]["running_after_sha256"]
    )
    assert (
        value["daemon_config"]["file_state_candidate"]
        == value["daemon_config"]["file_state_after"]
    )
    assert value["daemon_config"]["file_state_before"]["mode"] == 0o640
    assert value["daemon_config"]["file_state_before"]["gid"] == 44
    assert value["daemon_config"]["full_file_state_match"] is True
    assert runtime.active is None
    candidate_phase = runtime.events.index(("phase", "candidate_installing"))
    install = runtime.events.index(("install", "1" * 32))
    installed_phase = runtime.events.index(("phase", "candidate_installed"))
    assert candidate_phase < install < installed_phase
    validate_schema(value)


def test_restart_failure_rolls_back_config_and_exact_set() -> None:
    runtime = FakeRuntime()
    runtime.restart_failures = ["restart_failed"]
    value = remediate.execute_transaction(runtime)
    assert value["status"] == "failed"
    assert value["failure"] == "restart_failed"
    assert value["rollback"] == {
        "attempted": True,
        "config_restored": True,
        "exact_set_restored": True,
        "failures": [],
    }
    assert runtime.current.config == runtime.before.config
    assert runtime.current.running_ids == runtime.before.running_ids
    assert ("restart", "systemd") in runtime.events
    validate_schema(value)


def test_atomic_install_error_is_conservatively_rolled_back() -> None:
    runtime = FakeRuntime()
    runtime.fail_install = True
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "install_failed"
    assert value["rollback"]["attempted"] is True
    assert runtime.current.config == runtime.before.config
    assert runtime.active is None


def test_post_restart_wrong_driver_rolls_back() -> None:
    runtime = FakeRuntime()
    runtime.force_driver = "systemd"
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "post_restart_driver_not_cgroupfs"
    assert value["rollback"]["attempted"] is True
    assert runtime.current.config == runtime.before.config


def test_candidate_metadata_drift_is_not_a_digest_only_pass() -> None:
    class MetadataDriftRuntime(FakeRuntime):
        def restart_docker(self, expected_driver):
            super().restart_docker(expected_driver)
            if expected_driver == "cgroupfs":
                self.current = replace(
                    self.current,
                    config=replace(
                        self.current.config, mode=self.current.config.mode ^ 0o020
                    ),
                )

    runtime = MetadataDriftRuntime()
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "post_restart_daemon_file_state_drift"
    assert value["rollback"]["attempted"] is True
    assert runtime.current.config == runtime.before.config


def test_unknown_container_is_never_stopped_and_forces_rollback_failure() -> None:
    runtime = FakeRuntime()
    runtime.add_unknown_after_restart = True
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "container_inventory_drift"
    assert not any(kind == "stop" for kind, _ in runtime.events)
    assert "rollback_container_set_restore_failed" in value["rollback"]["failures"]


def test_signal_after_install_enters_rollback_before_unmasking() -> None:
    runtime = FakeRuntime()
    runtime.signal_during_install = signal.SIGTERM
    prior_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == f"interrupted_by_signal_{signal.SIGTERM}"
    assert value["rollback"]["config_restored"] is True
    assert runtime.current.config == runtime.before.config
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == prior_mask


def test_signal_during_rollback_cannot_interrupt_restoration() -> None:
    runtime = FakeRuntime()
    runtime.restart_failures = ["restart_failed"]
    runtime.signal_during_restore = signal.SIGINT
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "restart_failed"
    assert value["rollback"]["exact_set_restored"] is True
    assert runtime.current.config == runtime.before.config


def test_incomplete_rollback_keeps_active_recovery_journal() -> None:
    runtime = FakeRuntime()
    runtime.restart_failures = ["restart_failed"]
    runtime.fail_restore = True
    value = remediate.execute_transaction(runtime)
    assert value["rollback"]["failures"] == ["rollback_config_restore_failed"]
    assert runtime.active is not None
    assert runtime.active[2] == "rollback_incomplete"


def test_blocked_host_never_prepares_transaction() -> None:
    runtime = FakeRuntime(snapshot(live_restore=True))
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "host_admission_blocked"
    assert not any(kind == "prepare" for kind, _ in runtime.events)
    assert value["writes_or_lifecycle_actions"] is False


def test_precommit_container_drift_aborts_before_daemon_install() -> None:
    class DriftRuntime(FakeRuntime):
        def snapshot(self):
            if not any(kind == "install" for kind, _ in self.events):
                changed = tuple(
                    replace(item, health="unhealthy") if item.health else item
                    for item in self.current.containers
                )
                return replace(self.current, containers=changed)
            return self.current

    runtime = DriftRuntime()
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "host_state_changed_before_install"
    assert not any(kind == "install" for kind, _ in runtime.events)
    assert runtime.current.config == runtime.before.config
    assert runtime.active is None


def test_active_recovery_blocks_new_execute() -> None:
    runtime = FakeRuntime()
    transaction = remediate.Transaction("2" * 32)
    runtime.active = (transaction, runtime.before, "candidate_installed")
    value = remediate.execute_transaction(runtime)
    assert value["failure"] == "active_recovery_required"
    assert not any(kind == "install" for kind, _ in runtime.events)


def test_recover_candidate_installed_restores_original() -> None:
    runtime = FakeRuntime()
    transaction = remediate.Transaction("3" * 32)
    runtime.active = (transaction, runtime.before, "candidate_installed")
    runtime.current = replace(
        runtime.before,
        driver="cgroupfs",
        config=replace(runtime.before.config, content=runtime.inspection.candidate),
    )
    value = remediate.recover_transaction(runtime)
    assert value["status"] == "passed"
    assert value["rollback"]["config_restored"] is True
    assert runtime.current.config == runtime.before.config
    assert runtime.active is None


def test_recover_candidate_installing_conservatively_rolls_back() -> None:
    runtime = FakeRuntime()
    transaction = remediate.Transaction("5" * 32)
    runtime.active = (transaction, runtime.before, "candidate_installing")
    runtime.current = replace(
        runtime.before,
        driver="cgroupfs",
        config=replace(runtime.before.config, content=runtime.inspection.candidate),
    )
    value = remediate.recover_transaction(runtime)
    assert value["status"] == "passed"
    assert value["rollback"]["attempted"] is True
    assert runtime.current == runtime.before
    assert runtime.active is None


def test_recovery_rechecks_actual_final_snapshot_before_complete() -> None:
    class FinalDriftRuntime(FakeRuntime):
        def __init__(self):
            super().__init__()
            self.snapshot_calls = 0

        def snapshot(self):
            self.snapshot_calls += 1
            current = super().snapshot()
            if self.snapshot_calls >= 3:
                return replace(
                    current,
                    config=replace(current.config, gid=current.config.gid + 1),
                )
            return current

    runtime = FinalDriftRuntime()
    transaction = remediate.Transaction("6" * 32)
    runtime.active = (transaction, runtime.before, "candidate_installed")
    runtime.current = replace(
        runtime.before,
        driver="cgroupfs",
        config=replace(runtime.before.config, content=runtime.inspection.candidate),
    )
    value = remediate.recover_transaction(runtime)
    assert value["status"] == "failed"
    assert value["failure"] == "recovery_incomplete"
    assert "recovery_final_daemon_file_state_mismatch" in value["rollback"]["failures"]
    assert runtime.active is not None


def test_recover_preinstall_journal_closes_without_mutation() -> None:
    runtime = FakeRuntime()
    transaction = remediate.Transaction("4" * 32)
    runtime.active = (transaction, runtime.before, "prepared")
    value = remediate.recover_transaction(runtime)
    assert value["status"] == "passed"
    assert not any(
        kind in {"restore", "restart", "start"} for kind, _ in runtime.events
    )
    assert runtime.active is None


def test_recover_without_active_journal_is_ready_not_passed() -> None:
    value = remediate.recover_transaction(FakeRuntime())
    assert value["status"] == "ready"
    assert value["transaction_id"] is None
    assert value["writes_or_lifecycle_actions"] is False
    remediate.validate_evidence(value)


def test_fabricated_pass_is_rejected_semantically() -> None:
    value = remediate.execute_transaction(FakeRuntime())
    value["containers"]["running_after_sha256"] = "0" * 64
    with pytest.raises(
        remediate.RemediationError, match="evidence_container_identity_digest_invalid"
    ):
        remediate.validate_evidence(value)


def test_schema_rejects_fabricated_pass_with_extra_field() -> None:
    value = remediate.execute_transaction(FakeRuntime())
    value["surprise"] = True
    with pytest.raises(jsonschema.ValidationError):
        validate_schema(value)
    with pytest.raises(
        remediate.RemediationError, match="evidence_schema_validation_failed"
    ):
        remediate.validate_evidence(value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(mode="inspect"),
        lambda value: value.update(writes_or_lifecycle_actions=False),
        lambda value: value.update(acknowledgement=remediate.RECOVERY_ACKNOWLEDGEMENT),
        lambda value: value.update(lifecycle=["x"] * 5),
        lambda value: value["daemon_config"].update(full_file_state_match=False),
        lambda value: value["daemon_config"]["file_state_after"].update(mode=0o777),
    ],
)
def test_validate_evidence_rejects_cross_mode_or_unbound_passes(mutate) -> None:
    value = remediate.execute_transaction(FakeRuntime())
    mutate(value)
    with pytest.raises(remediate.RemediationError):
        remediate.validate_evidence(value)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_daemon_parser_rejects_nonfinite_json_constants(constant) -> None:
    with pytest.raises(remediate.RemediationError, match="json_nonfinite_number"):
        remediate.parse_daemon_config(f'{{"value":{constant}}}'.encode())


def test_merge_rejects_programmatic_nonfinite_values() -> None:
    with pytest.raises(
        remediate.RemediationError,
        match="daemon_json_nonfinite_or_unserializable",
    ):
        remediate.merge_cgroupfs({"value": float("nan")})


def test_durable_directory_creation_fsyncs_each_new_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fsyncs: list[Path] = []
    monkeypatch.setattr(
        remediate.SystemRuntime,
        "_fsync_dir",
        staticmethod(lambda path: fsyncs.append(Path(path))),
    )
    target = tmp_path / "journal" / "transactions" / "tx"
    remediate.SystemRuntime._mkdir_durable(target, 0o700)
    assert fsyncs == [
        tmp_path,
        tmp_path / "journal",
        tmp_path / "journal",
        tmp_path / "journal" / "transactions",
        tmp_path / "journal" / "transactions",
        target,
    ]
