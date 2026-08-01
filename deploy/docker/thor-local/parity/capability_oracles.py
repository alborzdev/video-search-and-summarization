#!/usr/bin/env python3

"""Compile and validate capability-specific acceptance oracles.

The compiler deliberately produces one fully expanded oracle per reviewed
official capability.  Shared policy lives here, while exact contract values,
scenario identity, fixtures, assertions, and cleanup targets remain bound to a
single capability.  This is a static plan: it never contacts a service or
changes host/container state.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
LEDGER = SCRIPT_DIR / "official-capabilities.json"
ORACLES = SCRIPT_DIR / "capability-oracles.json"
SCHEMA = SCRIPT_DIR / "capability-oracles.schema.json"
ACCEPTANCE = REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
PROTOCOL_CASES_PATH = "deploy/docker/thor-local/qualification/protocol-cases/protocol-cases.json"
PROTOCOL_CASES = REPO_ROOT / PROTOCOL_CASES_PATH
PROTOCOL_CASES_FILE_SHA256 = "28cbcabef1bf1f3ed41ebf398de3e2387548b2ec6de72b5a51d8c5f30a59a7a6"
PROTOCOL_CASES_SET_SHA256 = "3089ca096b4f86bbe54cce37027acf1769adff8bd1b4adf8a2018983c72ddb21"
OFFLINE_MV3DT_ROOT = "deploy/docker/thor-local/qualification/offline-mv3dt-tools"
OFFLINE_MV3DT_FILES = {
    "contract": {"path": f"{OFFLINE_MV3DT_ROOT}/contract.json", "raw_sha256": "070d8d89c0d38e2127da53478a5f093a460cc65b6a7ec4de1a45b79c36949984"},
    "executor": {"path": f"{OFFLINE_MV3DT_ROOT}/executor.py", "raw_sha256": "2055cf4ee3551a4cf680f1ad760eeef11c014ddb9fb952d78ec970864c9b0273"},
    "result_schema": {"path": f"{OFFLINE_MV3DT_ROOT}/result.schema.json", "raw_sha256": "e39cdaa74d3359f84be8cf16c2ace8dbf774c98de26ff89c01ff64d244d94887"},
    "fixture": {"path": f"{OFFLINE_MV3DT_ROOT}/fixtures/two-camera-calibration.json", "raw_sha256": "3b31aa74c5fa132437a35f2d2241f55fb204db58dedbe104cd8632fdef91cb33"},
    "execution_receipt": {"path": f"{OFFLINE_MV3DT_ROOT}/execution-receipt.json", "raw_sha256": "b01ae4fe7d6007ca89ce819462c44e04407ba0cedb20bb306067038091f38063"},
}
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")

# capability_id: (planning_requirement_id, minimum requests, maximum actions)
# Derived by qualification/runtime-execution-bounds-audit.  Exact IDs prevent
# an unrelated workload from inheriting a wider budget; actions are separate
# because three lifecycle/remediation flows contain non-request actions.
LOCAL_RUNTIME_WORKLOAD_OVERRIDES = {
    "runtime.workflow.base-chat-report": ("tiny-agent-media", 8, 8),
    "runtime.agent.base-hitl": ("hitl-state-transcript", 11, 11),
    "runtime.agent.lvs-profile": ("lvs-multi-file", 14, 14),
    "runtime.agent.search-profile": ("search-documents-and-bboxes", 14, 14),
    "runtime.workflow.alert-verification": ("candidate-alerts", 8, 8),
    "runtime.workflow.real-time-alerts": ("tiny-alert-stream", 12, 12),
    "runtime.ui.alerts-tab": ("ui-alert-api", 9, 9),
    "runtime.ui.search-tab": ("ui-search-api", 13, 13),
    "runtime.ui.video-management-tab": ("ui-tiny-media", 11, 11),
    "deployment.nemoclaw.same-host-operating-path": ("nemoclaw-lifecycle-mocks", 7, 9),
    "security.nemoclaw.policy-provider-network-boundary": ("nemoclaw-policy-network", 9, 9),
    "runtime.smart-city.chat-alert-dashboard": ("smartcity-ui-incidents", 8, 8),
    "runtime.smart-city.traffic-analytics": ("smartcity-synthetic-tracks", 14, 14),
    "runtime.smart-city.agent-workflow": ("smartcity-agent-pages", 12, 12),
    "calibration.legacy.core": ("smartcity-manual-calibration", 8, 8),
    "calibration.legacy.gis": ("smartcity-gis-calibration", 8, 8),
    "performance.alerts.worker-scaling": ("systems-alert-worker-scaling", 8, 8),
    "deployment.vios.horizontal-scaling": ("systems-vios-scaling", 7, 9),
    "behavior.elk.disk-watermark-recovery": ("systems-elk-recovery", 13, 13),
    "behavior.vios.upload-playback-remediation": ("systems-vios-playback-remediation", 8, 9),
}
LOCAL_RUNTIME_WORKLOAD_PHASES = ["pre_state", "positive", "adjacent_negative", "restore", "postcondition"]


class OracleContractError(ValueError):
    """The capability-oracle plan is incomplete or has drifted."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise OracleContractError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
    )
    if not isinstance(value, dict):
        raise OracleContractError(f"{path.name}: root must be an object")
    return value


def _resolve_reviewed_file(repo_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise OracleContractError(f"{label}: path must be a string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not value.startswith("deploy/docker/thor-local/"):
        raise OracleContractError(f"{label}: unsafe repository path")
    try:
        root = repo_root.resolve(strict=True)
        candidate = root
        for part in path.parts:
            candidate /= part
            if candidate.is_symlink():
                raise OracleContractError(f"{label}: path contains a symlink")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except OracleContractError:
        raise
    except (OSError, ValueError) as exc:
        raise OracleContractError(f"{label}: reviewed file is missing") from exc
    if not resolved.is_file():
        raise OracleContractError(f"{label}: reviewed path must be a file")
    return resolved


def _resolve_repo_regular_file(repo_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise OracleContractError(f"{label}: path must be a string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise OracleContractError(f"{label}: unsafe repository path")
    try:
        root = repo_root.resolve(strict=True)
        candidate = root
        for part in path.parts:
            candidate /= part
            if candidate.is_symlink():
                raise OracleContractError(f"{label}: path contains a symlink")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except OracleContractError:
        raise
    except (OSError, ValueError) as exc:
        raise OracleContractError(f"{label}: reviewed file is missing") from exc
    if not resolved.is_file():
        raise OracleContractError(f"{label}: reviewed path must be a file")
    return resolved


def _profile(capability: dict[str, Any]) -> tuple[str, str]:
    capability_id = capability["id"]
    kind = capability["kind"]
    if capability_id.startswith("model.remote-"):
        return "external-model-boundary", "model"
    if capability_id == "model.agent-vlm.custom-weights":
        return "custom-weight-directory", "model"
    if capability_id == "model.agent.openai-compatible-endpoints":
        return "openai-compatible-model-endpoint", "model"
    if kind == "model":
        return "exact-local-model-service", "model"
    if kind == "configuration":
        return f"configuration-{capability_id.split('.')[1]}", "config"
    if kind == "evaluation":
        return f"agent-evaluation-{capability_id.rsplit('.', 1)[-1]}", "runtime"
    if kind == "model_customization":
        return f"customization-{capability_id.split('.')[1]}", "runtime"
    if kind == "calibration":
        return f"calibration-{capability_id.removeprefix('calibration.').replace('.', '-')}", "runtime"
    if kind == "deployment":
        if capability_id.startswith("prereq.platform."):
            return f"host-prerequisite-{capability_id.rsplit('.', 1)[-1]}", "static"
        if capability_id.startswith("boundary.thor."):
            if capability_id == "boundary.thor.custom-all-local-extension":
                return "thor-custom-local-runtime-profiles", "runtime"
            return f"thor-support-boundary-{capability_id.rsplit('.', 1)[-1]}", "static"
        boundary = "external" if capability["acceptance_class"] == "external_optional" else "local"
        return f"{boundary}-deployment-{capability_id.split('.')[1]}", "deploy"
    if kind == "security":
        boundary = "external" if capability["acceptance_class"] == "external_optional" else "local"
        if boundary == "external":
            return "external-security-boundary", "deploy"
        if capability_id in {"behavior.rt-embed.ngc-scheme-key", "prereq.platform.credentials"}:
            return f"local-security-{capability_id.rsplit('.', 1)[-1]}", "config"
        return f"local-security-{capability_id.rsplit('.', 1)[-1]}", "runtime"
    if kind == "performance":
        return f"thor-measurement-{capability_id.rsplit('.', 1)[-1]}", "runtime"
    if kind == "tooling":
        return f"tool-{capability_id.rsplit('.', 1)[-1]}", "static"
    if kind == "api":
        if capability_id == "api.orchestrator-mcp.tools-9":
            return "orchestrator-mcp-approved-lifecycle", "runtime"
        return f"api-{capability_id.removeprefix('api.').replace('.', '-')}", "api"
    if kind == "protocol":
        return f"protocol-{capability_id.removeprefix('protocol.').replace('.', '-')}", "protocol"
    if kind == "runtime_behavior":
        return f"behavior-{capability_id.removeprefix('behavior.').replace('.', '-')}", "runtime"
    raise OracleContractError(f"{capability_id}: no oracle profile for kind {kind!r}")


def _action(capability: dict[str, Any], profile: str) -> str:
    capability_id = capability["id"]
    exact = {
        "config.vss-configurator.profile-manager": "render, validate, and diff a minimal 2D and 3D profile",
        "config.vss-configurator.sensor-manager": "create, validate, read back, and remove one namespaced sensor mapping",
        "config.sdrc.docker-distribution": "assign two namespaced streams and inspect Redis-backed ownership",
        "config.sdrc.envoy-routing": "route two stream IDs and verify stable workload affinity",
        "config.sdrc.session-restoration": "restart one namespaced workload and verify session restoration",
        "config.deepstream.init-adaptor": "run the init adaptor against one namespaced source config",
        "evaluation.agent.report": "score a two-row deterministic report fixture with every advertised metric",
        "evaluation.agent.qa": "score exact, incomplete, and semantically equivalent answers",
        "evaluation.agent.trajectory": "score one reference and one no-reference tool trajectory",
        "evaluation.agent.multi-turn": "score a two-turn conversation while preserving prior-turn context",
        "customization.siglip2": "load locked ONNX and TensorRT variants and compare embedding shape and tolerance",
        "customization.cosmos-embed1": "start RT-Embed with locked model and implementation paths, then index and query",
        "customization.sparse4d": "load a locked TAO Sparse4D artifact and run one calibrated multi-camera clip",
        "customization.rt-detr": "load a locked TAO RT-DETR artifact and run one short local clip",
        "customization.embedding-reindex-validation": "re-index a namespaced corpus and compare dimensions, completion, and similarity scale",
        "calibration.sdg.workflow": "generate calibration from a bounded synthetic custom scene and validate exported camera parameters",
        "calibration.legacy.core": "create a custom project, solve a 3x3 homography, validate ROI/tripwire, and export",
        "calibration.legacy.gis": "solve and export one custom GIS calibration project",
        "calibration.legacy.cartesian": "solve and export one custom Cartesian calibration project",
        "calibration.legacy.multi-camera": "solve and export one two-camera custom tracking calibration project",
        "calibration.legacy.image": "solve and export one custom image calibration project",
        "deployment.vlm-autoscaling.hpa": "render and server-validate an opt-in Kubernetes autoscaling manifest",
        "deployment.brev.launchable": "lint the pinned Brev notebook and review its explicit external boundary",
        "security.external-ingress-controls": "audit an operator-provided ingress for authentication, TLS, rate limiting, and deny-by-default access",
        "tool.mv3dt.cam-info-generator": "run the generator twice from one two-camera custom calibration fixture",
        "tool.mv3dt.pub-sub-generator": "run the generator twice from one two-camera sensor fixture",
        "api.vss-configurator.sensor": "exercise create/read/update/delete only in the oracle sensor namespace",
        "api.sdrc.control-plane": "exercise controller, router, and workload-coordinator health plus one namespaced assignment",
        "api.deepstream-configurator.post-config": "POST one valid and one invalid namespaced configuration",
        "api.auto-calibration.operations": "enumerate all 26 operations and run one namespaced upload-to-export lifecycle",
        "api.legacy-calibration.ui-server": "probe the loopback UI server and complete one namespaced project lifecycle",
        "protocol.agent.websocket": "open a loopback WebSocket, send one deterministic chat request, and observe ordered terminal completion",
        "protocol.alert.websocket": "subscribe on loopback, inject one namespaced alert, and observe exactly one matching delivery",
        "protocol.rt-vlm.sse": "request one short local clip and validate ordered SSE framing through the terminal event",
        "protocol.kafka.nvschema": "publish one namespaced NvSchema event and validate one consumer-decoded record",
        "protocol.redis.events": "append one namespaced event and validate consumer-group delivery and acknowledgement",
        "protocol.vios.webrtc-live": "negotiate loopback WebRTC for one local live source and observe decoded frames and timestamps",
        "protocol.vios.webrtc-replay": "negotiate loopback WebRTC replay, seek once, and observe decoded frames at the requested timestamp",
        "behavior.rt-embed.duplicate-id-409": "create duplicate camera and stream IDs and verify both conflict classes",
        "behavior.rt-vlm.url-auth": "serve a tiny clip from a loopback endpoint requiring the configured authorization token",
        "behavior.rt-vlm.url-redirect-limit": "serve redirect chains at the configured limit and one hop beyond it",
        "behavior.rt-vlm.url-size-limit": "serve bounded Content-Length fixtures immediately below and above the configured limit",
        "behavior.rt-vlm.url-tls-exception": "compare strict TLS rejection with an explicitly allowlisted loopback test hostname",
        "behavior.rt-vlm.generation-token-cap": "submit a deterministic request exceeding the generation cap and inspect bounded output",
        "behavior.rt-vlm.user-prompt-cap": "submit user prompts at and one character above the configured cap",
        "behavior.rt-vlm.system-prompt-cap": "submit system prompts at and one character above the configured cap",
        "behavior.rt-vlm.moe-backend": "inspect the selected MoE backend and complete one deterministic inference",
        "behavior.rt-vlm.kafka-queue-bound": "stall a namespaced consumer, fill the async queue to its bound, and verify bounded backpressure",
        "behavior.rt-cv.smart-infer": "run a short custom clip with smart-infer enabled and inspect inference scheduling",
        "behavior.rt-cv.ofa-predict": "run a short custom clip with OFA prediction enabled and inspect predicted tracks",
        "behavior.vios.per-camera-timestamps": "compare per-camera timestamps in replay and live-overlay modes",
        "behavior.vios.floor-map-formats": "load one tiny SVG and one tiny JPEG custom floor map on Thor",
        "behavior.vios.sensor-add-conflicts": "trigger each of the three documented sensor-add collision classes",
        "behavior.vios.byte-identical-download": "upload and download one small codec-compatible local clip and compare SHA-256",
        "behavior.rt-vlm.duplicate-id-409": "create duplicate camera and stream IDs and verify both documented 409 error classes without deleting pre-existing resources",
        "behavior.rt-vlm.independent-rtsp-jobs": "submit two caption jobs for one loopback RTSP stream and verify distinct request IDs plus independently observable job state",
        "behavior.rt-vlm.delete-stops-all-stream-jobs": "start two namespaced caption jobs for one loopback stream, delete by exact stream ID, and verify both jobs terminate while another stream remains active",
        "behavior.rt-vlm.generate-captions-endpoint-rename": "discover and call POST /v1/generate_captions, then verify the removed /v1/generate_captions_alerts route is absent",
        "behavior.rt-embed.base64-data-url": "submit the same tiny local clip as an RFC 2397 data URL and as a file, then compare successful embedding shape and provenance",
        "behavior.rt-embed.ngc-scheme-key": "inject a test-scoped NGC_API_KEY secret at runtime, verify ngc: resolution uses it, and scan config/log evidence to prove the value was not committed or emitted",
        "behavior.rt-embed.trt-precision": "render every allowed precision value, reject one invalid value, and prove the selected video and text engine precision at runtime",
        "behavior.rt-embed.trt-extra-args": "pass a shell-quoted sentinel argument to video and text engine builds and verify token-preserving argument parsing without command execution",
        "behavior.rt-embed.gop-decode-opt": "measure the same bounded file with GOP decode optimization off/on and verify RTSP behavior is unchanged",
        "behavior.rt-embed.kafka-queue-bound": "stall a namespaced Kafka consumer, fill the async queue to 1024, and verify bounded backpressure without unbounded memory growth",
        "behavior.rt-embed.file-url-allowlist": "with the allowlist unset reject file: URLs, then allow one exact temporary directory while rejecting a sibling and traversal path",
        "behavior.rt-embed.url-tls-exception": "compare strict TLS rejection with one explicitly allowlisted loopback test hostname and reject an unlisted hostname",
        "behavior.rt-embed.url-redirect-limit": "serve loopback redirect chains at zero, the configured limit, one beyond the limit, and above the maximum of ten",
        "behavior.rt-embed.url-size-limit": "serve bounded Content-Length fixtures immediately below and above the configured eight GiB limit using sparse/non-downloaded rejection probes",
        "behavior.rt-embed.url-auth": "serve a tiny clip from matching and non-matching loopback hostnames and verify authorization is attached only to the configured domain",
        "behavior.rt-embed.asset-max-age": "compare disabled eviction at zero with expiration of one backdated namespaced upload while a fresh upload remains",
        "prereq.platform.validated-gpus": "read host GPU identity and classify it against the exact validated, limited, or experimental platform sets without changing host state",
        "prereq.platform.agx-thor-software": "read BSP and driver versions and require exact AGX Thor 38.4 and 580.00 identities",
        "prereq.platform.toolchain-versions": "read toolkit, Docker, Compose, and NGC CLI versions and evaluate every exact version constraint",
        "prereq.platform.kernel-and-thor-runtime": "read every declared sysctl, nvpmodel, jetson_clocks, and cache-cleaner value; report exact drift without applying changes",
        "prereq.platform.docker-cgroupfs": "read Docker cgroup driver and daemon config; require cgroupfs and preserve a reviewed restart plan because applying it interrupts all containers",
        "prereq.platform.capacity-and-access": "measure CPU, RAM, SSD, network, GPU placement, and loopback browser-port readiness against every declared capacity field",
        "prereq.platform.credentials": "verify only presence, scope, and non-logging/non-commit controls for required NGC and Hugging Face credentials without printing secret values",
        "boundary.thor.official-profiles": "render each advertised Thor profile for AGX-THOR and IGX-THOR and require its remote-LLM layout without starting services",
        "boundary.thor.fully-local-future": "assert that VSS 3.2.1 does not label fully local workflows official and that future plans are never counted as current passed capability",
        "boundary.thor.custom-all-local-extension": "one profile at a time, deploy base, lvs, search, alerts, and warehouse-custom-data; run a bounded custom-data request with local endpoint provenance; clean up and restore before the next profile; exclude the sample bundle and preserve the non-official-support label",
        "tooling.agent-skills.catalog-16": "validate the exact 16-skill catalog, each SKILL.md frontmatter and agentskills.io identity, early-access warning, and advertised validated-model metadata",
        "tooling.agent-harnesses.validated-4": "run static discovery in each of the four named harness layouts and verify the skills remain developer-side rather than product-agent features",
        "api.orchestrator-mcp.tools-9": "phase one discovers exactly nine streamable-HTTP tools without mutation; only after explicit lifecycle approval, phase two executes namespaced generate/read/up/status/list/logs/down against one disposable Compose project",
    }
    if capability_id in exact:
        return exact[capability_id]
    if capability["feature_id"] == "core-api-operation-contracts":
        return "verify the expected manifest file digest and exact live operation/tool set, then run a reviewed method-specific positive, adjacent-negative, readback, and exact-cleanup oracle for every inventoried operation"
    if profile == "external-model-boundary":
        return "with explicit operator opt-in, query the exact managed model ID through its advertised provider"
    if profile == "custom-weight-directory":
        return "mount one immutable custom-weight directory and verify the service resolves only that directory"
    if profile == "openai-compatible-model-endpoint":
        return "query exact LLM and VLM model IDs through a loopback OpenAI-compatible endpoint"
    if profile == "exact-local-model-service":
        return "stage the exact immutable model, start only its namespaced service, and run one deterministic smoke request"
    if profile.startswith("thor-measurement-"):
        return "run a fixed one-stream custom fixture, record warmup/sample counts and Thor p50/p95/throughput without importing reference-hardware thresholds"
    # New reviewed claims within an already classified kind remain admissible
    # without a count- or source-specific code change. The action is still
    # capability-specific: its exact title and complete contract are embedded
    # in the expanded plan, and every contract leaf becomes an equality
    # assertion. Unknown kinds continue to fail in _profile().
    kind_actions = {
        "configuration": "apply, validate, read back, and restore the exact configuration contract",
        "evaluation": "run positive and adjacent-negative evaluator fixtures and record per-row plus aggregate results for the exact evaluation contract",
        "model_customization": "load one immutable custom artifact and validate selection, output schema, and a capability-specific semantic result for the exact customization contract",
        "calibration": "solve and export one bounded custom-data project, then validate schema, finite geometry, and input provenance for the exact calibration contract",
        "deployment": (
            "render, lint, and validate the opt-in external deployment contract without claiming a local runtime"
            if capability["acceptance_class"] == "external_optional"
            else "render, lint, deploy into an owned local namespace, verify readiness, and restore the exact local deployment contract"
        ),
        "security": (
            "audit deny-by-default behavior and every exact operator-managed security control"
            if capability["acceptance_class"] == "external_optional"
            else "exercise a permitted and denied local request, validate every exact security control, and restore the pre-test policy"
        ),
        "tooling": "run the exact tool contract twice in a temporary namespace and compare schema-valid output digests",
        "api": "discover the exact API contract, run one owned success lifecycle and one adjacent negative request, then clean up by exact ID",
        "protocol": "validate handshake, framing/schema, ordering, completion/acknowledgement, and disconnect behavior for the exact wire contract",
        "runtime_behavior": "run a passing boundary input and an adjacent rejected or limited input for the exact runtime behavior contract",
    }
    action = kind_actions.get(capability["kind"])
    if action is None:
        raise OracleContractError(f"{capability_id}: action is not defined")
    return f"{action}: {capability['title']}"


def _requires_media(capability: dict[str, Any]) -> bool:
    capability_id = capability["id"]
    if capability_id in {
        "customization.siglip2",
        "customization.cosmos-embed1",
        "boundary.thor.custom-all-local-extension",
    }:
        return True
    return any(
        token in capability_id
        for token in (
            "vlm",
            "video",
            "vios",
            "vst-",
            "calibration",
            "rt-cv",
            "rt-embed",
            "sparse4d",
            "rt-detr",
            "alert",
            "search",
            "siglip",
            "cosmos-embed",
        )
    )


def _fixture(capability: dict[str, Any], profile: str) -> dict[str, Any]:
    capability_id = capability["id"]
    external = capability["acceptance_class"] == "external_optional"
    media = _requires_media(capability)
    kind = "operator_external_contract" if external else "generated_custom_media" if media else "generated_minimal_contract"
    return {
        "id": f"fixture.{capability_id}",
        "kind": kind,
        "availability": "operator_required" if external else "not_staged",
        "source": "operator-provided opt-in boundary" if external else "bounded locally generated fixture",
        "warehouse_sample_bundle": False,
        "materialization": {
            "path": None,
            "generator": None,
            "sha256": None,
        },
        "input": {
            "capability_id": capability_id,
            "contract": copy.deepcopy(capability["contract"]),
            "namespace": f"vss-oracle-{capability_id.replace('.', '-')}",
            "action": _action(capability, profile),
        },
    }


def _observations(capability: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    capability_id = capability["id"]
    contract = capability["contract"]
    observations = [
        {
            "id": "contract_identity",
            "description": "The observed service/config/artifact identity exactly matches every declared contract field.",
        },
        {
            "id": "semantic_result",
            "description": _action(capability, profile),
        },
    ]
    if capability_id == "boundary.thor.custom-all-local-extension":
        observations.extend(
            {
                "id": f"profile_{profile_id.replace('-', '_')}",
                "description": f"The {profile_id} profile completes a bounded custom-data runtime qualification with local endpoint provenance and exact cleanup.",
            }
            for profile_id in contract["profiles"]
        )
        observations.append({"id": "sample_exclusion", "description": "No fixture, mount, command, or evidence references the excluded NVIDIA warehouse sample bundle."})
    elif capability_id == "api.orchestrator-mcp.tools-9":
        observations.extend(
            [
                {"id": "discovery_phase", "description": "The static phase discovers exactly nine tools and validates every input schema without invoking lifecycle tools."},
                {"id": "approved_lifecycle_phase", "description": "After explicit approval, generate/read/up/status/list/logs/down execute only against the owned Compose project and all cleanup postconditions pass."},
            ]
        )
    elif capability["kind"] == "model":
        observations.append({"id": "model_response", "description": "The exact model ID is reported by the backend and a bounded request completes without fallback."})
    elif capability["kind"] == "configuration":
        observations.append({"id": "round_trip", "description": "Rendered state validates, reads back without semantic drift, and restores the pre-test state."})
    elif capability["kind"] == "evaluation":
        observations.append({"id": "score_record", "description": "Per-row scores, aggregate scores, evaluator identity, and dataset digest are emitted."})
    elif capability["kind"] == "model_customization":
        observations.append({"id": "custom_artifact_selected", "description": "Runtime provenance identifies the locked custom artifact and the capability-specific output oracle passes."})
    elif capability["kind"] == "calibration":
        observations.append({"id": "calibration_export", "description": "Export is finite, schema-valid, bound to the custom inputs, and passes reprojection/geometry validation."})
    elif capability["kind"] in {"deployment", "security"}:
        if capability["acceptance_class"] == "external_optional":
            observations.append({"id": "boundary_admission", "description": "Only operator-opted external infrastructure is referenced; no local-complete claim is made."})
        else:
            observations.append({"id": "local_admission", "description": "The exact local contract reaches ready, satisfies its positive and negative probes, and returns to captured pre-test state."})
    elif capability["kind"] == "performance":
        observations.append({"id": "thor_measurement", "description": "Raw samples, warmup, concurrency, duration, p50, p95, throughput, errors, and Thor hardware metadata are recorded."})
    elif capability["kind"] == "tooling":
        observations.append({"id": "deterministic_output", "description": "Two clean runs produce schema-valid, byte-identical output in the exact declared output path."})
    elif capability["kind"] == "api":
        observations.append({"id": "api_contract", "description": "Exact operation discovery, success response, negative response, persistence/readback, and owned cleanup are observed."})
    elif capability["kind"] == "protocol":
        observations.append({"id": "wire_contract", "description": "Handshake, framing/schema, ordering, terminal/ack behavior, and disconnect cleanup match the declared protocol."})
    elif capability["kind"] == "runtime_behavior":
        observations.append({"id": "boundary_pair", "description": "A passing boundary case and a failing/limited adjacent case distinguish the advertised behavior."})
    else:
        raise OracleContractError(f"{capability_id}: observations are not defined")
    if not contract:
        raise OracleContractError(f"{capability_id}: empty contract")
    return observations


def _contract_assertions(capability: dict[str, Any]) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []

    def visit(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                escaped = key.replace("~", "~0").replace("/", "~1")
                visit(value[key], f"{pointer}/{escaped}")
            return
        assertions.append(
            {
                "id": f"contract-{len(assertions) + 1:02d}",
                "observation": f"contract_identity{pointer}",
                "operator": "equals",
                "expected": copy.deepcopy(value),
            }
        )

    visit(capability["contract"], "/contract")
    assertions.extend(
        {
            "id": f"observation-{index:02d}",
            "observation": observation["id"],
            "operator": "recorded_pass",
            "expected": True,
        }
        for index, observation in enumerate(_observations(capability, _profile(capability)[0]), 1)
        if observation["id"] != "contract_identity"
    )
    return assertions


def _admission(capability: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    capability_id = capability["id"]
    gates = [
        {"id": "operator-approval", "condition": "explicit approval exists for any service lifecycle or external access", "bounded": True},
        {"id": "target-bound", "condition": f"execution is pinned to capability {capability_id} and target commit", "bounded": True},
        {"id": "fixture-bound", "condition": "fixture digest, namespace, duration, and request count are recorded before execution", "bounded": True},
    ]
    if mode in {"model", "runtime", "api", "protocol"}:
        gates.append({"id": "runtime-capacity", "condition": "Thor cgroup, memory, disk, GPU, port, and exact artifact/image gates pass", "bounded": True})
    if capability["kind"] == "model":
        gates.append({"id": "model-artifact-staged", "condition": "the exact immutable model artifact and backend lock are staged and verified before the timed runtime oracle begins", "bounded": True})
    if capability["id"] == "api.orchestrator-mcp.tools-9":
        gates.append({"id": "orchestrator-lifecycle-approval", "condition": "explicit approval names the disposable Compose project before any lifecycle tool beyond discovery is invoked", "bounded": True})
    if capability["acceptance_class"] == "external_optional":
        gates.append({"id": "external-opt-in", "condition": "operator supplies the external environment and credentials; absence remains not_applicable", "bounded": True})
    return gates


def _cleanup(capability: dict[str, Any], mode: str) -> dict[str, Any]:
    capability_id = capability["id"]
    external_boundary = capability["acceptance_class"] == "external_optional"
    if external_boundary:
        return {"mutation": "none_by_default", "targets": [], "allowlist": [], "pre_state": "not_materialized", "restore": "revoke only test-scoped credentials/resources if the operator opts in", "executor": None, "postcondition_collectors": [], "postconditions": ["operator records removal or revocation of every test-scoped external resource"]}
    if capability["id"].startswith("prereq.platform.") or capability["id"] == "boundary.thor.fully-local-future":
        return {"mutation": "read_only", "targets": [], "allowlist": [], "pre_state": "read_only_snapshot_required", "restore": "no cleanup; the oracle records host or documentation state without applying remediation", "executor": None, "postcondition_collectors": [], "postconditions": ["a second read confirms the observed host or documentation state was not changed"]}
    if mode == "static":
        target = f"vss-oracle-{capability_id.replace('.', '-')}"
        return {"mutation": "temporary_files_only", "targets": [target], "allowlist": [target], "pre_state": "exact target absence or digest must be captured", "restore": "delete the exact temporary directory after digest capture", "executor": None, "postcondition_collectors": [], "postconditions": ["the exact temporary target is absent and no sibling path changed"]}
    target = f"vss-oracle-{capability_id.replace('.', '-')}"
    return {
        "mutation": "namespaced_and_reversible",
        "targets": [target],
        "allowlist": [target],
        "pre_state": "service, configuration, resource IDs, and target absence/digests must be captured before mutation",
        "restore": "remove only recorded oracle-owned resources and restore the captured pre-test service/config state",
        "executor": None,
        "postcondition_collectors": [],
        "postconditions": ["every allowlisted oracle-owned resource is absent", "captured service/config state and non-owned resource digests match pre-state"],
    }


def _workload(capability: dict[str, Any], live_integration: bool = True) -> dict[str, Any]:
    capability_id = capability["id"]
    contract = capability["contract"]
    if live_integration and capability_id in LOCAL_RUNTIME_WORKLOAD_OVERRIDES:
        _, request_budget, _ = LOCAL_RUNTIME_WORKLOAD_OVERRIDES[capability_id]
        units = 1
        phases = LOCAL_RUNTIME_WORKLOAD_PHASES
        per_unit = request_budget
        overhead = 0
    elif capability_id == "api.orchestrator-mcp.tools-9":
        units = len(contract["tools"])
        phases = ["schema_discovery", "approved_lifecycle", "state_readback", "cleanup"]
        per_unit = len(phases)
        overhead = 1
    elif capability["kind"] == "api":
        units = contract.get("operation_count") or contract.get("repository_tool_count") or contract.get("tool_count") or contract.get("operation_count", 1)
        phases = ["positive", "adjacent_negative", "readback", "cleanup"]
        per_unit = len(phases)
        overhead = 1
    elif capability_id in {"behavior.rt-vlm.kafka-queue-bound", "behavior.rt-embed.kafka-queue-bound"}:
        units = int(contract["default"]) + 1
        phases = ["bounded_send"]
        per_unit = 1
        overhead = 0
    elif capability_id == "boundary.thor.custom-all-local-extension":
        units = len(contract["profiles"])
        phases = ["deploy", "custom_data_request", "provenance_readback", "cleanup"]
        per_unit = len(phases)
        overhead = 1
    elif capability["kind"] == "model":
        units = 1
        phases = ["identity", "bounded_smoke"]
        per_unit = len(phases)
        overhead = 1
    else:
        units = 1
        phases = ["positive", "adjacent_negative"]
        per_unit = len(phases)
        overhead = 0
    max_requests = int(units) * per_unit + overhead
    return {
        "units": int(units),
        "requests_per_unit": per_unit,
        "overhead_requests": overhead,
        "calculated_max_requests": max_requests,
        "phases": phases,
    }


def _max_actions(capability: dict[str, Any], workload: dict[str, Any]) -> int:
    override = LOCAL_RUNTIME_WORKLOAD_OVERRIDES.get(capability["id"])
    return override[2] if override is not None else workload["calculated_max_requests"]


def canonical_oracle_sha256(oracle: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _protocol_case_bindings(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if hashlib.sha256(PROTOCOL_CASES.read_bytes()).hexdigest() != PROTOCOL_CASES_FILE_SHA256:
        raise OracleContractError("protocol case whole-file SHA-256 differs")
    if document.get("contract_set_sha256") != PROTOCOL_CASES_SET_SHA256:
        raise OracleContractError("protocol case internal set SHA-256 differs")
    target_commit = document.get("target_commit")
    cases = document.get("cases")
    if not isinstance(target_commit, str) or not isinstance(cases, list):
        raise OracleContractError("protocol case contract is malformed")
    bindings: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("capability_id"), str):
            raise OracleContractError("protocol case entry is malformed")
        capability_id = case["capability_id"]
        if capability_id in bindings:
            raise OracleContractError(f"{capability_id}: duplicate protocol case")
        sources = case.get("sources")
        negatives = case.get("adjacent_negative_vectors")
        positive = case.get("positive_vector")
        if not isinstance(sources, list) or not isinstance(negatives, list) or not isinstance(positive, dict):
            raise OracleContractError(f"{capability_id}: incomplete protocol case")
        bindings[capability_id] = {
            "path": PROTOCOL_CASES_PATH,
            "file_sha256": PROTOCOL_CASES_FILE_SHA256,
            "contract_set_sha256": PROTOCOL_CASES_SET_SHA256,
            "target_commit": target_commit,
            "case_id": case["case_id"],
            "case_sha256": hashlib.sha256(
                json.dumps(case, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "positive_vector_id": positive["id"],
            "negative_vector_ids": [item["id"] for item in negatives],
            "source_hashes": [
                {
                    "path": source["path"],
                    "git_blob_oid": source["git_blob_oid"],
                    "content_sha256": source["content_sha256"],
                }
                for source in sources
            ],
        }
    return bindings


def _planning_executor_bindings(
    acceptance_document: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Index live static-subset bindings without promoting full oracles.

    ``None`` deliberately means the historical pre-integration state.  Wave 3's
    immutable merge replay calls :func:`compile_plan` without an acceptance
    document, while live validation passes the checked-in acceptance inventory.
    """
    if acceptance_document is None:
        return {}
    requirements = acceptance_document.get("wave3_contracts", {}).get(
        "planning_requirements"
    )
    if not isinstance(requirements, list):
        raise OracleContractError("live planning requirements are malformed")
    result: dict[str, list[dict[str, Any]]] = {}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise OracleContractError("live planning requirement is malformed")
        materialized = requirement.get("materialized")
        executor_ready = requirement.get("executor_ready")
        binding = requirement.get("static_executor_binding")
        if materialized is False and executor_ready is False and binding is None:
            continue
        if materialized is not True or executor_ready is not True or not isinstance(
            binding, dict
        ):
            raise OracleContractError("partial live planning-executor integration")
        if requirement.get("runtime_evidence") != []:
            raise OracleContractError("planning executor must not contain runtime evidence")
        owner_type = requirement.get("owner_type")
        owner_id = requirement.get("owner_id")
        case = binding.get("case")
        if not isinstance(case, dict):
            raise OracleContractError("planning executor case is malformed")
        if (
            case.get("planning_requirement_id") != requirement.get("id")
            or case.get("planning_payload_sha256") != requirement.get("payload_canonical_sha256")
        ):
            raise OracleContractError("planning executor case ownership differs")
        case_capability_id = case.get("capability_id")
        if owner_type in {"capability", "performance_enrichment_target"}:
            capability_id = owner_id
            if not isinstance(capability_id, str) or case_capability_id != capability_id:
                raise OracleContractError("planning executor lacks its exact capability owner")
        elif owner_type == "global_acceptance_vector":
            applicable = requirement.get("applicable_record_ids")
            capability_id = case_capability_id
            if (
                owner_id != requirement.get("id")
                or case.get("planning_owner_type") != owner_type
                or case.get("planning_owner_id") != owner_id
                or not isinstance(capability_id, str)
                or not isinstance(applicable, list)
                or len(applicable) != len(set(applicable))
                or capability_id not in applicable
                or case.get("uncovered_applicable_record_ids")
                != [record_id for record_id in applicable if record_id != capability_id]
            ):
                raise OracleContractError("global planning executor target or uncovered partition differs")
        else:
            raise OracleContractError("planning executor owner type is unsupported")
        result.setdefault(capability_id, []).append(
            {
                "planning_requirement_id": requirement.get("id"),
                "scope": "bounded_static_assertion_subset_only",
                "materialization": copy.deepcopy(binding.get("materialization")),
                "executor": copy.deepcopy(binding.get("executor")),
                "case": copy.deepcopy(binding.get("case")),
                "result": copy.deepcopy(binding.get("result")),
                "can_advance_capability": False,
                "can_mark_passed_current": False,
                "runtime_evidence": [],
            }
        )
    return result


def _offline_mv3dt_tool_bindings(repo_root: Path = REPO_ROOT) -> dict[str, list[dict[str, Any]]]:
    """Bind the reviewed candidate result to only its supported oracle subset."""
    loaded: dict[str, dict[str, Any]] = {}
    for role, lock in OFFLINE_MV3DT_FILES.items():
        path = _resolve_reviewed_file(repo_root, lock["path"], f"offline_mv3dt.{role}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock["raw_sha256"]:
            raise OracleContractError(f"offline MV3DT {role} raw digest differs")
        if role in {"contract", "result_schema", "execution_receipt"}:
            loaded[role] = _load(path)
    contract = loaded["contract"]
    result_schema = loaded["result_schema"]
    receipt = loaded["execution_receipt"]
    expected_policy = {
        "candidate_only": True,
        "official_capability_effect": "none_candidate_only",
        "runtime_evidence": [],
        "network_allowed": False,
        "docker_allowed": False,
        "subprocess_allowed": False,
        "lifecycle_allowed": False,
        "downloads_allowed": False,
        "credentials_allowed": False,
        "warehouse_sample_bundle": "excluded",
        "writes": "private_temporary_directory_only",
    }
    entries = contract.get("advertised_entries")
    if (
        contract.get("mode") != "candidate_only_offline_mv3dt_tools"
        or contract.get("feature_id") != "mv3dt-config-utils"
        or contract.get("policy") != expected_policy
        or contract.get("execution", {}).get("runs") != 2
        or not isinstance(entries, list)
        or {item.get("capability_id") for item in entries if isinstance(item, dict)}
        != {"tool.mv3dt.cam-info-generator", "tool.mv3dt.pub-sub-generator"}
    ):
        raise OracleContractError("offline MV3DT candidate boundary differs")
    semantic = result_schema.get("$defs", {}).get("run", {}).get("properties", {}).get("semantic", {}).get("const")
    if not isinstance(semantic, dict) or set(semantic) != {"cam_info", "pub_sub"}:
        raise OracleContractError("offline MV3DT semantic result lock differs")
    source_locks = contract.get("source_locks")
    if not isinstance(source_locks, list) or len(source_locks) != 4:
        raise OracleContractError("offline MV3DT source-lock denominator differs")
    expected_source_paths = {
        "tools/rtvi-cv-mv3dt-utils/generate_cam_info_configs.py",
        "tools/rtvi-cv-mv3dt-utils/generate_pub_sub_configs.py",
        "tools/rtvi-cv-mv3dt-utils/requirements.txt",
        "deploy/docker/thor-local/parity/manifest.json",
    }
    if {item.get("path") for item in source_locks if isinstance(item, dict)} != expected_source_paths:
        raise OracleContractError("offline MV3DT source-lock path set differs")
    verified_source_locks: dict[str, str] = {}
    for source_lock in source_locks:
        relative = source_lock["path"]
        path = _resolve_repo_regular_file(repo_root, relative, f"offline_mv3dt.source_lock.{relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != source_lock.get("sha256"):
            raise OracleContractError(f"offline MV3DT source lock differs: {relative}")
        verified_source_locks[relative] = actual
    receipt_errors = sorted(
        Draft202012Validator(result_schema).iter_errors(receipt),
        key=lambda error: list(error.absolute_path),
    )
    if receipt_errors:
        first = receipt_errors[0]
        raise OracleContractError(f"offline MV3DT execution receipt schema failed: {first.message}")
    fixture_lock = OFFLINE_MV3DT_FILES["fixture"]
    expected_receipt_sources = {
        **verified_source_locks,
        fixture_lock["path"]: fixture_lock["raw_sha256"],
    }
    if receipt.get("source_and_fixture_sha256") != expected_receipt_sources:
        raise OracleContractError("offline MV3DT receipt source/fixture bindings differ")
    runs = receipt.get("deterministic_runs")
    if not isinstance(runs, list) or len(runs) != 2 or runs[0] != runs[1]:
        raise OracleContractError("offline MV3DT receipt does not contain two identical runs")
    observed_dependency = receipt.get("dependency_lock")
    if not isinstance(observed_dependency, dict):
        raise OracleContractError("offline MV3DT receipt dependency observation is absent")
    declared = observed_dependency.get("declared_requirements")
    observed_distributions = observed_dependency.get("observed_distribution_versions")
    expected_declared = contract.get("dependency_lock", {}).get("declared_requirements")
    if declared != expected_declared or not isinstance(observed_distributions, dict):
        raise OracleContractError("offline MV3DT receipt dependency declaration differs")
    declared_by_distribution = {
        "numpy": "numpy==2.2.6",
        "opencv-python": "opencv-python~=4.12.0",
        "PyYAML": "PyYAML==6.0.2",
        "tqdm": "tqdm==4.67.1",
    }
    if set(observed_distributions) != set(declared_by_distribution):
        raise OracleContractError("offline MV3DT dependency distribution set differs")
    mismatches = [
        {
            "distribution": distribution,
            "declared": requirement,
            "observed": observed_distributions[distribution],
        }
        for distribution, requirement in declared_by_distribution.items()
    ]
    if any(
        item["observed"] in item["declared"] for item in mismatches
    ):
        raise OracleContractError("offline MV3DT dependency mismatch boundary differs")
    receipt_run = runs[0]
    common = {
        "scope": "bounded_static_tool_observation_subset_only",
        "qualification_package": OFFLINE_MV3DT_ROOT,
        "contract": copy.deepcopy(OFFLINE_MV3DT_FILES["contract"]),
        "executor": {**OFFLINE_MV3DT_FILES["executor"], "invocation": ["python3", f"{OFFLINE_MV3DT_ROOT}/executor.py", "--check"]},
        "result_schema": copy.deepcopy(OFFLINE_MV3DT_FILES["result_schema"]),
        "fixture": copy.deepcopy(OFFLINE_MV3DT_FILES["fixture"]),
        "execution_receipt": copy.deepcopy(OFFLINE_MV3DT_FILES["execution_receipt"]),
        "source_locks": copy.deepcopy(source_locks),
        "dependency_observation": {
            **copy.deepcopy(observed_dependency),
            "declared_versions_match_observed_distributions": False,
            "normative_for_declared_requirements": False,
            "mismatches": mismatches,
        },
        "result": {
            key: copy.deepcopy(receipt[key])
            for key in (
                "observation",
                "run_count",
                "official_capability_effect",
                "warehouse_sample_bundle_used",
                "network_used",
                "docker_used",
                "subprocess_used",
                "lifecycle_used",
            )
        },
        "can_advance_capability": False,
        "can_mark_passed_current": False,
        "runtime_evidence": [],
    }
    coverage = {
        "covered_observation_ids": ["semantic_result", "deterministic_output"],
        "uncovered_observation_ids": ["contract_identity"],
        "covered_assertion_ids": ["contract-01", "contract-02", "contract-03", "contract-04", "observation-02", "observation-03"],
        "uncovered_assertion_ids": ["contract-05", "contract-06", "contract-07", "contract-08"],
    }
    outputs = receipt_run["output_locks"]
    observed_semantic = receipt_run["semantic"]
    return {
        "tool.mv3dt.cam-info-generator": [{**copy.deepcopy(common), "selected_output_locks": {"cam_info_tree_sha256": outputs["cam_info_tree_sha256"]}, "selected_semantic": {"cam_info": copy.deepcopy(observed_semantic["cam_info"])}, "oracle_coverage": copy.deepcopy(coverage)}],
        "tool.mv3dt.pub-sub-generator": [{**copy.deepcopy(common), "selected_output_locks": {"pub_sub_file_sha256": outputs["pub_sub_file_sha256"]}, "selected_semantic": {"pub_sub": copy.deepcopy(observed_semantic["pub_sub"])}, "oracle_coverage": copy.deepcopy(coverage)}],
    }


def compile_plan(
    ledger: dict[str, Any],
    protocol_document: dict[str, Any] | None = None,
    acceptance_document: dict[str, Any] | None = None,
    include_local_runtime_bounds: bool = True,
) -> dict[str, Any]:
    target = ledger.get("target")
    capabilities = ledger.get("capabilities")
    if not isinstance(target, dict) or not isinstance(capabilities, list):
        raise OracleContractError("official capability ledger is malformed")
    live_integration = include_local_runtime_bounds
    if live_integration:
        capability_ids = {item.get("id") for item in capabilities if isinstance(item, dict)}
        planning_ids = [row[0] for row in LOCAL_RUNTIME_WORKLOAD_OVERRIDES.values()]
        if (
            len(LOCAL_RUNTIME_WORKLOAD_OVERRIDES) != 20
            or not set(LOCAL_RUNTIME_WORKLOAD_OVERRIDES).issubset(capability_ids)
            or len(planning_ids) != len(set(planning_ids))
        ):
            raise OracleContractError("exact local-runtime workload override denominator drift")
    protocol_document = _load(PROTOCOL_CASES) if protocol_document is None else protocol_document
    protocol_bindings = _protocol_case_bindings(protocol_document)
    planning_bindings = _planning_executor_bindings(acceptance_document)
    offline_tool_bindings = {} if acceptance_document is None else _offline_mv3dt_tool_bindings()
    oracles = []
    for capability in capabilities:
        if not isinstance(capability, dict) or not isinstance(capability.get("id"), str):
            raise OracleContractError("official capability ledger contains an invalid capability")
        capability_id = capability["id"]
        profile, mode = _profile(capability)
        external_boundary = capability["acceptance_class"] == "external_optional"
        workload = _workload(capability, live_integration=live_integration)
        execution_bounds = {
            "executor": None,
            "collectors": [],
            "network_scope": "operator-approved external endpoint" if external_boundary else "loopback-or-compose-internal",
            "max_duration_seconds": 900,
            "max_requests": workload["calculated_max_requests"],
            "workload": workload,
            "model_staging": "prerequisite_only",
            "warehouse_sample_bundle": "excluded",
        }
        if live_integration:
            execution_bounds["max_actions"] = _max_actions(capability, workload)
        oracle = {
                "capability_id": capability_id,
                "oracle_id": f"oracle.{capability_id}",
                "profile": profile,
                "mode": mode,
                "ledger_binding": {
                    "feature_id": capability["feature_id"],
                    "kind": capability["kind"],
                    "title": capability["title"],
                    "source_claims": copy.deepcopy(capability["source_claims"]),
                    "acceptance_class": capability["acceptance_class"],
                    "thor_state": capability["thor_state"],
                    "runtime_state": capability["runtime_state"],
                    "contract": copy.deepcopy(capability["contract"]),
                    "gap": capability["gap"],
                },
                "reviewed_scenario_ids": [
                    *capability["scenario_ids"],
                    f"oracle.{capability_id}",
                ],
                "fixture": _fixture(capability, profile),
                "expected_observations": _observations(capability, profile),
                "assertions": _contract_assertions(capability),
                "admission_prerequisites": _admission(capability, mode),
                "execution_bounds": execution_bounds,
                "cleanup": _cleanup(capability, mode),
                "acceptance_readiness": {
                    "classification": "planning_index_only",
                    "blockers": [
                        "fixture path, generator, and digest are not materialized",
                        "request/command executor and collectors are not implemented",
                        "cleanup allowlist has no machine executor or postcondition collector",
                    ],
                },
                "current_state": "external_boundary_unexecuted" if external_boundary else "open_unexecuted",
                "evidence": [],
            }
        if capability["kind"] == "protocol":
            binding = protocol_bindings.get(capability_id)
            if binding is None:
                raise OracleContractError(f"{capability_id}: exact protocol case is missing")
            oracle["protocol_case_binding"] = binding
        if capability_id in planning_bindings:
            oracle["planning_executor_bindings"] = planning_bindings[capability_id]
            oracle["acceptance_readiness"]["blockers"] = [
                "the bounded static executor covers only named planning assertions, not the full capability runtime contract",
                "the full capability fixture, runtime executor, and collectors are not materialized",
                "the full capability cleanup allowlist has no machine executor or postcondition collector",
            ]
        if capability_id in offline_tool_bindings:
            oracle["offline_tool_observation_bindings"] = offline_tool_bindings[capability_id]
        oracles.append(oracle)
    return {
        "schema_version": 1,
        "target": {
            "product_version": target["product_version"],
            "main_commit": target["main_commit"],
            "captured_on": target["captured_on"],
        },
        "policy": {
            "claim_scope": "A checked-in planning_index_only oracle is an index of unresolved acceptance requirements, not an executable test or runtime evidence.",
            "pass_rule": "Only an executor_ready oracle with a materialized fixture and capability-bound current evidence satisfying every assertion may advance runtime_state to passed_current.",
            "generic_oracle_prohibited": True,
            "warehouse_sample_bundle": "excluded; custom-data fixtures remain in scope",
        },
        "oracles": oracles,
    }


def validate(
    plan: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    plan = _load(ORACLES) if plan is None else plan
    ledger = _load(LEDGER) if ledger is None else ledger
    schema = _load(SCHEMA)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise OracleContractError(f"invalid capability-oracle schema: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(plan),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise OracleContractError(f"oracle schema violation at {path}: {error.message}")
    expected = compile_plan(
        ledger,
        acceptance_document=_load(ACCEPTANCE),
        include_local_runtime_bounds=True,
    )
    if plan != expected:
        expected_by_id = {item["capability_id"]: item for item in expected["oracles"]}
        actual_by_id = {item.get("capability_id"): item for item in plan.get("oracles", []) if isinstance(item, dict)}
        if set(actual_by_id) != set(expected_by_id):
            missing = sorted(set(expected_by_id) - set(actual_by_id))
            extra = sorted(set(actual_by_id) - set(expected_by_id), key=str)
            raise OracleContractError(f"oracle coverage drift: missing={missing}, extra={extra}")
        changed = next(key for key in expected_by_id if actual_by_id[key] != expected_by_id[key])
        raise OracleContractError(f"{changed}: oracle contract drift; regenerate and review")
    oracle_ids = [item["oracle_id"] for item in plan["oracles"]]
    fixture_ids = [item["fixture"]["id"] for item in plan["oracles"]]
    unique_scenarios = [item["reviewed_scenario_ids"][-1] for item in plan["oracles"]]
    for label, values in (("oracle", oracle_ids), ("fixture", fixture_ids), ("scenario", unique_scenarios)):
        if len(values) != len(set(values)) or any(PLAIN_ID.fullmatch(value) is None for value in values):
            raise OracleContractError(f"capability-specific {label} identities must be unique plain IDs")
    signatures = {
        json.dumps(
            {
                "fixture": item["fixture"],
                "observations": item["expected_observations"],
                "assertions": item["assertions"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in plan["oracles"]
    }
    if len(signatures) != len(plan["oracles"]):
        raise OracleContractError("a generic oracle signature is reused across capabilities")
    if any(item["current_state"] not in {"open_unexecuted", "external_boundary_unexecuted"} or item["evidence"] for item in plan["oracles"]):
        raise OracleContractError("unexecuted oracle plans must not contain passed state or evidence")
    for item in plan["oracles"]:
        for binding in item.get("planning_executor_bindings", []):
            if (
                binding["can_advance_capability"] is not False
                or binding["can_mark_passed_current"] is not False
                or binding["runtime_evidence"] != []
                or binding["scope"] != "bounded_static_assertion_subset_only"
            ):
                raise OracleContractError(
                    f"{item['capability_id']}: static planning binding implies runtime advancement"
                )
        for binding in item.get("offline_tool_observation_bindings", []):
            if (
                binding["can_advance_capability"] is not False
                or binding["can_mark_passed_current"] is not False
                or binding["runtime_evidence"] != []
                or binding["scope"] != "bounded_static_tool_observation_subset_only"
                or binding["result"]["official_capability_effect"] != "none_candidate_only"
            ):
                raise OracleContractError(f"{item['capability_id']}: offline tool binding implies capability advancement")
            coverage = binding["oracle_coverage"]
            expected_observations = {observation["id"] for observation in item["expected_observations"]}
            covered_observations = set(coverage["covered_observation_ids"])
            uncovered_observations = set(coverage["uncovered_observation_ids"])
            expected_assertions = {assertion["id"] for assertion in item["assertions"]}
            covered_assertions = set(coverage["covered_assertion_ids"])
            uncovered_assertions = set(coverage["uncovered_assertion_ids"])
            if (
                covered_observations & uncovered_observations
                or covered_observations | uncovered_observations != expected_observations
                or covered_assertions & uncovered_assertions
                or covered_assertions | uncovered_assertions != expected_assertions
                or not uncovered_observations
                or not uncovered_assertions
            ):
                raise OracleContractError(f"{item['capability_id']}: offline tool oracle coverage is not an exact non-advancing partition")
        workload = item["execution_bounds"]["workload"]
        calculated = (
            workload["units"] * workload["requests_per_unit"]
            + workload["overhead_requests"]
        )
        if workload["calculated_max_requests"] != calculated or item["execution_bounds"]["max_requests"] != calculated:
            raise OracleContractError(f"{item['capability_id']}: execution-bound arithmetic differs")
        override = LOCAL_RUNTIME_WORKLOAD_OVERRIDES.get(item["capability_id"])
        expected_actions = override[2] if override is not None else calculated
        if item["execution_bounds"]["max_actions"] != expected_actions:
            raise OracleContractError(f"{item['capability_id']}: execution action bound differs")
        if override is not None:
            planning_ids = item["fixture"]["input"]["contract"].get("wave3_acceptance", {}).get("planning_requirement_ids")
            if planning_ids != [override[0]] or calculated != override[1] or workload["phases"] != LOCAL_RUNTIME_WORKLOAD_PHASES:
                raise OracleContractError(f"{item['capability_id']}: exact local-runtime workload override differs")
        if item["acceptance_readiness"]["classification"] == "planning_index_only":
            materialization = item["fixture"]["materialization"]
            if (
                not item["acceptance_readiness"]["blockers"]
                or any(materialization.values())
                or item["execution_bounds"]["executor"] is not None
                or item["execution_bounds"]["collectors"]
                or item["cleanup"]["executor"] is not None
                or item["cleanup"]["postcondition_collectors"]
            ):
                raise OracleContractError(f"{item['capability_id']}: planning-only oracle must not imply executable materialization")
        elif (
            item["acceptance_readiness"]["blockers"]
            or not all(item["fixture"]["materialization"].values())
            or not item["execution_bounds"]["executor"]
            or not item["execution_bounds"]["collectors"]
            or not item["cleanup"]["executor"]
            or not item["cleanup"]["postcondition_collectors"]
        ):
            raise OracleContractError(f"{item['capability_id']}: executor-ready oracle is incomplete")
        else:
            capability_id = item["capability_id"]
            materialization = item["fixture"]["materialization"]
            fixture_path = _resolve_reviewed_file(repo_root, materialization["path"], f"{capability_id}.fixture")
            if hashlib.sha256(fixture_path.read_bytes()).hexdigest() != materialization["sha256"]:
                raise OracleContractError(f"{capability_id}: fixture digest differs")
            _resolve_reviewed_file(repo_root, materialization["generator"], f"{capability_id}.fixture_generator")
            _resolve_reviewed_file(repo_root, item["execution_bounds"]["executor"], f"{capability_id}.executor")
            for index, collector in enumerate(item["execution_bounds"]["collectors"]):
                _resolve_reviewed_file(repo_root, collector, f"{capability_id}.collector[{index}]")
            _resolve_reviewed_file(repo_root, item["cleanup"]["executor"], f"{capability_id}.cleanup_executor")
            for index, collector in enumerate(item["cleanup"]["postcondition_collectors"]):
                _resolve_reviewed_file(repo_root, collector, f"{capability_id}.cleanup_collector[{index}]")
    return {
        "capabilities": len(ledger["capabilities"]),
        "oracles": len(plan["oracles"]),
        "open_runtime": sum(item["current_state"] == "open_unexecuted" for item in plan["oracles"]),
        "external_boundaries": sum(item["current_state"] == "external_boundary_unexecuted" for item in plan["oracles"]),
        "profiles": len({item["profile"] for item in plan["oracles"]}),
        "planning_index_only": sum(item["acceptance_readiness"]["classification"] == "planning_index_only" for item in plan["oracles"]),
        "executor_ready": sum(item["acceptance_readiness"]["classification"] == "executor_ready" for item in plan["oracles"]),
        "planning_executor_bindings": sum(
            len(item.get("planning_executor_bindings", [])) for item in plan["oracles"]
        ),
        "offline_tool_observation_bindings": sum(len(item.get("offline_tool_observation_bindings", [])) for item in plan["oracles"]),
        "static_subset_oracle_bindings": sum(
            len(item.get("planning_executor_bindings", []))
            + len(item.get("offline_tool_observation_bindings", []))
            for item in plan["oracles"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", action="store_true", help="print the canonical expanded plan")
    parser.add_argument("--report", action="store_true", help="print validation counts")
    args = parser.parse_args()
    try:
        if args.compile:
            print(
                json.dumps(
                    compile_plan(
                        _load(LEDGER),
                        acceptance_document=_load(ACCEPTANCE),
                        include_local_runtime_bounds=True,
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                end="",
            )
            return 0
        counts = validate()
    except (OSError, json.JSONDecodeError, OracleContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.report:
        print(json.dumps(counts, indent=2, sort_keys=True))
    else:
        print(f"PASS: {counts['oracles']} capability-specific planning-index records validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
