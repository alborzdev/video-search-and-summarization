#!/usr/bin/env python3
"""Guarded direct dispatcher for the 71 retained advertised-entry candidates."""

from __future__ import annotations

import argparse
import ast
import builtins
from collections import Counter
from contextlib import ExitStack, contextmanager
import _thread
import asyncio
import concurrent.futures
import hashlib
import importlib.util
import inspect
import io
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import types
from typing import Any, Iterator
from unittest import mock

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
RESULT_SCHEMA_PATH = LANE / "result.schema.json"
RECEIPT_PATH = LANE / "execution-receipt.json"

COMPILER_SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_74_successor_compiler", LANE / "compiler.py"
)
if COMPILER_SPEC is None or COMPILER_SPEC.loader is None:
    raise RuntimeError("unable to load successor compiler")
COMPILER = importlib.util.module_from_spec(COMPILER_SPEC)
sys.modules[COMPILER_SPEC.name] = COMPILER
COMPILER_SPEC.loader.exec_module(COMPILER)

EXPECTED_RESULT_SCHEMA_RAW_SHA256 = (
    "9776016ef702a0437e1926d28a243a5a6e1a135dfd83226c2a9718546c584a43"
)
EXPECTED_RECEIPT_RAW_SHA256 = (
    "acfe8215c0666a990109e2e1d34a531ba5c2b3c2fa415f7cf901c5e7bddec99c"
)

MAX_EXECUTOR_BYTES = 2_000_000
_REAL_IMPORT = builtins.__import__
_REAL_COMPILE = builtins.compile
_REAL_EXEC = builtins.exec
_REAL_OPEN = builtins.open
_REAL_IO_OPEN = io.open
_REAL_OS_OPEN = os.open
_REAL_SOCKET = socket.socket
_REAL_SOCKETPAIR = socket.socketpair
_GUARD_LOCK = threading.RLock()
_GUARD_LOCAL = threading.local()
_CASE_LOCAL = threading.local()

EXPECTED_IMPORTS = {
    1: {
        ("from", "__future__", ("annotations",)),
        ("import", "argparse", ()),
        ("import", "ast", ()),
        ("import", "datetime", ()),
        ("import", "hashlib", ()),
        ("import", "io", ()),
        ("import", "json", ()),
        ("import", "logging", ()),
        ("import", "math", ()),
        ("import", "posixpath", ()),
        ("import", "re", ()),
        ("from", "abc", ("ABC", "abstractmethod")),
        ("from", "pathlib", ("Path",)),
        ("from", "types", ("SimpleNamespace",)),
        (
            "from",
            "typing",
            ("Any", "Dict", "Iterable", "List", "Optional", "Tuple", "Union"),
        ),
        ("import", "cv2", ()),
        ("import", "numpy", ()),
        ("from", "jsonschema", ("Draft202012Validator",)),
        ("from", "jsonschema.exceptions", ("SchemaError",)),
        ("from", "scipy.optimize", ("linear_sum_assignment",)),
    },
    2: {
        ("from", "__future__", ("annotations",)),
        ("import", "argparse", ()),
        ("import", "ast", ()),
        ("import", "asyncio", ()),
        ("import", "base64", ()),
        ("import", "copy", ()),
        ("import", "datetime", ()),
        ("import", "hashlib", ()),
        ("import", "io", ()),
        ("import", "json", ()),
        ("import", "math", ()),
        ("import", "posixpath", ()),
        ("import", "re", ()),
        ("from", "collections", ("Counter", "defaultdict", "deque")),
        ("from", "pathlib", ("Path",)),
        ("from", "types", ("SimpleNamespace",)),
        (
            "from",
            "typing",
            (
                "Any",
                "Dict",
                "Iterable",
                "List",
                "MutableMapping",
                "Optional",
                "Set",
                "Tuple",
            ),
        ),
        ("import", "numpy", ()),
        ("from", "jsonschema", ("Draft202012Validator",)),
        ("from", "jsonschema.exceptions", ("SchemaError",)),
    },
    3: {
        ("from", "__future__", ("annotations",)),
        ("import", "argparse", ()),
        ("import", "ast", ()),
        ("import", "hashlib", ()),
        ("import", "json", ()),
        ("from", "pathlib", ("Path",)),
        ("from", "typing", ("Any",)),
        ("from", "jsonschema", ("Draft202012Validator",)),
        ("from", "jsonschema.exceptions", ("SchemaError",)),
    },
    4: {
        ("from", "__future__", ("annotations",)),
        ("import", "argparse", ()),
        ("import", "ast", ()),
        ("import", "hashlib", ()),
        ("import", "json", ()),
        ("from", "pathlib", ("Path", "PurePosixPath")),
        ("import", "re", ()),
        ("import", "stat", ()),
        ("from", "typing", ("Any", "Callable")),
        ("from", "jsonschema", ("Draft202012Validator",)),
        ("from", "jsonschema.exceptions", ("SchemaError",)),
        ("import", "yaml", ()),
    },
    5: {
        ("from", "__future__", ("annotations",)),
        ("import", "argparse", ()),
        ("import", "hashlib", ()),
        ("import", "json", ()),
        ("from", "pathlib", ("Path", "PurePosixPath")),
        ("import", "re", ()),
        ("import", "stat", ()),
        ("from", "typing", ("Any", "Callable")),
        ("from", "jsonschema", ("Draft202012Validator",)),
        ("from", "jsonschema.exceptions", ("SchemaError",)),
    },
    6: {
        ("from", "__future__", ("annotations",)),
        ("import", "argparse", ()),
        ("import", "hashlib", ()),
        ("import", "json", ()),
        ("from", "pathlib", ("Path", "PurePosixPath")),
        ("import", "stat", ()),
        ("from", "typing", ("Any", "Callable")),
        ("from", "jsonschema", ("Draft202012Validator",)),
        ("from", "jsonschema.exceptions", ("SchemaError",)),
    },
    7: {
        ("from", "__future__", ("annotations",)),
        ("import", "argparse", ()),
        ("import", "hashlib", ()),
        ("import", "json", ()),
        ("import", "stat", ()),
        ("from", "pathlib", ("Path", "PurePosixPath")),
        ("from", "typing", ("Any",)),
        ("from", "jsonschema", ("Draft202012Validator",)),
        ("from", "jsonschema.exceptions", ("SchemaError",)),
    },
}

EXPECTED_NESTED_AST_SHA256: dict[str, set[str]] = {
    "services/rtvi/rt-vlm/src/api_models/common.py": {
        "8d4ab32e77fc3d16b4ef3e789c131fa388bf1fdc3368d92af709e2ed9290fe7f"
    },
    "services/rtvi/rt-vlm/src/api_models/live_stream.py": {
        "69aab569c98e7d3a30979d6dff0ea76f34abb0c1ca1f34bdf37e67828c50fa25"
    },
    "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py": {
        "2d82a82f70afb2d7c0affe88e4984012340b0fe34034df87e527c95fc8d72ecb",
        "9e3c75fd91ae05a405f7b3da625e721f53bb7455872cd6d9404f112d5a1ae8a3",
        "a450f82d8292c4b0d9c603e91dcdd5c5d7177b7d002631c768a8a83d36b3c89e",
        "ca979dcda76be56af4d650ac121e83614ef1965b30220f965baaa8766d22b9d8",
        "f4fd8ad25f4a90c450cdd64ce3e94a57b8b62834e02cc62fc48973e36d9654b1",
    },
    "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py": {
        "5f23c25b5e4379975426b5d3d239c3f846f2fa7b7d4277c2b7c37bd722c6010c",
        "a6ebc14a3020904382342a656c8ecbba6c2cb2d11448c5d7604a2bfa6dcd919e",
    },
    "services/rtvi/rt-vlm/src/utils/asset_manager.py": {
        "2905e54dbdd634606ccdf5f097b5bb05cfaea59f6329a76260a8ff6da3363fbf",
        "91b95c332b7dec30fd2a71092d22a54255e2651641f6ef44d6d0a7707e9e8954",
        "e67ae86fb7722ef05e3d82a0f6813819197990b951c42ea2adeb79cc501672fd",
        "f3719aeb776769c753fbceb5e01c00cadce8f3c5325867f23d7cf06885c6713d",
    },
    "services/rtvi/rt-vlm/src/utils/dense_caption_serializer.py": {
        "acd27781546aca61f7ac34a2dbb224b9894346202f455093eeeb4dcddbd54d93"
    },
    "services/rtvi/rt-vlm/src/utils/media_io_kwargs.py": {
        "e7a68db4193918ab46ec36e08a7d51f08fd7d2085072162161d73f665136e089"
    },
    "services/rtvi/rt-vlm/src/vlm_pipeline/video_file_frame_getter.py": {
        "6cadccbc01bba0dfc44fd01a067e4b292eb08d7982cd9755e41273658f49af1e",
        "c4c245053633ba9173d6bc3591cf3c5b3eba478f783d8bd34a457256816e275b",
    },
}
RUNTIME_SUPPORT_IMPORTS = {"_strptime", "time"}
ALLOWED_BUILTIN_NAMES = {
    "AssertionError",
    "AttributeError",
    "BaseException",
    "ConnectionError",
    "Exception",
    "FileExistsError",
    "FileNotFoundError",
    "ImportError",
    "IndexError",
    "KeyError",
    "KeyboardInterrupt",
    "ModuleNotFoundError",
    "NotImplementedError",
    "OSError",
    "PermissionError",
    "RuntimeError",
    "StopIteration",
    "SyntaxError",
    "SystemExit",
    "TypeError",
    "UnicodeDecodeError",
    "ValueError",
    "ZeroDivisionError",
    "__build_class__",
    "__doc__",
    "__name__",
    "abs",
    "all",
    "any",
    "bool",
    "bytearray",
    "bytes",
    "classmethod",
    "dict",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "hash",
    "id",
    "int",
    "isinstance",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "print",
    "property",
    "range",
    "reversed",
    "round",
    "set",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip",
}


class ExecutionError(RuntimeError):
    """A selection, lock, guard, adapter, shape, or determinism check failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ExecutionError("adapter output is not finite canonical JSON") from exc


def _json_value(value: Any) -> Any:
    return json.loads(_canonical_bytes(value))


def _fd_read_once(relative: str, *, max_bytes: int = MAX_EXECUTOR_BYTES) -> bytes:
    pure = Path(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ExecutionError(f"unsafe fd-anchored path: {relative}")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        descriptor = _REAL_OS_OPEN(REPO_ROOT, directory_flags)
        descriptors.append(descriptor)
        for part in pure.parts[:-1]:
            descriptor = _REAL_OS_OPEN(part, directory_flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        descriptor = _REAL_OS_OPEN(pure.parts[-1], file_flags, dir_fd=descriptor)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ExecutionError(f"fd-anchored input is not a regular file: {relative}")
        if before.st_size > max_bytes:
            raise ExecutionError(f"fd-anchored input exceeds size bound: {relative}")
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after or len(payload) != before.st_size:
            raise ExecutionError(f"fd-anchored input changed while reading: {relative}")
        return payload
    except OSError as exc:
        raise ExecutionError(f"fd-anchored input rejected: {relative}") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _import_statements(tree: ast.Module) -> set[tuple[str, str, tuple[str, ...]]]:
    statements: set[tuple[str, str, tuple[str, ...]]] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            statements.update(("import", alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            statements.add(
                ("from", node.module or "", tuple(alias.name for alias in node.names))
            )
    return statements


def _preload_imports(wave: int) -> set[str]:
    names = {item[1] for item in EXPECTED_IMPORTS[wave]} | RUNTIME_SUPPORT_IMPORTS
    for name in sorted(names):
        _REAL_IMPORT(name, fromlist=("*",))
    return names


def _restricted_importer(allowed: set[str]):
    def restricted_import(
        name: str,
        _globals: dict[str, Any] | None = None,
        _locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if level != 0 or name not in allowed or name not in sys.modules:
            raise ExecutionError(f"historical import is not preapproved: {name}")
        if fromlist:
            return sys.modules[name]
        root = name.split(".", 1)[0]
        if root not in sys.modules:
            raise ExecutionError(f"historical import root is not preloaded: {root}")
        return sys.modules[root]

    return restricted_import


class _NestedCodeGate:
    def __init__(self, allowed_sources: dict[str, str]) -> None:
        self.allowed_sources = allowed_sources
        self.registered: dict[int, str] = {}
        self.observed: dict[str, set[str]] = {}

    def compile(
        self,
        source: Any,
        filename: str,
        mode: str,
        flags: int = 0,
        dont_inherit: bool = False,
        optimize: int = -1,
        **_kwargs: Any,
    ) -> types.CodeType:
        if not isinstance(source, ast.Module) or mode != "exec" or flags != 0:
            raise ExecutionError(
                "nested compile requires a registered AST Module in exec mode"
            )
        if filename not in self.allowed_sources:
            raise ExecutionError(
                f"nested compile filename is not source-locked: {filename}"
            )
        raw = _fd_read_once(filename)
        if _sha_bytes(raw) != self.allowed_sources[filename]:
            raise ExecutionError(f"nested compile source digest drift: {filename}")
        digest = _sha_bytes(ast.dump(source, include_attributes=False).encode())
        self.observed.setdefault(filename, set()).add(digest)
        expected = EXPECTED_NESTED_AST_SHA256.get(filename)
        if expected is None or digest not in expected:
            raise ExecutionError(f"nested AST shape digest drift: {filename}: {digest}")
        code = _REAL_COMPILE(
            source,
            filename,
            mode,
            flags=flags,
            dont_inherit=dont_inherit,
            optimize=optimize,
        )
        self.registered[id(code)] = digest
        return code

    def exec(
        self,
        code: Any,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(code, types.CodeType) or id(code) not in self.registered:
            raise ExecutionError("nested exec rejected unregistered code")
        if not isinstance(globals, dict):
            raise ExecutionError("nested exec requires an explicit scope")
        globals["__builtins__"] = globals.get("__builtins__", {})
        _REAL_EXEC(code, globals, globals if locals is None else locals)


def _restricted_builtins(wave: int, gate: _NestedCodeGate) -> dict[str, Any]:
    allowed_imports = _preload_imports(wave)
    result = {name: vars(builtins)[name] for name in ALLOWED_BUILTIN_NAMES}
    result["__import__"] = _restricted_importer(allowed_imports)
    result["open"] = _deny("historical builtins.open")
    result["compile"] = gate.compile
    result["exec"] = gate.exec
    return result


def _deny(operation: str):
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise ExecutionError(f"forbidden effect attempted: {operation}")

    return denied


@contextmanager
def _effect_guards() -> Iterator[dict[str, int]]:
    trace = {"asyncio_socketpair_bootstraps": 0, "forbidden_effect_attempts": 0}

    def denied(operation: str):
        def reject(*_args: Any, **_kwargs: Any) -> Any:
            trace["forbidden_effect_attempts"] += 1
            raise ExecutionError(f"forbidden effect attempted: {operation}")

        return reject

    def guarded_socket(
        family: int = socket.AF_INET,
        type: int = socket.SOCK_STREAM,
        proto: int = 0,
        fileno: int | None = None,
    ) -> socket.socket:
        allowed = getattr(_GUARD_LOCAL, "asyncio_socketpair", False)
        if (
            not allowed
            or (family, type, proto) != (socket.AF_UNIX, socket.SOCK_STREAM, 0)
            or (fileno is not None and not isinstance(fileno, int))
        ):
            return denied("direct socket construction")(family, type, proto, fileno)
        return _REAL_SOCKET(family, type, proto, fileno)

    def guarded_socketpair(
        family: int = socket.AF_UNIX,
        type: int = socket.SOCK_STREAM,
        proto: int = 0,
    ) -> tuple[socket.socket, socket.socket]:
        frame = inspect.currentframe()
        caller_is_asyncio = False
        try:
            frame = frame.f_back if frame is not None else None
            while frame is not None:
                module_name = frame.f_globals.get("__name__", "")
                if module_name.startswith("asyncio."):
                    caller_is_asyncio = True
                    break
                frame = frame.f_back
        finally:
            del frame
        if not caller_is_asyncio or (family, type, proto) != (
            socket.AF_UNIX,
            socket.SOCK_STREAM,
            0,
        ):
            return denied("non-asyncio socketpair")(family, type, proto)
        _GUARD_LOCAL.asyncio_socketpair = True
        try:
            pair = _REAL_SOCKETPAIR(family, type, proto)
        finally:
            _GUARD_LOCAL.asyncio_socketpair = False
        trace["asyncio_socketpair_bootstraps"] += 1
        return pair

    path_mutations = (
        "write_text",
        "write_bytes",
        "touch",
        "mkdir",
        "unlink",
        "rename",
        "replace",
        "rmdir",
        "symlink_to",
        "hardlink_to",
        "chmod",
        "lchmod",
        "owner",
    )
    os_mutations = (
        "remove",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "makedirs",
        "rmdir",
        "removedirs",
        "truncate",
        "link",
        "symlink",
        "chmod",
        "chown",
        "lchown",
        "utime",
        "mknod",
        "mkfifo",
    )
    subprocess_calls = (
        "run",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    )
    tempfile_calls = (
        "NamedTemporaryFile",
        "TemporaryFile",
        "SpooledTemporaryFile",
        "TemporaryDirectory",
        "mkstemp",
        "mkdtemp",
    )
    shutil_mutations = (
        "copy",
        "copy2",
        "copyfile",
        "copytree",
        "move",
        "rmtree",
    )
    os_process_calls = tuple(
        name
        for name in dir(os)
        if name == "fork"
        or name == "forkpty"
        or name.startswith("exec")
        or name.startswith("spawn")
        or name.startswith("posix_spawn")
    )
    socket_apis = (
        "create_connection",
        "create_server",
        "fromfd",
        "fromshare",
        "getaddrinfo",
        "gethostbyaddr",
        "gethostbyname",
        "gethostbyname_ex",
        "getnameinfo",
    )
    asyncio_apis = (
        "open_connection",
        "open_unix_connection",
        "start_server",
        "start_unix_server",
        "create_subprocess_exec",
        "create_subprocess_shell",
        "to_thread",
    )
    loop_apis = (
        "create_connection",
        "create_server",
        "create_unix_connection",
        "create_unix_server",
        "subprocess_exec",
        "subprocess_shell",
        "run_in_executor",
    )

    def patch_if_present(
        stack: ExitStack, owner: Any, name: str, operation: str
    ) -> None:
        if hasattr(owner, name):
            stack.enter_context(mock.patch.object(owner, name, denied(operation)))

    with _GUARD_LOCK, ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(builtins, "open", denied("builtins.open"))
        )
        stack.enter_context(mock.patch.object(io, "open", denied("io.open")))
        stack.enter_context(mock.patch.object(os, "open", denied("os.open")))
        stack.enter_context(mock.patch.object(os, "fdopen", denied("os.fdopen")))
        stack.enter_context(mock.patch.object(os, "ftruncate", denied("os.ftruncate")))
        stack.enter_context(mock.patch.object(socket, "socket", guarded_socket))
        stack.enter_context(mock.patch.object(socket, "socketpair", guarded_socketpair))
        for name in socket_apis:
            patch_if_present(stack, socket, name, f"socket.{name}")
        stack.enter_context(
            mock.patch.object(subprocess, "Popen", denied("subprocess.Popen"))
        )
        for name in subprocess_calls:
            stack.enter_context(
                mock.patch.object(subprocess, name, denied(f"subprocess.{name}"))
            )
        stack.enter_context(mock.patch.object(os, "system", denied("os.system")))
        stack.enter_context(mock.patch.object(os, "popen", denied("os.popen")))
        for name in os_process_calls:
            patch_if_present(stack, os, name, f"os.{name}")
        for name in path_mutations:
            patch_if_present(stack, Path, name, f"Path.{name}")
        for name in os_mutations:
            patch_if_present(stack, os, name, f"os.{name}")
        for name in tempfile_calls:
            patch_if_present(stack, tempfile, name, f"tempfile.{name}")
        for name in shutil_mutations:
            patch_if_present(stack, shutil, name, f"shutil.{name}")
        stack.enter_context(
            mock.patch.object(
                threading.Thread, "start", denied("threading.Thread.start")
            )
        )
        stack.enter_context(
            mock.patch.object(
                _thread, "start_new_thread", denied("_thread.start_new_thread")
            )
        )
        stack.enter_context(
            mock.patch.object(
                multiprocessing.Process,
                "start",
                denied("multiprocessing.Process.start"),
            )
        )
        stack.enter_context(
            mock.patch.object(
                concurrent.futures.ThreadPoolExecutor,
                "submit",
                denied("ThreadPoolExecutor.submit"),
            )
        )
        for name in asyncio_apis:
            patch_if_present(stack, asyncio, name, f"asyncio.{name}")
        for name in loop_apis:
            patch_if_present(stack, asyncio.BaseEventLoop, name, f"event_loop.{name}")
        yield trace


def _load_historical_module(
    lock: dict[str, Any], source_files: dict[str, str]
) -> tuple[types.ModuleType, _NestedCodeGate]:
    relative = lock["executor_path"]
    raw = _fd_read_once(relative)
    if _sha_bytes(raw) != lock["executor_sha256"]:
        raise ExecutionError(f"historical executor digest drift: Wave {lock['wave']}")
    try:
        tree = ast.parse(raw, filename=relative)
    except SyntaxError as exc:
        raise ExecutionError(
            f"historical executor AST parse failed: Wave {lock['wave']}"
        ) from exc
    if _import_statements(tree) != EXPECTED_IMPORTS[lock["wave"]]:
        raise ExecutionError(
            f"historical executor import allowlist drift: Wave {lock['wave']}"
        )
    main_guards: list[ast.If] = []
    retained_body: list[ast.stmt] = []
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
            and not node.orelse
        ):
            main_guards.append(node)
        else:
            retained_body.append(node)
    if len(main_guards) != 1:
        raise ExecutionError(f"historical __main__ guard drift: Wave {lock['wave']}")
    tree.body = retained_body
    ast.fix_missing_locations(tree)
    gate = _NestedCodeGate(source_files)
    module_name = f"_advertised_entry_successor_wave_{lock['wave']}"
    module = types.ModuleType(module_name)
    module.__file__ = str(REPO_ROOT / relative)
    module.__package__ = ""
    module.__dict__["__builtins__"] = _restricted_builtins(lock["wave"], gate)
    try:
        code = _REAL_COMPILE(tree, relative, "exec", dont_inherit=True)
        _REAL_EXEC(code, module.__dict__)
    except Exception as exc:
        raise ExecutionError(
            f"historical executor load failed: Wave {lock['wave']}"
        ) from exc

    def selected_source_read(
        relative_path: str, *, max_bytes: int = MAX_EXECUTOR_BYTES
    ) -> bytes:
        allowed = getattr(_CASE_LOCAL, "source_locks", None)
        if not isinstance(allowed, dict) or relative_path not in allowed:
            raise ExecutionError(
                f"adapter source read is outside selected capability: {relative_path}"
            )
        payload = _fd_read_once(relative_path, max_bytes=max_bytes)
        if _sha_bytes(payload) != allowed[relative_path]:
            raise ExecutionError(f"adapter source digest drift: {relative_path}")
        return payload

    if lock["wave"] <= 6:
        module._read_bytes = selected_source_read
    else:

        def selected_wave7_read(
            repo_root: Path,
            relative_path: str,
            *,
            max_bytes: int = MAX_EXECUTOR_BYTES,
        ) -> bytes:
            if repo_root.resolve() != REPO_ROOT.resolve():
                raise ExecutionError("Wave 7 repository root drift")
            return selected_source_read(relative_path, max_bytes=max_bytes)

        module._read_repo_bytes = selected_wave7_read
    return module, gate


def _historical_cases(
    inventory: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    cases: dict[str, dict[str, Any]] = {}
    locks: dict[int, dict[str, Any]] = {}
    for lock in inventory["historical_waves"]:
        historical, _raw = COMPILER._load_locked_json(
            {"path": lock["inventory_path"], "raw_sha256": lock["inventory_sha256"]},
            f"Wave {lock['wave']} historical inventory",
        )
        locks[lock["wave"]] = lock
        for row in historical["cases"]:
            entry_id = row["entry_id"]
            if entry_id in cases:
                raise ExecutionError(f"duplicate historical case: {entry_id}")
            cases[entry_id] = row
    return cases, locks


def _verify_case_sources(case: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    locks = case.get("source_locks")
    if not isinstance(locks, list) or not locks:
        raise ExecutionError(f"case has no source locks: {case.get('entry_id')}")
    for lock in locks:
        path = lock["path"]
        if path in observed:
            raise ExecutionError(
                f"duplicate case source lock: {case['entry_id']}: {path}"
            )
        digest = _sha_bytes(_fd_read_once(path))
        if digest != lock["sha256"]:
            raise ExecutionError(
                f"case source digest drift: {case['entry_id']}: {path}"
            )
        observed[path] = digest
    return observed


def _dispatch_once(
    wave: int,
    module: types.ModuleType,
    inventory_row: dict[str, Any],
    historical_case: dict[str, Any],
    plan_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    adapter_id = inventory_row["adapter_id"]
    try:
        if wave == 1:
            returned = module.ADAPTERS[adapter_id]()
            if not isinstance(returned, tuple) or len(returned) != 2:
                raise ExecutionError("Wave 1 adapter return shape drift")
            fixture, semantic_output = returned
            return {"fixture": fixture, "semantic_output": semantic_output}
        if wave == 2:
            returned = module.ADAPTERS[adapter_id](inventory_row["advertised"])
            if not isinstance(returned, tuple) or len(returned) != 2:
                raise ExecutionError("Wave 2 adapter return shape drift")
            fixture, semantic_output = returned
            return {"fixture": fixture, "semantic_output": semantic_output}
        if wave == 3:
            returned = module.ADAPTERS[adapter_id](historical_case)
            if not isinstance(returned, tuple) or len(returned) != 2:
                raise ExecutionError("Wave 3 adapter return shape drift")
            fixture, semantic_output = returned
            return {"fixture": fixture, "semantic_output": semantic_output}
        if wave in (4, 5):
            returned = module.ADAPTERS[adapter_id]()
            if not isinstance(returned, tuple) or len(returned) != 3:
                raise ExecutionError(f"Wave {wave} adapter return shape drift")
            assertions, edges, detail = returned
            return {"assertions": assertions, "edges": edges, "detail": detail}
        if wave == 6:
            returned = module.ADAPTERS[adapter_id]()
            if not isinstance(returned, tuple) or len(returned) != 4:
                raise ExecutionError("Wave 6 adapter return shape drift")
            assertions, edges, detail, route_state = returned
            return {
                "assertions": assertions,
                "edges": edges,
                "detail": detail,
                "route_state": route_state,
            }
        if wave == 7:
            returned = module._observe_case(
                REPO_ROOT, historical_case, plan_by_id, manifest
            )
            if not isinstance(returned, dict):
                raise ExecutionError("Wave 7 adapter return shape drift")
            return returned
    except ExecutionError:
        raise
    except Exception as exc:
        raise ExecutionError(
            f"direct adapter failed: {inventory_row['entry_id']}"
        ) from exc
    raise ExecutionError(f"unsupported historical wave: {wave}")


def _run_case_twice(
    module: types.ModuleType,
    inventory_row: dict[str, Any],
    historical_case: dict[str, Any],
    plan_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    entry_id = inventory_row["entry_id"]
    if (
        COMPILER._sha_json(historical_case)
        != inventory_row["legacy_row_canonical_sha256"]
    ):
        raise ExecutionError(f"historical row canonical drift: {entry_id}")
    source_runs: list[dict[str, str]] = []
    outputs: list[dict[str, Any]] = []
    effect_traces: list[dict[str, int]] = []
    for _run in range(2):
        before = _verify_case_sources(historical_case)
        _CASE_LOCAL.source_locks = before
        try:
            with _effect_guards() as trace:
                output = _dispatch_once(
                    inventory_row["legacy_wave"],
                    module,
                    inventory_row,
                    historical_case,
                    plan_by_id,
                    manifest,
                )
        finally:
            _CASE_LOCAL.source_locks = None
        after = _verify_case_sources(historical_case)
        if before != after:
            raise ExecutionError(f"source changed during adapter call: {entry_id}")
        source_runs.append(before)
        outputs.append(_json_value(output))
        effect_traces.append(dict(trace))
    if source_runs[0] != source_runs[1]:
        raise ExecutionError(f"source digest changed between runs: {entry_id}")
    output_hashes = [_sha_bytes(_canonical_bytes(output)) for output in outputs]
    if output_hashes[0] != output_hashes[1] or outputs[0] != outputs[1]:
        raise ExecutionError(f"adapter output is nondeterministic: {entry_id}")
    if effect_traces[0] != effect_traces[1]:
        raise ExecutionError(f"adapter effect trace is nondeterministic: {entry_id}")
    if effect_traces[0]["forbidden_effect_attempts"] != 0:
        raise ExecutionError(f"adapter attempted a forbidden effect: {entry_id}")
    return {
        "entry_id": entry_id,
        "manifest_pointer": inventory_row["manifest_pointer"],
        "proposed_capability_id": inventory_row["proposed_capability_id"],
        "legacy_wave": inventory_row["legacy_wave"],
        "adapter_id": inventory_row["adapter_id"],
        "observation": "observed_deterministic_candidate_match",
        "dispatch": "direct_historical_adapter",
        "historical_execute_or_main_called": False,
        "source_sha256": source_runs[0],
        "source_tree_sha256": _sha_bytes(_canonical_bytes(source_runs[0])),
        "run_count": 2,
        "run_output_sha256": output_hashes,
        "semantic_output": outputs[0],
        "effect_trace": effect_traces[0],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "can_mark_passed_current": False,
    }


def _validate_schema(value: Any, schema_raw: bytes) -> None:
    schema = COMPILER._strict_json(schema_raw, str(RESULT_SCHEMA_PATH))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ExecutionError("result schema is invalid") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(part) for part in first.absolute_path)
        raise ExecutionError(f"result schema failed at {location}: {first.message}")


def execute(selected: list[str] | None = None) -> dict[str, Any]:
    inventory, migration = COMPILER.check_checked_artifacts()
    candidate_rows = {
        row["entry_id"]: row
        for row in inventory["rows"]
        if row["disposition"] == "candidate"
    }
    blocker_ids = {
        row["entry_id"]
        for row in inventory["rows"]
        if row["disposition"] == "external_blocker"
    }
    migrated_ids = {row["former_gap_entry_id"] for row in migration["migrations"]}
    requested = list(candidate_rows) if selected is None else list(selected)
    if not requested:
        raise ExecutionError("empty explicit selection is not allowed")
    if len(requested) != len(set(requested)):
        raise ExecutionError("duplicate --case selection")
    for entry_id in requested:
        if entry_id in blocker_ids:
            raise ExecutionError(f"external blocker cannot execute: {entry_id}")
        if entry_id in migrated_ids:
            raise ExecutionError(f"migrated ID is not a gap candidate: {entry_id}")
        if entry_id not in candidate_rows:
            raise ExecutionError(f"unknown candidate ID: {entry_id}")

    plan, _ = COMPILER._load_locked_json(COMPILER.SOURCE_PLAN, "current gap plan")
    manifest, _ = COMPILER._load_locked_json(
        COMPILER.SOURCE_MANIFEST, "current manifest"
    )
    plan_by_id = {row["entry_id"]: row for row in plan["entries"]}
    historical_cases, wave_locks = _historical_cases(inventory)
    selected_waves = {candidate_rows[entry_id]["legacy_wave"] for entry_id in requested}
    source_files = {row["path"]: row["sha256"] for row in inventory["source_files"]}
    loaded = {
        wave: _load_historical_module(wave_locks[wave], source_files)
        for wave in sorted(selected_waves)
    }
    modules = {wave: value[0] for wave, value in loaded.items()}
    gates = {wave: value[1] for wave, value in loaded.items()}

    results = [
        _run_case_twice(
            modules[candidate_rows[entry_id]["legacy_wave"]],
            candidate_rows[entry_id],
            historical_cases[entry_id],
            plan_by_id,
            manifest,
        )
        for entry_id in requested
    ]
    per_wave = Counter(result["legacy_wave"] for result in results)
    aggregate_trace = {
        "asyncio_socketpair_bootstraps": sum(
            result["effect_trace"]["asyncio_socketpair_bootstraps"]
            for result in results
        ),
        "forbidden_effect_attempts": sum(
            result["effect_trace"]["forbidden_effect_attempts"] for result in results
        ),
    }
    nested_ast_sha256 = {
        path: sorted(digests)
        for wave in sorted(gates)
        for path, digests in sorted(gates[wave].observed.items())
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "guarded_direct_advertised_entry_executor_74_successor",
        "candidate_only": True,
        "can_mark_passed_current": False,
        "official_capability_effect": "none_candidate_only",
        "inventory_payload_sha256": inventory["inventory_payload_sha256"],
        "selection": {
            "default_all_candidates": selected is None,
            "requested_ids": requested,
            "executed_count": len(results),
            "per_wave_counts": {str(wave): per_wave[wave] for wave in range(1, 8)},
        },
        "denominator": {
            "current_gap_entries": 74,
            "dispatchable_candidates": 71,
            "external_blockers": 3,
            "migrated_predecessors": 13,
        },
        "guard_policy": {
            "boundary": "in_process_integrity_guard_not_os_sandbox",
            "repository_reads": "fd_anchored_exact_digest_selected_capability_only",
            "historical_module_execution": "restricted_builtins_preloaded_import_allowlist",
            "nested_execution": "registered_exact_source_ast_only",
            "asyncio_socketpair_exception": "AF_UNIX_SOCK_STREAM_proto0_event_loop_bootstrap_only",
            "denied_effect_classes": [
                "network_and_non_asyncio_sockets",
                "subprocess_fork_exec_spawn_and_threads",
                "general_file_open_and_filesystem_mutation",
                "temporary_files",
            ],
        },
        "effect_trace": aggregate_trace,
        "nested_ast_sha256": nested_ast_sha256,
        "runtime_evidence": [],
        "results": results,
    }
    report["execution_payload_sha256"] = _sha_bytes(_canonical_bytes(report))
    schema_raw = COMPILER._read_package_bytes(RESULT_SCHEMA_PATH)
    if _sha_bytes(schema_raw) != EXPECTED_RESULT_SCHEMA_RAW_SHA256:
        raise ExecutionError("result schema raw digest drift")
    _validate_schema(report, schema_raw)
    return report


def check_checked_receipt() -> dict[str, Any]:
    expected = execute()
    raw = COMPILER._read_package_bytes(RECEIPT_PATH)
    if _sha_bytes(raw) != EXPECTED_RECEIPT_RAW_SHA256:
        raise ExecutionError("checked execution receipt raw digest drift")
    receipt = COMPILER._strict_json(raw, str(RECEIPT_PATH))
    if receipt != expected:
        raise ExecutionError("checked execution receipt differs from deterministic run")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.list:
            if args.cases or args.check:
                raise ExecutionError("--list cannot be combined with --case or --check")
            inventory, _migration = COMPILER.check_checked_artifacts()
            print(
                "\n".join(
                    row["entry_id"]
                    for row in inventory["rows"]
                    if row["disposition"] == "candidate"
                )
            )
            return 0
        if args.check:
            if args.cases:
                raise ExecutionError("--check cannot be combined with --case")
            receipt = check_checked_receipt()
            print(
                "VALID: 71 guarded direct candidates; "
                f"receipt={receipt['execution_payload_sha256']}"
            )
            return 0
        print(
            json.dumps(execute(args.cases), indent=2, sort_keys=True, allow_nan=False)
        )
        return 0
    except (COMPILER.CompileError, ExecutionError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
