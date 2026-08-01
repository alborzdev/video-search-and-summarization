#!/usr/bin/env python3

from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from unittest import mock


SOURCE_LOCK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_LOCK_DIR))

import source_lock  # noqa: E402


class SourceLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = source_lock.load_json(source_lock.LOCK)

    def mutation(self) -> dict:
        return copy.deepcopy(self.document)

    def rehash(self, document: dict) -> None:
        records = document["records"]
        success = sum(item["outcome"] == "success" for item in records)
        document["summary"] = {
            "url_count": len(records),
            "success_count": success,
            "failure_count": len(records) - success,
            "total_byte_count": sum(item["byte_count"] or 0 for item in records),
            "aggregate_sha256": source_lock.canonical_record_hash(records),
        }

    def test_checked_in_lock_validates(self) -> None:
        with mock.patch.object(
            source_lock.subprocess,
            "run",
            side_effect=AssertionError("validation must be offline"),
        ):
            summary = source_lock.validate()
        self.assertEqual(summary["url_count"], 172)
        self.assertEqual(summary["failure_count"], 0)
        self.assertGreater(summary["total_byte_count"], 0)

    def test_source_set_is_exact_recursive_allowlist_with_provenance(self) -> None:
        urls = source_lock.source_urls()
        self.assertEqual(len(urls), 172)
        self.assertEqual(
            sum("recursive_fixed_point" in labels for labels in urls.values()), 172
        )
        self.assertEqual(sum("live_ledger" in labels for labels in urls.values()), 53)
        self.assertEqual(
            sum("wave2_candidate" in labels for labels in urls.values()), 24
        )
        self.assertEqual(sum(len(labels) == 3 for labels in urls.values()), 24)
        self.assertIn("https://docs.nvidia.com/vss/3.2.1/release-notes.html", urls)
        self.assertIn("https://docs.nvidia.com/vss/3.2.1/index.html", urls)

    def test_recursive_allowlist_hash_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target_path = Path(temp) / "recursive-targets.json"
            targets = source_lock.load_json(source_lock.INPUTS["recursive_targets"])
            targets["targets"][0] = (
                "https://docs.nvidia.com/vss/3.2.1/unreviewed.html"
            )
            targets["targets"].sort()
            target_path.write_text(json.dumps(targets), encoding="utf-8")
            inputs = {**source_lock.INPUTS, "recursive_targets": target_path}
            with self.assertRaisesRegex(
                source_lock.SourceLockError, "reviewed 172-URL set"
            ):
                source_lock.source_urls(inputs)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text(
                '{"schema_version": 1, "schema_version": 1}', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                source_lock.SourceLockError, "duplicate JSON key"
            ):
                source_lock.load_json(path)

    def test_duplicate_url_is_rejected(self) -> None:
        document = self.mutation()
        document["records"][1]["url"] = document["records"][0]["url"]
        self.rehash(document)
        with self.assertRaisesRegex(source_lock.SourceLockError, "unique URLs"):
            source_lock.validate(document)

    def test_missing_expected_url_is_rejected(self) -> None:
        document = self.mutation()
        document["records"].pop()
        self.rehash(document)
        with self.assertRaisesRegex(source_lock.SourceLockError, "locked URLs differ"):
            source_lock.validate(document)

    def test_non_https_url_is_rejected(self) -> None:
        document = self.mutation()
        document["records"][0]["url"] = document["records"][0]["url"].replace(
            "https://", "http://"
        )
        self.rehash(document)
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_external_final_url_is_rejected(self) -> None:
        document = self.mutation()
        document["records"][0]["final_url"] = "https://example.com/redirected.html"
        self.rehash(document)
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_final_url_outside_version_path_is_rejected(self) -> None:
        document = self.mutation()
        document["records"][0]["final_url"] = (
            "https://docs.nvidia.com/vss/latest/redirected.html"
        )
        self.rehash(document)
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_colliding_final_urls_are_rejected(self) -> None:
        document = self.mutation()
        document["records"][1]["final_url"] = document["records"][0]["final_url"]
        self.rehash(document)
        with self.assertRaisesRegex(
            source_lock.SourceLockError, "colliding final URLs"
        ):
            source_lock.validate(document)

    def test_redirect_policy_rejects_external_and_non_https_targets(self) -> None:
        current = "https://docs.nvidia.com/vss/3.2.1/index.html"
        with self.assertRaisesRegex(source_lock.SourceLockError, "unsafe"):
            source_lock.resolve_redirect(current, "https://example.com/page")
        with self.assertRaisesRegex(source_lock.SourceLockError, "unsafe"):
            source_lock.resolve_redirect(current, "http://docs.nvidia.com/page")
        with self.assertRaisesRegex(source_lock.SourceLockError, "unsafe"):
            source_lock.resolve_redirect(current, "https://docs.nvidia.com:bad/page")

    def test_relative_same_host_redirect_is_allowed(self) -> None:
        current = "https://docs.nvidia.com/vss/3.2.1/index.html"
        self.assertEqual(
            source_lock.resolve_redirect(current, "release-notes.html"),
            "https://docs.nvidia.com/vss/3.2.1/release-notes.html",
        )

    def test_unexpected_content_type_is_rejected(self) -> None:
        document = self.mutation()
        document["records"][0]["content_type"] = "application/octet-stream"
        self.rehash(document)
        with self.assertRaisesRegex(
            source_lock.SourceLockError, "unexpected content type"
        ):
            source_lock.validate(document)

    def test_unexpected_content_encoding_is_rejected(self) -> None:
        document = self.mutation()
        document["records"][0]["content_encoding"] = "gzip"
        self.rehash(document)
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_empty_success_body_is_rejected(self) -> None:
        document = self.mutation()
        document["records"][0]["byte_count"] = 0
        self.rehash(document)
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_failed_fetch_is_explicitly_recordable(self) -> None:
        document = self.mutation()
        record = document["records"][0]
        record.update(
            {
                "outcome": "failure",
                "http_status": 503,
                "byte_count": None,
                "sha256": None,
                "failure": "unexpected HTTP status 503",
            }
        )
        self.rehash(document)
        summary = source_lock.validate(document)
        self.assertEqual(summary["failure_count"], 1)

    def test_failure_without_reason_is_rejected(self) -> None:
        document = self.mutation()
        record = document["records"][0]
        record.update(
            {
                "outcome": "failure",
                "http_status": 503,
                "byte_count": None,
                "sha256": None,
                "failure": None,
            }
        )
        self.rehash(document)
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_aggregate_hash_tamper_is_rejected(self) -> None:
        document = self.mutation()
        document["summary"]["aggregate_sha256"] = "0" * 64
        with self.assertRaisesRegex(source_lock.SourceLockError, "aggregate hash"):
            source_lock.validate(document)

    def test_total_byte_count_tamper_is_rejected(self) -> None:
        document = self.mutation()
        document["summary"]["total_byte_count"] += 1
        with self.assertRaisesRegex(source_lock.SourceLockError, "summary counts"):
            source_lock.validate(document)

    def test_recursive_provenance_tamper_is_rejected(self) -> None:
        document = self.mutation()
        record = next(
            item
            for item in document["records"]
            if "live_ledger" in item["referenced_by"]
        )
        record["referenced_by"].remove("recursive_fixed_point")
        self.rehash(document)
        with self.assertRaisesRegex(
            source_lock.SourceLockError, "exact provenance"
        ):
            source_lock.validate(document)

    def test_input_byte_hash_tamper_is_rejected(self) -> None:
        document = self.mutation()
        document["inputs"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            source_lock.SourceLockError, "input path or byte hash"
        ):
            source_lock.validate(document)

    def test_fetch_policy_tamper_is_rejected(self) -> None:
        document = self.mutation()
        document["fetch_policy"]["max_redirects"] = 4
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_semantic_proof_overclaim_is_rejected(self) -> None:
        document = self.mutation()
        document["interpretation"]["semantic_extraction_proof"] = True
        with self.assertRaises(source_lock.SourceLockError):
            source_lock.validate(document)

    def test_unknown_field_is_rejected_by_strict_schema(self) -> None:
        document = self.mutation()
        document["unreviewed"] = True
        with self.assertRaisesRegex(source_lock.SourceLockError, "schema violation"):
            source_lock.validate(document)

    def test_curl_invocation_disables_config_and_replaces_environment(self) -> None:
        def fake_run(command, **kwargs):
            self.assertEqual(command[0], source_lock.CURL_PATH)
            self.assertEqual(command[1], "--disable")
            self.assertNotIn("--location", command)
            self.assertEqual(kwargs["env"], source_lock.SANITIZED_ENV)
            self.assertNotIn("HOME", kwargs["env"])
            self.assertFalse(
                any(
                    "proxy" in key.lower() and value != "*"
                    for key, value in kwargs["env"].items()
                )
            )
            self.assertIn("Accept-Encoding: identity", command)
            Path(command[command.index("--dump-header") + 1]).write_bytes(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
            )
            Path(command[command.index("--output") + 1]).write_bytes(b"body")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="200\ntext/html\nhttps://docs.nvidia.com/vss/3.2.1/index.html",
                stderr="",
            )

        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(source_lock.subprocess, "run", side_effect=fake_run),
        ):
            response = source_lock._curl_once(
                "https://docs.nvidia.com/vss/3.2.1/index.html", Path(temp)
            )
        self.assertIsNone(response.error)
        self.assertEqual(response.content_encoding, "identity")

    def test_curl_effective_url_mismatch_is_an_error(self) -> None:
        def fake_run(command, **_kwargs):
            Path(command[command.index("--dump-header") + 1]).write_bytes(
                b"HTTP/1.1 200 OK\r\n\r\n"
            )
            Path(command[command.index("--output") + 1]).write_bytes(b"body")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="200\ntext/html\nhttps://docs.nvidia.com/vss/3.2.1/other.html",
                stderr="",
            )

        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(source_lock.subprocess, "run", side_effect=fake_run),
        ):
            response = source_lock._curl_once(
                "https://docs.nvidia.com/vss/3.2.1/index.html", Path(temp)
            )
        self.assertEqual(response.error, "curl changed URL without manual redirect")

    def test_fetch_rejects_transfer_error_with_partial_body(self) -> None:
        response = source_lock.CurlResponse(
            status=200,
            content_type="text/html",
            content_encoding="identity",
            body=b"partial",
            effective_url="https://docs.nvidia.com/vss/3.2.1/index.html",
            location=None,
            error="curl: transfer closed with bytes remaining",
        )
        with mock.patch.object(source_lock, "_curl_once", return_value=response):
            record = source_lock.fetch_url(
                "https://docs.nvidia.com/vss/3.2.1/index.html", ["live_ledger"]
            )
        self.assertEqual(record["outcome"], "failure")
        self.assertIsNone(record["byte_count"])
        self.assertIsNone(record["sha256"])

    def test_fetch_rejects_status_type_encoding_and_empty_body(self) -> None:
        cases = [
            (503, "text/html", "identity", b"error", "unexpected HTTP status"),
            (200, "application/json", "identity", b"{}", "unexpected content type"),
            (200, "text/html", "gzip", b"compressed", "unexpected content encoding"),
            (200, "text/html", "br", b"compressed", "unexpected content encoding"),
            (200, "text/html", "identity", b"", "empty response body"),
        ]
        url = "https://docs.nvidia.com/vss/3.2.1/index.html"
        for status, content_type, encoding, body, expected in cases:
            with self.subTest(
                status=status, content_type=content_type, encoding=encoding
            ):
                response = source_lock.CurlResponse(
                    status=status,
                    content_type=content_type,
                    content_encoding=encoding,
                    body=body,
                    effective_url=url,
                    location=None,
                    error=None,
                )
                with mock.patch.object(
                    source_lock, "_curl_once", return_value=response
                ):
                    record = source_lock.fetch_url(url, ["live_ledger"])
                self.assertIn(expected, record["failure"])

    def test_fetch_rejects_redirect_loop(self) -> None:
        first = "https://docs.nvidia.com/vss/3.2.1/a.html"
        second = "https://docs.nvidia.com/vss/3.2.1/b.html"

        def response(url, _work):
            return source_lock.CurlResponse(
                status=302,
                content_type="text/html",
                content_encoding="identity",
                body=b"redirect",
                effective_url=url,
                location=second if url == first else first,
                error=None,
            )

        with mock.patch.object(source_lock, "_curl_once", side_effect=response):
            record = source_lock.fetch_url(first, ["live_ledger"])
        self.assertEqual(record["failure"], "redirect loop detected")

    def test_fetch_rejects_redirect_limit(self) -> None:
        first = "https://docs.nvidia.com/vss/3.2.1/a.html"

        def response(url, _work):
            suffix = (
                int(url.rsplit("-", 1)[-1].split(".", 1)[0]) if "hop-" in url else 0
            )
            return source_lock.CurlResponse(
                status=302,
                content_type="text/html",
                content_encoding="identity",
                body=b"redirect",
                effective_url=url,
                location=f"https://docs.nvidia.com/vss/3.2.1/hop-{suffix + 1}.html",
                error=None,
            )

        with mock.patch.object(source_lock, "_curl_once", side_effect=response):
            record = source_lock.fetch_url(first, ["live_ledger"], max_redirects=1)
        self.assertEqual(record["failure"], "redirect limit exceeded (1)")

    def test_atomic_write_refuses_capture_date_relabel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lock.json"
            document = self.mutation()
            source_lock.atomic_write_json(path, document)
            self.assertEqual(source_lock.load_json(path), document)
            relabeled = copy.deepcopy(document)
            relabeled["captured_on"] = "2026-08-01"
            with self.assertRaisesRegex(source_lock.SourceLockError, "relabel"):
                source_lock.atomic_write_json(path, relabeled)

    def test_capture_date_must_be_explicit_and_valid(self) -> None:
        for value in ("", "2026-7-31", "2026-02-30"):
            with (
                self.subTest(value=value),
                self.assertRaises(source_lock.SourceLockError),
            ):
                source_lock.validate_capture_date(value)

    def test_build_rejects_non_snapshot_date_before_network(self) -> None:
        with (
            mock.patch.object(source_lock, "verify_curl_identity") as verify,
            self.assertRaisesRegex(source_lock.SourceLockError, "2026-07-31"),
        ):
            source_lock.build_lock("2026-08-01")
        verify.assert_not_called()

    def test_fetch_cli_requires_explicit_capture_date(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["source_lock.py", "fetch"]),
            mock.patch.object(source_lock, "build_lock") as build,
        ):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(source_lock.main(), 1)
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
