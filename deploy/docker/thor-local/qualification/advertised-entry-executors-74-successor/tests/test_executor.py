from __future__ import annotations

import ast
import _thread
import asyncio
import builtins
import concurrent.futures
import copy
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import multiprocessing
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock


LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_74_phase2_executor", LANE / "executor.py"
)
assert SPEC and SPEC.loader
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


class AdvertisedEntry74Phase2ExecutorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory, cls.migration = EXECUTOR.COMPILER.check_checked_artifacts()
        cls.receipt = EXECUTOR.check_checked_receipt()
        cls.candidates = [
            row for row in cls.inventory["rows"] if row["disposition"] == "candidate"
        ]

    def test_checked_receipt_is_exact_complete_and_deterministic(self) -> None:
        receipt = self.receipt
        self.assertEqual(receipt, EXECUTOR.execute())
        self.assertEqual(receipt["selection"]["executed_count"], 71)
        self.assertEqual(
            receipt["selection"]["per_wave_counts"],
            {"1": 1, "2": 18, "3": 23, "4": 5, "5": 5, "6": 8, "7": 11},
        )
        self.assertEqual(receipt["effect_trace"]["forbidden_effect_attempts"], 0)
        self.assertEqual(receipt["effect_trace"]["asyncio_socketpair_bootstraps"], 3)
        self.assertEqual(
            {result["entry_id"] for result in receipt["results"]},
            {row["entry_id"] for row in self.candidates},
        )
        for result in receipt["results"]:
            with self.subTest(entry_id=result["entry_id"]):
                self.assertEqual(result["run_count"], 2)
                self.assertEqual(
                    result["run_output_sha256"][0], result["run_output_sha256"][1]
                )
                self.assertFalse(result["historical_execute_or_main_called"])
                self.assertEqual(result["effect_trace"]["forbidden_effect_attempts"], 0)
                self.assertEqual(result["runtime_evidence"], [])
                self.assertFalse(result["can_mark_passed_current"])

    def test_receipt_schema_raw_and_payload_locks_are_exact(self) -> None:
        raw = EXECUTOR.COMPILER._read_package_bytes(EXECUTOR.RECEIPT_PATH)
        schema_raw = EXECUTOR.COMPILER._read_package_bytes(EXECUTOR.RESULT_SCHEMA_PATH)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(), EXECUTOR.EXPECTED_RECEIPT_RAW_SHA256
        )
        self.assertEqual(
            hashlib.sha256(schema_raw).hexdigest(),
            EXECUTOR.EXPECTED_RESULT_SCHEMA_RAW_SHA256,
        )
        payload = copy.deepcopy(self.receipt)
        expected = payload.pop("execution_payload_sha256")
        self.assertEqual(
            EXECUTOR._sha_bytes(EXECUTOR._canonical_bytes(payload)), expected
        )

    def test_nested_ast_receipt_matches_closed_allowlist(self) -> None:
        self.assertEqual(
            self.receipt["nested_ast_sha256"],
            {
                path: sorted(digests)
                for path, digests in EXECUTOR.EXPECTED_NESTED_AST_SHA256.items()
            },
        )

    def test_historical_builtins_are_an_explicit_restricted_allowlist(self) -> None:
        gate = EXECUTOR._NestedCodeGate({})
        restricted = EXECUTOR._restricted_builtins(1, gate)
        self.assertEqual(
            set(restricted),
            EXECUTOR.ALLOWED_BUILTIN_NAMES | {"__import__", "open", "compile", "exec"},
        )
        for name in ("eval", "input", "breakpoint", "help", "exit", "quit"):
            self.assertNotIn(name, restricted)
        with self.assertRaisesRegex(
            EXECUTOR.ExecutionError, "historical builtins.open"
        ):
            restricted["open"]("ignored")

    def test_one_representative_from_every_wave(self) -> None:
        for wave in range(1, 8):
            entry_id = next(
                row["entry_id"] for row in self.candidates if row["legacy_wave"] == wave
            )
            with self.subTest(wave=wave):
                report = EXECUTOR.execute([entry_id])
                self.assertEqual(report["selection"]["executed_count"], 1)
                self.assertEqual(report["results"][0]["legacy_wave"], wave)

    def test_invalid_selections_are_rejected_before_module_load(self) -> None:
        blocker = next(
            row["entry_id"]
            for row in self.inventory["rows"]
            if row["disposition"] == "external_blocker"
        )
        migrated = self.migration["migrations"][0]["former_gap_entry_id"]
        candidate = self.candidates[0]["entry_id"]
        selections = (
            ([], "empty explicit selection"),
            ([candidate, candidate], "duplicate --case"),
            ([blocker], "external blocker"),
            ([migrated], "migrated ID"),
            (["manifest-gap.unknown.00-nope"], "unknown candidate ID"),
        )
        for selected, message in selections:
            with (
                self.subTest(selected=selected),
                mock.patch.object(EXECUTOR, "_load_historical_module") as loader,
            ):
                with self.assertRaisesRegex(EXECUTOR.ExecutionError, message):
                    EXECUTOR.execute(selected)
                loader.assert_not_called()

    def test_dispatch_shapes_are_exact_and_never_call_execute_or_main(self) -> None:
        advertised = "literal"
        historical = {"entry_id": "legacy"}
        plan_by_id = {"plan": {}}
        manifest = {"features": []}
        for wave in range(1, 8):
            with self.subTest(wave=wave):
                adapter = mock.Mock()
                observe = mock.Mock()
                if wave <= 3:
                    adapter.return_value = ({"fixture": wave}, {"semantic": wave})
                elif wave <= 5:
                    adapter.return_value = ([True], [], {"wave": wave})
                elif wave == 6:
                    adapter.return_value = ([True], [], {"wave": wave}, {"route": True})
                else:
                    observe.return_value = {"wave": wave}
                module = types.SimpleNamespace(
                    ADAPTERS={"adapter": adapter},
                    _observe_case=observe,
                    execute=mock.Mock(
                        side_effect=AssertionError("historical execute called")
                    ),
                    main=mock.Mock(
                        side_effect=AssertionError("historical main called")
                    ),
                )
                row = {
                    "adapter_id": "adapter",
                    "entry_id": "case",
                    "advertised": advertised,
                }
                EXECUTOR._dispatch_once(
                    wave, module, row, historical, plan_by_id, manifest
                )
                module.execute.assert_not_called()
                module.main.assert_not_called()
                if wave == 1 or 4 <= wave <= 6:
                    adapter.assert_called_once_with()
                elif wave == 2:
                    adapter.assert_called_once_with(advertised)
                elif wave == 3:
                    adapter.assert_called_once_with(historical)
                else:
                    adapter.assert_not_called()
                    observe.assert_called_once_with(
                        EXECUTOR.REPO_ROOT, historical, plan_by_id, manifest
                    )

    def test_effect_guard_denies_representative_external_effects(self) -> None:
        operations = (
            lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
            lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM),
            lambda: socket.socketpair(),
            lambda: socket.getaddrinfo("localhost", 80),
            lambda: socket.create_server(("127.0.0.1", 0)),
            lambda: builtins.open("/tmp/phase2-forbidden", "w"),
            lambda: io.open("/tmp/phase2-forbidden", "w"),
            lambda: os.open("/tmp/phase2-forbidden", os.O_WRONLY | os.O_CREAT),
            lambda: os.ftruncate(1, 0),
            lambda: Path("/tmp/phase2-forbidden").touch(),
            lambda: os.mkdir("/tmp/phase2-forbidden"),
            lambda: os.link("source", "destination"),
            lambda: os.symlink("source", "destination"),
            lambda: os.chmod("ignored", 0o600),
            lambda: os.chown("ignored", 0, 0),
            lambda: os.utime("ignored"),
            lambda: os.mkfifo("/tmp/phase2-forbidden"),
            lambda: tempfile.NamedTemporaryFile(),
            lambda: shutil.copy("source", "destination"),
            lambda: subprocess.run(["true"]),
            lambda: os.fork(),
            lambda: os.execv("/bin/true", ["true"]),
            lambda: os.spawnv(os.P_WAIT, "/bin/true", ["true"]),
            lambda: threading.Thread(target=lambda: None).start(),
            lambda: _thread.start_new_thread(lambda: None, ()),
            lambda: multiprocessing.Process(target=lambda: None).start(),
            lambda: concurrent.futures.ThreadPoolExecutor().submit(lambda: None),
            lambda: asyncio.open_connection("localhost", 80),
            lambda: asyncio.create_subprocess_exec("true"),
            lambda: asyncio.BaseEventLoop.create_connection(None, None),
        )
        for operation in operations:
            with self.subTest(operation=operation), EXECUTOR._effect_guards() as trace:
                with self.assertRaisesRegex(
                    EXECUTOR.ExecutionError, "forbidden effect attempted"
                ):
                    operation()
                self.assertEqual(trace["forbidden_effect_attempts"], 1)

    def test_asyncio_loop_socketpair_is_the_only_socket_exception(self) -> None:
        with EXECUTOR._effect_guards() as trace:
            asyncio.run(asyncio.sleep(0))
        self.assertEqual(
            trace,
            {"asyncio_socketpair_bootstraps": 1, "forbidden_effect_attempts": 0},
        )

    def test_fd_reader_rejects_leaf_and_intermediate_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            (real / "value.txt").write_text("locked")
            (root / "leaf.txt").symlink_to(real / "value.txt")
            (root / "linked").symlink_to(real, target_is_directory=True)
            with mock.patch.object(EXECUTOR, "REPO_ROOT", root):
                for relative in ("leaf.txt", "linked/value.txt"):
                    with (
                        self.subTest(relative=relative),
                        self.assertRaisesRegex(
                            EXECUTOR.ExecutionError, "fd-anchored input rejected"
                        ),
                    ):
                        EXECUTOR._fd_read_once(relative)

    def test_fd_reader_rejects_identity_change_during_single_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("locked")
            real_fstat = os.fstat
            calls = 0

            def changing_fstat(fd: int) -> object:
                nonlocal calls
                calls += 1
                observed = real_fstat(fd)
                if calls == 1:
                    return observed
                values = {
                    name: getattr(observed, name)
                    for name in (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                    )
                }
                values["st_mtime_ns"] += 1
                return types.SimpleNamespace(**values)

            with (
                mock.patch.object(EXECUTOR, "REPO_ROOT", root),
                mock.patch.object(EXECUTOR.os, "fstat", side_effect=changing_fstat),
            ):
                with self.assertRaisesRegex(
                    EXECUTOR.ExecutionError, "changed while reading"
                ):
                    EXECUTOR._fd_read_once("value.txt")

    def test_historical_loader_rejects_import_and_main_guard_drift(self) -> None:
        lock = self.inventory["historical_waves"][0]
        source_files = {
            row["path"]: row["sha256"] for row in self.inventory["source_files"]
        }
        with mock.patch.object(EXECUTOR, "_import_statements", return_value=set()):
            with self.assertRaisesRegex(
                EXECUTOR.ExecutionError, "import allowlist drift"
            ):
                EXECUTOR._load_historical_module(lock, source_files)

        real_parse = ast.parse

        def without_main_guard(*args: object, **kwargs: object) -> ast.Module:
            tree = real_parse(*args, **kwargs)
            tree.body = [
                node
                for node in tree.body
                if not (
                    isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "__name__"
                )
            ]
            return tree

        with mock.patch.object(EXECUTOR.ast, "parse", side_effect=without_main_guard):
            with self.assertRaisesRegex(
                EXECUTOR.ExecutionError, "__main__ guard drift"
            ):
                EXECUTOR._load_historical_module(lock, source_files)

    def test_nested_code_gate_rejects_unapproved_ast_and_unregistered_exec(
        self,
    ) -> None:
        path = next(iter(EXECUTOR.EXPECTED_NESTED_AST_SHA256))
        digest = next(
            row["sha256"]
            for row in self.inventory["source_files"]
            if row["path"] == path
        )
        gate = EXECUTOR._NestedCodeGate({path: digest})
        with self.assertRaisesRegex(
            EXECUTOR.ExecutionError, "filename is not source-locked"
        ):
            gate.compile(ast.Module(body=[], type_ignores=[]), "unknown.py", "exec")
        with self.assertRaisesRegex(EXECUTOR.ExecutionError, "AST shape digest drift"):
            gate.compile(ast.Module(body=[], type_ignores=[]), path, "exec")
        code = compile("value = 1", "registered.py", "exec")
        with self.assertRaisesRegex(EXECUTOR.ExecutionError, "unregistered code"):
            gate.exec(code, {})

    def test_legacy_reader_is_reduced_to_selected_case_capability(self) -> None:
        lock = next(
            row for row in self.inventory["historical_waves"] if row["wave"] == 2
        )
        source_files = {
            row["path"]: row["sha256"] for row in self.inventory["source_files"]
        }
        module, _gate = EXECUTOR._load_historical_module(lock, source_files)
        historical, _raw = EXECUTOR.COMPILER._load_locked_json(
            {"path": lock["inventory_path"], "raw_sha256": lock["inventory_sha256"]},
            "Wave 2 historical inventory",
        )
        case = historical["cases"][0]
        selected = {row["path"]: row["sha256"] for row in case["source_locks"]}
        path = next(iter(selected))
        EXECUTOR._CASE_LOCAL.source_locks = selected
        try:
            self.assertEqual(
                hashlib.sha256(module._read_bytes(path)).hexdigest(), selected[path]
            )
            with self.assertRaisesRegex(
                EXECUTOR.ExecutionError, "outside selected capability"
            ):
                module._read_bytes(lock["executor_path"])
        finally:
            EXECUTOR._CASE_LOCAL.source_locks = None

    def test_run_rejects_wrong_shape_nondeterminism_and_source_change(self) -> None:
        row = {
            "entry_id": "manifest-gap.synthetic.00-case",
            "manifest_pointer": "/features/0/advertised/0",
            "proposed_capability_id": "manifest-entry.synthetic.00-case",
            "legacy_wave": 1,
            "adapter_id": "adapter",
            "legacy_row_canonical_sha256": EXECUTOR.COMPILER._sha_json({}),
        }
        stable_sources = {"source.py": "0" * 64}
        with mock.patch.object(
            EXECUTOR, "_verify_case_sources", return_value=stable_sources
        ):
            module = types.SimpleNamespace(
                ADAPTERS={"adapter": lambda: {"wrong": True}}
            )
            with self.assertRaisesRegex(EXECUTOR.ExecutionError, "return shape drift"):
                EXECUTOR._run_case_twice(module, row, {}, {}, {})

            calls = iter((({"fixture": 1}, 1), ({"fixture": 2}, 2)))
            module = types.SimpleNamespace(ADAPTERS={"adapter": lambda: next(calls)})
            with self.assertRaisesRegex(EXECUTOR.ExecutionError, "nondeterministic"):
                EXECUTOR._run_case_twice(module, row, {}, {}, {})

        module = types.SimpleNamespace(ADAPTERS={"adapter": lambda: ({}, {})})
        with mock.patch.object(
            EXECUTOR,
            "_verify_case_sources",
            side_effect=({"source.py": "0" * 64}, {"source.py": "1" * 64}),
        ):
            with self.assertRaisesRegex(
                EXECUTOR.ExecutionError, "changed during adapter call"
            ):
                EXECUTOR._run_case_twice(module, row, {}, {}, {})

    def test_result_schema_rejects_tamper(self) -> None:
        tampered = copy.deepcopy(self.receipt)
        tampered["unexpected"] = True
        schema_raw = EXECUTOR.COMPILER._read_package_bytes(EXECUTOR.RESULT_SCHEMA_PATH)
        with self.assertRaisesRegex(EXECUTOR.ExecutionError, "result schema failed"):
            EXECUTOR._validate_schema(tampered, schema_raw)


if __name__ == "__main__":
    unittest.main()
