# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression coverage for the Alert Bridge WebSocket config path."""

import ast
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[2]
    / "alert-agent-web/app/websocket/websocket_service.py"
)


def test_websocket_service_uses_launcher_config_path_by_default():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    websocket_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WebSocketService"
    )
    initializer = next(
        node
        for node in websocket_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "__init__"
    )

    config_argument = next(
        argument
        for argument in initializer.args.args
        if argument.arg == "config_file"
    )
    default_index = initializer.args.args.index(config_argument) - (
        len(initializer.args.args) - len(initializer.args.defaults)
    )
    assert isinstance(initializer.args.defaults[default_index], ast.Constant)
    assert initializer.args.defaults[default_index].value is None

    assignments = [
        node
        for node in ast.walk(initializer)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "config_file"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    getenv_calls = [
        node
        for node in ast.walk(assignments[0].value)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
        and node.func.attr == "getenv"
    ]
    assert len(getenv_calls) == 1
    assert [argument.value for argument in getenv_calls[0].args] == [
        "CONFIG_PATH",
        "config.yaml",
    ]
