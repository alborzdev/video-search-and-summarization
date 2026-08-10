from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parents[1]
VERIFY_SPEC = importlib.util.spec_from_file_location(
    "ui_global_chat_verify", HERE / "verify.py"
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)

EVIDENCE_SPEC = importlib.util.spec_from_file_location(
    "ui_global_chat_build_official_evidence",
    HERE / "build_official_evidence.py",
)
assert EVIDENCE_SPEC and EVIDENCE_SPEC.loader
EVIDENCE = importlib.util.module_from_spec(EVIDENCE_SPEC)
EVIDENCE_SPEC.loader.exec_module(EVIDENCE)


def test_retained_receipt_and_canonical_binding_are_valid() -> None:
    assert VERIFY.verify()["status"] == "passed"


def test_harness_is_default_inert_and_suppresses_report_transport() -> None:
    source = (HERE / "harness.mjs").read_text(encoding="utf-8")
    assert "if (mode === 'plan')" in source
    assert source.index("if (mode === 'plan')") < source.index("chromium.launch")
    assert "WebSocket.prototype.send = function captureOnly" in source
    assert "actual_send_count: 0" in source
    assert "report_transport_send_suppressed: true" in source


def test_contract_is_browser_session_only_and_warehouse_free() -> None:
    contract = json.loads((HERE / "contract.json").read_text(encoding="utf-8"))
    boundary = contract["runtime_boundary"]
    assert boundary["server_side_persistent_mutation"] is False
    assert boundary["service_lifecycle_allowed"] is False
    assert boundary["numeric_loopback_only"] is True
    assert boundary["report_transport_send_suppressed"] is True
    assert boundary["warehouse_sample_bundle"] == "excluded"
    assert contract["cleanup"]["targets"] == []
    assert contract["cleanup"]["allowlist"] == []


def test_official_evidence_projection_has_no_drift() -> None:
    expected = EVIDENCE.build()
    retained = json.loads(
        (HERE / "official-runtime-evidence.json").read_text(encoding="utf-8")
    )
    assert retained == expected


def test_retained_documents_contain_no_raw_network_or_chat_payloads() -> None:
    raw = "\n".join(
        (HERE / name).read_text(encoding="utf-8")
        for name in ("runtime-receipt.json", "official-runtime-evidence.json")
    )
    assert re.search(r"(?:https?|wss?)://", raw, re.IGNORECASE) is None
    for forbidden in (
        '"text":',
        '"prompt":',
        '"request_id":',
        '"conversation_id":',
        '"session_id":',
        '"sensor_id":',
        '"incident_id":',
    ):
        assert forbidden not in raw


def test_synthetic_hydration_recovery_is_isolated_to_profile_fixture() -> None:
    receipt = json.loads(
        (HERE / "runtime-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["current_profile"]["diagnostics"][
        "synthetic_profile_hydration_recovery_counts"
    ] == {}
    assert receipt["report_boundary"]["diagnostics"][
        "synthetic_profile_hydration_recovery_counts"
    ] == {}
    assert set(
        receipt["profile_boundary"]["diagnostics"][
            "synthetic_profile_hydration_recovery_counts"
        ]
    ) <= {"418", "423"}
