from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest
from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = PACKAGE.parents[4]
SPEC = importlib.util.spec_from_file_location(
    "thor_runtime_campaign", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


def _sha(value: str | bytes) -> str:
    payload = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _resolve(
    schema: dict[str, Any] | bool, root: dict[str, Any]
) -> dict[str, Any] | bool:
    if isinstance(schema, bool):
        return schema
    if "$ref" not in schema:
        return schema
    value: Any = root
    for part in schema["$ref"].removeprefix("#/").split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _sample(
    schema: dict[str, Any] | bool,
    root: dict[str, Any],
    seed: str,
    *,
    evidence_root: bool = False,
) -> Any:
    schema = _resolve(schema, root)
    if schema is True:
        return True
    if schema is False:
        raise AssertionError(f"unsatisfiable sample schema at {seed}")
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if "oneOf" in schema:
        choice = schema["oneOf"][1] if evidence_root else schema["oneOf"][0]
        return _sample(choice, root, seed, evidence_root=False)
    if "enum" in schema:
        return copy.deepcopy(schema["enum"][0])
    value_type = schema.get("type")
    if isinstance(value_type, list):
        value_type = next(item for item in value_type if item != "null")
    if value_type == "object" or "properties" in schema:
        return {
            key: _sample(child, root, f"{seed}.{key}")
            for key, child in schema.get("properties", {}).items()
            if key in schema.get("required", [])
        }
    if value_type == "array":
        count = schema.get("minItems", 0)
        prefix_items = schema.get("prefixItems", [])
        return [
            _sample(
                prefix_items[index]
                if index < len(prefix_items)
                else schema.get("items", {}),
                root,
                f"{seed}[{index}]",
            )
            for index in range(count)
        ]
    if value_type == "integer":
        return int(schema.get("minimum", 0))
    if value_type == "number":
        return float(schema.get("minimum", 0))
    if value_type == "boolean":
        return True
    if value_type == "null":
        return None
    if value_type == "string" or "pattern" in schema:
        pattern = schema.get("pattern", "")
        if "[0-9a-f]{64}" in pattern:
            return _sha(seed)
        if pattern == "^lvs-[0-9a-f]{32}$":
            return "lvs-" + _sha(seed)[:32]
        if "[0-9]{6}" in pattern and r"\." in pattern:
            return "0.500000"
        if "date-time" == schema.get("format"):
            return "2026-08-02T00:00:00Z"
        minimum = max(1, int(schema.get("minLength", 1)))
        if "^/" in pattern:
            return "/sample"
        return ("sample-id-" + _sha(seed)[:12]).ljust(minimum, "x")
    raise AssertionError(f"unsupported sample schema at {seed}: {schema}")


def _schema(relative: str) -> dict[str, Any]:
    return json.loads((REPO / relative).read_text())


def _receipt(relative_schema: str, seed: str, *, host: bool = False) -> dict[str, Any]:
    schema = _schema(relative_schema)
    value = _sample(schema, schema, seed, evidence_root=host)
    assert isinstance(value, dict)
    return value


def _manifest(contract: dict[str, Any]) -> dict[str, Any]:
    profiles = []
    for profile_contract in contract["profiles"]:
        profile_id = profile_contract["profile_id"]
        images = []
        for role in profile_contract["required_image_roles"]:
            digest = _sha(f"{profile_id}:image:{role}")
            images.append(
                {
                    "role": role,
                    "reference": f"registry.invalid/{profile_id}/{role}@sha256:{digest}",
                    "digest": digest,
                }
            )
        models = []
        for model in profile_contract["required_models"]:
            models.append(
                {
                    **model,
                    "artifact_sha256": _sha(f"{profile_id}:model:{model['role']}"),
                    "local_thor": True,
                }
            )
        profiles.append(
            {
                "profile_id": profile_id,
                "resolved_compose_sha256": _sha(f"{profile_id}:compose"),
                "generated_env_sha256": _sha(f"{profile_id}:env"),
                "image_set_sha256": _sha(_canonical(images)),
                "images": images,
                "model_set_sha256": _sha(_canonical(models)),
                "models": models,
                "local_inference_only": True,
                "remote_endpoints": [],
            }
        )

    media_types = {
        "official-model-semantic-media": "video/mp4",
        "base-primary-mp4": "video/mp4",
        "base-secondary-mkv": "video/x-matroska",
        "search-owned-mp4": "video/mp4",
        "search-rtsp-descriptor": "application/rtsp-descriptor",
        "search-control-projection": "application/json",
        "ui-owned-mp4": "video/mp4",
        "ui-owned-mkv": "video/x-matroska",
        "ui-rtsp-descriptor": "application/rtsp-descriptor",
        "lvs-source-alpha": "video/mp4",
        "lvs-source-beta": "video/mp4",
        "lvs-live-stream-descriptor": "application/rtsp-descriptor",
        "lvs-static-oracle-fixture": "application/static-oracle",
        "lvs-focus-mp4": "video/mp4",
        "alerts-semantic-descriptor": "application/json",
        "alerts-served-media": "video/mp4",
    }
    fixture_ids = list(
        dict.fromkeys(
            fixture_id
            for phase in contract["phases"]
            for fixture_id in phase["fixture_ids"]
        )
    )
    fixture_hashes = {
        fixture_id: _sha(f"fixture:{fixture_id}") for fixture_id in fixture_ids
    }
    fixture_hashes["base-primary-mp4"] = (
        "c569a1a381a9b8f1f86cd4cb665285044cc16d05a79c96e992f938ca3a2470ad"
    )
    fixture_hashes["lvs-static-oracle-fixture"] = (
        "750e7a81b17464110ccaa3c80ccad04a0809ed5f2aadc348c4f76289c0e28664"
    )
    fixture_hashes["alerts-semantic-descriptor"] = (
        "28c1fe5c84ee5a81e6ca32908b667dd6af4b141d971b928740756c50b06a0e8f"
    )
    fixtures = [
        {
            "fixture_id": fixture_id,
            "sha256": fixture_hashes[fixture_id],
            "bytes": 2617799 if fixture_id == "base-primary-mp4" else 2048 + index,
            "media_type": media_types[fixture_id],
            "provenance": f"reviewed synthetic test identity for {fixture_id}",
            "warehouse_sample_bundle": "excluded",
        }
        for index, fixture_id in enumerate(fixture_ids)
    ]
    campaign_id = "campaign-test"
    phases = []
    for phase in contract["phases"]:
        runtime = phase["run_namespace_required"]
        phases.append(
            {
                "order": phase["order"],
                "phase_id": phase["phase_id"],
                "profile_id": phase["profile_id"],
                "receipt_id": phase["receipt_id"],
                "run_namespace": f"{campaign_id}-{phase['phase_id']}"
                if runtime
                else None,
                "executor_input_sha256": _sha(f"input:{phase['phase_id']}")
                if runtime
                else None,
                "model_semantic_receipt_sha256": None
                if phase["receipt_id"]
                in {"host-prerequisites", campaign.MODEL_RECEIPT_ID}
                else _sha("pending-model-semantic-receipt"),
                "fixture_ids": phase["fixture_ids"],
            }
        )
    overlay_lock = next(
        row for row in contract["source_locks"] if row["path"] == campaign.OVERLAY_PATH
    )
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "campaign_id": campaign_id,
        "repository_commit": contract["repository"]["commit"],
        "selected_binding_overlay_sha256": overlay_lock["sha256"],
        "required_cloud_inference": False,
        "warehouse_sample_bundle": "excluded",
        "model_semantic_receipt_sha256": _sha("pending-model-semantic-receipt"),
        "profiles": profiles,
        "fixtures": fixtures,
        "phases": phases,
    }


def _fixture(manifest: dict[str, Any], fixture_id: str) -> dict[str, Any]:
    return next(row for row in manifest["fixtures"] if row["fixture_id"] == fixture_id)


def _phase(manifest: dict[str, Any], receipt_id: str) -> dict[str, Any]:
    return next(row for row in manifest["phases"] if row["receipt_id"] == receipt_id)


def _descriptor(receipt_set: dict[str, Any], receipt_id: str) -> dict[str, Any]:
    return next(
        row for row in receipt_set["receipts"] if row["receipt_id"] == receipt_id
    )


def _build_receipts(
    contract: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    types = {row["receipt_id"]: row for row in contract["receipt_types"]}
    receipts = {
        receipt_id: _receipt(
            row["schema_path"], receipt_id, host=receipt_id == "host-prerequisites"
        )
        for receipt_id, row in types.items()
    }
    host = receipts["host-prerequisites"]
    host["result"] = "pass"
    host["capabilities"] = []
    for mapping in contract["capability_mappings"][:4]:
        schema = _schema(types["host-prerequisites"]["schema_path"])
        capability_schema = schema["$defs"]["capability"]
        row = _sample(capability_schema, schema, mapping["capability_id"])
        row["capability_id"] = mapping["capability_id"]
        row["contract_status"] = "pass"
        row["contract_satisfied"] = True
        host["capabilities"].append(row)
    host["summary"]["contract_result"] = "pass"
    host["summary"]["contracts_passed"] = 4
    host["summary"]["contracts_failed"] = 0
    host["summary"]["contracts_unknown"] = 0
    unsigned = dict(host)
    unsigned.pop("evidence_sha256", None)
    host["evidence_sha256"] = _sha(_canonical(unsigned))

    model_receipt = receipts[campaign.MODEL_RECEIPT_ID]
    model_receipt["collector_locks"] = {
        "contract_sha256": _sha(
            (REPO / campaign.MODEL_SEMANTIC_CONTRACT_PATH).read_bytes()
        ),
        "contract_schema_sha256": _sha(
            (REPO / campaign.MODEL_SEMANTIC_CONTRACT_SCHEMA_PATH).read_bytes()
        ),
        "executor_sha256": _sha(
            (REPO / campaign.MODEL_SEMANTIC_EXECUTOR_PATH).read_bytes()
        ),
        "manifest_schema_sha256": _sha(
            (REPO / campaign.MODEL_SEMANTIC_MANIFEST_SCHEMA_PATH).read_bytes()
        ),
        "receipt_schema_sha256": _sha(
            (REPO / campaign.MODEL_SEMANTIC_RECEIPT_SCHEMA_PATH).read_bytes()
        ),
    }
    model_receipt["identity"]["run_id"] = _phase(manifest, campaign.MODEL_RECEIPT_ID)[
        "run_namespace"
    ]
    semantic_contract = json.loads(
        (REPO / campaign.MODEL_SEMANTIC_CONTRACT_PATH).read_text(encoding="utf-8")
    )
    model_receipt["identity"]["llm_tool_challenge_sha256"] = _sha(
        (
            semantic_contract["semantic_contract"]["llm_challenge_prefix"]
            + model_receipt["identity"]["run_id"]
        ).encode("utf-8")
    )
    models = contract["official_thor_models"]
    model_receipt["model_contract"] = {
        "release_commit": models["release_commit"],
        "main_commit": models["main_commit"],
        "artifact_lock_sha256": models["artifact_lock_sha256"],
        "llm": {
            "served_model_id": models["llm_served_model"],
            "endpoint": "http://127.0.0.1:30081",
            "image_reference": models["llm_image_reference"],
            "image_id": models["llm_image_id"],
        },
        "vlm": {
            "served_model_id": models["vlm_served_model"],
            "endpoint": "http://127.0.0.1:8018",
            "image_reference": models["vlm_image_reference"],
            "image_id": models["vlm_image_id"],
        },
    }
    model_receipt["no_cloud_agent_wiring"] = {
        "status": "pass",
        "projection_sha256": models["no_cloud_projection_sha256"],
        "blank_api_key_count": 5,
        "forbidden_substitution_count": 0,
    }
    model_fixture = _fixture(manifest, "official-model-semantic-media")
    model_receipt["media"].update(
        sha256=model_fixture["sha256"],
        byte_count=model_fixture["bytes"],
        media_type=model_fixture["media_type"],
    )
    expected_observations = [
        ("llm-model-identity", "llm", ["exact-llm-served-id"]),
        (
            "llm-tool-positive",
            "llm",
            ["exact-tool-name", "exact-tool-arguments"],
        ),
        (
            "llm-tool-negative",
            "llm",
            ["negative-no-tool-call", "negative-exact-content"],
        ),
        ("vlm-model-identity", "vlm", ["exact-vlm-served-id"]),
        (
            "vlm-visual-positive",
            "vlm",
            [
                "digest-pinned-media",
                "positive-visual-literal",
                "absent-literal-excluded",
            ],
        ),
        (
            "vlm-visual-absent-negative",
            "vlm",
            ["digest-pinned-media", "absent-negative-exact"],
        ),
        (
            "agent-both-models-workflow",
            "agent",
            [
                "agent-consumed-vlm",
                "agent-consumed-llm",
                "agent-workflow-sentinel",
            ],
        ),
    ]
    for sequence, (row, expected) in enumerate(
        zip(model_receipt["observations"], expected_observations, strict=True), 1
    ):
        row["sequence"] = sequence
        row["observation_id"], row["role"], row["assertion_ids"] = expected
        row["result_code"] = "semantic_pass"

    for receipt_id, case_id in (
        ("base-tiny-agent-media", "tiny-agent-media"),
        ("base-hitl-state", "hitl-state-transcript"),
    ):
        receipt = receipts[receipt_id]
        receipt["case_id"] = case_id
        receipt["contract_sha256"] = _sha(
            (REPO / types[receipt_id]["contract_path"]).read_bytes()
        )
        receipt["manifest_sha256"] = _phase(manifest, receipt_id)[
            "executor_input_sha256"
        ]
        receipt["fixture"].update(
            primary_sha256=_fixture(manifest, "base-primary-mp4")["sha256"],
            primary_bytes=_fixture(manifest, "base-primary-mp4")["bytes"],
            secondary_sha256=_fixture(manifest, "base-secondary-mkv")["sha256"],
            secondary_bytes=_fixture(manifest, "base-secondary-mkv")["bytes"],
        )

    search = receipts["search-file-semantics"]
    search["identity"]["run_id"] = _phase(manifest, "search-file-semantics")[
        "run_namespace"
    ]
    search["identity"]["media_sha256"] = _fixture(manifest, "search-owned-mp4")[
        "sha256"
    ]
    search["fixture"].update(
        consumer_invoked=True,
        consumer_receipt_sha256=_sha("search-consumer"),
        consumer_transport_accounting="shared-lifecycle-budget-and-deadline",
    )
    search["budget"]["actions"] = 23

    rtsp = receipts["search-rtsp-archive"]
    rtsp["identity"]["run_id"] = _phase(manifest, "search-rtsp-archive")[
        "run_namespace"
    ]
    rtsp["identity"]["rtsp_url_sha256"] = _fixture(manifest, "search-rtsp-descriptor")[
        "sha256"
    ]
    rtsp["control"]["reviewed_projection_sha256"] = _fixture(
        manifest, "search-control-projection"
    )["sha256"]

    ui = receipts["ui-video-management"]
    ui["contract_sha256"] = _sha(
        (REPO / types["ui-video-management"]["contract_path"]).read_bytes()
    )
    ui["manifest_sha256"] = _phase(manifest, "ui-video-management")[
        "executor_input_sha256"
    ]
    ui["run_id_sha256"] = _sha(_phase(manifest, "ui-video-management")["run_namespace"])
    ui["fixture_sha256"] = [
        _fixture(manifest, "ui-owned-mp4")["sha256"],
        _fixture(manifest, "ui-owned-mkv")["sha256"],
    ]

    closure = receipts["lvs-closure"]
    closure["contract_sha256"] = _sha(
        (REPO / types["lvs-closure"]["contract_path"]).read_bytes()
    )
    closure["manifest_sha256"] = _phase(manifest, "lvs-closure")[
        "executor_input_sha256"
    ]
    closure["identity"]["run_id_sha256"] = _sha(
        _phase(manifest, "lvs-closure")["run_namespace"]
    )
    for row, fixture_id in zip(
        closure["fixture_readback"],
        ["lvs-source-alpha", "lvs-source-beta"],
        strict=True,
    ):
        row["stored_media_sha256"] = _fixture(manifest, fixture_id)["sha256"]

    agent = receipts["lvs-agent-session"]
    agent["contract_sha256"] = _sha(
        (REPO / types["lvs-agent-session"]["contract_path"]).read_bytes()
    )
    agent["manifest_sha256"] = _phase(manifest, "lvs-agent-session")[
        "executor_input_sha256"
    ]
    agent["identity"]["run_id_sha256"] = _sha(
        _phase(manifest, "lvs-agent-session")["run_namespace"]
    )
    agent["semantic_observations"]["multi_video_report"] = True
    agent["cleanup"]["artifact_set_sha256"] = _sha(
        _canonical(sorted(row["path_sha256"] for row in agent["artifacts"]))
    )

    static = receipts["lvs-multi-static-oracle"]
    static["contract_sha256"] = _sha(
        (REPO / types["lvs-multi-static-oracle"]["contract_path"]).read_bytes()
    )
    static["fixture_sha256"] = _fixture(manifest, "lvs-static-oracle-fixture")["sha256"]

    focus = receipts["lvs-focus-matrix"]
    focus["contract_sha256"] = _sha(
        (REPO / types["lvs-focus-matrix"]["contract_path"]).read_bytes()
    )
    focus["run_id_sha256"] = _sha(_phase(manifest, "lvs-focus-matrix")["run_namespace"])
    focus["fixture_sha256"] = _fixture(manifest, "lvs-focus-mp4")["sha256"]

    alerts = receipts["alerts-terminal"]
    alerts["contract_sha256"] = _sha(
        (REPO / types["alerts-terminal"]["contract_path"]).read_bytes()
    )
    alerts["fixture_sha256"] = _fixture(manifest, "alerts-semantic-descriptor")[
        "sha256"
    ]
    return receipts


def _write_campaign(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    contract = json.loads((PACKAGE / "contract.json").read_text())
    manifest = _manifest(contract)
    receipts = _build_receipts(contract, manifest)
    model_payload = json.dumps(
        receipts[campaign.MODEL_RECEIPT_ID], sort_keys=True
    ).encode()
    model_receipt_sha = _sha(model_payload)
    manifest["model_semantic_receipt_sha256"] = model_receipt_sha
    for phase in manifest["phases"][2:]:
        phase["model_semantic_receipt_sha256"] = model_receipt_sha
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(json.dumps(manifest, indent=2).encode())
    descriptors = []
    raw_hashes = {}
    types = {row["receipt_id"]: row for row in contract["receipt_types"]}
    for index, phase in enumerate(contract["phases"], start=1):
        receipt_id = phase["receipt_id"]
        relative = f"receipts/{index:02d}-{receipt_id}.json"
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        payload = json.dumps(receipts[receipt_id], sort_keys=True).encode()
        path.write_bytes(payload)
        raw_hashes[receipt_id] = _sha(payload)
        manifest_phase = _phase(manifest, receipt_id)
        namespace = manifest_phase["run_namespace"]
        receipt_type = types[receipt_id]
        descriptors.append(
            {
                "receipt_id": receipt_id,
                "phase_id": phase["phase_id"],
                "path": relative,
                "sha256": raw_hashes[receipt_id],
                "contract_sha256": _sha(
                    (REPO / receipt_type["contract_path"]).read_bytes()
                ),
                "schema_sha256": _sha(
                    (REPO / receipt_type["schema_path"]).read_bytes()
                ),
                "run_namespace_sha256": _sha(namespace)
                if namespace is not None
                else None,
                "executor_input_sha256": manifest_phase["executor_input_sha256"],
                "model_semantic_receipt_sha256": manifest_phase[
                    "model_semantic_receipt_sha256"
                ],
            }
        )
    receipt_set = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "campaign_id": manifest["campaign_id"],
        "repository_commit": manifest["repository_commit"],
        "manifest_sha256": _sha(manifest_path.read_bytes()),
        "status": "candidate-receipts-validated-incomplete-nonpromoting",
        "evidence_complete": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
        "model_semantic_receipt_sha256": model_receipt_sha,
        "receipts": descriptors,
        "capability_evidence": contract["capability_mappings"],
        "lvs_multi_provenance": {
            "agent_receipt_sha256": raw_hashes["lvs-agent-session"],
            "static_result_sha256": raw_hashes["lvs-multi-static-oracle"],
            "live_artifact_set_sha256": receipts["lvs-agent-session"]["cleanup"][
                "artifact_set_sha256"
            ],
            "static_fixture_sha256": receipts["lvs-multi-static-oracle"][
                "fixture_sha256"
            ],
            "connected": False,
            "blocker": "lvs-multi-live-artifacts-are-not-inputs-to-the-static-semantic-oracle",
        },
        "unresolved_blockers": contract["required_blockers"],
    }
    receipt_set_path = tmp_path / "receipt-set.json"
    receipt_set_path.write_text(json.dumps(receipt_set, indent=2))
    return manifest_path, receipt_set_path, manifest, receipt_set


def _rewrite(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2))


def test_plan_is_inert_and_complete() -> None:
    result = campaign.compile_plan()
    assert result["status"] == "inert-campaign-plan-valid"
    assert result["receipt_count"] == 12
    assert result["selected_capability_count"] == 10
    assert result["mapped_capability_count"] == 15
    assert result["source_lock_count"] == 34
    assert result["verified_source_file_count"] == 43
    assert result["model_semantic_receipt_required"] is True
    assert result["runtime_activity_performed"] is False
    assert result["authorization_granted"] is False
    assert result["warehouse_sample_bundle"] == "excluded"


def test_default_cli_is_plan_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert campaign.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "inert-campaign-plan-valid"


def test_valid_incomplete_receipt_set(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, _receipt_set = _write_campaign(
        tmp_path
    )
    result = campaign.check_campaign(manifest_path, receipt_set_path)
    assert result["status"] == "campaign-receipt-set-valid-incomplete-nonpromoting"
    assert result["receipt_count"] == 12
    assert result["evidence_complete"] is False
    assert result["promotion_eligible"] is False
    assert (
        result["model_semantic_receipt_sha256"]
        == _receipt_set["model_semantic_receipt_sha256"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository_commit", "f" * 40),
        ("selected_binding_overlay_sha256", "f" * 64),
        ("required_cloud_inference", True),
        ("warehouse_sample_bundle", "included"),
    ],
)
def test_manifest_global_identity_drift_rejected(
    tmp_path: Path, field: str, value: Any
) -> None:
    manifest_path, receipt_set_path, manifest, receipt_set = _write_campaign(tmp_path)
    manifest[field] = value
    _rewrite(manifest_path, manifest)
    receipt_set["manifest_sha256"] = _sha(manifest_path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_duplicate_run_namespace_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, manifest, receipt_set = _write_campaign(tmp_path)
    manifest["phases"][2]["run_namespace"] = manifest["phases"][1]["run_namespace"]
    _rewrite(manifest_path, manifest)
    receipt_set["manifest_sha256"] = _sha(manifest_path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="not disjoint"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_profile_image_reference_drift_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, manifest, receipt_set = _write_campaign(tmp_path)
    manifest["profiles"][0]["images"][0]["reference"] += "-wrong"
    manifest["profiles"][0]["image_set_sha256"] = _sha(
        _canonical(manifest["profiles"][0]["images"])
    )
    _rewrite(manifest_path, manifest)
    receipt_set["manifest_sha256"] = _sha(manifest_path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="image reference"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_model_identity_substitution_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, manifest, receipt_set = _write_campaign(tmp_path)
    manifest["profiles"][0]["models"][0]["identity"] = "nvidia/older-fallback"
    manifest["profiles"][0]["model_set_sha256"] = _sha(
        _canonical(manifest["profiles"][0]["models"])
    )
    _rewrite(manifest_path, manifest)
    receipt_set["manifest_sha256"] = _sha(manifest_path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="model identity"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_readiness_only_model_evidence_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = _descriptor(receipt_set, campaign.MODEL_RECEIPT_ID)
    path = tmp_path / descriptor["path"]
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "plan_id": "vss-3.2.1-thor-official-edge-readiness",
                "qualification_state": "prelaunch_ready_not_runtime_qualified",
                "runtime_qualification_performed": False,
            }
        )
    )
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="schema violation"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_wrong_model_collector_hash_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = _descriptor(receipt_set, campaign.MODEL_RECEIPT_ID)
    path = tmp_path / descriptor["path"]
    receipt = json.loads(path.read_text())
    receipt["collector_locks"]["executor_sha256"] = "f" * 64
    path.write_text(json.dumps(receipt))
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="collector"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_wrong_model_tool_challenge_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = _descriptor(receipt_set, campaign.MODEL_RECEIPT_ID)
    path = tmp_path / descriptor["path"]
    receipt = json.loads(path.read_text())
    receipt["identity"]["llm_tool_challenge_sha256"] = "f" * 64
    path.write_text(json.dumps(receipt))
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="semantics"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_downstream_phase_without_model_receipt_dependency_rejected(
    tmp_path: Path,
) -> None:
    manifest_path, receipt_set_path, manifest, receipt_set = _write_campaign(tmp_path)
    base_phase = _phase(manifest, "base-tiny-agent-media")
    base_phase["model_semantic_receipt_sha256"] = None
    _descriptor(receipt_set, "base-tiny-agent-media")[
        "model_semantic_receipt_sha256"
    ] = None
    _rewrite(manifest_path, manifest)
    receipt_set["manifest_sha256"] = _sha(manifest_path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="mandatory semantic model"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_missing_or_duplicate_receipt_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    receipt_set["receipts"][-1] = copy.deepcopy(receipt_set["receipts"][-2])
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_replaced_receipt_payload_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    receipt_path = tmp_path / receipt_set["receipts"][3]["path"]
    receipt_path.write_text("{}")
    with pytest.raises(campaign.CampaignError, match="stale or replaced"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_cross_run_search_receipt_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = _descriptor(receipt_set, "search-file-semantics")
    path = tmp_path / descriptor["path"]
    receipt = json.loads(path.read_text())
    receipt["identity"]["run_id"] = "campaign-other-search-file-semantics"
    path.write_text(json.dumps(receipt))
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="cross-run"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_cross_run_hashed_receipt_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = _descriptor(receipt_set, "lvs-closure")
    path = tmp_path / descriptor["path"]
    receipt = json.loads(path.read_text())
    receipt["identity"]["run_id_sha256"] = _sha("different-run")
    path.write_text(json.dumps(receipt))
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="run namespace"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_stale_executor_manifest_receipt_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = _descriptor(receipt_set, "base-tiny-agent-media")
    path = tmp_path / descriptor["path"]
    receipt = json.loads(path.read_text())
    receipt["manifest_sha256"] = _sha("stale-manifest")
    path.write_text(json.dumps(receipt))
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="manifest"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_conflicting_search_standalone_receipt_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = _descriptor(receipt_set, "search-file-semantics")
    path = tmp_path / descriptor["path"]
    schema_path = "deploy/docker/thor-local/qualification/search-semantic-runtime-evidence-successor/receipt.schema.json"
    receipt = _receipt(schema_path, "forbidden-search")
    path.write_text(json.dumps(receipt))
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_lvs_disconnected_provenance_cannot_be_claimed_connected(
    tmp_path: Path,
) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    receipt_set["lvs_multi_provenance"]["connected"] = True
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_lvs_live_receipt_hash_mismatch_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    receipt_set["lvs_multi_provenance"]["agent_receipt_sha256"] = _sha("foreign")
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="LVS live/static"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_alerts_media_descriptor_drift_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = receipt_set["receipts"][-1]
    path = tmp_path / descriptor["path"]
    receipt = json.loads(path.read_text())
    # This value is source-schema-locked, so even a rehashed wrapper cannot pass.
    receipt["fixture_sha256"] = _sha("different-alert-descriptor")
    path.write_text(json.dumps(receipt))
    descriptor["sha256"] = _sha(path.read_bytes())
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_capability_mapping_overclaim_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    receipt_set["capability_evidence"][6]["evidence_status"] = (
        "candidate-receipt-valid-nonpromoting"
    )
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="mapping drift"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_blocker_removal_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    receipt_set["unresolved_blockers"][-1] = "replacement-blocker"
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError, match="blocker"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_unsafe_receipt_path_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    receipt_set["receipts"][0]["path"] = "../foreign.json"
    _rewrite(receipt_set_path, receipt_set)
    with pytest.raises(campaign.CampaignError):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_receipt_symlink_rejected(tmp_path: Path) -> None:
    manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    descriptor = receipt_set["receipts"][0]
    path = tmp_path / descriptor["path"]
    target = tmp_path / "target.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(campaign.CampaignError, match="symlink"):
        campaign.check_campaign(manifest_path, receipt_set_path)


def test_check_cli_requires_only_evidence_paths() -> None:
    parser = campaign._parser()
    assert parser.parse_args(["plan"]).command == "plan"
    with pytest.raises(SystemExit):
        parser.parse_args(["check"])
    help_text = parser.format_help()
    for forbidden in ("execute", "authorize", "promote", "docker", "download"):
        assert forbidden not in help_text.lower()


def test_all_generated_receipts_are_source_schema_valid(tmp_path: Path) -> None:
    _manifest_path, receipt_set_path, _manifest_value, receipt_set = _write_campaign(
        tmp_path
    )
    contract = json.loads((PACKAGE / "contract.json").read_text())
    types = {row["receipt_id"]: row for row in contract["receipt_types"]}
    for descriptor in receipt_set["receipts"]:
        value = json.loads((tmp_path / descriptor["path"]).read_text())
        schema = _schema(types[descriptor["receipt_id"]]["schema_path"])
        assert not list(Draft202012Validator(schema).iter_errors(value))
    assert receipt_set_path.is_file()
