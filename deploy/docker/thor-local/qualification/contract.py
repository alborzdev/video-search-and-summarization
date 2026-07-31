#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Offline contract extraction and normalization for Thor-local VSS APIs."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
PROSE_KEYS = {
    "description",
    "example",
    "examples",
    "externalDocs",
    "summary",
    "tags",
    "title",
}
PATH_PARAMETER_RE = re.compile(r"\{[^{}]+\}")
MARKDOWN_ROUTE_RE = re.compile(
    r"^###\s+(DELETE|GET|HEAD|OPTIONS|PATCH|POST|PUT|TRACE)\s+`([^`]+)`",
    re.MULTILINE,
)


class ContractError(ValueError):
    """Raised when a checked-in contract cannot be derived safely."""


def canonical_route(path: str) -> str:
    """Normalize parameter names while preserving the route structure."""

    return PATH_PARAMETER_RE.sub("{}", path)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def shape_hash(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contract_shape(value: Any) -> Any:
    """Remove prose-only OpenAPI fields while retaining validation semantics."""

    if isinstance(value, dict):
        return {
            key: contract_shape(item)
            for key, item in sorted(value.items())
            if key not in PROSE_KEYS
        }
    if isinstance(value, list):
        return [contract_shape(item) for item in value]
    return value


def _runtime_path(source_path: str, path_prefix: str) -> str:
    if not path_prefix:
        return source_path
    if source_path == "/":
        return path_prefix or "/"
    return f"{path_prefix.rstrip('/')}/{source_path.lstrip('/')}"


def _operation(
    method: str,
    path: str,
    *,
    source_path: str | None = None,
    operation_id: str | None = None,
    schema_hash: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "method": method.upper(),
        "path": path,
        "operation_id": operation_id,
        "schema_hash": schema_hash,
    }
    if source_path is not None and source_path != path:
        item["source_path"] = source_path
    return item


def _sort_operations(operations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        operations,
        key=lambda item: (item["path"], item["method"], item.get("operation_id") or ""),
    )


def normalize_openapi_document(
    document: dict[str, Any],
    *,
    path_prefix: str = "",
) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize OpenAPI 3 or Swagger 2 operations into stable records."""

    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ContractError("OpenAPI/Swagger document has no paths object")

    operations: list[dict[str, Any]] = []
    for source_path, path_item in paths.items():
        if not isinstance(source_path, str) or not isinstance(path_item, dict):
            continue
        inherited_parameters = path_item.get("parameters", [])
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            shape = contract_shape(
                {
                    "inherited_parameters": inherited_parameters,
                    "operation": operation,
                }
            )
            operations.append(
                _operation(
                    method,
                    _runtime_path(source_path, path_prefix),
                    source_path=source_path,
                    operation_id=operation.get("operationId"),
                    schema_hash=shape_hash(shape),
                )
            )

    component_shape = contract_shape(
        {
            key: document[key]
            for key in (
                "components",
                "definitions",
                "parameters",
                "responses",
                "security",
                "securityDefinitions",
            )
            if key in document
        }
    )
    component_hash = shape_hash(component_shape) if component_shape else None
    return _sort_operations(operations), component_hash


def load_json_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON contract must be an object: {path}")
    return value


def extract_swagger_yaml_operations(
    path: Path, *, path_prefix: str = ""
) -> list[dict[str, Any]]:
    """Extract Swagger path/method/operationId using its stable indentation.

    The checked-in VIOS documents use ordinary two-space Swagger YAML. Keeping
    this extractor deliberately narrow avoids adding an online package install
    to an operator command that must work in a fully offline environment.
    The complete file SHA in each manifest catches schema/body changes beyond
    the normalized route metadata extracted here.
    """

    operations: list[dict[str, Any]] = []
    in_paths = False
    current_path: str | None = None
    current_operation: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            in_paths = stripped == "paths:"
            current_path = None
            current_operation = None
            continue
        if not in_paths:
            continue
        if indent == 2 and stripped.startswith("/") and stripped.endswith(":"):
            current_path = stripped[:-1]
            current_operation = None
            continue
        method_match = re.fullmatch(
            r"(delete|get|head|options|patch|post|put|trace):", stripped
        )
        if indent == 4 and current_path and method_match:
            current_operation = _operation(
                method_match.group(1),
                _runtime_path(current_path, path_prefix),
                source_path=current_path,
            )
            operations.append(current_operation)
            continue
        if indent == 6 and current_operation and stripped.startswith("operationId:"):
            operation_id = stripped.partition(":")[2].strip().strip("'\"")
            if not operation_id:
                raise ContractError(f"empty operationId in {path}:{line_number}")
            current_operation["operation_id"] = operation_id

    if not operations:
        raise ContractError(f"no Swagger operations found in {path}")
    return _sort_operations(operations)


def _format_python_path(node: ast.AST, substitutions: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and isinstance(
                value.value, ast.Name
            ):
                if value.value.id not in substitutions:
                    raise ContractError(
                        f"unknown route substitution {value.value.id!r}"
                    )
                parts.append(substitutions[value.value.id])
            else:
                raise ContractError(
                    f"unsupported dynamic route expression: {ast.dump(value)}"
                )
        return "".join(parts)
    raise ContractError(f"unsupported route expression: {ast.dump(node)}")


class _RouteVisitor(ast.NodeVisitor):
    def __init__(
        self, substitutions: dict[str, str], excluded_scopes: set[str]
    ) -> None:
        self.substitutions = substitutions
        self.excluded_scopes = excluded_scopes
        self.scope: list[str] = []
        self.operations: list[dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not self.excluded_scopes.intersection(self.scope):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                method = decorator.func.attr.lower()
                if method not in HTTP_METHODS or not decorator.args:
                    continue
                path = _format_python_path(decorator.args[0], self.substitutions)
                self.operations.append(_operation(method, path))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def extract_python_routes(
    path: Path,
    *,
    substitutions: dict[str, str] | None = None,
    excluded_scopes: Iterable[str] = (),
) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _RouteVisitor(substitutions or {}, set(excluded_scopes))
    visitor.visit(tree)
    return _sort_operations(visitor.operations)


def extract_markdown_routes(path: Path) -> list[dict[str, Any]]:
    operations = [
        _operation(method, route)
        for method, route in MARKDOWN_ROUTE_RE.findall(path.read_text(encoding="utf-8"))
    ]
    if not operations:
        raise ContractError(f"no Markdown API headings found in {path}")
    return _sort_operations(operations)


def extract_lvs_mcp_tools(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tools: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.func.id != "Tool"
        ):
            continue
        keywords = {
            keyword.arg: keyword.value for keyword in node.keywords if keyword.arg
        }
        try:
            name = ast.literal_eval(keywords["name"])
            input_schema = ast.literal_eval(keywords["inputSchema"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ContractError(
                f"cannot parse LVS MCP Tool declaration at line {node.lineno}"
            ) from exc
        tools.append({"name": name, "input_schema_hash": shape_hash(input_schema)})
    if not tools:
        raise ContractError(f"no MCP Tool declarations found in {path}")
    return sorted(tools, key=lambda item: item["name"])


def extract_va_mcp_tools(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    in_video_analytics = False
    in_include = False
    names: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 2 and stripped == "video_analytics:":
            in_video_analytics = True
            in_include = False
            continue
        if (
            in_video_analytics
            and indent <= 2
            and stripped
            and stripped != "video_analytics:"
        ):
            break
        if in_video_analytics and indent == 4 and stripped == "include:":
            in_include = True
            continue
        if in_include and indent == 4 and stripped.startswith("- "):
            names.append(stripped[2:].strip())
            continue
        if in_include and indent == 4 and stripped and stripped != "include:":
            break
    if not names:
        raise ContractError(f"no video_analytics include list found in {path}")
    return [
        {"name": f"video_analytics__{name}", "input_schema_hash": None}
        for name in sorted(names)
    ]


def _fastmcp_decorator_kind(
    decorator: ast.expr, *, instance_name: str
) -> tuple[str, ast.Call] | None:
    if (
        not isinstance(decorator, ast.Call)
        or not isinstance(decorator.func, ast.Attribute)
        or not isinstance(decorator.func.value, ast.Name)
        or decorator.func.value.id != instance_name
        or decorator.func.attr not in {"prompt", "tool"}
    ):
        return None
    return decorator.func.attr, decorator


def _fastmcp_declared_name(
    call: ast.Call, *, default: str, path: Path, line_number: int
) -> str:
    if call.args:
        raise ContractError(
            f"unsupported positional FastMCP decorator arguments in "
            f"{path}:{line_number}"
        )
    name_values = [keyword.value for keyword in call.keywords if keyword.arg == "name"]
    if len(name_values) > 1:
        raise ContractError(f"duplicate FastMCP name in {path}:{line_number}")
    if not name_values:
        return default
    try:
        name = ast.literal_eval(name_values[0])
    except (ValueError, TypeError) as exc:
        raise ContractError(
            f"FastMCP name must be a literal string in {path}:{line_number}"
        ) from exc
    if not isinstance(name, str) or not name:
        raise ContractError(
            f"FastMCP name must be a non-empty literal string in {path}:{line_number}"
        )
    return name


def _fastmcp_input_schema_hash(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    """Hash the Python signature FastMCP uses to derive its input schema."""

    return shape_hash(ast.dump(node.args, annotate_fields=True, include_attributes=False))


def extract_fastmcp_declarations(
    path: Path, *, instance_name: str = "mcp"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract top-level ``@mcp.tool`` and ``@mcp.prompt`` declarations.

    Importing a FastMCP server can initialize settings, logging, transports, or
    backend clients. Static AST extraction keeps the Thor contract qualifier
    offline and side-effect free while still pinning every declaration name and
    input signature. The complete source digest in the manifest covers handler
    bodies and decorator prose.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    declarations: dict[str, list[dict[str, Any]]] = {"prompt": [], "tool": []}
    names: dict[str, set[str]] = {"prompt": set(), "tool": set()}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        matching = [
            result
            for decorator in node.decorator_list
            if (
                result := _fastmcp_decorator_kind(
                    decorator, instance_name=instance_name
                )
            )
            is not None
        ]
        if not matching:
            continue
        if len(matching) != 1:
            raise ContractError(
                f"multiple FastMCP declarations on {path}:{node.lineno}"
            )
        kind, call = matching[0]
        name = _fastmcp_declared_name(
            call, default=node.name, path=path, line_number=node.lineno
        )
        if name in names[kind]:
            raise ContractError(f"duplicate FastMCP {kind} name {name!r} in {path}")
        names[kind].add(name)
        declarations[kind].append(
            {
                "name": name,
                "input_schema_hash": _fastmcp_input_schema_hash(node),
            }
        )

    if not declarations["tool"] and not declarations["prompt"]:
        raise ContractError(f"no FastMCP declarations found in {path}")
    return (
        sorted(declarations["tool"], key=lambda item: item["name"]),
        sorted(declarations["prompt"], key=lambda item: item["name"]),
    )


def build_rest_manifest(
    surface_id: str,
    operations: Iterable[dict[str, Any]],
    *,
    source_files: Iterable[tuple[str, Path]],
    component_schema_hash: str | None = None,
) -> dict[str, Any]:
    normalized = _sort_operations(operations)
    canonical = {(item["method"], canonical_route(item["path"])) for item in normalized}
    return {
        "schema_version": 1,
        "surface": surface_id,
        "kind": "rest",
        "declared_operation_count": len(normalized),
        "normalized_unique_operation_count": len(canonical),
        "method_counts": dict(
            sorted(Counter(item["method"] for item in normalized).items())
        ),
        "component_schema_hash": component_schema_hash,
        "source_files": [
            {"path": relative, "sha256": file_sha256(absolute)}
            for relative, absolute in sorted(source_files)
        ],
        "operations": normalized,
    }


def build_mcp_manifest(
    surface_id: str,
    tools: Iterable[dict[str, Any]],
    *,
    source_files: Iterable[tuple[str, Path]],
    prompts: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    normalized_tools = sorted(tools, key=lambda item: item["name"])
    normalized_prompts = sorted(prompts, key=lambda item: item["name"])
    return {
        "schema_version": 2,
        "surface": surface_id,
        "kind": "mcp",
        "tool_count": len(normalized_tools),
        "prompt_count": len(normalized_prompts),
        "source_files": [
            {"path": relative, "sha256": file_sha256(absolute)}
            for relative, absolute in sorted(source_files)
        ],
        "tools": normalized_tools,
        "prompts": normalized_prompts,
    }


def compare_manifest(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Return concise, machine-stable differences between two manifests."""

    if expected == actual:
        return []
    differences: list[str] = []
    if expected.get("kind") != actual.get("kind"):
        return [f"kind changed: {expected.get('kind')!r} -> {actual.get('kind')!r}"]
    if expected.get("kind") == "rest":
        expected_ops = {
            (item["method"], item["path"]): item
            for item in expected.get("operations", [])
        }
        actual_ops = {
            (item["method"], item["path"]): item
            for item in actual.get("operations", [])
        }
        missing = sorted(expected_ops.keys() - actual_ops.keys())
        extra = sorted(actual_ops.keys() - expected_ops.keys())
        changed = sorted(
            key
            for key in expected_ops.keys() & actual_ops.keys()
            if expected_ops[key] != actual_ops[key]
        )
        if missing:
            differences.append(
                "missing operations: "
                + ", ".join(f"{method} {path}" for method, path in missing)
            )
        if extra:
            differences.append(
                "extra operations: "
                + ", ".join(f"{method} {path}" for method, path in extra)
            )
        if changed:
            differences.append(
                "changed operation contracts: "
                + ", ".join(f"{method} {path}" for method, path in changed)
            )
    else:
        expected_tools = {item["name"]: item for item in expected.get("tools", [])}
        actual_tools = {item["name"]: item for item in actual.get("tools", [])}
        missing = sorted(expected_tools.keys() - actual_tools.keys())
        extra = sorted(actual_tools.keys() - expected_tools.keys())
        changed = sorted(
            key
            for key in expected_tools.keys() & actual_tools.keys()
            if expected_tools[key] != actual_tools[key]
        )
        if missing:
            differences.append("missing tools: " + ", ".join(missing))
        if extra:
            differences.append("extra tools: " + ", ".join(extra))
        if changed:
            differences.append("changed tool schemas: " + ", ".join(changed))
        expected_prompts = {
            item["name"]: item for item in expected.get("prompts", [])
        }
        actual_prompts = {item["name"]: item for item in actual.get("prompts", [])}
        missing_prompts = sorted(expected_prompts.keys() - actual_prompts.keys())
        extra_prompts = sorted(actual_prompts.keys() - expected_prompts.keys())
        changed_prompts = sorted(
            key
            for key in expected_prompts.keys() & actual_prompts.keys()
            if expected_prompts[key] != actual_prompts[key]
        )
        if missing_prompts:
            differences.append("missing prompts: " + ", ".join(missing_prompts))
        if extra_prompts:
            differences.append("extra prompts: " + ", ".join(extra_prompts))
        if changed_prompts:
            differences.append(
                "changed prompt schemas: " + ", ".join(changed_prompts)
            )
    if expected.get("source_files") != actual.get("source_files"):
        differences.append("source file digest changed")
    if not differences:
        differences.append("manifest metadata changed")
    return differences
