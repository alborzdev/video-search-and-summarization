#!/usr/bin/env python3
"""Static tests for the retained RT-Embed URL/broker/OTel successor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest

import jsonschema


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("rt_embed_url_brokers_executor", HERE / "execute.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not import executor")
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


class SuccessorTests(unittest.TestCase):
    def test_plan_is_inert_and_source_locked(self) -> None:
        contract = EXECUTOR._load(HERE / "contract.json")
        plan = EXECUTOR._plan(contract)
        self.assertEqual(plan["official_indices"], [370, 372])
        self.assertEqual(plan["http_requests"], 0)
        self.assertEqual(plan["model_requests"], 0)
        self.assertEqual(plan["docker_commands"], 0)
        self.assertFalse(plan["writes_or_lifecycle_actions"])

    def test_retained_receipt_matches_strict_schema(self) -> None:
        receipt = EXECUTOR._load(HERE / "runtime-receipt.json")
        schema = EXECUTOR._load(HERE / "receipt.schema.json")
        jsonschema.Draft202012Validator(schema).validate(receipt)
        contract = EXECUTOR._load(HERE / "contract.json")
        self.assertEqual(
            receipt["contract_sha256"],
            EXECUTOR._sha((HERE / "contract.json").read_bytes()),
        )
        self.assertEqual(receipt["policy"], contract["policy"])

    def test_receipt_retains_no_raw_runtime_identifiers_or_urls(self) -> None:
        raw = (HERE / "runtime-receipt.json").read_text()
        self.assertIsNone(
            re.search(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
                raw,
                re.IGNORECASE,
            )
        )
        self.assertIsNone(re.search(r"0x[0-9a-f]{16,32}", raw, re.IGNORECASE))
        self.assertNotIn("http://", raw)
        self.assertNotIn("https://", raw)
        self.assertNotIn("data:", raw)
        receipt = json.loads(raw)
        self.assertFalse(receipt["policy"]["raw_embeddings_retained"])
        self.assertFalse(receipt["policy"]["raw_resource_ids_retained"])
        self.assertFalse(receipt["policy"]["raw_request_ids_retained"])
        self.assertFalse(receipt["policy"]["raw_trace_ids_retained"])


if __name__ == "__main__":
    unittest.main()
