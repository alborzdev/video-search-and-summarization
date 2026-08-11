from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rt_vlm_url_security_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [60, 61, 62, 63]


def test_domain_auth_boundaries_are_exact() -> None:
    auth = verifier.verify()["authentication"]
    assert all(auth["request_headers"].values())
    assert auth["environment_auth"]["authorization_delivered"] is True
    assert auth["environment_auth"]["unmatched_domain_authorization_stripped"] is True
    assert auth["plain_http_authorization_stripped"] is True
    assert auth["same_host_redirect_authorization_retained"] is True
    assert auth["cross_host_redirect_authorization_stripped"] is True


def test_redirect_range_and_download_size_are_enforced() -> None:
    receipt = verifier.verify()
    redirects = receipt["redirects"]
    assert redirects["negative"]["effective_limit"] == 0
    assert redirects["above_max"]["effective_limit"] == 10
    assert redirects["two"]["downloaded"] is True
    assert redirects["two"]["ssrf_validation_calls"] == 3
    size = receipt["download_size"]
    assert size["default_limit_bytes"] == 8 * 1024**3
    assert size["over_limit_status_code"] == 413
    assert size["over_limit_not_saved"] is True


def test_tls_scope_live_api_and_cleanup_are_exact() -> None:
    receipt = verifier.verify()
    assert receipt["live_api"]["loopback_ssrf_status_code"] == 422
    assert receipt["tls"]["default_verification"]["self_signed_rejected"] is True
    assert receipt["tls"]["listed_domain"]["downloaded"] is True
    assert receipt["tls"]["unlisted_domain"]["self_signed_rejected"] is True
    assert receipt["cleanup"] == {
        "probe_container_absent": True,
        "main_container_exact": True,
        "main_asset_state_exact": True,
        "failures": [],
    }
