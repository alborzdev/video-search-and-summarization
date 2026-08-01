#!/usr/bin/env python3
"""Candidate-only static executor for six VIOS codec/audio advertised entries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_SOURCE_BYTES = 1_000_000

EXPECTED_INVENTORY_SHA256 = (
    "98876a18d628df644171cd1d0051753dadd904cca67a5fe0fa8696832cb08771"
)
EXPECTED_SOURCE_PLAN = {
    "path": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "raw_sha256": "dd3c8cbbcae859137e73da4a8d4d9227f535dd674979b5d9e8f5cf25b885d122",
    "plan_payload_sha256": "97cb92ffb83d05388759f7428324344f91ec294116e5d24721c1ba21d994ab7d",
}
EXPECTED_SOURCE_MANIFEST = {
    "path": "deploy/docker/thor-local/parity/manifest.json",
    "raw_sha256": "6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127",
}
EXPECTED_PREDECESSORS = [
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors/inventory.json",
        "raw_sha256": "91406a15ff1340b9b4dba988507470234971fa4905997bc52e64fb983fc12a18",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/inventory.json",
        "raw_sha256": "2c14f8ae5ade22ccbc556a844b4fcb63661048826660073fb21c5f882047c5d2",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/inventory.json",
        "raw_sha256": "0b7056eafce7686fc2b7315fef8ae491ddef03d2e52f41e7c7861247933f90ab",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave4/inventory.json",
        "raw_sha256": "1de6e9be3c93c349e45b192506e3081758553582dda6f73b79877bc4ff5155a6",
    },
]
EXPECTED_POLICY = {
    "candidate_only": True,
    "can_mark_passed_current": False,
    "live_acceptance_mutation_allowed": False,
    "live_oracle_mutation_allowed": False,
    "runtime_evidence": [],
    "network_allowed": False,
    "docker_allowed": False,
    "subprocess_allowed": False,
    "lifecycle_allowed": False,
    "downloads_allowed": False,
    "credentials_allowed": False,
    "file_writes_allowed": False,
}
EXPECTED_DENOMINATOR = {
    "advertised_gap_entries": 87,
    "previously_selected_candidate_entries": 57,
    "prior_open_entries": 30,
    "selected_candidate_entries": 6,
    "entries_left_open": 24,
}

TRANSCODE = (
    "services/vios/src/framework/media/media_pipelines/transcode_writer_consumer.cpp"
)
REMUX = "services/vios/src/framework/media/media_pipelines/remux_writer_consumer.cpp"
GST_UTILS = "services/vios/src/framework/media/media_utils/gst_utils.cpp"
MM_UTILS = "services/vios/src/framework/media/media_utils/mm_utils.cpp"
BYTE_STREAM = "services/vios/src/modules/rtsp_server/H264ByteStreamSource.cpp"
H265_RTP_SOURCE = "services/vios/src/framework/live555/inc/live/liveMedia/include/H265VideoRTPSource.hh"
MEDIA_SERVER = "services/vios/src/modules/rtsp_server/NvMediaServer.cpp"
DYNAMIC_RTSP = "services/vios/src/modules/rtsp_server/DynamicRTSPServer.cpp"
AV_LOOP = "services/vios/src/modules/rtsp_server/AvLoopSyncCoordinator.h"
STORAGE_API = "services/vios/src/modules/storage_management/storage_management_apis.cpp"
VST_CONFIG = "deploy/docker/thor-local/vios/vst_config.json"
CODEC_LOCK = "deploy/docker/thor-local/audio/codec-bundle.lock.json"
DOCKERFILE_VIOS = "deploy/docker/thor-local/Dockerfile.vios-streamprocessing"
DOCKERFILE_NVSTREAMER = "deploy/docker/thor-local/Dockerfile.vios-nvstreamer"
MEDIA_AUDITOR = "deploy/docker/thor-local/vios-codecs/vios_media.py"

EXPECTED_CASE_BINDINGS = {
    "manifest-gap.vios-codecs-audio.00-b-frame-handling": (
        "/features/20/advertised/0",
        "b_frame_contract",
        {TRANSCODE, GST_UTILS, MM_UTILS, MEDIA_AUDITOR},
    ),
    "manifest-gap.vios-codecs-audio.01-hevc-multislice-rfc7798": (
        "/features/20/advertised/1",
        "hevc_multislice_rfc7798_contract",
        {BYTE_STREAM, H265_RTP_SOURCE, MEDIA_SERVER, MEDIA_AUDITOR},
    ),
    "manifest-gap.vios-codecs-audio.02-h-264-h-265": (
        "/features/20/advertised/2",
        "h264_h265_contract",
        {MEDIA_SERVER, GST_UTILS, VST_CONFIG, MEDIA_AUDITOR},
    ),
    "manifest-gap.vios-codecs-audio.03-audio-recording": (
        "/features/20/advertised/3",
        "audio_recording_contract",
        {STORAGE_API, REMUX, TRANSCODE, VST_CONFIG, MEDIA_AUDITOR},
    ),
    "manifest-gap.vios-codecs-audio.04-audio-rtsp-republish": (
        "/features/20/advertised/4",
        "audio_rtsp_republish_contract",
        {DYNAMIC_RTSP, MEDIA_SERVER, AV_LOOP, VST_CONFIG, MEDIA_AUDITOR},
    ),
    "manifest-gap.vios-codecs-audio.05-cpu-multimedia-support": (
        "/features/20/advertised/5",
        "cpu_multimedia_contract",
        {
            GST_UTILS,
            TRANSCODE,
            VST_CONFIG,
            CODEC_LOCK,
            DOCKERFILE_VIOS,
            DOCKERFILE_NVSTREAMER,
            MEDIA_AUDITOR,
        },
    ),
}


class QualificationError(RuntimeError):
    """A digest, schema, denominator, or semantic source contract failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _safe_repo_path(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative_path}")
    path = REPO_ROOT.joinpath(*pure.parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationError(
            f"repository input is unavailable: {relative_path}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(
            f"repository input must be a regular non-symlink: {relative_path}"
        )
    resolved = path.resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise QualificationError(f"repository input escaped root: {relative_path}")
    return path


def _read_bytes(relative_path: str, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    path = _safe_repo_path(relative_path)
    if path.stat().st_size > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    return data


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid JSON schema: {schema_path.name}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {first.message}"
        )


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _verify_sha(path: str, expected: str, label: str) -> bytes:
    raw = _read_bytes(path)
    actual = _sha256(raw)
    if actual != expected:
        raise QualificationError(f"{label} mismatch for {path}: {actual} != {expected}")
    return raw


def _assert_fragments(path: str, fragments: tuple[str, ...]) -> list[str]:
    text = _read_bytes(path).decode("utf-8", errors="strict")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise QualificationError(
            f"semantic source fragment missing in {path}: {missing}"
        )
    return [f"fragment:{path}:{_sha256(fragment.encode())}" for fragment in fragments]


def _assert_ordered(path: str, fragments: tuple[str, ...]) -> list[str]:
    text = _read_bytes(path).decode("utf-8", errors="strict")
    positions: list[int] = []
    cursor = 0
    for fragment in fragments:
        position = text.find(fragment, cursor)
        if position < 0:
            raise QualificationError(
                f"ordered semantic fragment missing in {path}: {fragment!r}"
            )
        positions.append(position)
        cursor = position + len(fragment)
    if positions != sorted(positions):
        raise QualificationError(f"ordered semantic contract failed in {path}")
    return [f"ordered:{path}:{_sha256('|'.join(fragments).encode())}"]


def _vios_config() -> tuple[list[str], dict[str, Any]]:
    document = _strict_json_bytes(_read_bytes(VST_CONFIG), VST_CONFIG)
    data = document.get("data")
    if not isinstance(data, dict):
        raise QualificationError("Thor VIOS config data object is missing")
    expected_video = ["h264", "h265"]
    expected_audio = ["pcmu", "pcma", "mpeg4-generic"]
    if data.get("supported_video_codecs") != expected_video:
        raise QualificationError("Thor VIOS video codec allowlist drifted")
    if data.get("supported_audio_codecs") != expected_audio:
        raise QualificationError("Thor VIOS audio codec allowlist drifted")
    if data.get("use_software_path") is not False:
        raise QualificationError(
            "Thor VIOS default hardware/software-path selector drifted"
        )
    return (
        [
            "config:video-codecs:h264+h265",
            "config:audio-codecs:pcmu+pcma+mpeg4-generic",
            "config:default-use-software-path:false",
        ],
        {
            "supported_video_codecs": expected_video,
            "supported_audio_codecs": expected_audio,
            "default_use_software_path": False,
        },
    )


def _codec_package_contract() -> tuple[list[str], dict[str, Any]]:
    document = _strict_json_bytes(_read_bytes(CODEC_LOCK), CODEC_LOCK)
    packages = document.get("packages")
    if (
        document.get("architecture") != "arm64"
        or document.get("package_count") != 59
        or document.get("package_set_sha256")
        != "c34db3c88287c8c049190bafdc0096d91f70bdf14a3b0ffdcc30c01fbc11f44f"
        or not isinstance(packages, list)
        or len(packages) != 59
    ):
        raise QualificationError("exact 59-package ARM64 codec identity drifted")
    names = [item.get("package") for item in packages if isinstance(item, dict)]
    required = {
        "ffmpeg",
        "gstreamer1.0-libav",
        "gstreamer1.0-plugins-bad",
        "gstreamer1.0-plugins-good",
        "gstreamer1.0-plugins-ugly",
        "libx264-164",
        "libx265-199",
    }
    if len(names) != 59 or len(set(names)) != 59 or not required.issubset(names):
        raise QualificationError("required CPU codec package identities drifted")
    if any(item.get("architecture") != "arm64" for item in packages):
        raise QualificationError("codec lock contains a non-ARM64 package")
    return (
        [
            "codec-lock:architecture:arm64",
            "codec-lock:package-count:59",
            "codec-lock:software-codec-package-set",
        ],
        {
            "architecture": "arm64",
            "package_count": 59,
            "required_packages": sorted(required),
            "package_set_sha256": document["package_set_sha256"],
        },
    )


def _dockerfile_contract(path: str) -> list[str]:
    text = _read_bytes(path).decode("utf-8", errors="strict")
    required = (
        "COPY deploy/docker/thor-local/vios-codecs/bundle/",
        "COPY deploy/docker/thor-local/audio/codec-bundle.lock.json",
        'ENTRYPOINT ["/usr/local/bin/vios-offline-entrypoint"]',
        'com.nvidia.vss.thor.vios-runtime-network-install="disabled"',
    )
    missing = [fragment for fragment in required if fragment not in text]
    if missing:
        raise QualificationError(
            f"offline VIOS Dockerfile contract missing in {path}: {missing}"
        )
    if re.search(r"\b(?:apt|apt-get|curl|wget|pip)\b", text):
        raise QualificationError(f"network/package operation remains in {path}")
    return [f"dockerfile:{path}:{_sha256(fragment.encode())}" for fragment in required]


def _b_frame() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions: list[str] = []
    assertions += _assert_ordered(
        TRANSCODE,
        (
            "bool hasBframes = mCfg.has_bframes;",
            "hasBframes = (stream_row.isBframesPresent_value == 1);",
            "if (GET_CONFIG().enable_dec_low_latency_mode && !hasBframes)",
        ),
    )
    assertions += _assert_fragments(
        GST_UTILS,
        (
            "SliceType slice_type = parseH265SliceType",
            "slice_type == SLICE_TYPE_B || slice_type == SLICE_TYPE_EXT_B",
            "m_videoEncodeParams.m_isBframesPresent = true;",
            '"option-string", "bframes=0:b-adapt=0"',
            '"bframes", (guint)0',
        ),
    )
    assertions += _assert_fragments(
        MM_UTILS, ("SliceType parseH265SliceType", "first_slice_segment_in_pic_flag")
    )
    edges = [
        "H.265 slice header -> stream B-frame state",
        "config/database B-frame state -> decoder low-latency guard",
        "software H.264/H.265 output -> explicit zero-B-frame encoder settings",
    ]
    return (
        assertions,
        edges,
        {
            "detected_codecs": ["h264", "h265"],
            "low_latency_requires_no_bframes": True,
            "software_output_bframes": 0,
        },
    )


def _hevc_multislice() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions: list[str] = []
    assertions += _assert_fragments(
        BYTE_STREAM,
        (
            "bool isContinuationSlice",
            "if (nal_type > 31)",
            "if (content.size() < 3)",
            "return (content[2] & 0x80) == 0;",
            "const bool sameAuAsPrev = isContSlice || sameAuByPt;",
        ),
    )
    assertions += _assert_fragments(
        H265_RTP_SOURCE,
        (
            "Boolean expectDONFields = False",
            "DONL and DOND fields",
            "MultiFramedRTPSource",
        ),
    )
    assertions += _assert_fragments(
        MEDIA_SERVER,
        (
            "H265VideoStreamDiscreteFramer::createNew",
            "H265VideoRTPSink::createNew",
        ),
    )
    edges = [
        "HEVC first_slice_segment_in_pic_flag -> continuation-slice identity",
        "continuation slice/presentation time -> same access-unit pacing",
        "H.265 discrete framer -> RFC7798-capable RTP sink/source contract",
    ]
    return (
        assertions,
        edges,
        {
            "hevc_vcl_nal_range": [0, 31],
            "slice_header_minimum_bytes": 3,
            "don_fields_supported": True,
        },
    )


def _h264_h265() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions, config = _vios_config()
    assertions += _assert_fragments(
        MEDIA_SERVER,
        (
            "H264VideoStreamDiscreteFramer::createNew",
            "H265VideoStreamDiscreteFramer::createNew",
            "H264VideoRTPSink::createNew",
            "H265VideoRTPSink::createNew",
        ),
    )
    assertions += _assert_fragments(
        GST_UTILS,
        (
            'gst_element_factory_make ("h264parse"',
            'gst_element_factory_make ("h265parse"',
            'gst_element_factory_make("x264enc"',
            'gst_element_factory_make("x265enc"',
            'gst_element_factory_make("nvv4l2h264enc"',
            'gst_element_factory_make("nvv4l2h265enc"',
        ),
    )
    edges = [
        "Thor VIOS allowlist -> H.264/H.265 input admission",
        "codec selector -> matching parser and discrete RTSP framer/sink",
        "hardware/software selector -> matching H.264/H.265 encoder",
    ]
    return assertions, edges, config


def _audio_recording() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions, config = _vios_config()
    assertions += _assert_ordered(
        STORAGE_API,
        (
            'CivetServer::getParam(queryString, "disableAudio", disableAudio);',
            'bool isAacPresent = audioEncoding.find("AAC") != string::npos;',
            "video_codec, fullLength, sensor_type, container, transcode, disableAudio,",
        ),
    )
    assertions += _assert_fragments(
        REMUX,
        (
            "RemuxWriter: audio path set up",
            "RemuxWriterConsumer::getAudioConsumer()",
            "std::make_shared<AudioAppSrcConsumer>",
        ),
    )
    assertions += _assert_fragments(
        TRANSCODE,
        (
            'mAudioEncoder = gst_element_factory_make ("avenc_aac"',
            "Audio transcode branch: appsrc -> queue -> decodebin -> audioconvert -> audioresample -> avenc_aac -> mux",
        ),
    )
    edges = [
        "download disableAudio/AAC compatibility -> media-file audio selection",
        "remux audio appsrc/consumer -> output mux",
        "transcode audio appsrc -> AAC encoder -> output mux",
    ]
    return (
        assertions,
        edges,
        {
            "mp4_audio_codec": "AAC",
            "recording_paths": ["remux", "transcode"],
            "config": config,
        },
    )


def _audio_rtsp_republish() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions, config = _vios_config()
    assertions += _assert_ordered(
        DYNAMIC_RTSP,
        (
            'url_params.find("includeAudio=true")',
            "video_session = audio_session = true;",
            "MediaTypeAudio, sourceType, reuseSource, url_params",
            "sms->addSubsession(NvAudioFileServerSms);",
        ),
    )
    assertions += _assert_fragments(
        MEDIA_SERVER,
        (
            "else if (m_mediaType == MediaTypeAudio)",
            "DEFAULT_AUDIO_CODEC_AAC",
        ),
    )
    assertions += _assert_fragments(
        AV_LOOP,
        (
            "keep audio and video",
            '"includeAudio=true"',
            "when BOTH a video and an audio NvFileServerMediaSubsession",
        ),
    )
    edges = [
        "includeAudio=true -> video plus audio RTSP subsessions",
        "MediaTypeAudio -> audio source and RTP sink path",
        "shared AvLoopSyncCoordinator -> aligned audio/video loop boundaries",
    ]
    return (
        assertions,
        edges,
        {
            "selector": "includeAudio=true",
            "media_type": "MediaTypeAudio",
            "av_loop_synchronization": True,
            "config": config,
        },
    )


def _cpu_multimedia() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions, config = _vios_config()
    package_assertions, package_detail = _codec_package_contract()
    assertions += package_assertions
    assertions += _assert_fragments(
        TRANSCODE,
        (
            'gst_element_factory_make(iequals(mCfg.video_codec, "h265") ? "avdec_h265" : "avdec_h264"',
            'iequals(output_video_codec, "h265") ? "x265enc" : "x264enc"',
        ),
    )
    assertions += _assert_fragments(
        GST_UTILS,
        (
            'gst_element_factory_make("x264enc"',
            'gst_element_factory_make("x265enc"',
            'gst_element_factory_make ("h264parse"',
            'gst_element_factory_make ("h265parse"',
        ),
    )
    assertions += _dockerfile_contract(DOCKERFILE_VIOS)
    assertions += _dockerfile_contract(DOCKERFILE_NVSTREAMER)
    edges = [
        "software-path selector -> libav H.264/H.265 decoder",
        "software encoder selector -> x264enc/x265enc",
        "exact ARM64 codec bundle -> networkless immutable VIOS derivatives",
    ]
    return assertions, edges, {"config": config, "package_contract": package_detail}


ADAPTERS: dict[str, Callable[[], tuple[list[str], list[str], dict[str, Any]]]] = {
    "b_frame_contract": _b_frame,
    "hevc_multislice_rfc7798_contract": _hevc_multislice,
    "h264_h265_contract": _h264_h265,
    "audio_recording_contract": _audio_recording,
    "audio_rtsp_republish_contract": _audio_rtsp_republish,
    "cpu_multimedia_contract": _cpu_multimedia,
}


def _load_inventory() -> tuple[dict[str, Any], bytes]:
    raw = INVENTORY_PATH.read_bytes()
    if _sha256(raw) != EXPECTED_INVENTORY_SHA256:
        raise QualificationError("wave-five inventory identity drifted")
    inventory = _strict_json_bytes(raw, INVENTORY_PATH.name)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    if inventory.get("source_plan") != EXPECTED_SOURCE_PLAN:
        raise QualificationError("source plan lock drifted")
    if inventory.get("source_manifest") != EXPECTED_SOURCE_MANIFEST:
        raise QualificationError("source manifest lock drifted")
    if inventory.get("previous_candidate_inventories") != EXPECTED_PREDECESSORS:
        raise QualificationError("predecessor inventory chain drifted")
    if inventory.get("policy") != EXPECTED_POLICY:
        raise QualificationError("candidate-only policy drifted")
    if inventory.get("denominator") != EXPECTED_DENOMINATOR:
        raise QualificationError("87/57/30/6/24 denominator drifted")

    plan_raw = _verify_sha(
        EXPECTED_SOURCE_PLAN["path"],
        EXPECTED_SOURCE_PLAN["raw_sha256"],
        "gap plan lock",
    )
    plan = _strict_json_bytes(plan_raw, EXPECTED_SOURCE_PLAN["path"])
    if plan.get("plan_payload_sha256") != EXPECTED_SOURCE_PLAN["plan_payload_sha256"]:
        raise QualificationError("gap plan payload identity drifted")
    manifest = _strict_json_bytes(
        _verify_sha(
            EXPECTED_SOURCE_MANIFEST["path"],
            EXPECTED_SOURCE_MANIFEST["raw_sha256"],
            "manifest lock",
        ),
        EXPECTED_SOURCE_MANIFEST["path"],
    )

    predecessor_ids: set[str] = set()
    for spec in EXPECTED_PREDECESSORS:
        previous = _strict_json_bytes(
            _verify_sha(spec["path"], spec["raw_sha256"], "predecessor lock"),
            spec["path"],
        )
        ids = {case["entry_id"] for case in previous.get("cases", [])}
        if ids & predecessor_ids:
            raise QualificationError("predecessor inventories overlap")
        predecessor_ids.update(ids)
    if len(predecessor_ids) != 57:
        raise QualificationError(
            f"predecessor union must contain 57 IDs, found {len(predecessor_ids)}"
        )

    cases = inventory.get("cases", [])
    case_ids = {case["entry_id"] for case in cases}
    if len(cases) != 6 or len(case_ids) != 6 or case_ids != set(EXPECTED_CASE_BINDINGS):
        raise QualificationError("inventory must contain six exact unique VIOS cases")
    if predecessor_ids & case_ids:
        raise QualificationError("wave-five cases overlap predecessor inventories")

    plan_by_pointer = {entry["manifest_pointer"]: entry for entry in plan["entries"]}
    for case in cases:
        pointer, adapter_id, sources = EXPECTED_CASE_BINDINGS[case["entry_id"]]
        if case["manifest_pointer"] != pointer or case["adapter_id"] != adapter_id:
            raise QualificationError(f"case binding drifted: {case['entry_id']}")
        if {lock["path"] for lock in case["source_locks"]} != sources:
            raise QualificationError(f"case source set drifted: {case['entry_id']}")
        gap = plan_by_pointer.get(pointer)
        if gap is None:
            raise QualificationError(f"case pointer absent from gap plan: {pointer}")
        expected_fields = {
            "entry_id": gap["entry_id"],
            "proposed_capability_id": gap["proposed_capability"]["id"],
            "advertised": gap["advertised"],
            "advertised_utf8_sha256": gap["advertised_utf8_sha256"],
            "advertised_canonical_sha256": gap["advertised_canonical_sha256"],
        }
        for field, expected in expected_fields.items():
            if case.get(field) != expected:
                raise QualificationError(f"{pointer} differs from gap plan at {field}")
        oracle = gap.get("required_oracle", {})
        if (
            oracle.get("executor_class") != "bounded_vios_codec_audio_probe"
            or oracle.get("type") != "runtime_codec_audio_matrix"
            or oracle.get("status") != "open_unexecuted"
            or oracle.get("runtime_evidence") != []
        ):
            raise QualificationError(f"{pointer} runtime oracle boundary drifted")
        if _resolve_pointer(manifest, pointer) != case["advertised"]:
            raise QualificationError(f"{pointer} differs from manifest literal")
        for lock in case["source_locks"]:
            _verify_sha(lock["path"], lock["sha256"], "source lock")
    return inventory, raw


def execute(selected: list[str] | None = None) -> dict[str, Any]:
    inventory, inventory_raw = _load_inventory()
    cases = inventory["cases"]
    by_id = {case["entry_id"]: case for case in cases}
    selected_ids = selected or [case["entry_id"] for case in cases]
    if len(selected_ids) != len(set(selected_ids)):
        raise QualificationError("duplicate --case selection")
    unknown = sorted(set(selected_ids) - set(by_id))
    if unknown:
        raise QualificationError(f"unknown --case selection: {unknown}")

    results: list[dict[str, Any]] = []
    for entry_id in selected_ids:
        case = by_id[entry_id]
        assertions, edges, detail = ADAPTERS[case["adapter_id"]]()
        source_paths = sorted(lock["path"] for lock in case["source_locks"])
        semantic_output = {
            "contract_scope": "exact-digest-locked-vios-source-and-offline-package-contract-only",
            "contract_edges": edges,
            "semantic_assertions": assertions,
            "matched_source_files": source_paths,
            "bounded_cpp_parsed": sorted(
                path for path in source_paths if re.search(r"\.(?:cpp|h|hh)$", path)
            ),
            "bounded_config_parsed": sorted(
                path for path in source_paths if not re.search(r"\.(?:cpp|h|hh)$", path)
            ),
            "runtime_executed": False,
            "codec_fixture_executed": False,
            "rtsp_session_executed": False,
            "recording_executed": False,
            "cpu_pipeline_executed": False,
            "service_readiness_proven": False,
            "real_file_writes": 0,
            "detail": detail,
        }
        input_payload = {
            "case": case,
            "locked_source_digests": [lock["sha256"] for lock in case["source_locks"]],
        }
        results.append(
            {
                "manifest_pointer": case["manifest_pointer"],
                "entry_id": case["entry_id"],
                "proposed_capability_id": case["proposed_capability_id"],
                "advertised": case["advertised"],
                "evidence_scope": case["evidence_scope"],
                "observation": "observed_match",
                "input_sha256": _sha256(_canonical_bytes(input_payload)),
                "semantic_output_sha256": _sha256(_canonical_bytes(semantic_output)),
                "semantic_output": semantic_output,
                "runtime_evidence": [],
                "official_capability_effect": "none_candidate_only",
            }
        )

    result = {
        "schema_version": 1,
        "mode": inventory["mode"],
        "candidate_only": True,
        "inventory_sha256": _sha256(inventory_raw),
        "denominator": inventory["denominator"],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    try:
        inventory, _ = _load_inventory()
        if args.list:
            if args.cases:
                raise QualificationError("--list cannot be combined with --case")
            for case in inventory["cases"]:
                print(case["entry_id"])
            return 0
        print(json.dumps(execute(args.cases), sort_keys=True, indent=2))
        return 0
    except QualificationError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
