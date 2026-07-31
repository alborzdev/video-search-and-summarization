# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import contextlib
import io
import json
import re
import socket
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QUALIFICATION_DIR))

import acceptance  # noqa: E402
import acceptance_executor  # noqa: E402


class FakeState:
    def __init__(self) -> None:
        self.files: dict[str, dict[str, object]] = {}
        self.requests: list[tuple[str, str]] = []
        self.behavior: str | None = None


def _multipart_fields(
    body: bytes, content_type: str
) -> tuple[dict[str, str], bytes, str]:
    match = re.fullmatch(r"multipart/form-data; boundary=([A-Za-z0-9-]+)", content_type)
    if match is None:
        raise ValueError("bad multipart")
    marker = b"--" + match.group(1).encode()
    fields: dict[str, str] = {}
    file_body = b""
    filename = ""
    for raw_part in body.split(marker)[1:-1]:
        part = raw_part.removeprefix(b"\r\n").removesuffix(b"\r\n")
        headers, separator, content = part.partition(b"\r\n\r\n")
        if not separator:
            raise ValueError("bad multipart part")
        disposition = next(
            line.decode()
            for line in headers.split(b"\r\n")
            if line.lower().startswith(b"content-disposition:")
        )
        name_match = re.search(r'name="([a-z_]+)"', disposition)
        if name_match is None:
            raise ValueError("missing name")
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]+)"', disposition)
        if filename_match:
            filename = filename_match.group(1)
            file_body = content
        else:
            fields[name] = content.decode()
    return fields, file_body, filename


class FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> FakeState:
        return self.server.state  # type: ignore[attr-defined,no-any-return]

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def _send(
        self, status: int, body: bytes, media_type: str = "application/json"
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: object) -> None:
        self._send(status, json.dumps(value, sort_keys=True).encode())

    def do_GET(self) -> None:  # noqa: N802
        self.state.requests.append(("GET", self.path))
        content = self.path.endswith("/content")
        match = re.fullmatch(r"/v1/files/([0-9a-f-]+)(?:/content)?", self.path)
        if match is None:
            self._json(404, {"error": "not-found"})
            return
        file_id = match.group(1)
        item = self.state.files.get(file_id)
        if item is None:
            self._json(400, {"code": "BadParameter"})
        elif content:
            self._send(200, item["content"], "video/mp4")  # type: ignore[arg-type]
        else:
            response = {key: value for key, value in item.items() if key != "content"}
            self._json(200, response)

    def do_POST(self) -> None:  # noqa: N802
        self.state.requests.append(("POST", self.path))
        if self.path != "/v1/files":
            self._json(404, {"error": "not-found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        fields, content, filename = _multipart_fields(
            self.rfile.read(length), self.headers.get("Content-Type", "")
        )
        file_id = fields["id"]
        item: dict[str, object] = {
            "bytes": len(content),
            "content": content,
            "filename": filename,
            "id": file_id,
            "media_type": fields["media_type"],
            "purpose": fields["purpose"],
            "sensor_name": fields["sensor_name"],
        }
        self.state.files[file_id] = item
        if self.state.behavior == "drop-create-response":
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        if self.state.behavior == "redirect-create":
            self.send_response(302)
            self.send_header("Location", "http://192.0.2.1/escape")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        response = {key: value for key, value in item.items() if key != "content"}
        if self.state.behavior == "wrong-create-id":
            response["id"] = "00000000-0000-0000-0000-000000000000"
        if self.state.behavior == "oversized-create-response":
            self._send(200, b"x" * (1024 * 1024 + 1), "application/json")
            return
        self._json(200, response)

    def do_DELETE(self) -> None:  # noqa: N802
        self.state.requests.append(("DELETE", self.path))
        match = re.fullmatch(r"/v1/files/([0-9a-f-]+)", self.path)
        if match is None:
            self._json(404, {"error": "not-found"})
            return
        file_id = match.group(1)
        if self.state.behavior == "fail-delete":
            self._json(500, {"error": "injected"})
            return
        if self.state.files.pop(file_id, None) is None:
            self._json(400, {"code": "BadParameter"})
        else:
            self._json(200, {"deleted": True, "id": file_id, "object": "file"})


class FakeService:
    def __init__(self) -> None:
        self.state = FakeState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        self.server.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> "FakeService":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class AcceptanceExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.evidence_dir = Path(self.temporary.name)
        self.evidence_dir.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def source_fingerprint(self, run_id: str) -> str:
        return acceptance.compile_plan(run_id=run_id)["source_fingerprint"]

    def invoke(
        self,
        command: str,
        run_id: str,
        vlm: FakeService,
        embed: FakeService,
        *,
        ack: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        argv = [
            command,
            "--scenario",
            "rtvi-file-lifecycle",
            "--run-id",
            run_id,
            "--confirm-stateful",
            "rtvi-file-lifecycle",
            "--evidence-dir",
            str(self.evidence_dir),
            "--endpoint",
            f"rt-vlm={vlm.origin}",
            "--endpoint",
            f"rt-embed={embed.origin}",
            "--timeout",
            "2",
        ]
        if command == "execute":
            argv.extend(
                ("--ack-source-fingerprint", ack or self.source_fingerprint(run_id))
            )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = acceptance.main(argv)
        return status, json.loads(output.getvalue())

    def test_default_cli_remains_plan_only_and_inert(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = acceptance.main(["--run-id", "phase0-0001"])
        report = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(report["mode"], "plan-only")
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(report["network_requests_made"], 0)

    def test_success_uses_exact_ids_lifo_cleanup_and_private_evidence(self) -> None:
        with FakeService() as vlm, FakeService() as embed:
            status, report = self.invoke("execute", "phase1-0001", vlm, embed)
        self.assertEqual(status, 0)
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["residual_resource_count"], 0)
        self.assertFalse(vlm.state.files)
        self.assertFalse(embed.state.files)
        self.assertEqual(
            [item for item in embed.state.requests if item[0] == "DELETE"],
            [
                (
                    "DELETE",
                    f"/v1/files/{acceptance_executor._resource_uuid('phase1-0001', 'rtvi-file-lifecycle', 'embed-file')}",
                )
            ],
        )
        report_path = self.evidence_dir / "phase1-0001-report.json"
        ledger_path = self.evidence_dir / "phase1-0001-ledger-v2.jsonl"
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(ledger_path.stat().st_mode), 0o600)
        records = [json.loads(line) for line in ledger_path.read_text().splitlines()]
        self.assertEqual(records[-1]["event"], "run-finished")
        self.assertTrue(all(item["schema_version"] == 2 for item in records))

    def test_wrong_ack_and_remote_endpoint_make_no_requests(self) -> None:
        with FakeService() as vlm, FakeService() as embed:
            status, report = self.invoke(
                "execute", "phase1-0002", vlm, embed, ack="0" * 64
            )
            self.assertEqual(status, 1)
            self.assertEqual(report["error"], "approval_required")
            self.assertFalse(vlm.state.requests)
            self.assertFalse(embed.state.requests)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = acceptance.main(
                    [
                        "execute",
                        "--scenario",
                        "rtvi-file-lifecycle",
                        "--run-id",
                        "phase1-0003",
                        "--confirm-stateful",
                        "rtvi-file-lifecycle",
                        "--evidence-dir",
                        str(self.evidence_dir),
                        "--endpoint",
                        "rt-vlm=http://192.0.2.1:9999",
                        "--ack-source-fingerprint",
                        self.source_fingerprint("phase1-0003"),
                    ]
                )
            self.assertEqual(status, 1)
            self.assertEqual(
                json.loads(output.getvalue())["error"], "configuration_error"
            )
            self.assertFalse(vlm.state.requests)
            self.assertFalse(embed.state.requests)

    def test_preexisting_client_id_is_never_adopted_or_deleted(self) -> None:
        run_id = "phase1-0004"
        file_id = acceptance_executor._resource_uuid(
            run_id, "rtvi-file-lifecycle", "vlm-file"
        )
        existing = {
            "id": file_id,
            "bytes": 1,
            "filename": "foreign.mp4",
            "purpose": "vision",
            "media_type": "video",
            "sensor_name": "foreign",
            "content": b"x",
        }
        with FakeService() as vlm, FakeService() as embed:
            vlm.state.files[file_id] = existing
            status, report = self.invoke("execute", run_id, vlm, embed)
            self.assertEqual(status, 1)
            self.assertEqual(report["result"], "fail")
            self.assertIs(vlm.state.files[file_id], existing)
            self.assertFalse(
                any(method == "DELETE" for method, _ in vlm.state.requests)
            )
            self.assertFalse(embed.state.requests)

    def test_lost_or_invalid_create_response_still_cleans_exact_intent(self) -> None:
        for number, behavior in enumerate(
            (
                "drop-create-response",
                "wrong-create-id",
                "redirect-create",
                "oversized-create-response",
            ),
            start=5,
        ):
            with (
                self.subTest(behavior=behavior),
                FakeService() as vlm,
                FakeService() as embed,
            ):
                vlm.state.behavior = behavior
                status, report = self.invoke(
                    "execute", f"phase1-00{number}", vlm, embed
                )
                self.assertEqual(status, 1)
                self.assertEqual(report["result"], "fail")
                self.assertEqual(report["residual_resource_count"], 0)
                self.assertFalse(vlm.state.files)
                self.assertFalse(embed.state.requests)
                deletes = [item for item in vlm.state.requests if item[0] == "DELETE"]
                self.assertEqual(len(deletes), 1)

    def test_cleanup_failure_stops_at_top_and_recovery_resumes_lifo(self) -> None:
        run_id = "phase1-0010"
        with FakeService() as vlm, FakeService() as embed:
            embed.state.behavior = "fail-delete"
            status, report = self.invoke("execute", run_id, vlm, embed)
            self.assertEqual(status, 3)
            self.assertEqual(report["result"], "cleanup-incomplete")
            self.assertEqual(report["residual_resource_count"], 2)
            self.assertEqual(len(vlm.state.files), 1)
            self.assertEqual(len(embed.state.files), 1)
            self.assertFalse(
                any(method == "DELETE" for method, _ in vlm.state.requests)
            )

            embed.state.behavior = None
            status, recovery = self.invoke("recover", run_id, vlm, embed)
            self.assertEqual(status, 0)
            self.assertEqual(recovery["result"], "pass")
            self.assertTrue(recovery["recovery"])
            self.assertFalse(vlm.state.files)
            self.assertFalse(embed.state.files)
            records = [
                json.loads(line)
                for line in (self.evidence_dir / f"{run_id}-ledger-v2.jsonl")
                .read_text()
                .splitlines()
            ]
            cleanup_success = [
                item["resource_id"]
                for item in records
                if item["event"] == "cleanup-succeeded"
            ]
            self.assertEqual(cleanup_success, ["embed-file", "vlm-file"])
            self.assertEqual(records[-1]["event"], "run-finished")

    def test_recovery_resumes_durable_cleanup_started_without_duplicate_event(
        self,
    ) -> None:
        run_id = "phase1-0012"
        with FakeService() as vlm, FakeService() as embed:
            original_request = acceptance_executor.LoopbackHTTP.request

            def interrupt_top_cleanup(
                client: acceptance_executor.LoopbackHTTP,
                method: str,
                path: str,
                **kwargs: object,
            ) -> tuple[int, str, bytes]:
                if method == "DELETE" and client.origin == embed.origin:
                    raise KeyboardInterrupt
                return original_request(client, method, path, **kwargs)  # type: ignore[arg-type]

            with (
                mock.patch.object(
                    acceptance_executor.LoopbackHTTP,
                    "request",
                    new=interrupt_top_cleanup,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                self.invoke("execute", run_id, vlm, embed)

            ledger = self.evidence_dir / f"{run_id}-ledger-v2.jsonl"
            before = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(before[-1]["event"], "cleanup-started")
            self.assertEqual(before[-1]["resource_id"], "embed-file")
            self.assertEqual(len(vlm.state.files), 1)
            self.assertEqual(len(embed.state.files), 1)

            status, recovery = self.invoke("recover", run_id, vlm, embed)
            self.assertEqual(status, 0)
            self.assertEqual(recovery["result"], "pass")
            self.assertFalse(vlm.state.files)
            self.assertFalse(embed.state.files)
            after = [json.loads(line) for line in ledger.read_text().splitlines()]
            embed_starts = [
                item
                for item in after
                if item["event"] == "cleanup-started"
                and item["resource_id"] == "embed-file"
            ]
            self.assertEqual(len(embed_starts), 1)
            self.assertEqual(after[-1]["event"], "run-finished")

    def test_recovery_refuses_changed_endpoint_mapping_without_network(self) -> None:
        run_id = "phase1-0013"
        with (
            FakeService() as vlm,
            FakeService() as embed,
            FakeService() as other_vlm,
            FakeService() as other_embed,
        ):
            embed.state.behavior = "fail-delete"
            status, report = self.invoke("execute", run_id, vlm, embed)
            self.assertEqual(status, 3)
            self.assertEqual(report["result"], "cleanup-incomplete")
            before_original = (list(vlm.state.requests), list(embed.state.requests))

            status, recovery = self.invoke("recover", run_id, other_vlm, other_embed)
            self.assertEqual(status, 1)
            self.assertEqual(recovery["error"], "ledger_error")
            self.assertFalse(other_vlm.state.requests)
            self.assertFalse(other_embed.state.requests)
            self.assertEqual(vlm.state.requests, before_original[0])
            self.assertEqual(embed.state.requests, before_original[1])

    def test_tampered_ledger_refuses_recovery_without_network(self) -> None:
        run_id = "phase1-0011"
        with FakeService() as vlm, FakeService() as embed:
            embed.state.behavior = "fail-delete"
            status, _ = self.invoke("execute", run_id, vlm, embed)
            self.assertEqual(status, 3)
            ledger = self.evidence_dir / f"{run_id}-ledger-v2.jsonl"
            ledger.write_bytes(
                ledger.read_bytes().replace(b'"sequence":1', b'"sequence":9', 1)
            )
            before_vlm = list(vlm.state.requests)
            before_embed = list(embed.state.requests)
            embed.state.behavior = None
            status, report = self.invoke("recover", run_id, vlm, embed)
            self.assertEqual(status, 1)
            self.assertEqual(report["error"], "ledger_error")
            self.assertEqual(vlm.state.requests, before_vlm)
            self.assertEqual(embed.state.requests, before_embed)


if __name__ == "__main__":
    unittest.main()
