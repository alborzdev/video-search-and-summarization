"""Fake-only tests for the authorization-gated LVS semantic executor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lvs_semantic_executor", PACKAGE_DIR / "executor.py")
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

FIXTURES = ("1" * 64, "2" * 64)
ACK = "I_ACK_LVS_SEMANTIC_RUNTIME_AND_EXACT_OWNED_CLEANUP"
RUN_ID = "lvs-semantic-test-001"


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.cleanup_ids: list[str] = []
        self.postcondition_ids: list[str] = []
        self.override: dict[str, Mapping[str, Any]] = {}
        self.cleanup_ok = True
        self.unrelated = {"existing_reports_sha256": "a" * 64, "existing_streams_sha256": "b" * 64}

    def invoke(self, *, run_id: str, action_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert run_id == RUN_ID
        assert isinstance(request, Mapping)
        self.calls.append(action_id)
        if action_id in self.override:
            return self.override[action_id]
        facts: dict[str, Any]
        if action_id == "capture-pre-state":
            facts = {
                "owned_namespace_absent": True,
                "artifact_identity_verified": True,
                "unrelated_state": self.unrelated,
            }
        elif action_id == "discover-five-tools":
            facts = {
                "tools": [
                    "lvs_video_understanding",
                    "lvs_config_media",
                    "lvs_stream_understanding",
                    "lvs_caption_retrieval",
                    "video_report_gen",
                ]
            }
        elif action_id == "verify-local-dependencies":
            facts = {
                "lvs_backend": True,
                "rtvi_vlm": True,
                "elasticsearch": True,
                "kafka": True,
                "logstash": True,
                "local_inference": True,
            }
        elif action_id == "setup-owned-fixtures":
            facts = {
                "owner_run_id": RUN_ID,
                "resource_id": "owned-lvs-semantic-test-001",
                "fixture_sha256": list(FIXTURES),
                "warehouse_sample_bundle": False,
            }
        elif action_id == "single-video-report":
            facts = {"correlated": True, "nonempty_report": True, "source_count": 1}
        elif action_id == "multi-video-report":
            facts = {
                "correlated": True,
                "nonempty_report": True,
                "distinct_sources": True,
                "source_count": 2,
            }
        elif action_id == "start-live-caption":
            facts = {"caption_started": True, "kafka_delivery": True, "logstash_delivery": True}
        elif action_id == "retrieve-live-caption":
            facts = {"correlated": True, "caption_count": 2}
        elif action_id == "write-shared-prompt-first":
            facts = {"writer_agent": "agent-a", "prompt_version": 1, "written": True}
        elif action_id == "overwrite-shared-prompt-latest":
            facts = {"prompt_version": 2, "previous_overwritten": True, "latest_visible": True}
        elif action_id == "reject-cross-agent-prompt-visibility":
            facts = {"requesting_agent": "agent-b", "prompt_visible": False, "isolation_enforced": True}
        elif action_id == "probe-disconnect-cancel-quiescence":
            facts = {
                "disconnect_delivered_once": True,
                "exact_cancel_accepted": True,
                "quiescent": True,
                "sibling_unchanged": True,
                "ca_rag_cleanup_supported": True,
            }
        else:
            raise AssertionError(action_id)
        return {"status": "pass", "result_code": "observed", "facts": facts}

    def cleanup_exact_owned(self, *, run_id: str, resource_id: str) -> Mapping[str, Any]:
        assert run_id == RUN_ID
        self.cleanup_ids.append(resource_id)
        if not self.cleanup_ok:
            return {
                "disconnect_delivered_once": True,
                "exact_cancel_accepted": True,
                "quiescent_before_cleanup": False,
                "ca_rag_scope_absent": False,
                "only_owned_targets_deleted": False,
            }
        return {
            "disconnect_delivered_once": True,
            "exact_cancel_accepted": True,
            "quiescent_before_cleanup": True,
            "ca_rag_scope_absent": True,
            "only_owned_targets_deleted": True,
        }

    def verify_postcondition(self, *, run_id: str, resource_id: str) -> Mapping[str, Any]:
        assert run_id == RUN_ID
        self.postcondition_ids.append(resource_id)
        return {
            "owned_namespace_absent": True,
            "owned_reports_absent": True,
            "owned_stream_state_absent": True,
            "unrelated_state_restored": True,
            "unrelated_state": self.unrelated,
        }


def test_plan_binds_current_oracle_and_exact_envelope() -> None:
    plan = executor.compile_plan()
    assert plan == {
        "package_id": "thor-vss-lvs-semantic-runtime-evidence-v1",
        "capability_id": "runtime.agent.lvs-profile",
        "oracle_id": "oracle.runtime.agent.lvs-profile",
        "action_count": 14,
        "request_bound": 14,
        "tool_count": 5,
        "cleanup_proof_hooks": [
            "disconnect_delivered_once",
            "exact_cancel_accepted",
            "quiescent_before_cleanup",
            "ca_rag_scope_absent",
            "only_owned_targets_deleted",
        ],
        "runtime_activity_performed": False,
        "runtime_evidence_created": False,
        "warehouse_sample_bundle": "excluded",
        "status": "inert_plan_valid",
    }


def test_authorization_gate_precedes_adapter_activity() -> None:
    adapter = FakeAdapter()
    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.run_executor(
            adapter=adapter,
            run_id=RUN_ID,
            acknowledgement="wrong",
            fixture_sha256=FIXTURES,
        )
    assert adapter.calls == []
    assert adapter.cleanup_ids == []


def test_passing_run_emits_sanitized_exact_14_transition_receipt() -> None:
    adapter = FakeAdapter()
    receipt = executor.run_executor(
        adapter=adapter,
        run_id=RUN_ID,
        acknowledgement=ACK,
        fixture_sha256=FIXTURES,
    )
    assert receipt["status"] == "pass"
    assert receipt["budget"] == {"actions": 14, "max_actions": 14, "requests": 14, "max_requests": 14}
    assert [item["action_id"] for item in receipt["actions"]] == [
        item["id"] for item in executor._contract()["actions"][:12]
    ]
    assert receipt["cleanup"] == [
        {
            "order": 1,
            "resource_type": "lvs-semantic-run-namespace",
            "target_sha256": receipt["cleanup"][0]["target_sha256"],
            "action_status": "pass",
            "postcondition_status": "pass",
        }
    ]
    assert all(receipt["semantic_observations"].values())
    assert all(receipt["cleanup_proof"].values())
    assert all(receipt["postcondition_proof"].values())
    assert adapter.cleanup_ids == adapter.postcondition_ids == ["owned-lvs-semantic-test-001"]
    serialized = str(receipt)
    assert "owned-lvs-semantic-test-001" not in serialized
    assert ACK not in serialized


def test_semantic_failure_after_ownership_still_cleans_exact_target() -> None:
    adapter = FakeAdapter()
    adapter.override["single-video-report"] = {
        "status": "pass",
        "result_code": "observed",
        "facts": {"correlated": False, "nonempty_report": True, "source_count": 1},
    }
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.run_executor(adapter=adapter, run_id=RUN_ID, acknowledgement=ACK, fixture_sha256=FIXTURES)
    assert adapter.cleanup_ids == adapter.postcondition_ids == ["owned-lvs-semantic-test-001"]


def test_ambiguous_setup_never_registers_or_deletes() -> None:
    adapter = FakeAdapter()
    adapter.override["setup-owned-fixtures"] = {
        "status": "pass",
        "result_code": "observed",
        "facts": {
            "owner_run_id": "somebody-else",
            "resource_id": "not-owned",
            "fixture_sha256": list(FIXTURES),
            "warehouse_sample_bundle": False,
        },
    }
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.run_executor(adapter=adapter, run_id=RUN_ID, acknowledgement=ACK, fixture_sha256=FIXTURES)
    assert adapter.cleanup_ids == []
    assert adapter.postcondition_ids == []


def test_cleanup_proof_failure_is_fail_closed() -> None:
    adapter = FakeAdapter()
    adapter.cleanup_ok = False
    with pytest.raises(executor.ExecutorError, match="cleanup_failed"):
        executor.run_executor(adapter=adapter, run_id=RUN_ID, acknowledgement=ACK, fixture_sha256=FIXTURES)
    assert adapter.cleanup_ids == ["owned-lvs-semantic-test-001"]
    assert adapter.postcondition_ids == []


@pytest.mark.parametrize(
    "fixtures",
    [
        ("1" * 64, "1" * 64),
        ("x" * 64, "2" * 64),
        ("1" * 63, "2" * 64),
    ],
)
def test_fixture_identity_is_exact_and_distinct(fixtures: tuple[str, str]) -> None:
    adapter = FakeAdapter()
    with pytest.raises(executor.ExecutorError, match="configuration_error"):
        executor.run_executor(adapter=adapter, run_id=RUN_ID, acknowledgement=ACK, fixture_sha256=fixtures)
    assert adapter.calls == []
