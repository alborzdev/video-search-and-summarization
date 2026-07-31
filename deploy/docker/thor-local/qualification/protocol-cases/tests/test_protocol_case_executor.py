#!/usr/bin/env python3
"""Fail-closed tests for the inert bounded protocol-case executor."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import jsonschema


HERE = Path(__file__).resolve().parent
LANE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "protocol_case_executor", LANE / "protocol_case_executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


class ProtocolCaseExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = executor._contract()

    def request(self, case_id: str, vector_id: str | None = None) -> dict:
        case = executor._case_by_id(self.document, case_id)
        roles = executor.EXPECTED_TARGET_ROLES[case_id]
        ports = {"websocket": 9000, "http": 8080, "redis": 6379, "kafka": 9092}
        targets = [
            {
                "role": role,
                "kind": "numeric_loopback",
                "host": "127.0.0.1",
                "port": ports[role],
                "tls": False,
            }
            for role in sorted(roles)
        ]
        resources = {
            "protocol-case.agent.websocket": {
                "conversation_id": "vss-protocol-case-agent-test"
            },
            "protocol-case.alert.websocket": {"stream": "vss-protocol-case-alert-test"},
            "protocol-case.rt-vlm.sse": {
                "asset_id": "00000000-0000-4000-8000-000000000003",
                "model_id": "local-model",
                "delete_asset_after": True,
            },
            "protocol-case.kafka.nvschema": {
                "topic": "vss-protocol-case-kafka-test",
                "consumer_group": "vss-protocol-case-kafka-group-test",
            },
            "protocol-case.redis.events": {
                "stream": "vss-protocol-case-redis-test",
                "consumer_group": "vss-protocol-case-redis-group-test",
            },
            "protocol-case.vios.webrtc-live": {
                "stream_id": "vss-protocol-case-live-test",
                "peer_id": "00000000-0000-4000-8000-000000000005",
            },
            "protocol-case.vios.webrtc-replay": {
                "stream_id": "vss-protocol-case-replay-test",
                "peer_id": "00000000-0000-4000-8000-000000000007",
                "start_time": "2026-07-31T00:00:00Z",
                "end_time": "2026-07-31T00:00:10Z",
            },
        }[case_id]
        vector = executor._vector_by_id(
            case, vector_id or case["positive_vector"]["id"]
        )
        return {
            "schema_version": 1,
            "case_id": case_id,
            "vector_id": vector["id"],
            "operator_ack": executor.ACK,
            "run_id": "vss-protocol-case-test-run",
            "targets": targets,
            "bounds": {
                "deadline_seconds": vector["deadline_seconds"],
                "max_events": vector["max_events"],
                "max_bytes": executor.MAX_BYTES,
                "max_requests": executor.MAX_REQUESTS,
            },
            "resources": resources,
            "credentials_env": [],
            "evidence_dir": "deploy/docker/thor-local/qualification/protocol-cases/runtime-evidence/test-run",
        }

    def test_default_is_plan_only_and_cannot_reach_activation_primitives(self) -> None:
        output = io.StringIO()
        runner_sentinels = {
            case_id: mock.Mock(side_effect=AssertionError("runner reached"))
            for case_id in executor.RUNNERS
        }
        with (
            mock.patch.object(executor, "RUNNERS", runner_sentinels),
            mock.patch.object(
                executor.socket,
                "create_connection",
                side_effect=AssertionError("network reached"),
            ),
            mock.patch.object(
                executor.http.client,
                "HTTPConnection",
                side_effect=AssertionError("network reached"),
            ),
            mock.patch.object(
                executor.http.client,
                "HTTPSConnection",
                side_effect=AssertionError("network reached"),
            ),
            mock.patch.object(
                executor,
                "_websocket_connect",
                side_effect=AssertionError("network reached"),
            ),
            mock.patch.object(
                executor,
                "_write_evidence",
                side_effect=AssertionError("mutation reached"),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(executor.main([]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "plan_only")
        self.assertEqual(payload["network"], "disabled")
        self.assertTrue(
            all(not sentinel.called for sentinel in runner_sentinels.values())
        )

    def test_plan_has_five_activation_ready_and_two_blocks(self) -> None:
        plans = executor.compile_plans(self.document)
        self.assertEqual(sum(plan["activation_ready"] for plan in plans), 5)
        self.assertEqual(sum(plan["state"].startswith("blocked") for plan in plans), 2)
        self.assertEqual(sum(plan["can_advance_capability"] for plan in plans), 4)
        blocked_ids = {
            plan["case_id"] for plan in plans if plan["state"].startswith("blocked")
        }
        self.assertEqual(
            blocked_ids,
            {"protocol-case.agent.websocket", "protocol-case.kafka.nvschema"},
        )

    def test_execution_schemas_are_draft_2020_12_and_valid(self) -> None:
        for name in (
            "execution-request.schema.json",
            "runtime-evidence.schema.json",
            "external-agent-contract.schema.json",
        ):
            schema = executor._json_load(LANE / name)
            self.assertEqual(
                schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
            )
            jsonschema.Draft202012Validator.check_schema(schema)
        request_schema = executor._json_load(LANE / "execution-request.schema.json")
        jsonschema.Draft202012Validator(request_schema).validate(
            self.request("protocol-case.redis.events")
        )

    def test_missing_ack_fails_before_any_transport_or_evidence(self) -> None:
        request = self.request("protocol-case.redis.events")
        request["operator_ack"] = "yes"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "request.json"
            path.write_text(json.dumps(request), encoding="utf-8")
            with (
                mock.patch.object(
                    executor.socket,
                    "create_connection",
                    side_effect=AssertionError("network reached"),
                ),
                mock.patch.object(
                    executor,
                    "_write_evidence",
                    side_effect=AssertionError("evidence reached"),
                ),
            ):
                with self.assertRaisesRegex(executor.AdmissionError, "acknowledgement"):
                    executor.execute(path)

    def test_agent_remains_blocked_without_external_server_contract(self) -> None:
        request = self.request("protocol-case.agent.websocket")
        with self.assertRaisesRegex(
            executor.AdmissionError, "external endpoint/server contract"
        ):
            executor.admit(request, self.document)

    def test_kafka_is_blocked_before_transport_without_reversible_product_trigger(
        self,
    ) -> None:
        request = self.request("protocol-case.kafka.nvschema")
        with (
            mock.patch.object(
                executor.socket,
                "create_connection",
                side_effect=AssertionError("network reached"),
            ),
            self.assertRaisesRegex(
                executor.AdmissionError, "product trigger.*disposable topic"
            ),
        ):
            executor.admit(request, self.document)
        source = (LANE / "protocol_case_executor.py").read_text(encoding="utf-8")
        self.assertNotIn("producer.produce", source)

    def test_target_bypasses_fail_closed(self) -> None:
        base = self.request("protocol-case.rt-vlm.sse")
        for kind, host, pattern in (
            ("numeric_loopback", "localhost", "numeric IP literal"),
            ("numeric_loopback", "192.0.2.1", "not loopback"),
            ("compose_service", "evil.example", "not allowlisted"),
        ):
            request = json.loads(json.dumps(base))
            request["targets"][0].update({"kind": kind, "host": host})
            with self.subTest(kind=kind, host=host):
                with self.assertRaisesRegex(executor.AdmissionError, pattern):
                    executor.admit(request, self.document)

    def test_compose_allowlist_is_exact_and_tls_broker_bypass_is_denied(self) -> None:
        request = self.request("protocol-case.kafka.nvschema")
        request["targets"][0].update(
            {"kind": "compose_service", "host": "kafka", "tls": True}
        )
        with self.assertRaisesRegex(executor.AdmissionError, "TLS is not part"):
            executor.admit(request, self.document)

    def test_namespace_vector_and_bounds_bypasses_fail_closed(self) -> None:
        request = self.request("protocol-case.redis.events")
        request["resources"]["stream"] = "events"
        with self.assertRaisesRegex(executor.AdmissionError, "owned namespace"):
            executor.admit(request, self.document)
        request = self.request("protocol-case.redis.events")
        request["vector_id"] = "invented"
        with self.assertRaisesRegex(executor.AdmissionError, "not pinned"):
            executor.admit(request, self.document)
        request = self.request("protocol-case.redis.events")
        request["bounds"]["deadline_seconds"] += 1
        with self.assertRaisesRegex(executor.AdmissionError, "bounds exceed"):
            executor.admit(request, self.document)

    def test_discovered_endpoint_and_ice_bypasses_fail_closed(self) -> None:
        target = executor.Target("kafka", "numeric_loopback", "127.0.0.1", 9092, False)
        with self.assertRaisesRegex(executor.AdmissionError, "not loopback"):
            executor._admit_discovered_host("10.0.0.8", target)
        with self.assertRaisesRegex(executor.AdmissionError, "escapes loopback"):
            executor._assert_loopback_ice("candidate:1 1 udp 1 10.0.0.8 5000 typ host")

    def test_redirect_is_fatal_and_never_followed(self) -> None:
        response = mock.Mock(status=302)
        connection = mock.Mock()
        connection.getresponse.return_value = response
        target = executor.Target("http", "numeric_loopback", "127.0.0.1", 8080, False)
        budget = executor.Budget(5, 2, 4096, 4)
        with mock.patch.object(
            executor.http.client, "HTTPConnection", return_value=connection
        ):
            with self.assertRaisesRegex(
                executor.ExecutorError, "redirects are forbidden"
            ):
                executor.DirectHttpClient(target, budget).request("GET", "/redirect")
        connection.request.assert_called_once()
        response.read.assert_not_called()
        connection.close.assert_called_once()

    def test_cleanup_is_lifo_and_has_separate_bounded_reserve(self) -> None:
        order: list[str] = []
        evidence = {"cleanup": []}
        context = executor.ExecutionContext(
            {},
            {},
            {},
            {},
            executor.Budget(1, 1, 1024, 3, cleanup_reserve=2),
            evidence,
        )
        context.push_cleanup("first", lambda: order.append("first"))
        context.push_cleanup("second", lambda: order.append("second"))
        context.cleanup()
        self.assertEqual(order, ["second", "first"])
        self.assertEqual(
            [item["action"] for item in evidence["cleanup"]], ["second", "first"]
        )
        self.assertTrue(context.budget.cleanup_mode)

    def test_evidence_binds_contract_case_vector_sources_and_request(self) -> None:
        request = self.request("protocol-case.redis.events")
        case, vector, targets, admission = executor.admit(request, self.document)
        evidence = executor._initial_evidence(
            self.document, case, vector, request, targets, admission
        )
        self.assertEqual(
            evidence["contract_set_sha256"], self.document["contract_set_sha256"]
        )
        self.assertEqual(evidence["case_sha256"], executor._sha(case))
        self.assertEqual(evidence["vector_sha256"], executor._sha(vector))
        self.assertEqual(evidence["execution_request_sha256"], executor._sha(request))
        self.assertEqual(len(evidence["source_bindings"]), len(case["sources"]))
        self.assertEqual(evidence["cleanup_request_reserve"], 2)
        self.assertEqual(evidence["evidence_class"], "transport_fixture_only")
        self.assertFalse(evidence["can_advance_capability"])
        evidence.update(
            {
                "finished_at": "2026-07-31T00:00:01Z",
                "result": "passed",
                "cleanup": [
                    {
                        "order": 1,
                        "action": "test_cleanup",
                        "result": "pass",
                        "at": "2026-07-31T00:00:01Z",
                    }
                ],
            }
        )
        evidence_schema = executor._json_load(LANE / "runtime-evidence.schema.json")
        jsonschema.Draft202012Validator(evidence_schema).validate(evidence)

    def test_executor_has_no_process_or_container_lifecycle_primitive(self) -> None:
        tree = ast.parse(
            (LANE / "protocol_case_executor.py").read_text(encoding="utf-8")
        )
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse({"subprocess", "docker", "podman"} & imports)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse({"system", "Popen", "run", "exec", "spawn"} & called_names)


if __name__ == "__main__":
    unittest.main()
