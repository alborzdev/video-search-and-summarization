# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import decimal
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RTVLM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = RTVLM_DIR.parents[3]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


matrix = load_module("thor_rt_vlm_matrix", RTVLM_DIR / "model_matrix.py")
budget = load_module("thor_rt_vlm_budget", RTVLM_DIR / "memory_budget.py")


class MatrixTests(unittest.TestCase):
    def test_reviewed_matrix_matches_source_and_local_locks(self):
        document = matrix.validate_matrix(
            RTVLM_DIR / "model-matrix.json",
            RTVLM_DIR / "artifacts.lock.json",
            REPO_ROOT,
        )
        self.assertEqual(11, len(document["advertised_rt_vlm_variants"]))
        self.assertFalse(document["local_artifacts"][0]["runtime_qualified_on_thor"])

    def test_runtime_overclaim_is_rejected(self):
        document = json.loads((RTVLM_DIR / "model-matrix.json").read_text())
        document["advertised_rt_vlm_variants"][0]["thor_status"] = "qualified"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(matrix.MatrixError, "overclaims"):
                matrix.validate_matrix(
                    path, RTVLM_DIR / "artifacts.lock.json", REPO_ROOT
                )

    def test_cosmos3_super_remains_explicitly_unresolved(self):
        document = json.loads((RTVLM_DIR / "model-matrix.json").read_text())
        super_entry = document["adjacent_profile_variants"][0]
        self.assertIsNone(super_entry["artifact_id"])
        self.assertIn("unknown_unqualified", super_entry["thor_status"])


class MemoryBudgetTests(unittest.TestCase):
    def test_fixed_reserve_is_added_to_utilization(self):
        required = budget.required_available_kib(
            100 * budget.KIB_PER_GIB,
            decimal.Decimal("0.45"),
            0,
        )
        self.assertEqual(65 * budget.KIB_PER_GIB, required)
        with self.assertRaises(budget.BudgetError):
            budget.check(
                100 * budget.KIB_PER_GIB,
                64 * budget.KIB_PER_GIB,
                decimal.Decimal("0.45"),
                0,
            )

    def test_utilization_cannot_consume_the_reserve(self):
        with self.assertRaises(budget.BudgetError):
            budget.parse_fraction("0.81")


class RuntimeStateTests(unittest.TestCase):
    @staticmethod
    def helper():
        source = (
            REPO_ROOT
            / "services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_get_runtime_state_dir"
        )
        namespace = {"os": os, "RuntimeError": RuntimeError, "ValueError": ValueError}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"),
            namespace,
        )
        return namespace["_get_runtime_state_dir"]

    def test_relative_model_path_keeps_legacy_compatibility(self):
        helper = self.helper()
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {"VLM_RUNTIME_STATE_DIR": ""}, clear=False),
            mock.patch("os.getcwd", return_value=directory),
        ):
            result = helper("relative-model")
            self.assertTrue(Path(result).is_absolute())

    def test_explicit_runtime_state_must_be_absolute_and_writable(self):
        helper = self.helper()
        with mock.patch.dict(
            os.environ, {"VLM_RUNTIME_STATE_DIR": "relative"}, clear=False
        ):
            with self.assertRaises(ValueError):
                helper("model")
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {"VLM_RUNTIME_STATE_DIR": str(Path(directory) / "state")},
                clear=False,
            ),
        ):
            result = helper("model")
            self.assertTrue(Path(result).is_dir())


if __name__ == "__main__":
    unittest.main()
