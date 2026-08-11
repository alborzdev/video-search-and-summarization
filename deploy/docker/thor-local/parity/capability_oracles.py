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
import subprocess
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
ACCEPTANCE = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
PROTOCOL_CASES_PATH = (
    "deploy/docker/thor-local/qualification/protocol-cases/protocol-cases.json"
)
PROTOCOL_CASES = REPO_ROOT / PROTOCOL_CASES_PATH
PROTOCOL_CASES_FILE_SHA256 = (
    "28cbcabef1bf1f3ed41ebf398de3e2387548b2ec6de72b5a51d8c5f30a59a7a6"
)
PROTOCOL_CASES_SET_SHA256 = (
    "3089ca096b4f86bbe54cce37027acf1769adff8bd1b4adf8a2018983c72ddb21"
)
OFFLINE_MV3DT_ROOT = "deploy/docker/thor-local/qualification/offline-mv3dt-tools"
OFFLINE_MV3DT_FILES = {
    "contract": {
        "path": f"{OFFLINE_MV3DT_ROOT}/contract.json",
        "raw_sha256": "070d8d89c0d38e2127da53478a5f093a460cc65b6a7ec4de1a45b79c36949984",
    },
    "executor": {
        "path": f"{OFFLINE_MV3DT_ROOT}/executor.py",
        "raw_sha256": "2055cf4ee3551a4cf680f1ad760eeef11c014ddb9fb952d78ec970864c9b0273",
    },
    "result_schema": {
        "path": f"{OFFLINE_MV3DT_ROOT}/result.schema.json",
        "raw_sha256": "e39cdaa74d3359f84be8cf16c2ace8dbf774c98de26ff89c01ff64d244d94887",
    },
    "fixture": {
        "path": f"{OFFLINE_MV3DT_ROOT}/fixtures/two-camera-calibration.json",
        "raw_sha256": "3b31aa74c5fa132437a35f2d2241f55fb204db58dedbe104cd8632fdef91cb33",
    },
    "execution_receipt": {
        "path": f"{OFFLINE_MV3DT_ROOT}/execution-receipt.json",
        "raw_sha256": "b01ae4fe7d6007ca89ce819462c44e04407ba0cedb20bb306067038091f38063",
    },
}
SYNTHETIC_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "synthetic-data-runtime-evidence-successor/executor.py"
)
SYNTHETIC_RUNTIME_FIXTURES = {
    "manifest-entry.synthetic-data-tools.00-semantic-label-helpers": (
        "deploy/docker/thor-local/qualification/"
        "metadata-500-current-synthetic-data-successor/fixtures/"
        "00-semantic-label-helpers.json",
        "0a079066c4ad506e8589206c8b51e21a0ecacdecb16fc9785c52033b0d279d27",
    ),
    "manifest-entry.synthetic-data-tools.01-dataset-checks": (
        "deploy/docker/thor-local/qualification/"
        "metadata-500-current-synthetic-data-successor/fixtures/01-dataset-checks.json",
        "0cc773dd0ec64aa4a45c379b298dc7580eddf89ab7702172fe101807d52c1ff2",
    ),
    "manifest-entry.synthetic-data-tools.02-rgb-depth-video-conversion": (
        "deploy/docker/thor-local/qualification/"
        "metadata-500-current-synthetic-data-successor/fixtures/"
        "02-rgb-depth-video-conversion.json",
        "171aef78bdd4738fa78f7114b27b9ca9cd0ec528ed52ae2f8be051c5b14dfd25",
    ),
    "manifest-entry.synthetic-data-tools.03-ground-truth-conversion": (
        "deploy/docker/thor-local/qualification/"
        "metadata-500-current-synthetic-data-successor/fixtures/"
        "03-ground-truth-conversion.json",
        "0a1f7d857d582aa47cd54aa1a956175a67976719443c8a9ed946962d8ef77939",
    ),
}
MV3DT_RUNTIME_EXECUTOR = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "mv3dt-config-utils-runtime-evidence-successor/executor.py"
    ),
    "raw_sha256": "650894ecc69baa518a92d8315c2d11c356b815a299ee50dc1e7b21737a87d567",
}
MV3DT_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 7,
    "overhead_requests": 0,
    "calculated_max_requests": 7,
    "phases": ["positive_run_1", "positive_run_2", "adjacent_negative"],
}
MV3DT_RUNTIME_FIXTURES = {
    "tool.mv3dt.cam-info-generator": {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "mv3dt-config-utils-runtime-evidence-successor/fixtures/"
            "00-cam-info-generator.json"
        ),
        "raw_sha256": "8dd769695b2f9ce48081f79c6f1e9c6f54423411f738fb23e58abc791869d2a5",
        "namespace": "vss-oracle-tool-mv3dt-cam-info-generator",
        "max_actions": 7,
        "max_requests": 7,
    },
    "tool.mv3dt.pub-sub-generator": {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "mv3dt-config-utils-runtime-evidence-successor/fixtures/"
            "01-pub-sub-generator.json"
        ),
        "raw_sha256": "0cb77ffe349809e1a8fe9349ecb1859a63ac564077b3326aadac6af264cd57ab",
        "namespace": "vss-oracle-tool-mv3dt-pub-sub-generator",
        "max_actions": 10,
        "max_requests": 7,
    },
}
MV3DT_PROMOTED_GAP = (
    "No known gap: a current target-bound offline runtime receipt covers the exact "
    "MV3DT configuration generator contract twice, including adjacent-negative "
    "behavior, determinism, and exact cleanup without the Warehouse sample bundle."
)
SPATIAL_AI_CORE_INTERFACE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "metadata-500-current-spatial-ai-utils-core-rebind-successor/"
        "runtime-interface.json"
    ),
    "raw_sha256": "37a3d29e7a83f2bfa6c09c2a41508eb6c785f8b8267117e82f6ebfdcd1edd305",
}
SPATIAL_AI_CORE_INTERFACE_SCHEMA = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "metadata-500-current-spatial-ai-utils-core-rebind-successor/"
        "runtime-interface.schema.json"
    ),
    "raw_sha256": "5c08e40ff22e6101f20fa7938199a90763d1eab668edb156ae479a2061dcac83",
}
SPATIAL_AI_CORE_CANONICAL_BASE_COMMIT = "548f7fdda9148b3ee521c09dcdb298309f25fe2b"
SPATIAL_AI_CORE_PRODUCER_COMMIT = "68ed897f4a5121d8d487a60e0519205a28fc6c09"
SPATIAL_AI_CORE_IDS = (
    "manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-entry.spatial-ai-utils.05-nvschema-conversion",
)
SPATIAL_AI_IDS = tuple(
    f"manifest-entry.spatial-ai-utils.0{index}-{suffix}"
    for index, suffix in enumerate(
        (
            "calibration-and-camera-grouping",
            "3d-2d-geometry",
            "multiview-visualization",
            "detection-map",
            "tracking-hota-clear-identity-count",
            "nvschema-conversion",
            "video-frame-tools",
            "aws-gcs-validation",
        )
    )
)
SPATIAL_AI_CORE_GAP = (
    "No known gap: the committed target-bound offline SpatialAI runtime producer "
    "covers two positive runs, five named adjacent cases, deterministic output, "
    "exact cleanup, and observed imported-product calls without the Warehouse "
    "sample bundle. Runtime evidence remains a separate, non-promoting stage."
)
SPATIAL_AI_CORE_HISTORICAL_PREDECESSOR_SHA256 = {
    "manifest-entry.spatial-ai-utils.01-3d-2d-geometry": (
        "8e5db30cb2604c52d1b1ef1ad0e3aaa796649d9335ce2d570efe3e36e68c8669"
    ),
    "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count": (
        "73770bdd0758be1bcfeb74548740dcfd84ba06b6818ca0ba8c9661efb071d333"
    ),
    "manifest-entry.spatial-ai-utils.05-nvschema-conversion": (
        "eb82438b6bde164e4c12b18287e1e472362d8d694f0e088d537fb552b2899e0e"
    ),
}
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
CPU_MULTIMEDIA_CAPABILITY_ID = (
    "manifest-entry.vios-codecs-audio.05-cpu-multimedia-support"
)
VIOS_BYTE_DOWNLOAD_CAPABILITY_ID = "behavior.vios.byte-identical-download"
VIOS_BYTE_DOWNLOAD_EXECUTOR = (
    "deploy/docker/thor-local/qualification/vios-file-lifecycle-runtime/execute.py"
)
VIOS_BYTE_DOWNLOAD_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "vios-file-lifecycle-runtime/fixture-contract.json"
    ),
    "sha256": "297821477baaea974ad9c91736cf6a40871958528ccc7c41c6012fb7b3c85b61",
}
VIOS_BYTE_DOWNLOAD_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "vios-file-lifecycle-runtime/official-runtime-evidence.json"
        ),
        "sha256": "05d397fc57414b0cf404ce6e990f8759444597d7ce3901e6c467fbf0ca7ecdf7",
    }
]
VIOS_BYTE_DOWNLOAD_NAMESPACE = "vss_qual_vios_lifecycle"
VIOS_BYTE_DOWNLOAD_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 2,
    "overhead_requests": 11,
    "calculated_max_requests": 13,
    "phases": ["positive", "adjacent_negative", "cleanup"],
}
NVSTREAMER_FILE_CAPABILITY_ID = "runtime.nvstreamer.file-streaming"
NVSTREAMER_FILE_EXECUTOR = (
    "deploy/docker/thor-local/qualification/nvstreamer-file-workflow-runtime/execute.py"
)
NVSTREAMER_FILE_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "nvstreamer-file-workflow-runtime/fixture-contract.json"
    ),
    "sha256": "f7706aeb2a76e06945a080d258057ce25d23435f2cd1412f35975e515baafe00",
}
NVSTREAMER_FILE_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "nvstreamer-file-workflow-runtime/official-runtime-evidence.json"
        ),
        "sha256": "a4daa8ba496146cfb09feba89131c103efa7211734cc60cd655a29ae812ac7b2",
    }
]
NVSTREAMER_FILE_NAMESPACE = "vss_qual_nvstreamer"
NVSTREAMER_FILE_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 3,
    "overhead_requests": 45,
    "calculated_max_requests": 48,
    "phases": [
        "pre_state",
        "positive_upload",
        "positive_ui",
        "positive_local_mount",
        "rtsp",
        "webrtc",
        "adjacent_negative",
        "cleanup",
        "postcondition",
    ],
}
NVSTREAMER_SYNC_CAPABILITY_ID = "configuration.nvstreamer.sync"
NVSTREAMER_SYNC_EXECUTOR = (
    "deploy/docker/thor-local/qualification/nvstreamer-sync-playback-runtime/execute.py"
)
NVSTREAMER_SYNC_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "nvstreamer-sync-playback-runtime/fixture-contract.json"
    ),
    "sha256": "9135836e0962e2c1ed1634def225ffd873a4b57e563452c0652f317604afc019",
}
NVSTREAMER_SYNC_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "nvstreamer-sync-playback-runtime/official-runtime-evidence.json"
        ),
        "sha256": "eb13cebb154ac082803143e01e08df978991f40e1d15a5a0265d9f03aa8bd07e",
    }
]
NVSTREAMER_SYNC_NAMESPACE = "vss_qual_sync"
NVSTREAMER_SYNC_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 4,
    "overhead_requests": 12,
    "calculated_max_requests": 16,
    "phases": [
        "pre_state",
        "config_apply",
        "single_client_barrier",
        "second_client_release",
        "cleanup",
        "postcondition",
    ],
}
NVSTREAMER_SYNC_MAX_ACTIONS = 24
NVSTREAMER_FULL_CONFIG_CAPABILITY_ID = "configuration.nvstreamer.full-contract"
NVSTREAMER_FULL_CONFIG_EXECUTOR = (
    "deploy/docker/thor-local/qualification/nvstreamer-full-config-runtime/execute.py"
)
NVSTREAMER_FULL_CONFIG_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "nvstreamer-full-config-runtime/fixture-contract.json"
    ),
    "sha256": "7eb3789fcb182afe4259fd4c00e80d29ddbf68d929e648a2f06bac19b34db3b9",
}
NVSTREAMER_FULL_CONFIG_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "nvstreamer-full-config-runtime/official-runtime-evidence.json"
        ),
        "sha256": "59aa9c7c46bb8ea49398e20a7a9d109597b4115fbd33cb843a9d11bccee695e7",
    }
]
NVSTREAMER_FULL_CONFIG_NAMESPACE = "vss-qual-nvstreamer-full-config"
NVSTREAMER_FULL_CONFIG_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 5,
    "overhead_requests": 5,
    "calculated_max_requests": 10,
    "phases": [
        "pre_state",
        "config_apply",
        "five_service_readback",
        "writable_round_trip",
        "startup_readback",
        "cleanup",
        "postcondition",
    ],
}
NVSTREAMER_FULL_CONFIG_MAX_ACTIONS = 16
VIOS_WEBRTC_REPLAY_CAPABILITY_ID = "protocol.vios.webrtc-replay"
VIOS_WEBRTC_REPLAY_EXECUTOR = (
    "deploy/docker/thor-local/qualification/vios-webrtc-replay-runtime/execute.py"
)
VIOS_WEBRTC_REPLAY_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "vios-webrtc-replay-runtime/fixture-contract.json"
    ),
    "sha256": "0cdf3e7196e191f0a0f68c24c7b93eb06b223991372ec625443c40f7c19aeebd",
}
VIOS_WEBRTC_REPLAY_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "vios-webrtc-replay-runtime/official-runtime-evidence.json"
        ),
        "sha256": "1475508276dc062fccd070d696718a7b10a88c8a613778aa2b30d822728dba1f",
    }
]
VIOS_WEBRTC_REPLAY_NAMESPACE = "vss-oracle-protocol-vios-webrtc-replay"
VIOS_WEBRTC_REPLAY_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 8,
    "overhead_requests": 56,
    "calculated_max_requests": 64,
    "phases": [
        "pre_state",
        "browser_signaling",
        "positive_seek",
        "position_readback",
        "adjacent_negative",
        "native_ui_seek",
        "cleanup",
        "postcondition",
    ],
}
VIOS_WEBRTC_REPLAY_MAX_ACTIONS = 32
VIOS_WEBRTC_LIVE_CAPABILITY_ID = "protocol.vios.webrtc-live"
VIOS_WEBRTC_LIVE_EXECUTOR = (
    "deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/execute.py"
)
VIOS_WEBRTC_LIVE_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "vios-webrtc-live-runtime/fixture-contract.json"
    ),
    "sha256": "b8b1436835a8db5f7cfc29f8eb12cda959e3df1056b9a3003123a44f3eaffc89",
}
VIOS_WEBRTC_LIVE_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "vios-webrtc-live-runtime/official-runtime-evidence.json"
        ),
        "sha256": "01a6f1e7e37445235256218ea9d87268d1b8fefbbc5d3766b789a93951d8009c",
    }
]
VIOS_WEBRTC_LIVE_NAMESPACES = [
    "vss-vios-webrtc-live-owned-container",
    "vss_qual_nvstreamer_owned_local_mount",
    "vss_qual_nvstreamer_owned_api_upload",
]
VIOS_WEBRTC_LIVE_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 10,
    "overhead_requests": 86,
    "calculated_max_requests": 96,
    "phases": [
        "pre_state",
        "bootstrap",
        "upload",
        "adjacent_negative",
        "browser_signaling",
        "decoded_media",
        "timestamp_readback",
        "explicit_stop",
        "cleanup",
        "postcondition",
    ],
}
VIOS_WEBRTC_LIVE_MAX_ACTIONS = 32
VIDEO_ANALYTICS_RUNTIME_CAPABILITY_IDS = (
    "runtime.video-analytics.query-and-library-contract",
    "behavior.video-analytics.optional-kafka",
)
VIDEO_ANALYTICS_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/video-analytics-api-runtime/harness.mjs"
)
VIDEO_ANALYTICS_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "video-analytics-api-runtime/contract.json"
    ),
    "sha256": "7cbe3cdb682e0180e835eddb703920afc3538645e2669d73076ef3e6c123502b",
}
VIDEO_ANALYTICS_RUNTIME_EVIDENCE = {
    "runtime.video-analytics.query-and-library-contract": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/video-analytics-api-runtime/"
                "official-runtime-evidence-query-library.json"
            ),
            "sha256": "895962811784eb8b03897f048fb9ed5d31156fc0443384ad39c49c1ed13bf8f5",
        }
    ],
    "behavior.video-analytics.optional-kafka": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/video-analytics-api-runtime/"
                "official-runtime-evidence-optional-kafka.json"
            ),
            "sha256": "125f3ab237b425c3d0bbd530755f26040d66fc13664fab43626da26d563eb1b3",
        }
    ],
}
VIDEO_ANALYTICS_RUNTIME_NAMESPACE = "vss-oracle-video-analytics"
VIDEO_ANALYTICS_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 71,
    "overhead_requests": 0,
    "calculated_max_requests": 71,
    "phases": [
        "pre_state",
        "positive_posts",
        "all_get_operations",
        "adjacent_negative_posts",
        "calibration_cleanup",
        "brokerless_boundary",
        "cleanup",
        "postcondition",
    ],
}
VIDEO_ANALYTICS_RUNTIME_MAX_ACTIONS = 96
EVENT_TRANSPORT_RUNTIME_CAPABILITY_IDS = (
    "protocol.kafka.nvschema",
    "protocol.redis.events",
)
EVENT_TRANSPORT_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/event-transports-runtime/execute.py"
)
EVENT_TRANSPORT_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/event-transports-runtime/contract.json"
    ),
    "sha256": "2229e2ff89a22fe0454bab8028d5d3764d5d21908fc2e9c742e6e208a29ef043",
}
EVENT_TRANSPORT_RUNTIME_EVIDENCE = {
    "protocol.kafka.nvschema": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/event-transports-runtime/"
                "official-runtime-evidence-kafka.json"
            ),
            "sha256": "c17aa7a3747f60498e3f5ede7897fae415ddabec2fe1cfa377c1e572cb41f192",
        }
    ],
    "protocol.redis.events": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/event-transports-runtime/"
                "official-runtime-evidence-redis.json"
            ),
            "sha256": "ddd6ee935c5a8da3d231d226d9695091ba90d28e9e094335e82137ced124a2e6",
        }
    ],
}
EVENT_TRANSPORT_RUNTIME_NAMESPACES = {
    "protocol.kafka.nvschema": [
        "vss-protocol-case-kafka-nvschema",
        "vss-protocol-case-kafka-nvschema-group",
        "vss-oracle-protocol-kafka-nvschema",
    ],
    "protocol.redis.events": [
        "vss-protocol-case-redis-events",
        "vss-protocol-case-redis-group",
        "vss-oracle-protocol-redis-events",
    ],
}
EVENT_TRANSPORT_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 4,
    "overhead_requests": 0,
    "calculated_max_requests": 4,
    "phases": [
        "pre_state",
        "kafka_positive",
        "kafka_adjacent_negative",
        "redis_positive",
        "redis_adjacent_negative",
        "cleanup",
        "postcondition",
    ],
}
EVENT_TRANSPORT_RUNTIME_MAX_ACTIONS = 16
AGENT_WEBSOCKET_RUNTIME_CAPABILITY_ID = "protocol.agent.websocket"
AGENT_WEBSOCKET_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "agent-websocket-runtime-successor/execute.py"
)
AGENT_WEBSOCKET_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "agent-websocket-runtime-successor/contract.json"
    ),
    "sha256": "f6c6508734f7e4ce2bc724c78617f28821fea0f2810276f912498ec9800b5180",
}
AGENT_WEBSOCKET_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "agent-websocket-runtime-successor/official-runtime-evidence.json"
        ),
        "sha256": "d2b82ab841a5ee9dc65ede6ada0903b973432129b71188251f2d70dc25d6da30",
    }
]
AGENT_WEBSOCKET_RUNTIME_NAMESPACES = [
    "vss-oracle-protocol-agent-websocket",
]
AGENT_WEBSOCKET_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 2,
    "overhead_requests": 0,
    "calculated_max_requests": 2,
    "phases": [
        "pre_state",
        "handshake",
        "positive",
        "adjacent_negative",
        "disconnect",
        "postcondition",
    ],
}
AGENT_WEBSOCKET_RUNTIME_MAX_ACTIONS = 2
ALERT_WEBSOCKET_RUNTIME_CAPABILITY_ID = "protocol.alert.websocket"
ALERT_WEBSOCKET_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/alert-websocket-runtime/execute.py"
)
ALERT_WEBSOCKET_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/alert-websocket-runtime/contract.json"
    ),
    "sha256": "bb96e55fe28f1c480175086e4f6cfc1dc1b0216d72a825fb73eb6c9f2722953f",
}
ALERT_WEBSOCKET_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/alert-websocket-runtime/"
            "official-runtime-evidence.json"
        ),
        "sha256": "66ed95ec555d38d32a745c14e6ff8a1af4af0e56c6874f0fb1c6d2975444b44a",
    }
]
ALERT_WEBSOCKET_RUNTIME_NAMESPACES = [
    "vss-oracle-protocol-alert-websocket",
    "vss-protocol-case-alert-input",
    "vss-protocol-case-alert-enhanced",
    "vss-protocol-case-alert-group",
]
ALERT_WEBSOCKET_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 2,
    "overhead_requests": 0,
    "calculated_max_requests": 2,
    "phases": [
        "pre_state",
        "handshake",
        "positive",
        "adjacent_negative",
        "acknowledgement",
        "disconnect",
        "cleanup",
        "postcondition",
    ],
}
ALERT_WEBSOCKET_RUNTIME_MAX_ACTIONS = 12
RT_VLM_SSE_RUNTIME_CAPABILITY_IDS = {
    "model.rt-vlm.default-cosmos3-nano-bf16",
    "protocol.rt-vlm.sse",
    "behavior.rt-vlm.generation-token-cap",
    "behavior.rt-vlm.user-prompt-cap",
    "behavior.rt-vlm.system-prompt-cap",
    "behavior.rt-vlm.generate-captions-endpoint-rename",
}
RT_VLM_SSE_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/execute.py"
)
RT_VLM_SSE_RUNTIME_FIXTURE = {
    "path": ("deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/contract.json"),
    "sha256": "63dd1f62586621d057c8a962de5dfbef67995f5d9c563cf115311159393dafdc",
}
RT_VLM_SSE_RUNTIME_EVIDENCE = {
    "model.rt-vlm.default-cosmos3-nano-bf16": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/"
                "official-runtime-evidence-model.json"
            ),
            "sha256": "a92a884b145f218c0be58111553494371dc1300f7bd0435fe0b412dc636e3409",
        }
    ],
    "protocol.rt-vlm.sse": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/"
                "official-runtime-evidence-sse.json"
            ),
            "sha256": "6d78857a71168d7e4400bb7d57b24e64e9639d50f461858e17fd4c245bbab56b",
        }
    ],
    "behavior.rt-vlm.generation-token-cap": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/"
                "official-runtime-evidence-generation-token-cap.json"
            ),
            "sha256": "d8125f3e06804e39be83bb6931028450e122bc8357df311ddb2d2f2f89debc11",
        }
    ],
    "behavior.rt-vlm.user-prompt-cap": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/"
                "official-runtime-evidence-user-prompt-cap.json"
            ),
            "sha256": "35d9c234983c137f31ab888367d7d89b4dea4d3db83354fefdec88f6ec8621b1",
        }
    ],
    "behavior.rt-vlm.system-prompt-cap": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/"
                "official-runtime-evidence-system-prompt-cap.json"
            ),
            "sha256": "efe38ec8bef437f1717c1811c0d2ec7e06925e14d28a66c6e85220d85bdf46c5",
        }
    ],
    "behavior.rt-vlm.generate-captions-endpoint-rename": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/"
                "official-runtime-evidence-endpoint-rename.json"
            ),
            "sha256": "68a010f9812af969985cc8d2f8a828fcd7b5f9d7ecf65a92f1fb23f195c4009e",
        }
    ],
}
RT_VLM_SSE_RUNTIME_NAMESPACES = [
    "00000000-0000-4000-8000-000000000003",
    "vss-oracle-protocol-rt-vlm-sse",
]
RT_VLM_SSE_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 22,
    "overhead_requests": 0,
    "calculated_max_requests": 22,
    "phases": [
        "static_and_runtime_identity",
        "pre_state",
        "owned_file_upload_and_readback",
        "blank_prompt_negative",
        "generation_token_boundary_pair",
        "user_prompt_boundary_pair",
        "system_prompt_boundary_pair",
        "caption_sse_positive",
        "exact_owned_cleanup",
        "postcondition",
    ],
}
RT_VLM_SSE_RUNTIME_MAX_ACTIONS = 8
OFFICIAL_EDGE_MODEL_RUNTIME_CAPABILITY_IDS = {
    "model.edge.nemotron-3-nano-4b-fp8",
    "model.edge.cosmos3-nano-served-id",
}
OFFICIAL_EDGE_MODEL_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "official-edge-model-identities-runtime/execute.py"
)
OFFICIAL_EDGE_MODEL_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "official-edge-model-identities-runtime/contract.json"
    ),
    "sha256": "87f7d363c51c840dd079297cb55bc66d312d2e79b2679f4db0c6d5a878d0b924",
}
OFFICIAL_EDGE_MODEL_RUNTIME_EVIDENCE = {
    "model.edge.nemotron-3-nano-4b-fp8": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "official-edge-model-identities-runtime/"
                "official-runtime-evidence-nemotron.json"
            ),
            "sha256": "2ff121a4cc600641ccd62d4e6fc163e115e759b8654523ebf1ffc383577e69a4",
        }
    ],
    "model.edge.cosmos3-nano-served-id": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "official-edge-model-identities-runtime/"
                "official-runtime-evidence-cosmos3.json"
            ),
            "sha256": "b142e6a770b126611fb2033575210cb51f61ee5c9326bdb930bbfc89ac4fa373",
        }
    ],
}
OFFICIAL_EDGE_MODEL_RUNTIME_NAMESPACES = [
    "vss-oracle-model-edge-nemotron-3-nano-4b-fp8",
    "vss-oracle-model-edge-cosmos3-nano-served-id",
]
OFFICIAL_EDGE_MODEL_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 6,
    "overhead_requests": 0,
    "calculated_max_requests": 6,
    "phases": [
        "exact_model_readiness",
        "runtime_and_endpoint_identity",
        "asset_pre_state",
        "llm_and_vlm_semantic_inference",
        "asset_and_container_postcondition",
    ],
}
OFFICIAL_EDGE_MODEL_RUNTIME_MAX_ACTIONS = 2
RT_EMBED_CURRENT_RUNTIME_CAPABILITY_IDS = {
    "model.rt-embed.cosmos-embed1-448p-anomaly",
    "behavior.rt-embed.base64-data-url",
    "behavior.rt-embed.duplicate-id-409",
    "api.core.rt-embed-24",
}
RT_EMBED_CURRENT_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/rt-embed-current-runtime/execute.py"
)
RT_EMBED_CURRENT_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/rt-embed-current-runtime/contract.json"
    ),
    "sha256": "ff00f1cb91045a9f758c3dc23223fc6bc562b9a1819735e8c97d790c96ca2494",
}
RT_EMBED_CURRENT_RUNTIME_EVIDENCE = {
    "model.rt-embed.cosmos-embed1-448p-anomaly": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-embed-current-runtime/"
                "official-runtime-evidence-model.json"
            ),
            "sha256": "38e367d7d35e18d7e80cf9b0a20ec324e68750e2767a4ce3f0abf289e35dbe99",
        }
    ],
    "behavior.rt-embed.base64-data-url": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-embed-current-runtime/"
                "official-runtime-evidence-data-url.json"
            ),
            "sha256": "f9cd87923a4d66c2f89641bd52a70f3cbfb1b950f6c0725960415d0d0d6beeb6",
        }
    ],
    "behavior.rt-embed.duplicate-id-409": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-embed-current-runtime/"
                "official-runtime-evidence-duplicate-id.json"
            ),
            "sha256": "4fd5ce16811e73041b935398b49729d0499dcdd20c8adb49ea3f03878b855b89",
        }
    ],
    "api.core.rt-embed-24": [
        {
            "path": (
                "deploy/docker/thor-local/qualification/rt-embed-current-runtime/"
                "official-runtime-evidence-api.json"
            ),
            "sha256": "033cdb49311c8b5c443aaa5f921d682c5c03a3abd0147d6e278e2c6043497586",
        }
    ],
}
RT_EMBED_CURRENT_RUNTIME_NAMESPACES = [
    "vss-oracle-model-rt-embed-cosmos-embed1-448p-anomaly",
    "vss-oracle-behavior-rt-embed-base64-data-url",
    "vss-oracle-behavior-rt-embed-duplicate-id-409",
    "vss-oracle-api-core-rt-embed-24",
    "00000000-0000-4000-8000-000000000061",
    "00000000-0000-4000-8000-000000000062",
    "00000000-0000-4000-8000-000000000063",
    "00000000-0000-4000-8000-000000000064",
    "00000000-0000-4000-8000-000000000065",
    "00000000-0000-4000-8000-000000000066",
    "vss-oracle-rt-embed-camera",
    "vss-oracle-rt-embed-runtime",
    "vss-oracle-rt-embed-mediamtx",
    "vss-oracle-rt-embed-artifact-model",
    "vss-oracle-rt-embed-artifact-triton",
]
RT_EMBED_CURRENT_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 43,
    "overhead_requests": 0,
    "calculated_max_requests": 43,
    "phases": [
        "exact_artifact_verification",
        "api_and_runtime_identity",
        "complete_pre_state",
        "local_rtsp_helper_and_publisher",
        "upload_file_and_readback",
        "text_file_and_data_url_semantics",
        "file_url_negative",
        "duplicate_camera_and_stream_boundaries",
        "live_rtsp_sse_and_control",
        "batch_stream_cleanup",
        "complete_postcondition",
    ],
}
RT_EMBED_CURRENT_RUNTIME_MAX_ACTIONS = 4
SEARCH_BACKEND_RUNTIME_CAPABILITY_ID = "runtime.agent.search-profile"
SEARCH_BACKEND_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "search-semantic-current-runtime-successor/executor.py"
)
SEARCH_BACKEND_RUNTIME_VERIFIER = (
    "deploy/docker/thor-local/qualification/"
    "search-semantic-current-runtime-successor/verify.py"
)
SEARCH_BACKEND_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "search-semantic-current-runtime-successor/contract.json"
    ),
    "sha256": "7276e965e723e8beab3dc443ad70caa5927c5c11c6036817610c117a7dd0b658",
}
SEARCH_BACKEND_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "search-semantic-current-runtime-successor/"
            "canonical-runtime-evidence.json"
        ),
        "sha256": "1b70532a34bc3d44d6f2a2ec6d773b8c07f55a6ffc6dc6c15b0d34973d5ecd32",
    }
]
SEARCH_BACKEND_RUNTIME_NAMESPACES = [
    "mdx-behavior-2025-01-01",
    "mdx-raw-2025-01-01",
]
SEARCH_BACKEND_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 48,
    "overhead_requests": 0,
    "calculated_max_requests": 48,
    "phases": [
        "current_runtime_and_source_locks",
        "complete_pre_state",
        "owned_fixture_materialization",
        "text_attribute_and_fusion_routes",
        "selected_object_image_knn",
        "negative_source_boundary",
        "exact_owned_cleanup",
        "complete_postcondition",
    ],
}
SEARCH_BACKEND_RUNTIME_MAX_ACTIONS = 14
SEARCH_CONTENT_TYPE_RUNTIME_CAPABILITY_ID = "behavior.search-upload.content-type"
SEARCH_CONTENT_TYPE_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "search-content-type-current-runtime-successor/executor.py"
)
SEARCH_CONTENT_TYPE_RUNTIME_VERIFIER = (
    "deploy/docker/thor-local/qualification/"
    "search-content-type-current-runtime-successor/verify.py"
)
SEARCH_CONTENT_TYPE_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "search-content-type-current-runtime-successor/contract.json"
    ),
    "sha256": "5dc1b70063cb6c9df1c4c15b6694f83bbd41ae80dc32138239bb5d68ba354a53",
}
SEARCH_CONTENT_TYPE_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "search-content-type-current-runtime-successor/"
            "canonical-runtime-evidence.json"
        ),
        "sha256": "59c55696d84cae84b5cea839bc319ed1f91dd3107af76dc62a78bbd78a5381c3",
    }
]
SEARCH_CONTENT_TYPE_RUNTIME_NAMESPACES = ["vss-oracle-search-content-type-"]
SEARCH_CONTENT_TYPE_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 48,
    "overhead_requests": 0,
    "calculated_max_requests": 48,
    "phases": [
        "current_runtime_and_source_locks",
        "complete_pre_state",
        "missing_and_unsupported_boundaries",
        "generated_mp4_ingest_and_embedding",
        "generated_matroska_ingest_and_embedding",
        "exact_owned_cleanup",
        "complete_postcondition",
    ],
}
SEARCH_CONTENT_TYPE_RUNTIME_MAX_ACTIONS = 6
SEARCH_UI_RUNTIME_CAPABILITY_ID = "runtime.ui.search-tab"
SEARCH_UI_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "ui-search-contract-current-runtime-successor/executor.py"
)
SEARCH_UI_RUNTIME_VERIFIER = (
    "deploy/docker/thor-local/qualification/"
    "ui-search-contract-current-runtime-successor/verify.py"
)
SEARCH_UI_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "ui-search-contract-current-runtime-successor/contract.json"
    ),
    "sha256": "71dec2ac7077970df573a6d09181db546ff21d58ac7783fb42601eb75e111230",
}
SEARCH_UI_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "ui-search-contract-current-runtime-successor/"
            "canonical-runtime-evidence.json"
        ),
        "sha256": "becddbdeab6c3d12597adf3acbec2ec161f995bbe2c2704af8d9414bb9670161",
    }
]
SEARCH_UI_RUNTIME_WORKLOAD = {
    "units": 3,
    "requests_per_unit": 83,
    "overhead_requests": 1,
    "calculated_max_requests": 250,
    "phases": [
        "dependency_evidence_verification",
        "current_runtime_and_source_locks",
        "desktop_filter_request_and_critic_ordering",
        "mobile_overflow_and_browser_diagnostics",
        "read_only_postcondition",
    ],
}
SEARCH_UI_RUNTIME_MAX_ACTIONS = 18
UI_DASHBOARD_RUNTIME_CAPABILITY_ID = "runtime.ui.dashboard-tab"
UI_DASHBOARD_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "ui-dashboard-playwright-runtime-successor/harness.mjs"
)
UI_DASHBOARD_RUNTIME_VERIFIER = (
    "deploy/docker/thor-local/qualification/"
    "ui-dashboard-playwright-runtime-successor/verify.py"
)
UI_DASHBOARD_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "ui-dashboard-playwright-runtime-successor/contract.json"
    ),
    "sha256": "21a6f9a7d70489d4bde567cfe6aa6fca2d4f18381a8052757e5b474b4384add2",
}
UI_DASHBOARD_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "ui-dashboard-playwright-runtime-successor/official-runtime-evidence.json"
        ),
        "sha256": "436f55119607c83a1fbbf29cbd29d2fe18c40cfe1134d8f82bdb0370cd334e08",
    }
]
UI_DASHBOARD_RUNTIME_WORKLOAD = {
    "units": 5,
    "requests_per_unit": 100,
    "overhead_requests": 4,
    "calculated_max_requests": 504,
    "phases": [
        "saved_object_identity_and_adjacent_negative",
        "desktop_render_and_interaction",
        "mobile_render_and_overflow",
        "browser_diagnostics_and_read_only_postcondition",
    ],
}
UI_DASHBOARD_RUNTIME_MAX_ACTIONS = 12
UI_GLOBAL_CHAT_RUNTIME_CAPABILITY_ID = "runtime.ui.global-chat-sidebar"
UI_GLOBAL_CHAT_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "ui-global-chat-sidebar-runtime-successor/harness.mjs"
)
UI_GLOBAL_CHAT_RUNTIME_VERIFIER = (
    "deploy/docker/thor-local/qualification/"
    "ui-global-chat-sidebar-runtime-successor/verify.py"
)
UI_GLOBAL_CHAT_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "ui-global-chat-sidebar-runtime-successor/contract.json"
    ),
    "sha256": "a049b6596436e09dd7e9c9be0da76534c3b17b9d545d4af5c4c7ae062d37e632",
}
UI_GLOBAL_CHAT_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "ui-global-chat-sidebar-runtime-successor/official-runtime-evidence.json"
        ),
        "sha256": "cdda66a198192335c1bbc9e59cdb907a8084e3ff9590c62388c1926e23e3357f",
    }
]
UI_GLOBAL_CHAT_RUNTIME_WORKLOAD = {
    "units": 12,
    "requests_per_unit": 100,
    "overhead_requests": 0,
    "calculated_max_requests": 1200,
    "phases": [
        "current_profile_state_model",
        "profile_controlled_legacy_and_global_chat_boundary",
        "generate_report_positive_and_adjacent_negative",
        "browser_diagnostics_and_runtime_postcondition",
    ],
}
UI_GLOBAL_CHAT_RUNTIME_MAX_ACTIONS = 40
LVS_MCP_RUNTIME_CAPABILITY_ID = "api.core.lvs-mcp-doc-13-repo-9"
LVS_MCP_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/"
    "lvs-mcp-current-runtime-successor/executor.py"
)
LVS_MCP_RUNTIME_VERIFIER = (
    "deploy/docker/thor-local/qualification/lvs-mcp-current-runtime-successor/verify.py"
)
LVS_MCP_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "lvs-mcp-current-runtime-successor/contract.json"
    ),
    "sha256": "e3056541c684aa2cc0144637d68a8698db19a0530feab44923b46f92a04e583d",
}
LVS_MCP_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "lvs-mcp-current-runtime-successor/canonical-runtime-evidence.json"
        ),
        "sha256": "0e206430f68a32cbbf4bb1cb0bfc353632a89057ac158362163e7468eb92a63e",
    }
]
LVS_MCP_RUNTIME_NAMESPACES = ["vss-oracle-lvs-mcp-"]
LVS_MCP_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 20,
    "overhead_requests": 0,
    "calculated_max_requests": 20,
    "phases": [
        "source_and_runtime_identity",
        "complete_catalog_and_media_pre_state",
        "exact_13_tool_discovery",
        "non_inference_read_only_calls",
        "adapter_file_lifecycle_and_adjacent_negatives",
        "exact_cleanup_and_postcondition",
    ],
}
LVS_MCP_RUNTIME_MAX_ACTIONS = 4
LVS_FORMATS_RUNTIME_CAPABILITY_ID = "runtime.lvs.supported-formats"
LVS_FORMATS_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/lvs-formats-runtime/execute.py"
)
LVS_FORMATS_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/lvs-formats-runtime/contract.json"
    ),
    "sha256": "28030f32ef10d0fe240b11671511a75b5b308041732206a258f9e1f333bf20d7",
}
LVS_FORMATS_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/lvs-formats-runtime/"
            "official-runtime-evidence.json"
        ),
        "sha256": "bedea1ec8ad2f7f10796a8aa6d8fe06bae0fd58912064c081abdcabc4b774574",
    }
]
LVS_FORMATS_RUNTIME_NAMESPACES = [
    "vss-oracle-runtime-lvs-supported-formats",
    "00000000-0000-4000-8000-000000000021",
    "00000000-0000-4000-8000-000000000022",
    "00000000-0000-4000-8000-000000000023",
    "00000000-0000-4000-8000-000000000024",
    "00000000-0000-4000-8000-000000000025",
    "00000000-0000-4000-8000-000000000026",
]
LVS_FORMATS_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 37,
    "overhead_requests": 0,
    "calculated_max_requests": 37,
    "phases": [
        "static_and_runtime_identity",
        "pre_state",
        "five_format_derivation_and_media_probe",
        "five_format_upload_readback_summarize_delete",
        "invalid_media_adjacent_negative",
        "exact_cleanup",
        "postcondition",
    ],
}
LVS_FORMATS_RUNTIME_MAX_ACTIONS = 9
LVS_SINGLE_REQUEST_RUNTIME_CAPABILITY_ID = "runtime.lvs.single-request-queue"
LVS_SINGLE_REQUEST_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/lvs-single-request-queue-runtime/execute.py"
)
LVS_SINGLE_REQUEST_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "lvs-single-request-queue-runtime/contract.json"
    ),
    "sha256": "2065ca45457490b299bbde56dfa0fd64529cc857f7b5e4a34c34468cc29ab49c",
}
LVS_SINGLE_REQUEST_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "lvs-single-request-queue-runtime/official-runtime-evidence.json"
        ),
        "sha256": "7467cc46d9ebe25f6dec89dcacb60da602abce314c28b7c35bb11e13e708e9bf",
    }
]
LVS_SINGLE_REQUEST_RUNTIME_NAMESPACES = [
    "vss-oracle-runtime-lvs-single-request-queue",
    "00000000-0000-4000-8000-000000000031",
    "00000000-0000-4000-8000-000000000032",
]
LVS_SINGLE_REQUEST_RUNTIME_WORKLOAD = {
    "units": 2,
    "requests_per_unit": 75,
    "overhead_requests": 0,
    "calculated_max_requests": 150,
    "phases": [
        "static_and_runtime_identity",
        "pre_state",
        "two_owned_file_uploads_and_readbacks",
        "simultaneous_summary_submission",
        "outstanding_work_metric_sampling",
        "one_worker_one_inflight_topology_proof",
        "exact_cleanup",
        "postcondition",
    ],
}
LVS_SINGLE_REQUEST_RUNTIME_MAX_ACTIONS = 2
LVS_CUSTOM_MODEL_PROMPT_RUNTIME_CAPABILITY_ID = "configuration.lvs.custom-model-prompt"
LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EXECUTOR = (
    "deploy/docker/thor-local/qualification/lvs-custom-model-prompt-runtime/execute.py"
)
LVS_CUSTOM_MODEL_PROMPT_RUNTIME_FIXTURE = {
    "path": (
        "deploy/docker/thor-local/qualification/"
        "lvs-custom-model-prompt-runtime/contract.json"
    ),
    "sha256": "16a1c5ff167774c07e1a9dca057bf15650ff5ae0367db42d7576bfc55322de9b",
}
LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EVIDENCE = [
    {
        "path": (
            "deploy/docker/thor-local/qualification/"
            "lvs-custom-model-prompt-runtime/official-runtime-evidence.json"
        ),
        "sha256": "79269793902ca6a4cb603d4caf99476707233c2dab05435bf0ca9d1eaae191ad",
    }
]
LVS_CUSTOM_MODEL_PROMPT_RUNTIME_NAMESPACES = [
    "vss-oracle-configuration-lvs-custom-model-prompt",
    "00000000-0000-4000-8000-000000000041",
]
LVS_CUSTOM_MODEL_PROMPT_RUNTIME_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 19,
    "overhead_requests": 0,
    "calculated_max_requests": 19,
    "phases": [
        "static_source_and_compose_contract",
        "runtime_identity_and_pre_state",
        "owned_file_upload_and_readback",
        "invalid_model_adjacent_negative",
        "compatible_custom_prompt_summary",
        "exact_cleanup",
        "postcondition",
    ],
}
LVS_CUSTOM_MODEL_PROMPT_RUNTIME_MAX_ACTIONS = 2


def _is_current_vios_byte_download(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == VIOS_BYTE_DOWNLOAD_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == VIOS_BYTE_DOWNLOAD_RUNTIME_EVIDENCE
    )


def _is_current_nvstreamer_file_workflow(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == NVSTREAMER_FILE_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == NVSTREAMER_FILE_RUNTIME_EVIDENCE
    )


def _is_current_nvstreamer_sync(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == NVSTREAMER_SYNC_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == NVSTREAMER_SYNC_RUNTIME_EVIDENCE
    )


def _is_current_nvstreamer_full_config(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == NVSTREAMER_FULL_CONFIG_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence")
        == NVSTREAMER_FULL_CONFIG_RUNTIME_EVIDENCE
    )


def _is_current_vios_webrtc_replay(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == VIOS_WEBRTC_REPLAY_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == VIOS_WEBRTC_REPLAY_RUNTIME_EVIDENCE
    )


def _is_current_vios_webrtc_live(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == VIOS_WEBRTC_LIVE_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == VIOS_WEBRTC_LIVE_RUNTIME_EVIDENCE
    )


def _is_current_video_analytics_runtime(capability: dict[str, Any]) -> bool:
    capability_id = capability.get("id")
    return (
        capability_id in VIDEO_ANALYTICS_RUNTIME_CAPABILITY_IDS
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence")
        == VIDEO_ANALYTICS_RUNTIME_EVIDENCE[capability_id]
    )


def _is_current_event_transport_runtime(capability: dict[str, Any]) -> bool:
    capability_id = capability.get("id")
    return (
        capability_id in EVENT_TRANSPORT_RUNTIME_CAPABILITY_IDS
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence")
        == EVENT_TRANSPORT_RUNTIME_EVIDENCE[capability_id]
    )


def _is_current_alert_websocket_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == ALERT_WEBSOCKET_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == ALERT_WEBSOCKET_RUNTIME_EVIDENCE
    )


def _is_current_agent_websocket_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == AGENT_WEBSOCKET_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == AGENT_WEBSOCKET_RUNTIME_EVIDENCE
    )


def _is_current_rt_vlm_sse_runtime(capability: dict[str, Any]) -> bool:
    capability_id = capability.get("id")
    return (
        capability_id in RT_VLM_SSE_RUNTIME_CAPABILITY_IDS
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence")
        == RT_VLM_SSE_RUNTIME_EVIDENCE[capability_id]
    )


def _is_current_official_edge_model_runtime(capability: dict[str, Any]) -> bool:
    capability_id = capability.get("id")
    return (
        capability_id in OFFICIAL_EDGE_MODEL_RUNTIME_CAPABILITY_IDS
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence")
        == OFFICIAL_EDGE_MODEL_RUNTIME_EVIDENCE[capability_id]
    )


def _is_current_rt_embed_runtime(capability: dict[str, Any]) -> bool:
    capability_id = capability.get("id")
    return (
        capability_id in RT_EMBED_CURRENT_RUNTIME_CAPABILITY_IDS
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence")
        == RT_EMBED_CURRENT_RUNTIME_EVIDENCE[capability_id]
    )


def _is_current_search_backend_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == SEARCH_BACKEND_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == SEARCH_BACKEND_RUNTIME_EVIDENCE
    )


def _is_current_search_content_type_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == SEARCH_CONTENT_TYPE_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == SEARCH_CONTENT_TYPE_RUNTIME_EVIDENCE
    )


def _is_current_search_ui_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == SEARCH_UI_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == SEARCH_UI_RUNTIME_EVIDENCE
    )


def _is_current_ui_dashboard_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == UI_DASHBOARD_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == UI_DASHBOARD_RUNTIME_EVIDENCE
    )


def _is_current_ui_global_chat_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == UI_GLOBAL_CHAT_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == UI_GLOBAL_CHAT_RUNTIME_EVIDENCE
    )


def _is_current_lvs_formats_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == LVS_FORMATS_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == LVS_FORMATS_RUNTIME_EVIDENCE
    )


def _is_current_lvs_mcp_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == LVS_MCP_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == LVS_MCP_RUNTIME_EVIDENCE
    )


def _is_current_lvs_single_request_runtime(capability: dict[str, Any]) -> bool:
    return (
        capability.get("id") == LVS_SINGLE_REQUEST_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence") == LVS_SINGLE_REQUEST_RUNTIME_EVIDENCE
    )


def _is_current_lvs_custom_model_prompt_runtime(
    capability: dict[str, Any],
) -> bool:
    return (
        capability.get("id") == LVS_CUSTOM_MODEL_PROMPT_RUNTIME_CAPABILITY_ID
        and capability.get("runtime_state") == "passed_current"
        and capability.get("runtime_evidence")
        == LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EVIDENCE
    )


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
    "security.nemoclaw.policy-provider-network-boundary": (
        "nemoclaw-policy-network",
        9,
        9,
    ),
    "runtime.smart-city.chat-alert-dashboard": ("smartcity-ui-incidents", 8, 8),
    "runtime.smart-city.traffic-analytics": ("smartcity-synthetic-tracks", 14, 14),
    "runtime.smart-city.agent-workflow": ("smartcity-agent-pages", 12, 12),
    "calibration.legacy.core": ("smartcity-manual-calibration", 8, 8),
    "calibration.legacy.gis": ("smartcity-gis-calibration", 8, 8),
    "performance.alerts.worker-scaling": ("systems-alert-worker-scaling", 8, 8),
    "deployment.vios.horizontal-scaling": ("systems-vios-scaling", 7, 9),
    "behavior.elk.disk-watermark-recovery": ("systems-elk-recovery", 13, 13),
    "behavior.vios.upload-playback-remediation": (
        "systems-vios-playback-remediation",
        8,
        9,
    ),
}
LOCAL_RUNTIME_WORKLOAD_PHASES = [
    "pre_state",
    "positive",
    "adjacent_negative",
    "restore",
    "postcondition",
]


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
    if (
        path.is_absolute()
        or ".." in path.parts
        or not value.startswith("deploy/docker/thor-local/")
    ):
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
    if capability_id == "manifest-entry.spatial-ai-utils.07-aws-gcs-validation":
        return "external-spatial-object-store-boundary", "deploy"
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
        return (
            f"calibration-{capability_id.removeprefix('calibration.').replace('.', '-')}",
            "runtime",
        )
    if kind == "deployment":
        if capability_id.startswith("prereq.platform."):
            return f"host-prerequisite-{capability_id.rsplit('.', 1)[-1]}", "static"
        if capability_id.startswith("boundary.thor."):
            if capability_id == "boundary.thor.custom-all-local-extension":
                return "thor-custom-local-runtime-profiles", "runtime"
            return f"thor-support-boundary-{capability_id.rsplit('.', 1)[-1]}", "static"
        boundary = (
            "external"
            if capability["acceptance_class"] == "external_optional"
            else "local"
        )
        return f"{boundary}-deployment-{capability_id.split('.')[1]}", "deploy"
    if kind == "security":
        boundary = (
            "external"
            if capability["acceptance_class"] == "external_optional"
            else "local"
        )
        if boundary == "external":
            return "external-security-boundary", "deploy"
        if capability_id in {
            "behavior.rt-embed.ngc-scheme-key",
            "prereq.platform.credentials",
        }:
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
        return (
            f"protocol-{capability_id.removeprefix('protocol.').replace('.', '-')}",
            "protocol",
        )
    if kind == "runtime_behavior":
        return (
            f"behavior-{capability_id.removeprefix('behavior.').replace('.', '-')}",
            "runtime",
        )
    raise OracleContractError(f"{capability_id}: no oracle profile for kind {kind!r}")


def _action(capability: dict[str, Any], profile: str) -> str:
    capability_id = capability["id"]
    exact = {
        "manifest-entry.spatial-ai-utils.07-aws-gcs-validation": (
            "with explicit operator authorization, upload one namespaced tiny object "
            "to the selected AWS S3 or Google Cloud Storage provider, read and "
            "validate it through the exact SpatialAI utilities, then delete only "
            "that object and record provider, TLS, content, and cleanup evidence"
        ),
        CPU_MULTIMEDIA_CAPABILITY_ID: (
            "run bounded hardware-default and use_software_path=true H.264/H.265/AAC "
            "workflows, prove m_useNvV4l2Dec and m_useNvV4l2Enc select distinct "
            "nvv4l2 and CPU elements, then restore the checked-in false default"
        ),
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
    kind = (
        "operator_external_contract"
        if external
        else "generated_custom_media"
        if media
        else "generated_minimal_contract"
    )
    return {
        "id": f"fixture.{capability_id}",
        "kind": kind,
        "availability": "operator_required" if external else "not_staged",
        "source": "operator-provided opt-in boundary"
        if external
        else "bounded locally generated fixture",
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
    if capability_id == CPU_MULTIMEDIA_CAPABILITY_ID:
        observations.append(
            {
                "id": "hardware_cpu_discrimination",
                "description": (
                    "The false-default path records nvv4l2 decoder/encoder selection, "
                    "while the opted-in path records the declared libav/x264/x265 "
                    "elements for the same bounded H.264/H.265 media matrix."
                ),
            }
        )
    elif capability_id == "boundary.thor.custom-all-local-extension":
        observations.extend(
            {
                "id": f"profile_{profile_id.replace('-', '_')}",
                "description": f"The {profile_id} profile completes a bounded custom-data runtime qualification with local endpoint provenance and exact cleanup.",
            }
            for profile_id in contract["profiles"]
        )
        observations.append(
            {
                "id": "sample_exclusion",
                "description": "No fixture, mount, command, or evidence references the excluded NVIDIA warehouse sample bundle.",
            }
        )
    elif capability_id == "api.orchestrator-mcp.tools-9":
        observations.extend(
            [
                {
                    "id": "discovery_phase",
                    "description": "The static phase discovers exactly nine tools and validates every input schema without invoking lifecycle tools.",
                },
                {
                    "id": "approved_lifecycle_phase",
                    "description": "After explicit approval, generate/read/up/status/list/logs/down execute only against the owned Compose project and all cleanup postconditions pass.",
                },
            ]
        )
    elif capability["kind"] == "model":
        observations.append(
            {
                "id": "model_response",
                "description": "The exact model ID is reported by the backend and a bounded request completes without fallback.",
            }
        )
    elif capability["kind"] == "configuration":
        observations.append(
            {
                "id": "round_trip",
                "description": "Rendered state validates, reads back without semantic drift, and restores the pre-test state.",
            }
        )
    elif capability["kind"] == "evaluation":
        observations.append(
            {
                "id": "score_record",
                "description": "Per-row scores, aggregate scores, evaluator identity, and dataset digest are emitted.",
            }
        )
    elif capability["kind"] == "model_customization":
        observations.append(
            {
                "id": "custom_artifact_selected",
                "description": "Runtime provenance identifies the locked custom artifact and the capability-specific output oracle passes.",
            }
        )
    elif capability["kind"] == "calibration":
        observations.append(
            {
                "id": "calibration_export",
                "description": "Export is finite, schema-valid, bound to the custom inputs, and passes reprojection/geometry validation.",
            }
        )
    elif capability["kind"] in {"deployment", "security"}:
        if capability["acceptance_class"] == "external_optional":
            observations.append(
                {
                    "id": "boundary_admission",
                    "description": "Only operator-opted external infrastructure is referenced; no local-complete claim is made.",
                }
            )
        else:
            observations.append(
                {
                    "id": "local_admission",
                    "description": "The exact local contract reaches ready, satisfies its positive and negative probes, and returns to captured pre-test state.",
                }
            )
    elif capability["kind"] == "performance":
        observations.append(
            {
                "id": "thor_measurement",
                "description": "Raw samples, warmup, concurrency, duration, p50, p95, throughput, errors, and Thor hardware metadata are recorded.",
            }
        )
    elif capability["kind"] == "tooling":
        observations.append(
            {
                "id": "deterministic_output",
                "description": "Two clean runs produce schema-valid, byte-identical output in the exact declared output path.",
            }
        )
    elif capability["kind"] == "api":
        observations.append(
            {
                "id": "api_contract",
                "description": "Exact operation discovery, success response, negative response, persistence/readback, and owned cleanup are observed.",
            }
        )
    elif capability["kind"] == "protocol":
        observations.append(
            {
                "id": "wire_contract",
                "description": "Handshake, framing/schema, ordering, terminal/ack behavior, and disconnect cleanup match the declared protocol.",
            }
        )
    elif capability["kind"] == "runtime_behavior":
        observations.append(
            {
                "id": "boundary_pair",
                "description": "A passing boundary case and a failing/limited adjacent case distinguish the advertised behavior.",
            }
        )
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
        for index, observation in enumerate(
            _observations(capability, _profile(capability)[0]), 1
        )
        if observation["id"] != "contract_identity"
    )
    return assertions


def _admission(capability: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    capability_id = capability["id"]
    gates = [
        {
            "id": "operator-approval",
            "condition": "explicit approval exists for any service lifecycle or external access",
            "bounded": True,
        },
        {
            "id": "target-bound",
            "condition": f"execution is pinned to capability {capability_id} and target commit",
            "bounded": True,
        },
        {
            "id": "fixture-bound",
            "condition": "fixture digest, namespace, duration, and request count are recorded before execution",
            "bounded": True,
        },
    ]
    if mode in {"model", "runtime", "api", "protocol"}:
        gates.append(
            {
                "id": "runtime-capacity",
                "condition": "Thor cgroup, memory, disk, GPU, port, and exact artifact/image gates pass",
                "bounded": True,
            }
        )
    if capability["kind"] == "model":
        gates.append(
            {
                "id": "model-artifact-staged",
                "condition": "the exact immutable model artifact and backend lock are staged and verified before the timed runtime oracle begins",
                "bounded": True,
            }
        )
    if capability["id"] == "api.orchestrator-mcp.tools-9":
        gates.append(
            {
                "id": "orchestrator-lifecycle-approval",
                "condition": "explicit approval names the disposable Compose project before any lifecycle tool beyond discovery is invoked",
                "bounded": True,
            }
        )
    if capability["acceptance_class"] == "external_optional":
        gates.append(
            {
                "id": "external-opt-in",
                "condition": "operator supplies the external environment and credentials; absence remains not_applicable",
                "bounded": True,
            }
        )
    return gates


def _cleanup(capability: dict[str, Any], mode: str) -> dict[str, Any]:
    capability_id = capability["id"]
    external_boundary = capability["acceptance_class"] == "external_optional"
    if external_boundary:
        return {
            "mutation": "none_by_default",
            "targets": [],
            "allowlist": [],
            "pre_state": "not_materialized",
            "restore": "revoke only test-scoped credentials/resources if the operator opts in",
            "executor": None,
            "postcondition_collectors": [],
            "postconditions": [
                "operator records removal or revocation of every test-scoped external resource"
            ],
        }
    if (
        capability["id"].startswith("prereq.platform.")
        or capability["id"] == "boundary.thor.fully-local-future"
    ):
        return {
            "mutation": "read_only",
            "targets": [],
            "allowlist": [],
            "pre_state": "read_only_snapshot_required",
            "restore": "no cleanup; the oracle records host or documentation state without applying remediation",
            "executor": None,
            "postcondition_collectors": [],
            "postconditions": [
                "a second read confirms the observed host or documentation state was not changed"
            ],
        }
    if mode == "static":
        target = f"vss-oracle-{capability_id.replace('.', '-')}"
        return {
            "mutation": "temporary_files_only",
            "targets": [target],
            "allowlist": [target],
            "pre_state": "exact target absence or digest must be captured",
            "restore": "delete the exact temporary directory after digest capture",
            "executor": None,
            "postcondition_collectors": [],
            "postconditions": [
                "the exact temporary target is absent and no sibling path changed"
            ],
        }
    target = f"vss-oracle-{capability_id.replace('.', '-')}"
    return {
        "mutation": "namespaced_and_reversible",
        "targets": [target],
        "allowlist": [target],
        "pre_state": "service, configuration, resource IDs, and target absence/digests must be captured before mutation",
        "restore": "remove only recorded oracle-owned resources and restore the captured pre-test service/config state",
        "executor": None,
        "postcondition_collectors": [],
        "postconditions": [
            "every allowlisted oracle-owned resource is absent",
            "captured service/config state and non-owned resource digests match pre-state",
        ],
    }


def _workload(
    capability: dict[str, Any], live_integration: bool = True
) -> dict[str, Any]:
    capability_id = capability["id"]
    contract = capability["contract"]
    if live_integration and _is_current_vios_byte_download(capability):
        return copy.deepcopy(VIOS_BYTE_DOWNLOAD_WORKLOAD)
    if live_integration and _is_current_nvstreamer_file_workflow(capability):
        return copy.deepcopy(NVSTREAMER_FILE_WORKLOAD)
    if live_integration and _is_current_nvstreamer_sync(capability):
        return copy.deepcopy(NVSTREAMER_SYNC_WORKLOAD)
    if live_integration and _is_current_nvstreamer_full_config(capability):
        return copy.deepcopy(NVSTREAMER_FULL_CONFIG_WORKLOAD)
    if live_integration and _is_current_vios_webrtc_replay(capability):
        return copy.deepcopy(VIOS_WEBRTC_REPLAY_WORKLOAD)
    if live_integration and _is_current_vios_webrtc_live(capability):
        return copy.deepcopy(VIOS_WEBRTC_LIVE_WORKLOAD)
    if live_integration and _is_current_video_analytics_runtime(capability):
        return copy.deepcopy(VIDEO_ANALYTICS_RUNTIME_WORKLOAD)
    if live_integration and _is_current_event_transport_runtime(capability):
        return copy.deepcopy(EVENT_TRANSPORT_RUNTIME_WORKLOAD)
    if live_integration and _is_current_agent_websocket_runtime(capability):
        return copy.deepcopy(AGENT_WEBSOCKET_RUNTIME_WORKLOAD)
    if live_integration and _is_current_alert_websocket_runtime(capability):
        return copy.deepcopy(ALERT_WEBSOCKET_RUNTIME_WORKLOAD)
    if live_integration and _is_current_rt_vlm_sse_runtime(capability):
        return copy.deepcopy(RT_VLM_SSE_RUNTIME_WORKLOAD)
    if live_integration and _is_current_official_edge_model_runtime(capability):
        return copy.deepcopy(OFFICIAL_EDGE_MODEL_RUNTIME_WORKLOAD)
    if live_integration and _is_current_rt_embed_runtime(capability):
        return copy.deepcopy(RT_EMBED_CURRENT_RUNTIME_WORKLOAD)
    if live_integration and _is_current_search_backend_runtime(capability):
        return copy.deepcopy(SEARCH_BACKEND_RUNTIME_WORKLOAD)
    if live_integration and _is_current_search_content_type_runtime(capability):
        return copy.deepcopy(SEARCH_CONTENT_TYPE_RUNTIME_WORKLOAD)
    if live_integration and _is_current_search_ui_runtime(capability):
        return copy.deepcopy(SEARCH_UI_RUNTIME_WORKLOAD)
    if live_integration and _is_current_ui_dashboard_runtime(capability):
        return copy.deepcopy(UI_DASHBOARD_RUNTIME_WORKLOAD)
    if live_integration and _is_current_ui_global_chat_runtime(capability):
        return copy.deepcopy(UI_GLOBAL_CHAT_RUNTIME_WORKLOAD)
    if live_integration and _is_current_lvs_mcp_runtime(capability):
        return copy.deepcopy(LVS_MCP_RUNTIME_WORKLOAD)
    if live_integration and _is_current_lvs_formats_runtime(capability):
        return copy.deepcopy(LVS_FORMATS_RUNTIME_WORKLOAD)
    if live_integration and _is_current_lvs_single_request_runtime(capability):
        return copy.deepcopy(LVS_SINGLE_REQUEST_RUNTIME_WORKLOAD)
    if live_integration and _is_current_lvs_custom_model_prompt_runtime(capability):
        return copy.deepcopy(LVS_CUSTOM_MODEL_PROMPT_RUNTIME_WORKLOAD)
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
        units = (
            contract.get("operation_count")
            or contract.get("repository_tool_count")
            or contract.get("tool_count")
            or contract.get("operation_count", 1)
        )
        phases = ["positive", "adjacent_negative", "readback", "cleanup"]
        per_unit = len(phases)
        overhead = 1
    elif capability_id in {
        "behavior.rt-vlm.kafka-queue-bound",
        "behavior.rt-embed.kafka-queue-bound",
    }:
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
    if _is_current_nvstreamer_sync(capability):
        return NVSTREAMER_SYNC_MAX_ACTIONS
    if _is_current_nvstreamer_full_config(capability):
        return NVSTREAMER_FULL_CONFIG_MAX_ACTIONS
    if _is_current_vios_webrtc_replay(capability):
        return VIOS_WEBRTC_REPLAY_MAX_ACTIONS
    if _is_current_vios_webrtc_live(capability):
        return VIOS_WEBRTC_LIVE_MAX_ACTIONS
    if _is_current_video_analytics_runtime(capability):
        return VIDEO_ANALYTICS_RUNTIME_MAX_ACTIONS
    if _is_current_event_transport_runtime(capability):
        return EVENT_TRANSPORT_RUNTIME_MAX_ACTIONS
    if _is_current_agent_websocket_runtime(capability):
        return AGENT_WEBSOCKET_RUNTIME_MAX_ACTIONS
    if _is_current_alert_websocket_runtime(capability):
        return ALERT_WEBSOCKET_RUNTIME_MAX_ACTIONS
    if _is_current_rt_vlm_sse_runtime(capability):
        return RT_VLM_SSE_RUNTIME_MAX_ACTIONS
    if _is_current_official_edge_model_runtime(capability):
        return OFFICIAL_EDGE_MODEL_RUNTIME_MAX_ACTIONS
    if _is_current_rt_embed_runtime(capability):
        return RT_EMBED_CURRENT_RUNTIME_MAX_ACTIONS
    if _is_current_search_backend_runtime(capability):
        return SEARCH_BACKEND_RUNTIME_MAX_ACTIONS
    if _is_current_search_content_type_runtime(capability):
        return SEARCH_CONTENT_TYPE_RUNTIME_MAX_ACTIONS
    if _is_current_search_ui_runtime(capability):
        return SEARCH_UI_RUNTIME_MAX_ACTIONS
    if _is_current_ui_dashboard_runtime(capability):
        return UI_DASHBOARD_RUNTIME_MAX_ACTIONS
    if _is_current_ui_global_chat_runtime(capability):
        return UI_GLOBAL_CHAT_RUNTIME_MAX_ACTIONS
    if _is_current_lvs_mcp_runtime(capability):
        return LVS_MCP_RUNTIME_MAX_ACTIONS
    if _is_current_lvs_formats_runtime(capability):
        return LVS_FORMATS_RUNTIME_MAX_ACTIONS
    if _is_current_lvs_single_request_runtime(capability):
        return LVS_SINGLE_REQUEST_RUNTIME_MAX_ACTIONS
    if _is_current_lvs_custom_model_prompt_runtime(capability):
        return LVS_CUSTOM_MODEL_PROMPT_RUNTIME_MAX_ACTIONS
    override = LOCAL_RUNTIME_WORKLOAD_OVERRIDES.get(capability["id"])
    return override[2] if override is not None else workload["calculated_max_requests"]


def canonical_oracle_sha256(oracle: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def is_spatial_ai_core_stage1_binding(
    capability: dict[str, Any], oracle: dict[str, Any]
) -> bool:
    """Recognize only the reviewed, evidence-empty SpatialAI Stage-1 delta."""
    capability_id = capability.get("id")
    binding = oracle.get("ledger_binding")
    if capability_id not in SPATIAL_AI_CORE_IDS or not isinstance(binding, dict):
        return False
    unchanged_fields = (
        "feature_id",
        "kind",
        "title",
        "source_claims",
        "acceptance_class",
        "thor_state",
    )
    return (
        capability.get("runtime_state") == "not_qualified"
        and all(binding.get(key) == capability.get(key) for key in unchanged_fields)
        and binding.get("runtime_state") == "passed_current"
        and binding.get("gap") == SPATIAL_AI_CORE_GAP
        and isinstance(binding.get("contract"), dict)
        and binding["contract"].get("warehouse_sample_bundle") == "excluded"
        and oracle.get("acceptance_readiness")
        == {"classification": "executor_ready", "blockers": []}
        and oracle.get("current_state") == "open_unexecuted"
        and oracle.get("evidence") == []
        and oracle.get("execution_bounds", {}).get("warehouse_sample_bundle")
        == "excluded"
    )


def _mv3dt_runtime_state(capability: dict[str, Any]) -> str:
    if capability["id"] not in MV3DT_RUNTIME_FIXTURES:
        return "not_mv3dt_runtime"
    state = (capability.get("thor_state"), capability.get("runtime_state"))
    if state == ("source_only", "not_qualified"):
        return "historical_planning"
    if (
        state == ("wired", "passed_current")
        and capability.get("gap") == MV3DT_PROMOTED_GAP
    ):
        return "promoted_runtime"
    raise OracleContractError(
        f"{capability['id']}: partial MV3DT runtime promotion state"
    )


def _validate_mv3dt_runtime_locks(repo_root: Path) -> None:
    expected = {
        "tool.mv3dt.cam-info-generator": (
            "vss-oracle-tool-mv3dt-cam-info-generator",
            7,
            7,
        ),
        "tool.mv3dt.pub-sub-generator": (
            "vss-oracle-tool-mv3dt-pub-sub-generator",
            10,
            7,
        ),
    }
    if set(MV3DT_RUNTIME_FIXTURES) != set(expected):
        raise OracleContractError("MV3DT runtime fixture denominator drift")
    if MV3DT_RUNTIME_WORKLOAD != {
        "units": 1,
        "requests_per_unit": 7,
        "overhead_requests": 0,
        "calculated_max_requests": 7,
        "phases": ["positive_run_1", "positive_run_2", "adjacent_negative"],
    }:
        raise OracleContractError("MV3DT runtime workload drift")
    locks = [MV3DT_RUNTIME_EXECUTOR, *MV3DT_RUNTIME_FIXTURES.values()]
    for lock in locks:
        path = _resolve_reviewed_file(
            repo_root, lock["path"], "mv3dt_runtime_materialization"
        )
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock["raw_sha256"]:
            raise OracleContractError(f"MV3DT runtime file lock drift: {lock['path']}")
    for capability_id, (namespace, max_actions, max_requests) in expected.items():
        lock = MV3DT_RUNTIME_FIXTURES[capability_id]
        if (
            lock["namespace"] != namespace
            or lock["max_actions"] != max_actions
            or lock["max_requests"] != max_requests
        ):
            raise OracleContractError(
                f"{capability_id}: MV3DT runtime action/request/cleanup drift"
            )
        fixture = _load(
            _resolve_reviewed_file(
                repo_root,
                lock["path"],
                f"{capability_id}.mv3dt_runtime_fixture",
            )
        )
        if (
            fixture.get("capability_id") != capability_id
            or fixture.get("fixture_id") != f"fixture.{capability_id}"
            or fixture.get("namespace") != namespace
            or fixture.get("warehouse_sample_bundle") != "excluded"
        ):
            raise OracleContractError(
                f"{capability_id}: MV3DT runtime fixture identity drift"
            )


def _load_locked_reviewed_json(
    repo_root: Path, lock: dict[str, str], label: str
) -> dict[str, Any]:
    path = _resolve_reviewed_file(repo_root, lock.get("path"), label)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != lock.get("raw_sha256"):
        raise OracleContractError(f"{label}: raw digest drift")
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OracleContractError(f"{label}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise OracleContractError(f"{label}: root must be an object")
    return value


def _validate_json_schema(
    value: dict[str, Any], schema: dict[str, Any], label: str
) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise OracleContractError(f"{label}: invalid schema: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "/".join(str(item) for item in error.absolute_path) or "<root>"
        raise OracleContractError(
            f"{label}: schema violation at {path}: {error.message}"
        )


def _spatial_ai_promoted_runtime_bindings(
    repo_root: Path, ledger_rows: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = "deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor"
    locks = {
        "contract": (
            f"{root}/contract.json",
            "029b17846f5e137d6aaad1e092abd444e7e17f112517841ce59fc960b096ec70",
        ),
        "contract_schema": (
            f"{root}/contract.schema.json",
            "beda5705dad3b6cdff0c9aa11ae3ecd716df1508e0f7042d503f3a87fde80553",
        ),
        "executor": (
            f"{root}/executor.py",
            "6f3af563886565f2688f97472fa2e6d993f8dc47ed12215d2d02c77ac4f8066c",
        ),
        "result_schema": (
            f"{root}/result.schema.json",
            "c49f98b4ad1aea73b6c1938eb06b1218b252902d3f54d19b0b3c891c2fcbbf1b",
        ),
    }
    documents: dict[str, dict[str, Any]] = {}
    for name, (relative_path, expected) in locks.items():
        path = _resolve_reviewed_file(repo_root, relative_path, f"SpatialAI {name}")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise OracleContractError(f"SpatialAI promoted {name} lock drift")
        if name != "executor":
            documents[name] = json.loads(
                payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs
            )
    _validate_json_schema(
        documents["contract"], documents["contract_schema"], "SpatialAI contract"
    )
    try:
        Draft202012Validator.check_schema(documents["result_schema"])
    except SchemaError as exc:
        raise OracleContractError(
            f"SpatialAI result schema is invalid: {exc.message}"
        ) from exc
    contract_rows = {
        row["capability_id"]: row for row in documents["contract"]["capabilities"]
    }
    if list(contract_rows) != list(SPATIAL_AI_IDS[:7]):
        raise OracleContractError("SpatialAI promoted contract denominator drift")
    bindings: dict[str, dict[str, Any]] = {}
    for capability_id, runtime in contract_rows.items():
        ledger_contract = ledger_rows[capability_id]["contract"]
        semantic_key = (
            "required_metrics"
            if "required_metrics" in ledger_contract
            else "required_semantics"
        )
        if (
            ledger_contract.get("source_controls") != runtime["source_controls"]
            or ledger_contract.get(semantic_key) != runtime["required_semantics"]
            or not ledger_rows[capability_id].get("runtime_evidence")
        ):
            raise OracleContractError(
                f"{capability_id}: promoted SpatialAI ledger contract drift"
            )
        fixture_path = _resolve_reviewed_file(
            repo_root,
            runtime["fixture_manifest"]["path"],
            f"{capability_id}.SpatialAI promoted fixture",
        )
        if (
            hashlib.sha256(fixture_path.read_bytes()).hexdigest()
            != runtime["fixture_manifest"]["sha256"]
        ):
            raise OracleContractError(f"{capability_id}: SpatialAI fixture drift")
        fixture = _load(fixture_path)
        for source in runtime["source_controls"]:
            source_path = _resolve_repo_regular_file(
                repo_root, source["path"], f"{capability_id}.source_control"
            )
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
                raise OracleContractError(
                    f"{capability_id}: SpatialAI source-control drift"
                )
        bindings[capability_id] = {
            "runtime": runtime,
            "runtime_namespace": f"spatial-ai-{capability_id.split('.')[2]}",
            "fixture_manifest": copy.deepcopy(runtime["fixture_manifest"]),
            "fixture_payload_id": fixture["fixture_id"],
            "max_actions": 7,
            "max_requests": 7,
            "promotion_state": "promoted_runtime",
        }
    return {"producer": {"executor": {"path": locks["executor"][0]}}}, bindings


def _spatial_ai_core_runtime_bindings(
    repo_root: Path, ledger: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    ledger_rows = {row["id"]: row for row in ledger["capabilities"]}
    if not set(SPATIAL_AI_IDS).issubset(ledger_rows):
        raise OracleContractError("SpatialAI canonical ledger denominator drift")
    target_states = {
        capability_id: (
            ledger_rows[capability_id]["thor_state"],
            ledger_rows[capability_id]["runtime_state"],
        )
        for capability_id in SPATIAL_AI_IDS[:7]
    }
    historical = all(state[1] == "not_qualified" for state in target_states.values())
    promoted = all(
        state == ("wired", "passed_current") for state in target_states.values()
    )
    if not historical and not promoted:
        raise OracleContractError("partial SpatialAI runtime family promotion")
    if promoted:
        return _spatial_ai_promoted_runtime_bindings(repo_root, ledger_rows)

    interface = _load_locked_reviewed_json(
        repo_root, SPATIAL_AI_CORE_INTERFACE, "SpatialAI core runtime interface"
    )
    interface_schema = _load_locked_reviewed_json(
        repo_root,
        SPATIAL_AI_CORE_INTERFACE_SCHEMA,
        "SpatialAI core runtime interface schema",
    )
    _validate_json_schema(interface, interface_schema, "SpatialAI core interface")

    producer = interface["producer"]
    executor = producer["executor"]["path"]
    if (
        producer["canonical_base_commit"] != SPATIAL_AI_CORE_CANONICAL_BASE_COMMIT
        or producer["source_binding"] != "raw_sha256_current_checkpoint"
    ):
        raise OracleContractError("SpatialAI core producer source-binding drift")
    if set(interface["roles"].values()) != {executor}:
        raise OracleContractError("SpatialAI core producer role binding drift")
    producer_documents: dict[str, dict[str, Any]] = {}
    for name in ("contract", "contract_schema", "executor", "result_schema"):
        lock = producer[name]
        result = subprocess.run(
            [
                "git",
                "show",
                f"{SPATIAL_AI_CORE_PRODUCER_COMMIT}:{lock['path']}",
            ],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if (
            result.returncode
            or hashlib.sha256(result.stdout).hexdigest() != lock["sha256"]
        ):
            raise OracleContractError(
                f"SpatialAI core producer source lock drift: {name}"
            )
        if name != "executor":
            producer_documents[name] = json.loads(
                result.stdout.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs
            )
    contract = producer_documents["contract"]
    _validate_json_schema(
        contract, producer_documents["contract_schema"], "SpatialAI core contract"
    )
    try:
        Draft202012Validator.check_schema(producer_documents["result_schema"])
    except SchemaError as exc:
        raise OracleContractError(
            f"SpatialAI core result schema is invalid: {exc.message}"
        ) from exc

    policy = contract["policy"]
    if (
        contract["target"]
        != {
            "upstream_repository": "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization",
            "upstream_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "product_version": "3.2.1",
            "current_oracle_document": "deploy/docker/thor-local/parity/capability-oracles.json",
            "current_ledger_document": "deploy/docker/thor-local/parity/official-capabilities.json",
        }
        or contract["environment"]["platform"] != "linux-aarch64"
        or contract["environment"]["python_major_minor"] != "3.12"
        or contract["environment"]["dependency_policy"]
        != "preinstalled_only_no_bootstrap"
        or interface["target_environment"]
        != {"platform": "linux-aarch64", "python_major_minor": "3.12"}
        or policy["independent_positive_runs"] != 2
        or policy["adjacent_negative_count_per_capability"] != 5
        or policy["target_case_actions_per_capability"] != 7
        or policy["product_execution_deadline_seconds"] != 900
        or policy["warehouse_sample_bundle"] != "excluded"
        or any(
            policy[key]
            for key in (
                "network_allowed",
                "docker_allowed",
                "service_lifecycle_allowed",
                "model_access_allowed",
                "downloads_allowed",
                "credentials_allowed",
            )
        )
    ):
        raise OracleContractError("SpatialAI core target or confinement policy drift")
    if (
        policy["external_provider_entry"] != SPATIAL_AI_IDS[7]
        or policy["external_provider_treatment"]
        != "excluded_external_optional_not_applicable"
        or interface["projection"]
        != {
            "canonical_mutation": False,
            "evidence_added": False,
            "ledger_rows_changed": 0,
            "oracle_rows_changed": 0,
            "promotion_performed": False,
            "selected_oracle_state": "open_unexecuted",
            "selected_readiness": "executor_ready",
        }
        or interface["confinement"]
        != {
            "docker": False,
            "downloads": False,
            "filesystem_escape_attempts": 0,
            "models": False,
            "network": False,
            "product_subprocesses": False,
            "services": False,
            "warehouse_sample_bundle": "excluded",
        }
    ):
        raise OracleContractError("SpatialAI core projection boundary drift")

    contract_rows = {row["capability_id"]: row for row in contract["capabilities"]}
    if list(contract_rows) != list(SPATIAL_AI_IDS[:7]):
        raise OracleContractError("SpatialAI seven-capability contract drift")
    for capability_id, runtime in contract_rows.items():
        if (
            canonical_oracle_sha256(ledger_rows[capability_id])
            != runtime["current_ledger_row_sha256"]
        ):
            raise OracleContractError(
                f"{capability_id}: SpatialAI current ledger binding drift"
            )

    if [row["capability_id"] for row in interface["capabilities"]] != list(
        SPATIAL_AI_CORE_IDS
    ):
        raise OracleContractError("SpatialAI core interface target order drift")
    bindings: dict[str, dict[str, Any]] = {}
    for row in interface["capabilities"]:
        capability_id = row["capability_id"]
        runtime = contract_rows[capability_id]
        if (
            row["oracle_id"] != runtime["oracle_id"]
            or row["adapter"] != runtime["adapter"]
            or row["fixture_manifest"] != runtime["fixture_manifest"]
            or row["positive_runs"] != 2
            or row["max_actions"] != 7
            or row["max_requests"] != 7
            or len(row["adjacent_negative_case_ids"]) != 5
        ):
            raise OracleContractError(
                f"{capability_id}: SpatialAI core runtime binding drift"
            )
        fixture_lock = row["fixture_manifest"]
        fixture_result = subprocess.run(
            [
                "git",
                "show",
                f"{SPATIAL_AI_CORE_PRODUCER_COMMIT}:{fixture_lock['path']}",
            ],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if (
            fixture_result.returncode
            or hashlib.sha256(fixture_result.stdout).hexdigest()
            != fixture_lock["sha256"]
        ):
            raise OracleContractError(f"{capability_id}: SpatialAI fixture drift")
        fixture = json.loads(
            fixture_result.stdout.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
        if fixture.get("fixture_id") != row["fixture_payload_id"]:
            raise OracleContractError(
                f"{capability_id}: SpatialAI fixture identity drift"
            )
        for source in runtime["source_controls"]:
            source_path = _resolve_repo_regular_file(
                repo_root, source["path"], f"{capability_id}.source_control"
            )
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
                raise OracleContractError(
                    f"{capability_id}: SpatialAI source-control drift"
                )
        bindings[capability_id] = {**copy.deepcopy(row), "runtime": runtime}
    accounting = interface["aggregate_execution_accounting"]
    if accounting != {
        "bounded_capability_actions": 21,
        "requests": 21,
        "imported_product_function_invocations": 34,
    }:
        raise OracleContractError("SpatialAI aggregate execution accounting drift")
    return interface, bindings


def _apply_spatial_ai_core_runtime(
    oracle: dict[str, Any], binding: dict[str, Any], executor: str
) -> None:
    capability_id = oracle["capability_id"]
    runtime = binding["runtime"]
    contract = copy.deepcopy(oracle["ledger_binding"]["contract"])
    contract["source_controls"] = copy.deepcopy(runtime["source_controls"])
    if "required_metrics" in contract:
        contract["required_metrics"] = copy.deepcopy(runtime["required_semantics"])
    elif "required_semantics" in contract:
        contract["required_semantics"] = copy.deepcopy(runtime["required_semantics"])
    else:
        raise OracleContractError(
            f"{capability_id}: SpatialAI semantic contract key is absent"
        )
    oracle["ledger_binding"]["runtime_state"] = "passed_current"
    if binding.get("promotion_state") != "promoted_runtime":
        oracle["ledger_binding"]["gap"] = SPATIAL_AI_CORE_GAP
    oracle["ledger_binding"]["contract"] = copy.deepcopy(contract)
    oracle["fixture"]["input"]["contract"] = copy.deepcopy(contract)
    oracle["fixture"]["input"]["namespace"] = binding["runtime_namespace"]
    oracle["fixture"]["materialization"] = {
        "path": binding["fixture_manifest"]["path"],
        "generator": executor,
        "sha256": binding["fixture_manifest"]["sha256"],
    }
    prefix = "contract_identity/contract/"
    for assertion in oracle["assertions"]:
        observation = assertion["observation"]
        if observation.startswith(prefix):
            key = observation.removeprefix(prefix)
            if key in contract:
                assertion["expected"] = copy.deepcopy(contract[key])
    workload = {
        "units": 1,
        "requests_per_unit": binding["max_requests"],
        "overhead_requests": 0,
        "calculated_max_requests": binding["max_requests"],
        "phases": ["positive_run_1", "positive_run_2", "adjacent_negative"],
    }
    oracle["execution_bounds"]["executor"] = executor
    oracle["execution_bounds"]["collectors"] = [executor]
    oracle["execution_bounds"]["max_actions"] = binding["max_actions"]
    oracle["execution_bounds"]["max_requests"] = binding["max_requests"]
    oracle["execution_bounds"]["workload"] = workload
    oracle["cleanup"]["targets"] = [binding["runtime_namespace"]]
    oracle["cleanup"]["allowlist"] = [binding["runtime_namespace"]]
    oracle["cleanup"]["executor"] = executor
    oracle["cleanup"]["postcondition_collectors"] = [executor]
    oracle["acceptance_readiness"] = {
        "classification": "executor_ready",
        "blockers": [],
    }
    if (
        binding.get("promotion_state") != "promoted_runtime"
        and canonical_oracle_sha256(oracle) != runtime["current_oracle_sha256"]
    ):
        raise OracleContractError(
            f"{capability_id}: SpatialAI current oracle binding drift"
        )


def _protocol_case_bindings(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        hashlib.sha256(PROTOCOL_CASES.read_bytes()).hexdigest()
        != PROTOCOL_CASES_FILE_SHA256
    ):
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
        if (
            not isinstance(sources, list)
            or not isinstance(negatives, list)
            or not isinstance(positive, dict)
        ):
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
        if (
            materialized is not True
            or executor_ready is not True
            or not isinstance(binding, dict)
        ):
            raise OracleContractError("partial live planning-executor integration")
        if requirement.get("runtime_evidence") != []:
            raise OracleContractError(
                "planning executor must not contain runtime evidence"
            )
        owner_type = requirement.get("owner_type")
        owner_id = requirement.get("owner_id")
        case = binding.get("case")
        if not isinstance(case, dict):
            raise OracleContractError("planning executor case is malformed")
        if case.get("planning_requirement_id") != requirement.get("id") or case.get(
            "planning_payload_sha256"
        ) != requirement.get("payload_canonical_sha256"):
            raise OracleContractError("planning executor case ownership differs")
        case_capability_id = case.get("capability_id")
        if owner_type in {"capability", "performance_enrichment_target"}:
            capability_id = owner_id
            if (
                not isinstance(capability_id, str)
                or case_capability_id != capability_id
            ):
                raise OracleContractError(
                    "planning executor lacks its exact capability owner"
                )
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
                raise OracleContractError(
                    "global planning executor target or uncovered partition differs"
                )
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


def _offline_mv3dt_tool_bindings(
    repo_root: Path = REPO_ROOT,
) -> dict[str, list[dict[str, Any]]]:
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
    semantic = (
        result_schema.get("$defs", {})
        .get("run", {})
        .get("properties", {})
        .get("semantic", {})
        .get("const")
    )
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
    if {
        item.get("path") for item in source_locks if isinstance(item, dict)
    } != expected_source_paths:
        raise OracleContractError("offline MV3DT source-lock path set differs")
    verified_source_locks: dict[str, str] = {}
    for source_lock in source_locks:
        relative = source_lock["path"]
        if relative == "deploy/docker/thor-local/parity/manifest.json":
            # This candidate receipt is an immutable observation of the live
            # manifest that existed when the two tool runs were captured.  A
            # later canonical-ledger successor must retain that recorded input
            # identity rather than rewrite history or require today's manifest
            # to have the historical digest.
            if source_lock.get("sha256") != (
                "6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127"
            ):
                raise OracleContractError(
                    "offline MV3DT historical manifest lock differs"
                )
            verified_source_locks[relative] = source_lock["sha256"]
            continue
        path = _resolve_repo_regular_file(
            repo_root, relative, f"offline_mv3dt.source_lock.{relative}"
        )
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
        raise OracleContractError(
            f"offline MV3DT execution receipt schema failed: {first.message}"
        )
    fixture_lock = OFFLINE_MV3DT_FILES["fixture"]
    expected_receipt_sources = {
        **verified_source_locks,
        fixture_lock["path"]: fixture_lock["raw_sha256"],
    }
    if receipt.get("source_and_fixture_sha256") != expected_receipt_sources:
        raise OracleContractError(
            "offline MV3DT receipt source/fixture bindings differ"
        )
    runs = receipt.get("deterministic_runs")
    if not isinstance(runs, list) or len(runs) != 2 or runs[0] != runs[1]:
        raise OracleContractError(
            "offline MV3DT receipt does not contain two identical runs"
        )
    observed_dependency = receipt.get("dependency_lock")
    if not isinstance(observed_dependency, dict):
        raise OracleContractError(
            "offline MV3DT receipt dependency observation is absent"
        )
    declared = observed_dependency.get("declared_requirements")
    observed_distributions = observed_dependency.get("observed_distribution_versions")
    expected_declared = contract.get("dependency_lock", {}).get("declared_requirements")
    if declared != expected_declared or not isinstance(observed_distributions, dict):
        raise OracleContractError(
            "offline MV3DT receipt dependency declaration differs"
        )
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
    if any(item["observed"] in item["declared"] for item in mismatches):
        raise OracleContractError("offline MV3DT dependency mismatch boundary differs")
    receipt_run = runs[0]
    common = {
        "scope": "bounded_static_tool_observation_subset_only",
        "qualification_package": OFFLINE_MV3DT_ROOT,
        "contract": copy.deepcopy(OFFLINE_MV3DT_FILES["contract"]),
        "executor": {
            **OFFLINE_MV3DT_FILES["executor"],
            "invocation": ["python3", f"{OFFLINE_MV3DT_ROOT}/executor.py", "--check"],
        },
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
        "covered_assertion_ids": [
            "contract-01",
            "contract-02",
            "contract-03",
            "contract-04",
            "observation-02",
            "observation-03",
        ],
        "uncovered_assertion_ids": [
            "contract-05",
            "contract-06",
            "contract-07",
            "contract-08",
        ],
    }
    outputs = receipt_run["output_locks"]
    observed_semantic = receipt_run["semantic"]
    return {
        "tool.mv3dt.cam-info-generator": [
            {
                **copy.deepcopy(common),
                "selected_output_locks": {
                    "cam_info_tree_sha256": outputs["cam_info_tree_sha256"]
                },
                "selected_semantic": {
                    "cam_info": copy.deepcopy(observed_semantic["cam_info"])
                },
                "oracle_coverage": copy.deepcopy(coverage),
            }
        ],
        "tool.mv3dt.pub-sub-generator": [
            {
                **copy.deepcopy(common),
                "selected_output_locks": {
                    "pub_sub_file_sha256": outputs["pub_sub_file_sha256"]
                },
                "selected_semantic": {
                    "pub_sub": copy.deepcopy(observed_semantic["pub_sub"])
                },
                "oracle_coverage": copy.deepcopy(coverage),
            }
        ],
    }


def compile_plan(
    ledger: dict[str, Any],
    protocol_document: dict[str, Any] | None = None,
    acceptance_document: dict[str, Any] | None = None,
    include_local_runtime_bounds: bool = True,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    target = ledger.get("target")
    capabilities = ledger.get("capabilities")
    if not isinstance(target, dict) or not isinstance(capabilities, list):
        raise OracleContractError("official capability ledger is malformed")
    mv3dt_states = {
        item["id"]: _mv3dt_runtime_state(item)
        for item in capabilities
        if isinstance(item, dict) and item.get("id") in MV3DT_RUNTIME_FIXTURES
    }
    if set(mv3dt_states) != set(MV3DT_RUNTIME_FIXTURES):
        raise OracleContractError("exact MV3DT runtime capability denominator drift")
    mv3dt_runtime_ready_ids = {
        capability_id
        for capability_id, state in mv3dt_states.items()
        if state == "promoted_runtime"
    }
    if len(mv3dt_runtime_ready_ids) not in {0, len(MV3DT_RUNTIME_FIXTURES)}:
        raise OracleContractError("partial MV3DT runtime family promotion")
    if mv3dt_runtime_ready_ids:
        _validate_mv3dt_runtime_locks(repo_root)
    spatial_ai_interface, spatial_ai_bindings = _spatial_ai_core_runtime_bindings(
        repo_root, ledger
    )
    spatial_ai_executor = spatial_ai_interface["producer"]["executor"]["path"]
    live_integration = include_local_runtime_bounds
    if live_integration:
        capability_ids = {
            item.get("id") for item in capabilities if isinstance(item, dict)
        }
        planning_ids = [row[0] for row in LOCAL_RUNTIME_WORKLOAD_OVERRIDES.values()]
        if (
            len(LOCAL_RUNTIME_WORKLOAD_OVERRIDES) != 20
            or not set(LOCAL_RUNTIME_WORKLOAD_OVERRIDES).issubset(capability_ids)
            or len(planning_ids) != len(set(planning_ids))
        ):
            raise OracleContractError(
                "exact local-runtime workload override denominator drift"
            )
    protocol_document = (
        _load(PROTOCOL_CASES) if protocol_document is None else protocol_document
    )
    protocol_bindings = _protocol_case_bindings(protocol_document)
    planning_bindings = _planning_executor_bindings(acceptance_document)
    offline_tool_bindings = (
        {} if acceptance_document is None else _offline_mv3dt_tool_bindings()
    )
    oracles = []
    for capability in capabilities:
        if not isinstance(capability, dict) or not isinstance(
            capability.get("id"), str
        ):
            raise OracleContractError(
                "official capability ledger contains an invalid capability"
            )
        capability_id = capability["id"]
        profile, mode = _profile(capability)
        external_boundary = capability["acceptance_class"] == "external_optional"
        workload = _workload(capability, live_integration=live_integration)
        if capability_id in mv3dt_runtime_ready_ids:
            workload = copy.deepcopy(MV3DT_RUNTIME_WORKLOAD)
        execution_bounds = {
            "executor": None,
            "collectors": [],
            "network_scope": "operator-approved external endpoint"
            if external_boundary
            else "loopback-or-compose-internal",
            "max_duration_seconds": 900,
            "max_requests": workload["calculated_max_requests"],
            "workload": workload,
            "model_staging": "prerequisite_only",
            "warehouse_sample_bundle": "excluded",
        }
        if live_integration:
            execution_bounds["max_actions"] = (
                MV3DT_RUNTIME_FIXTURES[capability_id]["max_actions"]
                if capability_id in mv3dt_runtime_ready_ids
                else _max_actions(capability, workload)
            )
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
            "current_state": "external_boundary_unexecuted"
            if external_boundary
            else "open_unexecuted",
            "evidence": [],
        }
        if capability["kind"] == "protocol":
            binding = protocol_bindings.get(capability_id)
            if binding is None:
                raise OracleContractError(
                    f"{capability_id}: exact protocol case is missing"
                )
            oracle["protocol_case_binding"] = binding
        if capability_id in planning_bindings:
            oracle["planning_executor_bindings"] = planning_bindings[capability_id]
            oracle["acceptance_readiness"]["blockers"] = [
                "the bounded static executor covers only named planning assertions, not the full capability runtime contract",
                "the full capability fixture, runtime executor, and collectors are not materialized",
                "the full capability cleanup allowlist has no machine executor or postcondition collector",
            ]
        if capability_id in offline_tool_bindings:
            oracle["offline_tool_observation_bindings"] = offline_tool_bindings[
                capability_id
            ]
        if capability_id in SYNTHETIC_RUNTIME_FIXTURES:
            fixture_path, fixture_sha256 = SYNTHETIC_RUNTIME_FIXTURES[capability_id]
            oracle["fixture"]["materialization"] = {
                "path": fixture_path,
                "generator": SYNTHETIC_RUNTIME_EXECUTOR,
                "sha256": fixture_sha256,
            }
            oracle["execution_bounds"]["executor"] = SYNTHETIC_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [SYNTHETIC_RUNTIME_EXECUTOR]
            oracle["cleanup"]["executor"] = SYNTHETIC_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [SYNTHETIC_RUNTIME_EXECUTOR]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_vios_byte_download(capability):
            oracle["fixture"]["materialization"] = {
                "path": VIOS_BYTE_DOWNLOAD_FIXTURE["path"],
                "generator": VIOS_BYTE_DOWNLOAD_EXECUTOR,
                "sha256": VIOS_BYTE_DOWNLOAD_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = VIOS_BYTE_DOWNLOAD_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [VIOS_BYTE_DOWNLOAD_EXECUTOR]
            oracle["cleanup"]["targets"] = [VIOS_BYTE_DOWNLOAD_NAMESPACE]
            oracle["cleanup"]["allowlist"] = [VIOS_BYTE_DOWNLOAD_NAMESPACE]
            oracle["cleanup"]["executor"] = VIOS_BYTE_DOWNLOAD_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                VIOS_BYTE_DOWNLOAD_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_nvstreamer_file_workflow(capability):
            oracle["fixture"]["materialization"] = {
                "path": NVSTREAMER_FILE_FIXTURE["path"],
                "generator": NVSTREAMER_FILE_EXECUTOR,
                "sha256": NVSTREAMER_FILE_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = NVSTREAMER_FILE_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [NVSTREAMER_FILE_EXECUTOR]
            oracle["cleanup"]["targets"] = [NVSTREAMER_FILE_NAMESPACE]
            oracle["cleanup"]["allowlist"] = [NVSTREAMER_FILE_NAMESPACE]
            oracle["cleanup"]["executor"] = NVSTREAMER_FILE_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [NVSTREAMER_FILE_EXECUTOR]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_nvstreamer_sync(capability):
            oracle["fixture"]["materialization"] = {
                "path": NVSTREAMER_SYNC_FIXTURE["path"],
                "generator": NVSTREAMER_SYNC_EXECUTOR,
                "sha256": NVSTREAMER_SYNC_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = NVSTREAMER_SYNC_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [NVSTREAMER_SYNC_EXECUTOR]
            oracle["cleanup"]["targets"] = [NVSTREAMER_SYNC_NAMESPACE]
            oracle["cleanup"]["allowlist"] = [NVSTREAMER_SYNC_NAMESPACE]
            oracle["cleanup"]["executor"] = NVSTREAMER_SYNC_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [NVSTREAMER_SYNC_EXECUTOR]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_nvstreamer_full_config(capability):
            oracle["fixture"]["materialization"] = {
                "path": NVSTREAMER_FULL_CONFIG_FIXTURE["path"],
                "generator": NVSTREAMER_FULL_CONFIG_EXECUTOR,
                "sha256": NVSTREAMER_FULL_CONFIG_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = NVSTREAMER_FULL_CONFIG_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [NVSTREAMER_FULL_CONFIG_EXECUTOR]
            oracle["cleanup"]["targets"] = [NVSTREAMER_FULL_CONFIG_NAMESPACE]
            oracle["cleanup"]["allowlist"] = [NVSTREAMER_FULL_CONFIG_NAMESPACE]
            oracle["cleanup"]["executor"] = NVSTREAMER_FULL_CONFIG_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                NVSTREAMER_FULL_CONFIG_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_vios_webrtc_replay(capability):
            oracle["fixture"]["materialization"] = {
                "path": VIOS_WEBRTC_REPLAY_FIXTURE["path"],
                "generator": VIOS_WEBRTC_REPLAY_EXECUTOR,
                "sha256": VIOS_WEBRTC_REPLAY_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = VIOS_WEBRTC_REPLAY_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [VIOS_WEBRTC_REPLAY_EXECUTOR]
            oracle["cleanup"]["targets"] = [VIOS_WEBRTC_REPLAY_NAMESPACE]
            oracle["cleanup"]["allowlist"] = [VIOS_WEBRTC_REPLAY_NAMESPACE]
            oracle["cleanup"]["executor"] = VIOS_WEBRTC_REPLAY_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                VIOS_WEBRTC_REPLAY_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_vios_webrtc_live(capability):
            oracle["fixture"]["materialization"] = {
                "path": VIOS_WEBRTC_LIVE_FIXTURE["path"],
                "generator": VIOS_WEBRTC_LIVE_EXECUTOR,
                "sha256": VIOS_WEBRTC_LIVE_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = VIOS_WEBRTC_LIVE_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [VIOS_WEBRTC_LIVE_EXECUTOR]
            oracle["cleanup"]["targets"] = copy.deepcopy(VIOS_WEBRTC_LIVE_NAMESPACES)
            oracle["cleanup"]["allowlist"] = copy.deepcopy(VIOS_WEBRTC_LIVE_NAMESPACES)
            oracle["cleanup"]["executor"] = VIOS_WEBRTC_LIVE_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [VIOS_WEBRTC_LIVE_EXECUTOR]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_video_analytics_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": VIDEO_ANALYTICS_RUNTIME_FIXTURE["path"],
                "generator": VIDEO_ANALYTICS_RUNTIME_EXECUTOR,
                "sha256": VIDEO_ANALYTICS_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = VIDEO_ANALYTICS_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [
                VIDEO_ANALYTICS_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["targets"] = [VIDEO_ANALYTICS_RUNTIME_NAMESPACE]
            oracle["cleanup"]["allowlist"] = [VIDEO_ANALYTICS_RUNTIME_NAMESPACE]
            oracle["cleanup"]["executor"] = VIDEO_ANALYTICS_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                VIDEO_ANALYTICS_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_event_transport_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": EVENT_TRANSPORT_RUNTIME_FIXTURE["path"],
                "generator": EVENT_TRANSPORT_RUNTIME_EXECUTOR,
                "sha256": EVENT_TRANSPORT_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = EVENT_TRANSPORT_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [
                EVENT_TRANSPORT_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["targets"] = copy.deepcopy(
                EVENT_TRANSPORT_RUNTIME_NAMESPACES[capability_id]
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                EVENT_TRANSPORT_RUNTIME_NAMESPACES[capability_id]
            )
            oracle["cleanup"]["executor"] = EVENT_TRANSPORT_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                EVENT_TRANSPORT_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_agent_websocket_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": AGENT_WEBSOCKET_RUNTIME_FIXTURE["path"],
                "generator": AGENT_WEBSOCKET_RUNTIME_EXECUTOR,
                "sha256": AGENT_WEBSOCKET_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = AGENT_WEBSOCKET_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [
                AGENT_WEBSOCKET_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["targets"] = copy.deepcopy(
                AGENT_WEBSOCKET_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                AGENT_WEBSOCKET_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["executor"] = AGENT_WEBSOCKET_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                AGENT_WEBSOCKET_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_alert_websocket_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": ALERT_WEBSOCKET_RUNTIME_FIXTURE["path"],
                "generator": ALERT_WEBSOCKET_RUNTIME_EXECUTOR,
                "sha256": ALERT_WEBSOCKET_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = ALERT_WEBSOCKET_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [
                ALERT_WEBSOCKET_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["targets"] = copy.deepcopy(
                ALERT_WEBSOCKET_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                ALERT_WEBSOCKET_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["executor"] = ALERT_WEBSOCKET_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                ALERT_WEBSOCKET_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_rt_vlm_sse_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": RT_VLM_SSE_RUNTIME_FIXTURE["path"],
                "generator": RT_VLM_SSE_RUNTIME_EXECUTOR,
                "sha256": RT_VLM_SSE_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = RT_VLM_SSE_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [RT_VLM_SSE_RUNTIME_EXECUTOR]
            oracle["cleanup"]["targets"] = copy.deepcopy(RT_VLM_SSE_RUNTIME_NAMESPACES)
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                RT_VLM_SSE_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["executor"] = RT_VLM_SSE_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                RT_VLM_SSE_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_official_edge_model_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": OFFICIAL_EDGE_MODEL_RUNTIME_FIXTURE["path"],
                "generator": OFFICIAL_EDGE_MODEL_RUNTIME_EXECUTOR,
                "sha256": OFFICIAL_EDGE_MODEL_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = (
                OFFICIAL_EDGE_MODEL_RUNTIME_EXECUTOR
            )
            oracle["execution_bounds"]["collectors"] = [
                OFFICIAL_EDGE_MODEL_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["mutation"] = "read_only"
            oracle["cleanup"]["targets"] = copy.deepcopy(
                OFFICIAL_EDGE_MODEL_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                OFFICIAL_EDGE_MODEL_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["pre_state"] = (
                "exact model endpoint, asset statistics, and container identity "
                "state must be captured before semantic inference"
            )
            oracle["cleanup"]["restore"] = (
                "no restore action: the executor performs no mutation"
            )
            oracle["cleanup"]["executor"] = OFFICIAL_EDGE_MODEL_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                OFFICIAL_EDGE_MODEL_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["postconditions"] = [
                "RT-VLM asset statistics match pre-state exactly",
                "both model container identities, start times, health, restart counts, and OOM states match pre-state exactly",
                "no file, stream, report, rule, sensor, index, model, image, container, or volume is created or removed",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_rt_embed_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": RT_EMBED_CURRENT_RUNTIME_FIXTURE["path"],
                "generator": RT_EMBED_CURRENT_RUNTIME_EXECUTOR,
                "sha256": RT_EMBED_CURRENT_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = RT_EMBED_CURRENT_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [
                RT_EMBED_CURRENT_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["targets"] = copy.deepcopy(
                RT_EMBED_CURRENT_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                RT_EMBED_CURRENT_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["pre_state"] = (
                "complete file, batch-stream, single-stream, asset-statistics, "
                "RT-Embed container, helper, and operator-paused workload state "
                "must be captured before mutation"
            )
            oracle["cleanup"]["restore"] = (
                "stop inference and delete only fixed oracle-owned file, stream, "
                "camera, publisher, and helper resources"
            )
            oracle["cleanup"]["executor"] = RT_EMBED_CURRENT_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                RT_EMBED_CURRENT_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["postconditions"] = [
                "all six fixed UUID resources and the fixed camera ID are absent",
                "complete file and both stream inventories match pre-state exactly",
                "asset statistics match pre-state exactly",
                "the ephemeral RTSP path again returns RTSP 404",
                "the publisher and all three exact helper containers are absent",
                "the RT-Embed container identity, start time, health, restart count, OOM state, mounts, and safe model environment match pre-state exactly",
                "the three operator-paused unrelated workloads remain stopped",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_search_backend_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": SEARCH_BACKEND_RUNTIME_FIXTURE["path"],
                "generator": SEARCH_BACKEND_RUNTIME_EXECUTOR,
                "sha256": SEARCH_BACKEND_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = SEARCH_BACKEND_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [SEARCH_BACKEND_RUNTIME_VERIFIER]
            oracle["execution_bounds"]["max_duration_seconds"] = 300
            oracle["cleanup"]["targets"] = copy.deepcopy(
                SEARCH_BACKEND_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                SEARCH_BACKEND_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["pre_state"] = (
                "the complete target-index absence state, read-only embedding "
                "index identity/count, analytics frame state, source locks, and "
                "five related runtime identities must be captured before mutation"
            )
            oracle["cleanup"]["restore"] = (
                "delete only the two fixed executor-owned indices after exact "
                "UUID and complete document-inventory matches; otherwise delete "
                "only exact owned documents and fail promotion"
            )
            oracle["cleanup"]["executor"] = SEARCH_BACKEND_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                SEARCH_BACKEND_RUNTIME_VERIFIER
            ]
            oracle["cleanup"]["postconditions"] = [
                "both fixed executor-owned indices are absent in two delayed checks",
                "the analytics frame query is empty",
                "the pre-existing embedding index UUID and document count match pre-state exactly",
                "all five related runtime identities, start times, health states, restart counts, and OOM states match pre-state exactly",
                "no sensor, stream, service lifecycle, or Warehouse sample mutation occurred",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_search_content_type_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": SEARCH_CONTENT_TYPE_RUNTIME_FIXTURE["path"],
                "generator": SEARCH_CONTENT_TYPE_RUNTIME_EXECUTOR,
                "sha256": SEARCH_CONTENT_TYPE_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = (
                SEARCH_CONTENT_TYPE_RUNTIME_EXECUTOR
            )
            oracle["execution_bounds"]["collectors"] = [
                SEARCH_CONTENT_TYPE_RUNTIME_VERIFIER
            ]
            oracle["execution_bounds"]["max_duration_seconds"] = 300
            oracle["cleanup"]["targets"] = copy.deepcopy(
                SEARCH_CONTENT_TYPE_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                SEARCH_CONTENT_TYPE_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["pre_state"] = (
                "complete VIOS sensor/file inventories, exact owned-document "
                "absence, source locks, and four related runtime identities "
                "must be captured before mutation"
            )
            oracle["cleanup"]["restore"] = (
                "delete only sensor IDs recorded from the two generated "
                "qualification uploads or recovered under the exact owned prefix"
            )
            oracle["cleanup"]["executor"] = SEARCH_CONTENT_TYPE_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                SEARCH_CONTENT_TYPE_RUNTIME_VERIFIER
            ]
            oracle["cleanup"]["postconditions"] = [
                "both exact generated sensor names are absent",
                "all exact owned embed, behavior, and raw documents are absent",
                "complete sensor identity and file inventories match pre-state exactly",
                "all four related container identities, health states, and restart counts match pre-state exactly",
                "no service lifecycle or Warehouse sample mutation occurred",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_search_ui_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": SEARCH_UI_RUNTIME_FIXTURE["path"],
                "generator": SEARCH_UI_RUNTIME_EXECUTOR,
                "sha256": SEARCH_UI_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = SEARCH_UI_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [SEARCH_UI_RUNTIME_VERIFIER]
            oracle["execution_bounds"]["max_duration_seconds"] = 180
            oracle["cleanup"]["mutation"] = "read_only"
            oracle["cleanup"]["targets"] = []
            oracle["cleanup"]["allowlist"] = []
            oracle["cleanup"]["pre_state"] = (
                "the UI, ingress, and Agent identities, source locks, critic "
                "defaults, and both sealed Search dependency packages must match "
                "the reviewed contract"
            )
            oracle["cleanup"]["restore"] = (
                "no server restore action: all interception and presentation "
                "fixtures are isolated to a discarded browser context"
            )
            oracle["cleanup"]["executor"] = SEARCH_UI_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [SEARCH_UI_RUNTIME_VERIFIER]
            oracle["cleanup"]["postconditions"] = [
                "the isolated browser and temporary screenshot are absent",
                "the UI, ingress, and Agent runtime identities match pre-state exactly",
                "the current selected-object and prior real critic evidence still verify",
                "no server-side sensor, stream, index, report, rule, incident, image, volume, container, or configuration changed",
                "all unexpected browser diagnostics and non-loopback traffic remain absent",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_ui_dashboard_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": UI_DASHBOARD_RUNTIME_FIXTURE["path"],
                "generator": UI_DASHBOARD_RUNTIME_EXECUTOR,
                "sha256": UI_DASHBOARD_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = UI_DASHBOARD_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [UI_DASHBOARD_RUNTIME_VERIFIER]
            oracle["execution_bounds"]["max_duration_seconds"] = 120
            oracle["cleanup"]["mutation"] = "read_only"
            oracle["cleanup"]["targets"] = []
            oracle["cleanup"]["allowlist"] = []
            oracle["cleanup"]["pre_state"] = (
                "the UI and Kibana image identities, source locks, saved-object "
                "identity, and loopback health must match the reviewed contract"
            )
            oracle["cleanup"]["restore"] = (
                "no restore action: the rendered-browser executor is read-only"
            )
            oracle["cleanup"]["executor"] = UI_DASHBOARD_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                UI_DASHBOARD_RUNTIME_VERIFIER
            ]
            oracle["cleanup"]["postconditions"] = [
                "no persistent resource or configuration is created, changed, or deleted by the runtime executor",
                "only bounded screenshots outside the repository are created",
                "the embedded dashboard and adjacent missing saved object remain distinguishable",
                "all unknown browser diagnostics and unknown 404 paths remain absent",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_ui_global_chat_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": UI_GLOBAL_CHAT_RUNTIME_FIXTURE["path"],
                "generator": UI_GLOBAL_CHAT_RUNTIME_EXECUTOR,
                "sha256": UI_GLOBAL_CHAT_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = UI_GLOBAL_CHAT_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [UI_GLOBAL_CHAT_RUNTIME_VERIFIER]
            oracle["execution_bounds"]["max_duration_seconds"] = 180
            oracle["cleanup"]["mutation"] = "read_only"
            oracle["cleanup"]["targets"] = []
            oracle["cleanup"]["allowlist"] = []
            oracle["cleanup"]["pre_state"] = (
                "the UI, gateway, and VIOS ingress identities, source locks, "
                "runtime flags, and numeric-loopback endpoint hashes must match "
                "the reviewed contract"
            )
            oracle["cleanup"]["restore"] = (
                "no server restore action: all changes are isolated to discarded "
                "browser contexts and report transport is suppressed"
            )
            oracle["cleanup"]["executor"] = UI_GLOBAL_CHAT_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                UI_GLOBAL_CHAT_RUNTIME_VERIFIER
            ]
            oracle["cleanup"]["postconditions"] = [
                "all three isolated browser contexts and the browser are closed",
                "all temporary screenshots are deleted after hashing",
                "the one-key runtime environment override and two-row report fixture are discarded",
                "the compiled Generate Report WebSocket frame is captured in memory and never transported",
                "the UI, gateway, and VIOS ingress identities, start times, health, restart counts, and OOM states match pre-state exactly",
                "no server-side file, sensor, stream, report, alert rule, incident, container, image, or volume is created, changed, or removed",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_lvs_mcp_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": LVS_MCP_RUNTIME_FIXTURE["path"],
                "generator": LVS_MCP_RUNTIME_EXECUTOR,
                "sha256": LVS_MCP_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = LVS_MCP_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [LVS_MCP_RUNTIME_VERIFIER]
            oracle["execution_bounds"]["max_duration_seconds"] = 180
            oracle["cleanup"]["targets"] = copy.deepcopy(LVS_MCP_RUNTIME_NAMESPACES)
            oracle["cleanup"]["allowlist"] = copy.deepcopy(LVS_MCP_RUNTIME_NAMESPACES)
            oracle["cleanup"]["pre_state"] = (
                "exact source locks, the LVS container identity, complete LVS REST "
                "and MCP file catalogs, and the complete MCP media-root inventory "
                "must be captured before mutation"
            )
            oracle["cleanup"]["restore"] = (
                "delete only the exact recorded oracle-owned LVS file asset and "
                "remove only the exact generated media fixture"
            )
            oracle["cleanup"]["executor"] = LVS_MCP_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [LVS_MCP_RUNTIME_VERIFIER]
            oracle["cleanup"]["postconditions"] = [
                "the exact owned LVS asset is absent from MCP and REST catalogs",
                "the complete LVS REST and MCP file catalogs match pre-state exactly",
                "the complete MCP media-root inventory matches pre-state exactly",
                "the LVS container identity, health, start time, and restart count match pre-state exactly",
                "no inference, stream, service-lifecycle, or Warehouse sample action occurred",
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_lvs_formats_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": LVS_FORMATS_RUNTIME_FIXTURE["path"],
                "generator": LVS_FORMATS_RUNTIME_EXECUTOR,
                "sha256": LVS_FORMATS_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = LVS_FORMATS_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [LVS_FORMATS_RUNTIME_EXECUTOR]
            oracle["cleanup"]["targets"] = copy.deepcopy(LVS_FORMATS_RUNTIME_NAMESPACES)
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                LVS_FORMATS_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["executor"] = LVS_FORMATS_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                LVS_FORMATS_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_lvs_single_request_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": LVS_SINGLE_REQUEST_RUNTIME_FIXTURE["path"],
                "generator": LVS_SINGLE_REQUEST_RUNTIME_EXECUTOR,
                "sha256": LVS_SINGLE_REQUEST_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = LVS_SINGLE_REQUEST_RUNTIME_EXECUTOR
            oracle["execution_bounds"]["collectors"] = [
                LVS_SINGLE_REQUEST_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["targets"] = copy.deepcopy(
                LVS_SINGLE_REQUEST_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                LVS_SINGLE_REQUEST_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["executor"] = LVS_SINGLE_REQUEST_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                LVS_SINGLE_REQUEST_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if _is_current_lvs_custom_model_prompt_runtime(capability):
            oracle["fixture"]["materialization"] = {
                "path": LVS_CUSTOM_MODEL_PROMPT_RUNTIME_FIXTURE["path"],
                "generator": LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EXECUTOR,
                "sha256": LVS_CUSTOM_MODEL_PROMPT_RUNTIME_FIXTURE["sha256"],
            }
            oracle["execution_bounds"]["executor"] = (
                LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EXECUTOR
            )
            oracle["execution_bounds"]["collectors"] = [
                LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EXECUTOR
            ]
            oracle["cleanup"]["targets"] = copy.deepcopy(
                LVS_CUSTOM_MODEL_PROMPT_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["allowlist"] = copy.deepcopy(
                LVS_CUSTOM_MODEL_PROMPT_RUNTIME_NAMESPACES
            )
            oracle["cleanup"]["executor"] = LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EXECUTOR
            oracle["cleanup"]["postcondition_collectors"] = [
                LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EXECUTOR
            ]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if capability_id in mv3dt_runtime_ready_ids:
            fixture = MV3DT_RUNTIME_FIXTURES[capability_id]
            executor = MV3DT_RUNTIME_EXECUTOR["path"]
            oracle["fixture"]["materialization"] = {
                "path": fixture["path"],
                "generator": executor,
                "sha256": fixture["raw_sha256"],
            }
            oracle["execution_bounds"]["executor"] = executor
            oracle["execution_bounds"]["collectors"] = [executor]
            oracle["execution_bounds"]["max_requests"] = fixture["max_requests"]
            oracle["cleanup"]["targets"] = [fixture["namespace"]]
            oracle["cleanup"]["allowlist"] = [fixture["namespace"]]
            oracle["cleanup"]["executor"] = executor
            oracle["cleanup"]["postcondition_collectors"] = [executor]
            oracle["acceptance_readiness"] = {
                "classification": "executor_ready",
                "blockers": [],
            }
        if capability_id in spatial_ai_bindings:
            _apply_spatial_ai_core_runtime(
                oracle, spatial_ai_bindings[capability_id], spatial_ai_executor
            )
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
        raise OracleContractError(
            f"invalid capability-oracle schema: {exc.message}"
        ) from exc
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
        repo_root=repo_root,
    )
    historical_spatial_prefix = False
    if plan != expected:
        expected_by_id = {item["capability_id"]: item for item in expected["oracles"]}
        actual_by_id = {
            item.get("capability_id"): item
            for item in plan.get("oracles", [])
            if isinstance(item, dict)
        }
        if set(actual_by_id) != set(expected_by_id):
            missing = sorted(set(expected_by_id) - set(actual_by_id))
            extra = sorted(set(actual_by_id) - set(expected_by_id), key=str)
            raise OracleContractError(
                f"oracle coverage drift: missing={missing}, extra={extra}"
            )
        changed = {
            key for key in expected_by_id if actual_by_id[key] != expected_by_id[key]
        }
        historical_spatial_prefix = changed == set(SPATIAL_AI_CORE_IDS) and all(
            canonical_oracle_sha256(actual_by_id[capability_id])
            == SPATIAL_AI_CORE_HISTORICAL_PREDECESSOR_SHA256[capability_id]
            for capability_id in SPATIAL_AI_CORE_IDS
        )
        if not historical_spatial_prefix:
            first_changed = next(key for key in expected_by_id if key in changed)
            raise OracleContractError(
                f"{first_changed}: oracle contract drift; regenerate and review"
            )
    oracle_ids = [item["oracle_id"] for item in plan["oracles"]]
    fixture_ids = [item["fixture"]["id"] for item in plan["oracles"]]
    unique_scenarios = [item["reviewed_scenario_ids"][-1] for item in plan["oracles"]]
    for label, values in (
        ("oracle", oracle_ids),
        ("fixture", fixture_ids),
        ("scenario", unique_scenarios),
    ):
        if len(values) != len(set(values)) or any(
            PLAIN_ID.fullmatch(value) is None for value in values
        ):
            raise OracleContractError(
                f"capability-specific {label} identities must be unique plain IDs"
            )
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
        raise OracleContractError(
            "a generic oracle signature is reused across capabilities"
        )
    if any(
        item["current_state"] not in {"open_unexecuted", "external_boundary_unexecuted"}
        or item["evidence"]
        for item in plan["oracles"]
    ):
        raise OracleContractError(
            "unexecuted oracle plans must not contain passed state or evidence"
        )
    ledger_by_id = {item["id"]: item for item in ledger["capabilities"]}
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
                or binding["result"]["official_capability_effect"]
                != "none_candidate_only"
            ):
                raise OracleContractError(
                    f"{item['capability_id']}: offline tool binding implies capability advancement"
                )
            coverage = binding["oracle_coverage"]
            expected_observations = {
                observation["id"] for observation in item["expected_observations"]
            }
            covered_observations = set(coverage["covered_observation_ids"])
            uncovered_observations = set(coverage["uncovered_observation_ids"])
            expected_assertions = {assertion["id"] for assertion in item["assertions"]}
            covered_assertions = set(coverage["covered_assertion_ids"])
            uncovered_assertions = set(coverage["uncovered_assertion_ids"])
            if (
                covered_observations & uncovered_observations
                or covered_observations | uncovered_observations
                != expected_observations
                or covered_assertions & uncovered_assertions
                or covered_assertions | uncovered_assertions != expected_assertions
                or not uncovered_observations
                or not uncovered_assertions
            ):
                raise OracleContractError(
                    f"{item['capability_id']}: offline tool oracle coverage is not an exact non-advancing partition"
                )
        workload = item["execution_bounds"]["workload"]
        calculated = (
            workload["units"] * workload["requests_per_unit"]
            + workload["overhead_requests"]
        )
        if (
            workload["calculated_max_requests"] != calculated
            or item["execution_bounds"]["max_requests"] != calculated
        ):
            raise OracleContractError(
                f"{item['capability_id']}: execution-bound arithmetic differs"
            )
        capability_id = item["capability_id"]
        override = LOCAL_RUNTIME_WORKLOAD_OVERRIDES.get(capability_id)
        if (
            _is_current_search_backend_runtime(ledger_by_id[capability_id])
            or _is_current_search_content_type_runtime(ledger_by_id[capability_id])
            or _is_current_search_ui_runtime(ledger_by_id[capability_id])
        ):
            override = None
        mv3dt_runtime = MV3DT_RUNTIME_FIXTURES.get(capability_id)
        if is_spatial_ai_core_stage1_binding(ledger_by_id[capability_id], item):
            expected_actions = 7
        elif _is_current_nvstreamer_sync(ledger_by_id[capability_id]):
            expected_actions = NVSTREAMER_SYNC_MAX_ACTIONS
        elif _is_current_nvstreamer_full_config(ledger_by_id[capability_id]):
            expected_actions = NVSTREAMER_FULL_CONFIG_MAX_ACTIONS
        elif _is_current_vios_webrtc_replay(ledger_by_id[capability_id]):
            expected_actions = VIOS_WEBRTC_REPLAY_MAX_ACTIONS
        elif _is_current_vios_webrtc_live(ledger_by_id[capability_id]):
            expected_actions = VIOS_WEBRTC_LIVE_MAX_ACTIONS
        elif _is_current_video_analytics_runtime(ledger_by_id[capability_id]):
            expected_actions = VIDEO_ANALYTICS_RUNTIME_MAX_ACTIONS
        elif _is_current_event_transport_runtime(ledger_by_id[capability_id]):
            expected_actions = EVENT_TRANSPORT_RUNTIME_MAX_ACTIONS
        elif _is_current_agent_websocket_runtime(ledger_by_id[capability_id]):
            expected_actions = AGENT_WEBSOCKET_RUNTIME_MAX_ACTIONS
        elif _is_current_alert_websocket_runtime(ledger_by_id[capability_id]):
            expected_actions = ALERT_WEBSOCKET_RUNTIME_MAX_ACTIONS
        elif _is_current_rt_vlm_sse_runtime(ledger_by_id[capability_id]):
            expected_actions = RT_VLM_SSE_RUNTIME_MAX_ACTIONS
        elif _is_current_official_edge_model_runtime(ledger_by_id[capability_id]):
            expected_actions = OFFICIAL_EDGE_MODEL_RUNTIME_MAX_ACTIONS
        elif _is_current_rt_embed_runtime(ledger_by_id[capability_id]):
            expected_actions = RT_EMBED_CURRENT_RUNTIME_MAX_ACTIONS
        elif _is_current_search_backend_runtime(ledger_by_id[capability_id]):
            expected_actions = SEARCH_BACKEND_RUNTIME_MAX_ACTIONS
        elif _is_current_search_content_type_runtime(ledger_by_id[capability_id]):
            expected_actions = SEARCH_CONTENT_TYPE_RUNTIME_MAX_ACTIONS
        elif _is_current_search_ui_runtime(ledger_by_id[capability_id]):
            expected_actions = SEARCH_UI_RUNTIME_MAX_ACTIONS
        elif _is_current_ui_dashboard_runtime(ledger_by_id[capability_id]):
            expected_actions = UI_DASHBOARD_RUNTIME_MAX_ACTIONS
        elif _is_current_ui_global_chat_runtime(ledger_by_id[capability_id]):
            expected_actions = UI_GLOBAL_CHAT_RUNTIME_MAX_ACTIONS
        elif _is_current_lvs_mcp_runtime(ledger_by_id[capability_id]):
            expected_actions = LVS_MCP_RUNTIME_MAX_ACTIONS
        elif _is_current_lvs_formats_runtime(ledger_by_id[capability_id]):
            expected_actions = LVS_FORMATS_RUNTIME_MAX_ACTIONS
        elif _is_current_lvs_single_request_runtime(ledger_by_id[capability_id]):
            expected_actions = LVS_SINGLE_REQUEST_RUNTIME_MAX_ACTIONS
        elif _is_current_lvs_custom_model_prompt_runtime(ledger_by_id[capability_id]):
            expected_actions = LVS_CUSTOM_MODEL_PROMPT_RUNTIME_MAX_ACTIONS
        elif (
            capability_id in SPATIAL_AI_IDS[:7]
            and item["ledger_binding"]["thor_state"] == "wired"
            and item["ledger_binding"]["runtime_state"] == "passed_current"
        ):
            expected_actions = 7
        elif (
            mv3dt_runtime is not None
            and item["ledger_binding"]["thor_state"] == "wired"
            and item["ledger_binding"]["runtime_state"] == "passed_current"
        ):
            expected_actions = mv3dt_runtime["max_actions"]
        else:
            expected_actions = override[2] if override is not None else calculated
        if item["execution_bounds"]["max_actions"] != expected_actions:
            raise OracleContractError(
                f"{item['capability_id']}: execution action bound differs"
            )
        if override is not None:
            planning_ids = (
                item["fixture"]["input"]["contract"]
                .get("wave3_acceptance", {})
                .get("planning_requirement_ids")
            )
            if (
                planning_ids != [override[0]]
                or calculated != override[1]
                or workload["phases"] != LOCAL_RUNTIME_WORKLOAD_PHASES
            ):
                raise OracleContractError(
                    f"{item['capability_id']}: exact local-runtime workload override differs"
                )
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
                raise OracleContractError(
                    f"{item['capability_id']}: planning-only oracle must not imply executable materialization"
                )
        elif (
            item["acceptance_readiness"]["blockers"]
            or not all(item["fixture"]["materialization"].values())
            or not item["execution_bounds"]["executor"]
            or not item["execution_bounds"]["collectors"]
            or not item["cleanup"]["executor"]
            or not item["cleanup"]["postcondition_collectors"]
        ):
            raise OracleContractError(
                f"{item['capability_id']}: executor-ready oracle is incomplete"
            )
        else:
            capability_id = item["capability_id"]
            materialization = item["fixture"]["materialization"]
            fixture_path = _resolve_reviewed_file(
                repo_root, materialization["path"], f"{capability_id}.fixture"
            )
            fixture_matches = (
                hashlib.sha256(fixture_path.read_bytes()).hexdigest()
                == materialization["sha256"]
            )
            if not fixture_matches and is_spatial_ai_core_stage1_binding(
                ledger_by_id[capability_id], item
            ):
                historical_fixture = subprocess.run(
                    [
                        "git",
                        "show",
                        f"{SPATIAL_AI_CORE_PRODUCER_COMMIT}:{materialization['path']}",
                    ],
                    cwd=repo_root,
                    capture_output=True,
                    check=False,
                )
                fixture_matches = (
                    historical_fixture.returncode == 0
                    and hashlib.sha256(historical_fixture.stdout).hexdigest()
                    == materialization["sha256"]
                )
            if not fixture_matches:
                raise OracleContractError(f"{capability_id}: fixture digest differs")
            _resolve_reviewed_file(
                repo_root,
                materialization["generator"],
                f"{capability_id}.fixture_generator",
            )
            _resolve_reviewed_file(
                repo_root,
                item["execution_bounds"]["executor"],
                f"{capability_id}.executor",
            )
            for index, collector in enumerate(item["execution_bounds"]["collectors"]):
                _resolve_reviewed_file(
                    repo_root, collector, f"{capability_id}.collector[{index}]"
                )
            _resolve_reviewed_file(
                repo_root,
                item["cleanup"]["executor"],
                f"{capability_id}.cleanup_executor",
            )
            for index, collector in enumerate(
                item["cleanup"]["postcondition_collectors"]
            ):
                _resolve_reviewed_file(
                    repo_root, collector, f"{capability_id}.cleanup_collector[{index}]"
                )
    return {
        "capabilities": len(ledger["capabilities"]),
        "oracles": len(plan["oracles"]),
        "open_runtime": sum(
            item["current_state"] == "open_unexecuted" for item in plan["oracles"]
        ),
        "external_boundaries": sum(
            item["current_state"] == "external_boundary_unexecuted"
            for item in plan["oracles"]
        ),
        "profiles": len({item["profile"] for item in plan["oracles"]}),
        "planning_index_only": sum(
            item["acceptance_readiness"]["classification"] == "planning_index_only"
            for item in plan["oracles"]
        ),
        "executor_ready": sum(
            item["acceptance_readiness"]["classification"] == "executor_ready"
            for item in plan["oracles"]
        ),
        "planning_executor_bindings": sum(
            len(item.get("planning_executor_bindings", [])) for item in plan["oracles"]
        ),
        "offline_tool_observation_bindings": sum(
            len(item.get("offline_tool_observation_bindings", []))
            for item in plan["oracles"]
        ),
        "static_subset_oracle_bindings": sum(
            len(item.get("planning_executor_bindings", []))
            + len(item.get("offline_tool_observation_bindings", []))
            for item in plan["oracles"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compile", action="store_true", help="print the canonical expanded plan"
    )
    parser.add_argument(
        "--write", action="store_true", help="write the canonical expanded plan"
    )
    parser.add_argument("--report", action="store_true", help="print validation counts")
    args = parser.parse_args()
    try:
        if args.compile or args.write:
            rendered = (
                json.dumps(
                    compile_plan(
                        _load(LEDGER),
                        acceptance_document=_load(ACCEPTANCE),
                        include_local_runtime_bounds=True,
                    ),
                    indent=2,
                    ensure_ascii=True,
                    sort_keys=True,
                )
                + "\n"
            )
            if args.write:
                ORACLES.write_text(rendered, encoding="utf-8")
                print(f"WROTE: {ORACLES.relative_to(REPO_ROOT)}")
            else:
                print(rendered, end="")
            return 0
        counts = validate()
    except (OSError, json.JSONDecodeError, OracleContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.report:
        print(json.dumps(counts, indent=2, sort_keys=True))
    else:
        print(
            f"PASS: {counts['oracles']} capability-specific planning-index records validated"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
