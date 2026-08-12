#!/usr/bin/env python3
"""Deterministic external parser used by the Thor row-326 qualification.

The module intentionally depends only on Python's standard library.  Alert
Bridge bind-mounts it as an operator-owned extension and loads the class by
its dotted path, which is the deployment contract advertised for custom VLM
parsing.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class ThorStructuredAlertParser:
    """Normalize JSON verdict/reasoning fields without retaining raw output."""

    parser_id = "thor-structured-alert-parser-v1"

    @staticmethod
    def _json_object(raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("custom parser expected a JSON object") from None
            try:
                value = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError("custom parser received invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("custom parser expected a JSON object")
        return value

    def parse(self, raw_response: str) -> dict[str, Any]:
        if not isinstance(raw_response, str) or not raw_response.strip():
            raise ValueError("custom parser received an empty response")
        value = self._json_object(raw_response)
        raw_verdict = value.get("prediction_answer", value.get("verdict"))
        verdict_token = str(raw_verdict).strip().casefold()
        if verdict_token in {"yes", "true", "confirmed", "1"}:
            normalized_verdict = "confirmed"
        elif verdict_token in {"no", "false", "rejected", "0"}:
            normalized_verdict = "rejected"
        else:
            raise ValueError("custom parser received an unsupported verdict")
        reasoning = value.get("reasoning", value.get("explanation"))
        normalized_reasoning = " ".join(str(reasoning or "").split())
        if not normalized_reasoning:
            raise ValueError("custom parser received no reasoning")
        return {
            "parser_id": self.parser_id,
            "normalized_verdict": normalized_verdict,
            "normalized_reasoning": normalized_reasoning,
            "raw_response_sha256": hashlib.sha256(
                raw_response.encode("utf-8")
            ).hexdigest(),
        }
