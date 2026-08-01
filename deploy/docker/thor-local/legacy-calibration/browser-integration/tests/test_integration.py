# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]
REPO_ROOT = HERE.parents[4]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "thor_calibration_ui_materialize", HERE / "materialize.py"
)
assert MODULE_SPEC and MODULE_SPEC.loader
materialize = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(materialize)


def _overlay() -> dict:
    return json.loads((HERE / "overlay.json").read_text(encoding="utf-8"))


def _outputs() -> dict[str, str]:
    overlay = _overlay()
    source_root = REPO_ROOT / overlay["source_root"]
    values = {}
    for contract in overlay["files"]:
        source = (source_root / contract["path"]).read_bytes()
        values[contract["path"]] = materialize.transform(source, contract).decode()
    return values


def test_overlay_is_digest_locked_and_keeps_upstream_unchanged() -> None:
    overlay = materialize._validate_overlay(_overlay())
    results = materialize.verify_source_tree(
        REPO_ROOT / overlay["source_root"], overlay
    )
    assert len(results) == 5
    assert {row["output_sha256"] for row in results} == {
        item["output_sha256"] for item in overlay["files"]
    }


def test_output_digest_sentinel_and_malformed_digests_fail_closed() -> None:
    for invalid in (
        "TO_BE_GENERATED",
        "0" * 63,
        "G" * 64,
        "A" * 64,
        0,
    ):
        overlay = copy.deepcopy(_overlay())
        overlay["files"][0]["output_sha256"] = invalid
        with pytest.raises(materialize.OverlayError, match="lowercase SHA-256"):
            materialize._validate_overlay(overlay)


def test_unknown_overlay_path_fails_closed() -> None:
    overlay = copy.deepcopy(_overlay())
    overlay["files"][0]["path"] = "src/unknown.tsx"
    with pytest.raises(materialize.OverlayError, match="unexpected overlay file path"):
        materialize._validate_overlay(overlay)


@pytest.mark.parametrize("level", ["top", "file", "replacement"])
def test_unknown_overlay_keys_fail_closed(level: str) -> None:
    overlay = copy.deepcopy(_overlay())
    if level == "top":
        overlay["unexpected"] = True
        match = "top-level keys are not exact"
    elif level == "file":
        overlay["files"][0]["unexpected"] = True
        match = "overlay file keys are not exact"
    else:
        overlay["files"][0]["replacements"][0]["unexpected"] = True
        match = "replacement keys are not exact"
    with pytest.raises(materialize.OverlayError, match=match):
        materialize._validate_overlay(overlay)


def test_replacement_list_and_required_keys_fail_closed() -> None:
    empty = copy.deepcopy(_overlay())
    empty["files"][0]["replacements"] = []
    with pytest.raises(materialize.OverlayError, match="replacements are not exact"):
        materialize._validate_overlay(empty)

    missing = copy.deepcopy(_overlay())
    del missing["files"][0]["replacements"][0]["old"]
    with pytest.raises(
        materialize.OverlayError, match="replacement keys are not exact"
    ):
        materialize._validate_overlay(missing)


def test_materialized_browser_route_navigation_and_same_origin_endpoint() -> None:
    outputs = _outputs()
    routes = outputs["src/layout/routes/Routes.tsx"]
    nav = outputs["src/layout/nav/ListItems.tsx"]
    config = outputs["src/config.tsx"]
    json_manager = outputs[
        "src/pages/vst/calibration-steps/CalibrationJsonManager.tsx"
    ]
    mms_configuration = outputs[
        "src/pages/vst/calibration-steps/MmsURLConfiguration.tsx"
    ]
    assert (
        "import CalibrationWorkflow from '../../pages/vst/CalibrationWorkflow';"
        in routes
    )
    assert "{ path: 'calibration', element: <CalibrationWorkflow /> }" in routes
    assert "<NavLink to='/calibration'" in nav
    assert "<ListItemText primary='Calibration' />" in nav
    assert "analyticsUIServerEndpoint: '/vst/calibration-api'" in config
    assert "8003" not in config
    assert "8013" not in config
    assert "window.location.hostname" not in re.search(
        r"analyticsUIServerEndpoint: ([^,]+)", config
    ).group(1)
    assert "import config from '../../../config';" in json_manager
    assert "fetch(`/api/projects/" not in json_manager
    assert (
        "fetch(`${config.analyticsUIServerEndpoint}/api/projects/"
        in json_manager
    )
    assert "method: 'POST'" in mms_configuration
    assert "'Content-Type': 'application/json'" in mms_configuration
    assert "JSON.stringify({ action: 'import-staged' })" in mms_configuration


def test_materialize_copies_to_new_root_only(tmp_path: Path) -> None:
    output = tmp_path / "derived-ui"
    results = materialize.materialize(
        REPO_ROOT / "services/vios/ui", output, _overlay()
    )
    assert len(results) == 5
    derived = (output / "vios-ui/src/config.tsx").read_text(encoding="utf-8")
    upstream = (REPO_ROOT / "services/vios/ui/vios-ui/src/config.tsx").read_text(
        encoding="utf-8"
    )
    assert "'/vst/calibration-api'" in derived
    assert "analyticsUIServerDefaultPort = '8003'" in upstream


def test_digest_and_replacement_tampering_fail_closed() -> None:
    overlay = _overlay()
    contract = overlay["files"][0]
    source = (REPO_ROOT / overlay["source_root"] / contract["path"]).read_bytes()
    with pytest.raises(materialize.OverlayError, match="source digest mismatch"):
        materialize.transform(source + b" ", contract)
    missing = copy.deepcopy(contract)
    missing["replacements"][0]["occurrence"] = 99
    with pytest.raises(materialize.OverlayError, match="occurrence missing"):
        materialize.transform(source, missing)


@pytest.mark.parametrize("unsafe", ["../escape", "/absolute", "a/../../b", ""])
def test_unsafe_overlay_paths_are_rejected(unsafe: str) -> None:
    with pytest.raises(materialize.OverlayError, match="unsafe relative path"):
        materialize._safe_relative(unsafe)


def test_existing_or_nested_output_is_rejected(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(materialize.OverlayError, match="must not already exist"):
        materialize.materialize(REPO_ROOT / "services/vios/ui", existing, _overlay())
    nested = REPO_ROOT / "services/vios/ui/forbidden-derived-output"
    with pytest.raises(materialize.OverlayError, match="must not be within"):
        materialize.materialize(REPO_ROOT / "services/vios/ui", nested, _overlay())


def test_symlinked_or_lexically_disguised_nested_output_is_rejected(
    tmp_path: Path,
) -> None:
    source = REPO_ROOT / "services/vios/ui"
    source_link = tmp_path / "source-link"
    source_link.symlink_to(source, target_is_directory=True)
    disguised = source_link / "unused" / ".." / "derived-output"
    with pytest.raises(materialize.OverlayError, match="must not be within"):
        materialize.materialize(source, disguised, _overlay())


def test_nginx_proxy_is_same_origin_and_numeric_loopback_only() -> None:
    nginx = (HERE / "nginx-vst-direct.conf").read_text(encoding="utf-8")
    assert nginx.count("location ^~ /vst/calibration-api/") == 1
    assert "rewrite ^/vst/calibration-api/(.*)$ /$1 break;" in nginx
    assert "proxy_pass http://127.0.0.1:8013;" in nginx
    block = nginx.split("location ^~ /vst/calibration-api/ {", 1)[1].split(
        "\n        }", 1
    )[0]
    assert "proxy_pass http://127.0.0.1:8013;" in block
    assert "proxy_pass http://$" not in block
    assert "resolver " not in block
    assert "Access-Control-Allow-Origin" in block
    assert "client_max_body_size 16m;" in block
    assert "proxy_request_buffering off;" in block
    assert "client_max_body_size 25G;" not in block
    released = (
        REPO_ROOT / "deploy/docker/services/vios/configs/nginx-vst-direct.conf"
    ).read_text(encoding="utf-8")
    for route in (
        "location /vst/",
        "location /vst/api/v1/sensor/",
        "location /vst/api/v1/",
        "location /vst/storage/",
    ):
        assert route in released and route in nginx


def test_compose_keeps_backend_private_and_fails_without_derived_ui_image() -> None:
    raw = (HERE / "compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(raw)
    backend = compose["services"]["thor-calibration-ui-api"]
    ingress = compose["services"]["vst-ingress"]
    assert backend["network_mode"] == "host"
    assert "ports" not in backend
    assert backend["read_only"] is True
    assert backend["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in backend["security_opt"]
    assert "I_ACCEPT_LOCAL_VIOS_CALIBRATION_UI_SERVER_8013" in backend["command"]
    assert "${THOR_CALIBRATION_VIOS_INGRESS_IMAGE:?" in ingress["image"]
    assert (
        ingress["depends_on"]["thor-calibration-ui-api"]["condition"]
        == "service_healthy"
    )
    assert "8013:" not in raw and ":8013" not in raw.split("healthcheck:", 1)[0]


def test_contract_remains_non_promoting() -> None:
    contract = json.loads((HERE.parent / "contract.json").read_text(encoding="utf-8"))
    assert contract["runtime_evidence"] == []
    assert contract["can_mark_capability_passed"] is False
    assert "runtime_qualification_on_Thor" in contract["not_implemented"]
