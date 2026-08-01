from __future__ import annotations

import copy
import importlib.util
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import jsonschema
import pytest


HERE = Path(__file__).resolve()
LANE_DIR = HERE.parents[1]
LIFECYCLE_PATH = LANE_DIR / "lifecycle.py"
SPEC = importlib.util.spec_from_file_location(
    "local_alternate_lifecycle", LIFECYCLE_PATH
)
assert SPEC is not None and SPEC.loader is not None
lifecycle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lifecycle
SPEC.loader.exec_module(lifecycle)


def successful_qualification() -> dict[str, Any]:
    return lifecycle.qualifier._evidence(
        "passed",
        hashlib.sha256(lifecycle.qualifier.CONTRACT_PATH.read_bytes()).hexdigest(),
        4,
        [
            {"id": probe_id, "status": "passed"}
            for probe_id in lifecycle.qualifier.PROBE_IDS
        ],
    )


class FakeRuntime:
    def __init__(self) -> None:
        self.states = {
            lifecycle.VISION_CONTAINER: lifecycle.ContainerState("running", True),
            lifecycle.EMBEDDING_CONTAINER: lifecycle.ContainerState("running", True),
            lifecycle.LLM_CONTAINER: lifecycle.ContainerState("running", True),
            lifecycle.QWEN_CONTAINER: lifecycle.ContainerState("created", False),
        }
        self.memories = [lifecycle.MINIMUM_AVAILABLE_KIB] * 8
        self.vlm_ready = [True]
        self.qualification = successful_qualification()
        self.events: list[tuple[Any, ...]] = []
        self.identity_error: lifecycle.LifecycleError | None = None
        self.stop_fail_before: set[str] = set()
        self.stop_fail_after: set[str] = set()
        self.start_fail_before: set[str] = set()
        self.start_fail_after: set[str] = set()
        self.exit_qwen_after_vlm_probe = False
        self.stop_embedding_during_qualifier = False
        self.qwen_state_during_cleanup: Any | None = None
        self.clock = 0.0
        self.vlm_request_latency = 0.0
        self.readiness_timeouts: list[float] = []
        self.state_calls: dict[str, int] = {}
        self.fail_state_call: dict[str, int] = {}

    def verify_identity(self) -> None:
        self.events.append(("verify_identity",))
        if self.identity_error is not None:
            raise self.identity_error

    def container_state(self, name: str, timeout_seconds: float = 30) -> Any:
        self.events.append(("state", name, timeout_seconds))
        self.state_calls[name] = self.state_calls.get(name, 0) + 1
        if self.fail_state_call.get(name) == self.state_calls[name]:
            raise lifecycle.LifecycleError(f"state_failed_{name}")
        return self.states[name]

    def stop_container(self, name: str) -> None:
        self.events.append(("stop", name))
        if name in self.stop_fail_before:
            raise lifecycle.LifecycleError(f"stop_failed_{name}")
        self.states[name] = lifecycle.ContainerState("exited", False)
        if name in self.stop_fail_after:
            raise lifecycle.LifecycleError(f"stop_failed_after_{name}")

    def start_container(self, name: str) -> None:
        self.events.append(("start", name))
        if name in self.start_fail_before:
            raise lifecycle.LifecycleError(f"start_failed_{name}")
        self.states[name] = lifecycle.ContainerState("running", True)
        if name in self.start_fail_after:
            raise lifecycle.LifecycleError(f"start_failed_after_{name}")

    def available_memory_kib(self) -> int:
        self.events.append(("memory",))
        if len(self.memories) > 1:
            return self.memories.pop(0)
        return self.memories[0]

    def model_is_exact(self, role: str, timeout_seconds: float) -> bool:
        self.events.append(("model", role, timeout_seconds))
        if role == "llm":
            return True
        self.readiness_timeouts.append(timeout_seconds)
        self.clock += min(self.vlm_request_latency, timeout_seconds)
        ready = self.vlm_ready.pop(0) if self.vlm_ready else False
        if self.exit_qwen_after_vlm_probe:
            self.states[lifecycle.QWEN_CONTAINER] = lifecycle.ContainerState(
                "exited", False
            )
        return ready

    def run_qualifier(self) -> dict[str, Any]:
        self.events.append(("qualifier",))
        if self.stop_embedding_during_qualifier:
            self.states[lifecycle.EMBEDDING_CONTAINER] = lifecycle.ContainerState(
                "exited", False
            )
        if self.qwen_state_during_cleanup is not None:
            self.states[lifecycle.QWEN_CONTAINER] = self.qwen_state_during_cleanup
        return self.qualification

    def sleep(self, seconds: float) -> None:
        self.events.append(("sleep", seconds))
        self.clock += seconds

    def monotonic(self) -> float:
        self.events.append(("monotonic",))
        return self.clock


def mutations(runtime: FakeRuntime) -> list[tuple[Any, ...]]:
    return [event for event in runtime.events if event[0] in {"start", "stop"}]


def run(runtime: FakeRuntime, **kwargs: int) -> dict[str, Any]:
    defaults = {
        "vision_memory_attempts": 1,
        "embedding_memory_attempts": 1,
        "readiness_attempts": 2,
        "readiness_deadline_seconds": 900,
    }
    defaults.update(kwargs)
    return lifecycle.execute_lifecycle(runtime, **defaults)


def run_sigterm_scenario(point: str) -> dict[str, Any]:
    """Exercise real signals in a child so a regression cannot kill pytest."""
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        try:
            runtime = FakeRuntime()
            if point == "after_qwen_start":
                original_start = runtime.start_container

                def start_then_signal(name: str) -> None:
                    original_start(name)
                    if name == lifecycle.QWEN_CONTAINER:
                        os.kill(os.getpid(), signal.SIGTERM)

                runtime.start_container = start_then_signal  # type: ignore[method-assign]
            elif point == "during_qwen_cleanup":
                original_stop = runtime.stop_container

                def stop_then_signal(name: str) -> None:
                    original_stop(name)
                    if name == lifecycle.QWEN_CONTAINER:
                        os.kill(os.getpid(), signal.SIGTERM)

                runtime.stop_container = stop_then_signal  # type: ignore[method-assign]
            else:
                raise AssertionError(f"unknown signal point: {point}")

            result = run(runtime)
            payload = {
                "result": result,
                "qwen_running": runtime.states[lifecycle.QWEN_CONTAINER].running,
                "vision_running": runtime.states[lifecycle.VISION_CONTAINER].running,
            }
            os.write(write_fd, json.dumps(payload).encode())
            os.close(write_fd)
            os._exit(0)
        except BaseException:
            os.close(write_fd)
            os._exit(70)

    os.close(write_fd)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(read_fd, 65_536)
        if not chunk:
            break
        chunks.append(chunk)
    os.close(read_fd)
    _pid, status = os.waitpid(child, 0)
    assert os.WIFEXITED(status), (
        f"signal scenario died from signal {os.WTERMSIG(status)}"
    )
    assert os.WEXITSTATUS(status) == 0
    return json.loads(b"".join(chunks))


def test_default_plan_is_inert_and_contains_all_bounds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class ForbiddenRuntime:
        def __init__(self) -> None:
            raise AssertionError("plan mode must not construct a runtime")

    monkeypatch.setattr(lifecycle, "DockerRuntime", ForbiddenRuntime)
    assert lifecycle.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "planned"
    assert output["writes_or_lifecycle_actions"] is False
    assert output["memory_admission_kib"] == 50 * 1024 * 1024
    assert output["readiness"]["maximum_requests"] == 90
    assert output["readiness"]["deadline_seconds"] == 900
    assert output["readiness"]["proxies_allowed"] is False
    assert output["qualifier"]["requests_attempted"] == 0


def test_cold_plan_does_not_write_qualifier_bytecode(tmp_path: Path) -> None:
    pycache_root = tmp_path / "pycache"
    result = subprocess.run(
        [sys.executable, str(LIFECYCLE_PATH)],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        env={
            "PYTHONPYCACHEPREFIX": str(pycache_root),
            "PYTHONDONTWRITEBYTECODE": "0",
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "planned"
    assert not list(pycache_root.rglob("qualify*.pyc"))


def test_plan_execution_and_gate_outputs_validate_against_strict_schema() -> None:
    schema = json.loads(
        (LANE_DIR / "lifecycle-evidence.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(lifecycle._plan())

    runtime = FakeRuntime()
    validator.validate(run(runtime))

    gate_failure = {
        "schema_version": 1,
        "lane": "non-official-local-alternate",
        "status": "failed",
        "failure": "exact_acknowledgement_required",
    }
    validator.validate(gate_failure)
    gate_failure["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(gate_failure)


def test_schema_rejects_semantically_impossible_passed_evidence() -> None:
    schema = json.loads(
        (LANE_DIR / "lifecycle-evidence.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    passed = run(FakeRuntime())
    validator.validate(passed)

    mutations = []
    for path, value in (
        (("qualification",), {}),
        (("readiness_requests",), 0),
        (("lifecycle", "qwen_start_attempted"), False),
        (("lifecycle", "qwen_stopped_before_restore"), False),
        (("lifecycle", "stop_attempted"), []),
        (("lifecycle", "stopped_by_runner"), []),
    ):
        candidate = copy.deepcopy(passed)
        target = candidate
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        mutations.append(candidate)

    for candidate in mutations:
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(candidate)


@pytest.mark.parametrize(
    ("arguments", "failure"),
    [
        (["--ack", lifecycle.ACKNOWLEDGEMENT], "acknowledgement_without_execute"),
        (["--execute", "--ack", "yes"], "exact_acknowledgement_required"),
        (["--execute"], "exact_acknowledgement_required"),
    ],
)
def test_exact_execute_ack_gate_is_before_runtime(
    arguments: list[str],
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class ForbiddenRuntime:
        def __init__(self) -> None:
            raise AssertionError("bad gate must not construct a runtime")

    monkeypatch.setattr(lifecycle, "DockerRuntime", ForbiddenRuntime)
    assert lifecycle.main(arguments) == 1
    assert json.loads(capsys.readouterr().out)["failure"] == failure


def test_success_stops_only_vision_when_that_reaches_admission() -> None:
    runtime = FakeRuntime()
    runtime.memories = [
        lifecycle.MINIMUM_AVAILABLE_KIB,
        lifecycle.MINIMUM_AVAILABLE_KIB,
    ]
    result = run(runtime)
    assert result["status"] == "passed"
    assert result["embedding_was_stopped"] is False
    assert result["readiness_requests"] == 1
    assert result["qualification"] == successful_qualification()
    assert result["lifecycle"]["qwen_stopped_before_restore"] is True
    assert mutations(runtime) == [
        ("stop", lifecycle.VISION_CONTAINER),
        ("start", lifecycle.QWEN_CONTAINER),
        ("stop", lifecycle.QWEN_CONTAINER),
        ("start", lifecycle.VISION_CONTAINER),
    ]
    assert all(
        runtime.states[name].running
        for name in (
            lifecycle.VISION_CONTAINER,
            lifecycle.EMBEDDING_CONTAINER,
            lifecycle.LLM_CONTAINER,
        )
    )
    assert not runtime.states[lifecycle.QWEN_CONTAINER].running


def test_main_execute_path_uses_injected_runtime_and_emits_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()
    previous_handlers = {
        signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    assert (
        lifecycle.main(
            ["--execute", "--ack", lifecycle.ACKNOWLEDGEMENT], runtime=runtime
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "passed"
    assert output["qualification"]["requests_attempted"] == 4
    assert not runtime.states[lifecycle.QWEN_CONTAINER].running
    assert {
        signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    } == previous_handlers
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == previous_mask


def test_embedding_is_stopped_only_when_vision_does_not_reach_50_gib() -> None:
    runtime = FakeRuntime()
    runtime.memories = [
        lifecycle.MINIMUM_AVAILABLE_KIB - 1,
        lifecycle.MINIMUM_AVAILABLE_KIB,
        lifecycle.MINIMUM_AVAILABLE_KIB,
    ]
    result = run(runtime)
    assert result["status"] == "passed"
    assert result["embedding_was_stopped"] is True
    assert result["lifecycle"]["stopped_by_runner"] == [
        lifecycle.VISION_CONTAINER,
        lifecycle.EMBEDDING_CONTAINER,
    ]
    assert mutations(runtime) == [
        ("stop", lifecycle.VISION_CONTAINER),
        ("stop", lifecycle.EMBEDDING_CONTAINER),
        ("start", lifecycle.QWEN_CONTAINER),
        ("stop", lifecycle.QWEN_CONTAINER),
        ("start", lifecycle.EMBEDDING_CONTAINER),
        ("start", lifecycle.VISION_CONTAINER),
    ]


def test_low_memory_after_both_stops_aborts_before_qwen_and_restores() -> None:
    runtime = FakeRuntime()
    runtime.memories = [lifecycle.MINIMUM_AVAILABLE_KIB - 1]
    result = run(runtime)
    assert result["status"] == "failed"
    assert result["failure"] == "memory_below_50_gib_after_authorized_stops"
    assert ("start", lifecycle.QWEN_CONTAINER) not in runtime.events
    assert mutations(runtime) == [
        ("stop", lifecycle.VISION_CONTAINER),
        ("stop", lifecycle.EMBEDDING_CONTAINER),
        ("start", lifecycle.EMBEDDING_CONTAINER),
        ("start", lifecycle.VISION_CONTAINER),
    ]


def test_memory_is_rechecked_immediately_before_qwen_start() -> None:
    runtime = FakeRuntime()
    runtime.memories = [
        lifecycle.MINIMUM_AVAILABLE_KIB,
        lifecycle.MINIMUM_AVAILABLE_KIB - 1,
    ]
    result = run(runtime)
    assert result["failure"] == "memory_below_50_gib_before_qwen_start"
    assert ("start", lifecycle.QWEN_CONTAINER) not in runtime.events
    assert runtime.states[lifecycle.VISION_CONTAINER].running


def test_readiness_is_bounded_and_timeout_always_cleans_up() -> None:
    runtime = FakeRuntime()
    runtime.vlm_ready = [False, False, False]
    result = run(runtime, readiness_attempts=2)
    assert result["failure"] == "qwen_readiness_timeout"
    assert result["readiness_requests"] == 2
    assert (
        len([event for event in runtime.events if event[:2] == ("model", "vlm")]) == 2
    )
    assert ("stop", lifecycle.QWEN_CONTAINER) in runtime.events
    assert runtime.states[lifecycle.VISION_CONTAINER].running


def test_readiness_enforces_monotonic_900_second_style_deadline() -> None:
    runtime = FakeRuntime()
    runtime.vlm_ready = [False] * 90
    runtime.vlm_request_latency = 10
    result = run(
        runtime,
        readiness_attempts=90,
        readiness_deadline_seconds=20,
    )
    assert result["failure"] == "qwen_readiness_timeout"
    assert result["readiness_requests"] == 2
    assert runtime.clock == 20
    assert runtime.readiness_timeouts == [10, 5]


def test_slow_drip_http_is_cut_off_at_absolute_deadline_without_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]

    class SlowSocket:
        closed = False

        @staticmethod
        def setblocking(_value: bool) -> None:
            pass

        @staticmethod
        def send(value: Any) -> int:
            return len(value)

        @staticmethod
        def recv(_amount: int) -> bytes:
            return b"x"

        def close(self) -> None:
            self.closed = True

    connection = SlowSocket()

    def fake_select(
        readable: list[Any],
        writable: list[Any],
        _errors: list[Any],
        timeout: float,
    ) -> tuple[list[Any], list[Any], list[Any]]:
        if writable:
            return [], writable, []
        if timeout < 2:
            clock[0] += timeout
            return [], [], []
        clock[0] += 2
        return readable, [], []

    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        lifecycle.socket, "create_connection", lambda *_args, **_kwargs: connection
    )
    monkeypatch.setattr(lifecycle.select, "select", fake_select)
    with pytest.raises(lifecycle.LifecycleError, match="readiness_request_deadline"):
        lifecycle._direct_model_response("vlm", 5)
    assert clock[0] == 5
    assert connection.closed is True


def test_readiness_request_count_survives_post_wait_state_failure() -> None:
    runtime = FakeRuntime()
    runtime.vlm_ready = [False]
    # Qwen state calls: prestate, post-start, wait, post-wait classification.
    runtime.fail_state_call[lifecycle.QWEN_CONTAINER] = 4
    result = run(runtime, readiness_attempts=1)
    assert result["failure"] == f"state_failed_{lifecycle.QWEN_CONTAINER}"
    assert result["readiness_requests"] == 1
    assert not runtime.states[lifecycle.QWEN_CONTAINER].running
    assert runtime.states[lifecycle.VISION_CONTAINER].running


def test_readiness_request_count_survives_in_loop_state_failure() -> None:
    runtime = FakeRuntime()
    runtime.vlm_ready = [False, False]
    # Qwen state calls: prestate, post-start, first wait, second wait.
    runtime.fail_state_call[lifecycle.QWEN_CONTAINER] = 4
    result = run(runtime, readiness_attempts=2)
    assert result["failure"] == f"state_failed_{lifecycle.QWEN_CONTAINER}"
    assert result["readiness_requests"] == 1
    assert not runtime.states[lifecycle.QWEN_CONTAINER].running
    assert runtime.states[lifecycle.VISION_CONTAINER].running


def test_qwen_exit_during_readiness_aborts_early_and_restores() -> None:
    runtime = FakeRuntime()
    runtime.vlm_ready = [False]
    runtime.exit_qwen_after_vlm_probe = True
    result = run(runtime, readiness_attempts=2)
    assert result["failure"] == "qwen_exited_during_readiness"
    assert result["readiness_requests"] == 1
    assert runtime.states[lifecycle.VISION_CONTAINER].running
    assert not runtime.states[lifecycle.QWEN_CONTAINER].running


def test_qwen_oom_during_readiness_is_reported_and_restored() -> None:
    runtime = FakeRuntime()

    def oom_after_probe(role: str, timeout_seconds: float) -> bool:
        runtime.events.append(("model", role, timeout_seconds))
        if role == "llm":
            return True
        runtime.states[lifecycle.QWEN_CONTAINER] = lifecycle.ContainerState(
            "exited", False, True
        )
        return False

    runtime.model_is_exact = oom_after_probe  # type: ignore[method-assign]
    result = run(runtime, readiness_attempts=2)
    assert result["failure"] == "qwen_oom_during_readiness"
    assert runtime.states[lifecycle.VISION_CONTAINER].running


def test_qwen_start_error_after_transition_is_still_cleaned_up() -> None:
    runtime = FakeRuntime()
    runtime.start_fail_after.add(lifecycle.QWEN_CONTAINER)
    result = run(runtime)
    assert result["failure"] == f"start_failed_after_{lifecycle.QWEN_CONTAINER}"
    assert ("stop", lifecycle.QWEN_CONTAINER) in runtime.events
    assert not runtime.states[lifecycle.QWEN_CONTAINER].running
    assert runtime.states[lifecycle.VISION_CONTAINER].running


@pytest.mark.parametrize(
    "qualification",
    [
        {
            "status": "failed",
            "classification": "non-official-local-alternate",
            "requests_attempted": 4,
        },
        {
            "status": "passed",
            "classification": "official-edge",
            "requests_attempted": 4,
        },
        {
            "status": "passed",
            "classification": "non-official-local-alternate",
            "requests_attempted": 3,
        },
    ],
)
def test_only_an_exact_four_request_alternate_pass_is_accepted(
    qualification: dict[str, Any],
) -> None:
    runtime = FakeRuntime()
    runtime.qualification = qualification
    result = run(runtime)
    assert result["failure"] == "qwen_qualification_failed"
    assert not runtime.states[lifecycle.QWEN_CONTAINER].running
    assert runtime.states[lifecycle.VISION_CONTAINER].running


def test_cleanup_failure_overrides_success_and_does_not_restore_under_qwen() -> None:
    runtime = FakeRuntime()
    runtime.stop_fail_before.add(lifecycle.QWEN_CONTAINER)
    result = run(runtime)
    assert result["failure"] is None
    assert result["status"] == "failed"
    assert result["cleanup_failures"] == ["cleanup_qwen_still_running"]
    assert result["lifecycle"]["qwen_stopped_before_restore"] is False
    assert runtime.states[lifecycle.QWEN_CONTAINER].running
    assert not runtime.states[lifecycle.VISION_CONTAINER].running
    assert ("start", lifecycle.VISION_CONTAINER) not in runtime.events


@pytest.mark.parametrize("status", ["paused", "restarting", "exited"])
def test_cleanup_treats_raw_running_qwen_as_active_for_every_status(
    status: str,
) -> None:
    runtime = FakeRuntime()
    runtime.qwen_state_during_cleanup = lifecycle.ContainerState(status, True)
    runtime.stop_fail_before.add(lifecycle.QWEN_CONTAINER)
    result = run(runtime)
    assert result["status"] == "failed"
    assert result["cleanup_failures"] == ["cleanup_qwen_still_running"]
    assert ("stop", lifecycle.QWEN_CONTAINER) in runtime.events
    assert ("start", lifecycle.VISION_CONTAINER) not in runtime.events
    assert not runtime.states[lifecycle.VISION_CONTAINER].running


def test_cleanup_is_idempotent_after_successful_restoration() -> None:
    runtime = FakeRuntime()
    tracker = lifecycle.LifecycleTracker(
        stopped_by_runner=[lifecycle.VISION_CONTAINER],
        stop_attempted=[lifecycle.VISION_CONTAINER],
        qwen_start_attempted=True,
    )
    runtime.states[lifecycle.VISION_CONTAINER] = lifecycle.ContainerState(
        "exited", False
    )
    runtime.states[lifecycle.QWEN_CONTAINER] = lifecycle.ContainerState("running", True)
    first = lifecycle._cleanup(runtime, tracker)
    first_mutations = list(mutations(runtime))
    second = lifecycle._cleanup(runtime, tracker)
    assert first == ([], True)
    assert second == ([], True)
    assert first_mutations == [
        ("stop", lifecycle.QWEN_CONTAINER),
        ("start", lifecycle.VISION_CONTAINER),
    ]
    assert mutations(runtime) == first_mutations


def test_sigterm_after_qwen_start_enters_cleanup_and_restores_vision() -> None:
    payload = run_sigterm_scenario("after_qwen_start")
    result = payload["result"]

    assert result["status"] == "failed"
    assert result["failure"] == f"interrupted_by_signal_{signal.SIGTERM}"
    assert result["cleanup_failures"] == []
    assert result["lifecycle"]["qwen_stopped_before_restore"] is True
    assert payload["qwen_running"] is False
    assert payload["vision_running"] is True


def test_sigterm_during_qwen_cleanup_does_not_interrupt_restoration() -> None:
    payload = run_sigterm_scenario("during_qwen_cleanup")
    result = payload["result"]

    assert result["status"] == "failed"
    assert result["failure"] == f"interrupted_by_signal_{signal.SIGTERM}"
    assert result["cleanup_failures"] == []
    assert result["lifecycle"]["qwen_stopped_before_restore"] is True
    assert payload["qwen_running"] is False
    assert payload["vision_running"] is True


def test_execute_fails_closed_before_mutation_when_another_thread_is_live() -> None:
    runtime = FakeRuntime()
    release = threading.Event()
    worker = threading.Thread(target=release.wait)
    worker.start()
    try:
        result = run(runtime)
    finally:
        release.set()
        worker.join()

    assert result["status"] == "failed"
    assert result["failure"] == "signal_safety_requires_single_thread"
    assert mutations(runtime) == []


def test_restore_failure_overrides_success() -> None:
    runtime = FakeRuntime()
    runtime.start_fail_before.add(lifecycle.VISION_CONTAINER)
    result = run(runtime)
    assert result["failure"] is None
    assert result["status"] == "failed"
    assert result["cleanup_failures"] == [
        f"cleanup_restore_failed_{lifecycle.VISION_CONTAINER}"
    ]


def test_cleanup_does_not_start_a_workload_the_runner_did_not_stop() -> None:
    runtime = FakeRuntime()
    runtime.stop_embedding_during_qualifier = True
    result = run(runtime)
    assert result["status"] == "failed"
    assert result["cleanup_failures"] == [
        f"cleanup_untargeted_workload_not_running_{lifecycle.EMBEDDING_CONTAINER}"
    ]
    assert ("stop", lifecycle.EMBEDDING_CONTAINER) not in runtime.events
    assert ("start", lifecycle.EMBEDDING_CONTAINER) not in runtime.events
    assert not runtime.states[lifecycle.EMBEDDING_CONTAINER].running


def test_external_qwen_activation_before_runner_start_blocks_restoration() -> None:
    runtime = FakeRuntime()
    memory_calls = 0

    def low_memory_with_external_qwen_start() -> int:
        nonlocal memory_calls
        memory_calls += 1
        runtime.events.append(("memory",))
        if memory_calls == 2:
            runtime.states[lifecycle.QWEN_CONTAINER] = lifecycle.ContainerState(
                "running", True
            )
        return lifecycle.MINIMUM_AVAILABLE_KIB - 1

    runtime.available_memory_kib = low_memory_with_external_qwen_start  # type: ignore[method-assign]
    result = run(runtime)
    assert result["failure"] == "memory_below_50_gib_after_authorized_stops"
    assert result["cleanup_failures"] == ["cleanup_qwen_unexpected_external_activation"]
    assert result["lifecycle"]["qwen_start_attempted"] is False
    assert result["lifecycle"]["qwen_stopped_before_restore"] is False
    assert runtime.states[lifecycle.QWEN_CONTAINER].running
    assert not runtime.states[lifecycle.VISION_CONTAINER].running
    assert not runtime.states[lifecycle.EMBEDDING_CONTAINER].running
    assert ("stop", lifecycle.QWEN_CONTAINER) not in runtime.events
    assert ("start", lifecycle.VISION_CONTAINER) not in runtime.events
    assert ("start", lifecycle.EMBEDDING_CONTAINER) not in runtime.events


def test_stop_failure_after_transition_is_tracked_and_restored() -> None:
    runtime = FakeRuntime()
    runtime.stop_fail_after.add(lifecycle.VISION_CONTAINER)
    result = run(runtime)
    assert result["failure"] == f"stop_failed_after_{lifecycle.VISION_CONTAINER}"
    assert result["lifecycle"]["stopped_by_runner"] == [lifecycle.VISION_CONTAINER]
    assert runtime.states[lifecycle.VISION_CONTAINER].running


def test_identity_or_prestate_failure_causes_no_mutation() -> None:
    identity_runtime = FakeRuntime()
    identity_runtime.identity_error = lifecycle.LifecycleError("identity_gate_failed")
    result = run(identity_runtime)
    assert result["failure"] == "identity_gate_failed"
    assert mutations(identity_runtime) == []

    qwen_runtime = FakeRuntime()
    qwen_runtime.states[lifecycle.QWEN_CONTAINER] = lifecycle.ContainerState(
        "running", True
    )
    result = run(qwen_runtime)
    assert result["failure"] == "prestate_qwen_not_stopped"
    assert mutations(qwen_runtime) == []


def test_llm_identity_failure_is_before_any_stop() -> None:
    runtime = FakeRuntime()

    def wrong_model(role: str, timeout_seconds: float) -> bool:
        runtime.events.append(("model", role, timeout_seconds))
        return False

    runtime.model_is_exact = wrong_model  # type: ignore[method-assign]
    result = run(runtime)
    assert result["failure"] == "preflight_llm_identity_not_exact"
    assert mutations(runtime) == []


def test_datasheet_llm_is_never_a_lifecycle_target() -> None:
    runtime = FakeRuntime()
    result = run(runtime)
    assert result["status"] == "passed"
    assert not any(
        event[0] in {"start", "stop"} and event[1] == lifecycle.LLM_CONTAINER
        for event in runtime.events
    )
    assert result["lifecycle"]["llm_was_lifecycle_targeted"] is False


def test_production_environment_removes_all_model_override_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THOR_LOCAL_VLM_CONTAINER", "wrong")
    monkeypatch.setenv("THOR_LOCAL_HF_CACHE_DIR", "/wrong")
    monkeypatch.setenv("LLM_ENDPOINT_URL", "http://example.com")
    monkeypatch.setenv("VLM_ENDPOINT_URL", "http://example.com")
    monkeypatch.setenv("DOCKER_HOST", "unix:///test")
    environment = lifecycle.DockerRuntime._environment()
    assert set(environment) == {"DOCKER_HOST", "HOME", "LANG", "PATH"}
    assert environment["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert environment["HOME"] == lifecycle.pwd.getpwuid(lifecycle.os.getuid()).pw_dir
    assert "/usr/bin" in environment["PATH"].split(":")


def exact_container_contract(name: str, role: str, image_id: str) -> dict[str, Any]:
    return {
        "Name": f"/{name}",
        "Image": image_id,
        "Config": {
            "Image": lifecycle.qualifier.VLLM_IMAGE,
            "Cmd": lifecycle._expected_command(role),
            "Entrypoint": None,
            "WorkingDir": "/",
            "User": "",
            "Labels": {"com.nvidia.vss.thor-local.model-role": role},
            "Env": [
                f"{key}={content}"
                for key, content in lifecycle.REQUIRED_OFFLINE_ENV.items()
            ],
        },
        "HostConfig": {
            "NetworkMode": "host",
            "Runtime": "nvidia",
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "Privileged": False,
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "UsernsMode": "",
            "ReadonlyRootfs": False,
            "AutoRemove": False,
            "CapAdd": None,
            "CapDrop": None,
            "SecurityOpt": None,
            "Devices": [],
            "DeviceRequests": None,
            "ExtraHosts": None,
            "Links": None,
            "CgroupnsMode": "private",
            "OomKillDisable": False,
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(
                    Path(lifecycle.DockerRuntime._environment()["HOME"])
                    / ".cache/huggingface"
                ),
                "Destination": lifecycle.HF_CACHE_TARGET,
                "RW": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["Config"].update(Cmd=["vllm", "serve", "wrong"]),
        lambda value: value["Config"].update(Entrypoint=["/bin/false"]),
        lambda value: value["Config"].update(
            Healthcheck={"Test": ["CMD-SHELL", "touch /tmp/unauthorized"]}
        ),
        lambda value: value["Config"].update(Image="mutable:latest"),
        lambda value: value.update(Image="sha256:" + "b" * 64),
        lambda value: value["Config"]["Labels"].clear(),
        lambda value: value["HostConfig"].update(NetworkMode="bridge"),
        lambda value: value["HostConfig"].update(Runtime="runc"),
        lambda value: value["HostConfig"].update(Privileged=True),
        lambda value: value["HostConfig"].update(PidMode="host"),
        lambda value: value["HostConfig"].update(IpcMode="host"),
        lambda value: value["HostConfig"].update(CapAdd=["SYS_ADMIN"]),
        lambda value: value["HostConfig"].update(SecurityOpt=["seccomp=unconfined"]),
        lambda value: value["HostConfig"].update(Tmpfs={"/tmp": "rw"}),
        lambda value: value["HostConfig"]["RestartPolicy"].update(Name="always"),
        lambda value: value["Mounts"][0].update(Source="/wrong/cache"),
        lambda value: value["Mounts"][0].update(Destination="/wrong/target"),
        lambda value: value["Mounts"][0].update(RW=False),
        lambda value: value["Config"]["Env"].remove("HF_HUB_OFFLINE=1"),
        lambda value: value["Config"]["Env"].append("HF_TOKEN=secret"),
        lambda value: value["Config"]["Env"].append("PYTHONPATH=/attacker"),
        lambda value: value["Config"]["Env"].append("LD_PRELOAD=/attacker.so"),
    ],
)
def test_full_qwen_container_contract_fails_closed_before_lifecycle(
    mutation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_id = "sha256:" + "a" * 64
    value = exact_container_contract(lifecycle.QWEN_CONTAINER, "vlm", image_id)
    environment = dict(item.split("=", 1) for item in value["Config"]["Env"])
    monkeypatch.setitem(
        lifecycle.EXPECTED_ENVIRONMENT_SHA256,
        "vlm",
        {lifecycle._environment_sha256(environment)},
    )
    monkeypatch.setitem(
        lifecycle.EXPECTED_CONTAINER_CONFIG_PAIRS,
        "vlm",
        {lifecycle._container_config_pair_sha256(value["Config"], value["HostConfig"])},
    )
    mutation(value)
    runtime = lifecycle.DockerRuntime()

    def fake_run(*_args: Any, **_kwargs: Any) -> Any:
        return lifecycle.subprocess.CompletedProcess([], 0, json.dumps(value), "")

    monkeypatch.setattr(runtime, "_run", fake_run)
    with pytest.raises(lifecycle.LifecycleError):
        runtime._verify_container_contract(lifecycle.QWEN_CONTAINER, "vlm", image_id)


def test_preserved_running_legacy_llm_boundary_is_narrow_and_qwen_stays_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = "sha256:" + "a" * 64
    legacy_llm = exact_container_contract(lifecycle.LLM_CONTAINER, "llm", image_id)
    legacy_llm["Config"]["Labels"].clear()
    legacy_llm["Config"]["Env"] = [
        item
        for item in legacy_llm["Config"]["Env"]
        if item.split("=", 1)[0]
        not in {
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "HF_HUB_DISABLE_TELEMETRY",
        }
    ]
    legacy_environment = dict(
        item.split("=", 1) for item in legacy_llm["Config"]["Env"]
    )
    legacy_digest = lifecycle._environment_sha256(legacy_environment)
    monkeypatch.setattr(lifecycle, "LEGACY_LLM_ENVIRONMENT_SHA256", legacy_digest)
    monkeypatch.setitem(
        lifecycle.EXPECTED_ENVIRONMENT_SHA256,
        "llm",
        {legacy_digest, lifecycle.CURRENT_PROVISIONER_ENVIRONMENT_SHA256},
    )
    monkeypatch.setitem(
        lifecycle.EXPECTED_CONTAINER_CONFIG_PAIRS,
        "llm",
        {
            lifecycle._container_config_pair_sha256(
                legacy_llm["Config"], legacy_llm["HostConfig"]
            )
        },
    )
    runtime = lifecycle.DockerRuntime()
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda *_args, **_kwargs: lifecycle.subprocess.CompletedProcess(
            [], 0, json.dumps(legacy_llm), ""
        ),
    )
    runtime._verify_container_contract(lifecycle.LLM_CONTAINER, "llm", image_id)

    wrong_offline_llm = json.loads(json.dumps(legacy_llm))
    wrong_offline_llm["Config"]["Env"].append("HF_HUB_OFFLINE=0")
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda *_args, **_kwargs: lifecycle.subprocess.CompletedProcess(
            [], 0, json.dumps(wrong_offline_llm), ""
        ),
    )
    with pytest.raises(lifecycle.LifecycleError):
        runtime._verify_container_contract(lifecycle.LLM_CONTAINER, "llm", image_id)

    legacy_qwen = exact_container_contract(lifecycle.QWEN_CONTAINER, "vlm", image_id)
    exact_qwen_environment = dict(
        item.split("=", 1) for item in legacy_qwen["Config"]["Env"]
    )
    monkeypatch.setitem(
        lifecycle.EXPECTED_ENVIRONMENT_SHA256,
        "vlm",
        {lifecycle._environment_sha256(exact_qwen_environment)},
    )
    monkeypatch.setitem(
        lifecycle.EXPECTED_CONTAINER_CONFIG_PAIRS,
        "vlm",
        {
            lifecycle._container_config_pair_sha256(
                legacy_qwen["Config"], legacy_qwen["HostConfig"]
            )
        },
    )
    legacy_qwen["Config"]["Labels"].clear()
    legacy_qwen["Config"]["Env"] = [
        item
        for item in legacy_qwen["Config"]["Env"]
        if not item.startswith("HF_HUB_OFFLINE=")
    ]
    monkeypatch.setattr(
        runtime,
        "_run",
        lambda *_args, **_kwargs: lifecycle.subprocess.CompletedProcess(
            [], 0, json.dumps(legacy_qwen), ""
        ),
    )
    with pytest.raises(lifecycle.LifecycleError):
        runtime._verify_container_contract(lifecycle.QWEN_CONTAINER, "vlm", image_id)


def test_expected_container_argv_is_source_locked_to_exact_artifacts() -> None:
    llm = lifecycle._expected_command("llm")
    vlm = lifecycle._expected_command("vlm")
    assert llm[2] == lifecycle.qualifier.ARTIFACTS["qwen_llm"]["repository"]
    assert vlm[2] == lifecycle.qualifier.ARTIFACTS["qwen_vlm"]["repository"]
    assert (
        llm[llm.index("--revision") + 1]
        == lifecycle.qualifier.ARTIFACTS["qwen_llm"]["revision"]
    )
    assert (
        vlm[vlm.index("--revision") + 1]
        == lifecycle.qualifier.ARTIFACTS["qwen_vlm"]["revision"]
    )
    assert llm[-2:] == ["--tool-call-parser", "qwen3_coder"]
    assert vlm[-2:] == ["--limit-mm-per-prompt", '{"image":4,"video":0}']
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == expected_digest
        for path, expected_digest in lifecycle.SOURCE_LOCKS.items()
    )


def test_production_runtime_uses_only_exact_identity_inspect_stop_start_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    image_id = "sha256:" + "a" * 64
    current_environment = dict(
        item.split("=", 1)
        for item in exact_container_contract(lifecycle.QWEN_CONTAINER, "vlm", image_id)[
            "Config"
        ]["Env"]
    )
    current_digest = lifecycle._environment_sha256(current_environment)
    monkeypatch.setattr(
        lifecycle, "CURRENT_PROVISIONER_ENVIRONMENT_SHA256", current_digest
    )
    monkeypatch.setitem(lifecycle.EXPECTED_ENVIRONMENT_SHA256, "llm", {current_digest})
    monkeypatch.setitem(lifecycle.EXPECTED_ENVIRONMENT_SHA256, "vlm", {current_digest})
    for name, role in (
        (lifecycle.LLM_CONTAINER, "llm"),
        (lifecycle.QWEN_CONTAINER, "vlm"),
    ):
        contract = exact_container_contract(name, role, image_id)
        monkeypatch.setitem(
            lifecycle.EXPECTED_CONTAINER_CONFIG_PAIRS,
            role,
            {
                lifecycle._container_config_pair_sha256(
                    contract["Config"], contract["HostConfig"]
                )
            },
        )

    def container_contract(name: str, role: str) -> str:
        return json.dumps(exact_container_contract(name, role, image_id))

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        calls.append((command, kwargs))
        if command[:3] == ["docker", "image", "inspect"]:
            stdout = image_id + "\n"
        elif command[:4] == ["docker", "inspect", "--format", "{{json .}}"]:
            name = command[-1]
            role = "llm" if name == lifecycle.LLM_CONTAINER else "vlm"
            stdout = container_contract(name, role)
        elif command[:4] == [
            "docker",
            "inspect",
            "--format",
            "{{json .State}}",
        ]:
            stdout = '{"Status":"running","Running":true,"OOMKilled":false}'
        else:
            stdout = ""
        return lifecycle.subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    runtime = lifecycle.DockerRuntime()
    runtime.verify_identity()
    assert runtime.container_state(lifecycle.LLM_CONTAINER) == lifecycle.ContainerState(
        "running", True, False
    )
    runtime.stop_container(lifecycle.VISION_CONTAINER)
    runtime.start_container(lifecycle.QWEN_CONTAINER)

    assert [item[0] for item in calls] == [
        [str(lifecycle.PROVISIONER), "status"],
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            lifecycle.qualifier.VLLM_IMAGE,
        ],
        [
            "docker",
            "inspect",
            "--format",
            "{{json .}}",
            lifecycle.LLM_CONTAINER,
        ],
        [
            "docker",
            "inspect",
            "--format",
            "{{json .}}",
            lifecycle.QWEN_CONTAINER,
        ],
        [
            "docker",
            "inspect",
            "--format",
            "{{json .State}}",
            lifecycle.LLM_CONTAINER,
        ],
        [
            "docker",
            "stop",
            "--time",
            "30",
            lifecycle.VISION_CONTAINER,
        ],
        ["docker", "start", lifecycle.QWEN_CONTAINER],
    ]
    assert all(
        item[1]["env"]["DOCKER_HOST"] == "unix:///var/run/docker.sock"
        and item[1]["stdin"] is lifecycle.subprocess.DEVNULL
        and item[1]["stdout"] is lifecycle.subprocess.PIPE
        and item[1]["stderr"] is lifecycle.subprocess.PIPE
        and item[1]["start_new_session"] is True
        for item in calls
    )


def test_production_runtime_redacts_subprocess_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_run(command: list[str], **_kwargs: Any) -> Any:
        return lifecycle.subprocess.CompletedProcess(
            command, 1, "sensitive stdout", "sensitive stderr"
        )

    monkeypatch.setattr(lifecycle.subprocess, "run", failed_run)
    with pytest.raises(lifecycle.LifecycleError, match="identity_gate_failed"):
        lifecycle.DockerRuntime().verify_identity()


def test_source_has_only_the_four_allowed_lifecycle_mutations() -> None:
    source = LIFECYCLE_PATH.read_text()
    assert '["docker", "stop", "--time", "30", name]' in source
    assert '["docker", "start", name]' in source
    for forbidden in (
        '"docker", "rm"',
        '"docker", "restart"',
        '"docker", "pull"',
        '"docker", "create"',
        '"docker", "compose"',
    ):
        assert forbidden not in source
