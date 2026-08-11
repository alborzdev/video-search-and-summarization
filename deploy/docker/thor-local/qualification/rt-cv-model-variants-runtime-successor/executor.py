#!/usr/bin/env python3
"""Qualify Warehouse RT-DETR and Smart City RT-DETR/GDINO on Thor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CORE_PACKAGE = HERE.parent / "rt-cv-2d-core-runtime-successor"
CORE_EXECUTOR = CORE_PACKAGE / "executor.py"

SPEC = importlib.util.spec_from_file_location("rt_cv_2d_core_helpers", CORE_EXECUTOR)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load RT-CV core qualification helpers")
core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)
QualificationError = core.QualificationError


def _progress(message: str) -> None:
    print(f"[rt-cv-model-variants] {message}", file=sys.stderr, flush=True)


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON token: {token}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _verify_static(contract: dict[str, Any]) -> None:
    if contract.get("package_id") != "rt-cv-model-variants-runtime-successor":
        raise QualificationError("package identity drifted")
    if contract.get("official_indices") != [376]:
        raise QualificationError("official index binding drifted")
    if contract.get("capability_ids") != [
        "manifest-entry.rt-cv-2d.01-warehouse-and-smart-city-rt-detr-gdino"
    ]:
        raise QualificationError("capability binding drifted")
    if contract.get("policy", {}).get("warehouse_sample_bundle") != "excluded":
        raise QualificationError("Warehouse sample exclusion drifted")
    for lock in contract.get("source_locks", []):
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha_file(path) != lock["sha256"]:
            raise QualificationError(f"locked source drifted: {lock['path']}")
    for asset in contract["assets"].values():
        path = REPO / asset["path"]
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != asset["bytes"]
            or _sha_file(path) != asset["sha256"]
        ):
            raise QualificationError(f"asset identity drifted: {asset['path']}")
    ffmpeg = Path(contract["support"]["ffmpeg_path"])
    if not ffmpeg.is_file() or ffmpeg.is_symlink() or _sha_file(ffmpeg) != contract["support"]["ffmpeg_sha256"]:
        raise QualificationError("host ffmpeg identity drifted")


def _warehouse_evidence() -> dict[str, Any]:
    contract = _load_json(CORE_PACKAGE / "contract.json")
    receipt = _load_json(CORE_PACKAGE / "runtime-receipt.json")
    schema = _load_json(CORE_PACKAGE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda item: list(item.path))
    if errors:
        raise QualificationError("Warehouse RT-DETR source receipt is schema-invalid")
    if (
        receipt.get("status") != "passed"
        or receipt.get("contract_sha256") != _sha_file(CORE_PACKAGE / "contract.json")
        or receipt.get("official_indices") != [375, 380, 381, 382]
    ):
        raise QualificationError("Warehouse RT-DETR source receipt identity drifted")
    file_proof = receipt["file_detection_tracking"]["detection_tracking"]
    rtsp_proof = receipt["rtsp_detection_tracking"]["detection_tracking"]
    detector = contract["assets"]
    if (
        file_proof["frames"] != 8
        or rtsp_proof["frames"] != 8
        or not {"Person", "Pallet"}.issubset(file_proof["types"])
        or not {"Person", "Pallet"}.issubset(rtsp_proof["types"])
    ):
        raise QualificationError("Warehouse RT-DETR source receipt is not substantive")
    return {
        "source_package_id": contract["package_id"],
        "source_receipt_sha256": _sha_file(CORE_PACKAGE / "runtime-receipt.json"),
        "detector_onnx_sha256": detector["detector_onnx"]["sha256"],
        "detector_engine_sha256": detector["detector_engine"]["sha256"],
        "file_frames": file_proof["frames"],
        "file_objects": file_proof["objects"],
        "rtsp_frames": rtsp_proof["frames"],
        "rtsp_objects": rtsp_proof["objects"],
        "class_map_person_and_pallet": True,
        "finite_bboxes_and_confidences": all(
            proof["finite_bboxes"] and proof["finite_confidences"]
            for proof in (file_proof, rtsp_proof)
        ),
        "custom_fixture_only": True,
    }


def _stage_configs(contract: dict[str, Any], destination: Path) -> None:
    shutil.copytree(REPO / contract["execution"]["config_source"], destination)
    main = destination / "run_config-api-rtdetr-protobuf.txt"
    text = main.read_text(encoding="utf-8")
    text = core._replace_section_key(text, "source-list", "http-port", str(contract["execution"]["port"]))
    text = core._replace_section_key(text, "sink1", "enable", "1")
    text = core._replace_section_key(
        text,
        "sink1",
        "msg-broker-conn-str",
        f"localhost;9092;{contract['execution']['topic']}",
    )
    text = core._replace_section_key(text, "sink1", "topic", contract["execution"]["topic"])
    text = core._replace_section_key(text, "tests", "file-loop", "1")
    main.write_text(text, encoding="utf-8")


def _ini(text: str, section: str, key: str) -> str:
    match = re.search(
        rf"^\[{re.escape(section)}\]\n(.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise QualificationError(f"effective section missing: {section}")
    values = re.findall(rf"^{re.escape(key)}=(.*)$", match.group(1), re.MULTILINE)
    if len(values) != 1:
        raise QualificationError(f"effective key ambiguous: {section}.{key}")
    return values[0].strip()


def _configuration_oracle(
    contract: dict[str, Any], variant: str, counter: list[int]
) -> dict[str, Any]:
    name = contract["execution"]["container"]
    app = "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/configs"
    main_raw = core._docker(
        ["exec", name, "cat", f"{app}/run_config-api-rtdetr-protobuf.txt"], counter
    ).stdout
    main = main_raw.decode("utf-8")
    labels_raw = core._docker(
        ["exec", name, "cat", f"{app}/rtdetr-960x544-labels.txt"], counter
    ).stdout
    classmap_raw = core._docker(
        ["exec", name, "cat", f"{app}/coco_classmap.txt"], counter
    ).stdout
    tracker_raw = core._docker(
        [
            "exec",
            name,
            "cat",
            "/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_tracker_NvDCF_accuracy.yml",
        ],
        counter,
    ).stdout
    reid_values = re.findall(
        r"^[ ]*reidType:[ ]*([0-9]+)", tracker_raw.decode(), re.MULTILINE
    )
    if len(reid_values) != 1:
        raise QualificationError("effective tracker ReID mode is ambiguous")
    common = {
        "http_port": int(_ini(main, "source-list", "http-port")),
        "source_batch_size": int(_ini(main, "source-list", "max-batch-size")),
        "streammux_batch_size": int(_ini(main, "streammux", "batch-size")),
        "primary_batch_size": int(_ini(main, "primary-gie", "batch-size")),
        "primary_interval": int(_ini(main, "primary-gie", "interval")),
        "tracker_compute_hw": int(_ini(main, "tracker", "compute-hw")),
        "source_low_latency_mode": int(_ini(main, "source-list", "low-latency-mode")),
        "streammux_extract_sei_sim_time": int(
            _ini(main, "streammux", "extract-sei-sim-time")
        ),
        "streammux_drop_backward_sei": int(
            _ini(main, "streammux", "drop-backward-sei")
        ),
        "tracker_reid_type": int(reid_values[0]),
        "topic_exact": _ini(main, "sink1", "topic") == contract["execution"]["topic"],
        "main_config_sha256": _sha_bytes(main_raw),
        "tracker_config_sha256": _sha_bytes(tracker_raw),
        "rtdetr_labels_sha256": _sha_bytes(labels_raw),
        "coco_classmap_sha256": _sha_bytes(classmap_raw),
    }
    expected_common = {
        "http_port": contract["execution"]["port"],
        "source_batch_size": 1,
        "streammux_batch_size": 1,
        "primary_batch_size": 1,
        "primary_interval": 1,
        "tracker_compute_hw": 2,
        "source_low_latency_mode": 0,
        "tracker_reid_type": 0,
        "topic_exact": True,
    }
    if any(common[key] != value for key, value in expected_common.items()):
        raise QualificationError(f"{variant} common effective configuration drifted")
    if labels_raw.decode().splitlines() != ["background", "bicycle", "car", "person", "road_sign"]:
        raise QualificationError("Smart City RT-DETR label map drifted")
    class_lines = classmap_raw.decode().splitlines()
    if len(class_lines) != 80 or class_lines[0] != "Person" or "Vehicle" not in class_lines:
        raise QualificationError("Smart City COCO class map drifted")

    if variant == "rtdetr":
        infer_raw = core._docker(["exec", name, "cat", f"{app}/rtdetr-960x544.txt"], counter).stdout
        infer = infer_raw.decode("utf-8")
        expected_engine = "/opt/storage/rtdetr-its/model_epoch_035.fp16.onnx_b1_gpu0_fp16.engine"
        if (
            _ini(main, "primary-gie", "config-file") != "rtdetr-960x544.txt"
            or _ini(infer, "property", "onnx-file") != "/opt/storage/rtdetr-its/model_epoch_035.fp16.onnx"
            or _ini(infer, "property", "model-engine-file") != expected_engine
            or int(_ini(infer, "property", "batch-size")) != 1
            or int(_ini(infer, "property", "num-detected-classes")) != 5
            or _ini(infer, "property", "parse-bbox-func-name") != "NvDsInferParseCustomDDETRTAO"
        ):
            raise QualificationError("Smart City RT-DETR detector identity drifted")
        specific = {
            "variant": "smart_city_rtdetr",
            "mode": 7,
            "detector_backend": "nvinfer",
            "model_onnx_sha256": contract["assets"]["smart_city_rtdetr_onnx"]["sha256"],
            "detector_config_sha256": _sha_bytes(infer_raw),
            "declared_class_count": 5,
            "declared_person_class": True,
        }
    else:
        infer_raw = core._docker(
            ["exec", name, "cat", f"{app}/config_triton_nvinferserver_gdino.txt"], counter
        ).stdout
        infer = infer_raw.decode("utf-8")
        primary_config = _ini(main, "primary-gie", "config-file")
        if (
            not primary_config.endswith("/config_triton_nvinferserver_gdino.txt")
            or int(_ini(main, "primary-gie", "plugin-type")) != 1
            or 'model_name: "ensemble_python_gdino"' not in infer
            or "max_batch_size: 1" not in infer
            or 'type_name: "person . ;0.5"' not in infer
        ):
            raise QualificationError("Smart City GDINO detector identity/prompt drifted")
        specific = {
            "variant": "smart_city_gdino",
            "mode": 4,
            "detector_backend": "triton",
            "model_onnx_sha256": contract["assets"]["smart_city_gdino_onnx"]["sha256"],
            "detector_config_sha256": _sha_bytes(infer_raw),
            "prompt_exact": True,
            "prompt_class": "person",
            "prompt_threshold": 0.5,
        }
    return {**common, **specific, "effective_configuration_exact": True}


CONSUMER_CODE = r'''
import json, math, os, time
from collections import Counter
from confluent_kafka import Consumer
from schema_pb2 import Frame

consumer=Consumer({
    "bootstrap.servers":"127.0.0.1:9092",
    "group.id":os.environ["QUAL_GROUP"],
    "auto.offset.reset":"latest",
    "enable.auto.commit":False,
})
consumer.subscribe([os.environ["QUAL_TOPIC"]])
consumer.poll(1.0)
print(json.dumps({"state":"ready"},sort_keys=True),flush=True)
frames=[]
deadline=time.monotonic()+1500
while len(frames)<8 and time.monotonic()<deadline:
    message=consumer.poll(2.0)
    if message is None or message.error():
        continue
    frame=Frame()
    frame.ParseFromString(message.value())
    frames.append(frame)
consumer.close()
objects=[obj for frame in frames for obj in frame.objects]
ids=Counter(str(obj.id) for obj in objects)
types=sorted(set(obj.type for obj in objects))
normalized={value.casefold() for value in types}
result={
    "state":"complete",
    "frames":len(frames),
    "objects":len(objects),
    "minimum_objects_per_frame":min((len(frame.objects) for frame in frames),default=0),
    "maximum_objects_per_frame":max((len(frame.objects) for frame in frames),default=0),
    "types":types,
    "person_class_correlated":"person" in normalized,
    "unique_track_ids":len(ids),
    "repeated_track_ids":sum(1 for count in ids.values() if count>1),
    "finite_bboxes":all(math.isfinite(value) for obj in objects for value in (obj.bbox.leftX,obj.bbox.topY,obj.bbox.rightX,obj.bbox.bottomY)),
    "finite_confidences":all(math.isfinite(obj.confidence) for obj in objects),
    "single_sensor_value":bool(frames) and len(set(frame.sensorId for frame in frames))==1,
    "sensor_value_present":bool(frames) and all(bool(frame.sensorId) for frame in frames),
}
print(json.dumps(result,sort_keys=True),flush=True)
passed=(
    result["frames"]==8
    and result["objects"]>0
    and result["person_class_correlated"]
    and result["repeated_track_ids"]>0
    and result["finite_bboxes"]
    and result["finite_confidences"]
    and result["single_sensor_value"]
    and result["sensor_value_present"]
)
raise SystemExit(0 if passed else 7)
'''


def _start_consumer(
    contract: dict[str, Any], group: str, counter: list[int]
) -> None:
    execution = contract["execution"]
    name = execution["consumer"]
    if not core._container_absent(name, counter):
        raise QualificationError("owned Smart City consumer already exists")
    run = core._docker(
        [
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "host",
            "--label",
            "vss.thor.qualifier=rt-cv-model-variants",
            "-e",
            f"QUAL_TOPIC={execution['topic']}",
            "-e",
            f"QUAL_GROUP={group}",
            "-v",
            f"{REPO / 'tools/message-broker-consumers'}:/work:ro",
            "-w",
            "/work",
            contract["support"]["consumer_image"],
            "python3",
            "-c",
            CONSUMER_CODE,
        ],
        counter,
        timeout=30,
    )
    if len(run.stdout.decode().strip()) != 64:
        raise QualificationError("Smart City consumer identity invalid")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        logs = core._docker(["logs", name], counter, check=False).stdout.decode(errors="replace")
        if '"state": "ready"' in logs:
            return
        row = core._inspect_container(name, counter)
        if row.get("State", {}).get("Running") is not True:
            raise QualificationError("Smart City consumer exited before assignment")
        time.sleep(0.5)
    raise QualificationError("Smart City consumer did not become ready")


def _finish_consumer(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    name = contract["execution"]["consumer"]
    wait = core._docker(["wait", name], counter, check=False, timeout=1520)
    logs = core._docker(["logs", name], counter).stdout.decode(errors="replace")
    results: list[dict[str, Any]] = []
    for line in logs.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("state") == "complete":
            results.append(value)
    if wait.returncode != 0 or wait.stdout.decode().strip() != "0" or len(results) != 1:
        sanitized = results[0] if len(results) == 1 else {"log_sha256": _sha_bytes(logs.encode())}
        raise QualificationError("Smart City detector oracle failed: " + _canonical(sanitized).decode())
    result = results[0]
    if (
        result.get("frames") != 8
        or int(result.get("objects", 0)) <= 0
        or result.get("person_class_correlated") is not True
        or int(result.get("repeated_track_ids", 0)) <= 0
        or not all(
            result.get(key) is True
            for key in (
                "finite_bboxes",
                "finite_confidences",
                "single_sensor_value",
                "sensor_value_present",
            )
        )
    ):
        raise QualificationError("Smart City sanitized detector result drifted")
    core._docker(["rm", name], counter)
    result.pop("state", None)
    return result


def _engine_identity(path: Path, minimum_bytes: int) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size < minimum_bytes:
        raise QualificationError(f"TensorRT engine was not materialized: {path.name}")
    return {
        "byte_count": path.stat().st_size,
        "sha256": _sha_file(path),
        "retained_for_local_reuse": True,
    }


def _wait_engine_materialized(
    path: Path, minimum_bytes: int, container: str, counter: list[int], deadline: float
) -> None:
    next_container_check = 0.0
    while time.monotonic() < deadline:
        if path.is_file() and not path.is_symlink() and path.stat().st_size >= minimum_bytes:
            return
        if time.monotonic() >= next_container_check:
            row = core._inspect_container(container, counter)
            state = row.get("State", {})
            if state.get("Running") is not True or state.get("OOMKilled") is not False:
                raise QualificationError("detector engine builder exited before materialization")
            next_container_check = time.monotonic() + 10
        time.sleep(1)
    raise QualificationError("detector engine did not materialize within the bounded build window")


def _run_lane(
    contract: dict[str, Any],
    variant: str,
    configs: Path,
    runtime_file: Path,
    rtsp_url: str,
    docker_commands: list[int],
    http_requests: list[int],
    cleanup_failures: list[str],
    publisher: subprocess.Popen[bytes],
) -> dict[str, Any]:
    execution = contract["execution"]
    name = execution["container"]
    endpoint = execution["endpoint"]
    model_name = "RTDETR" if variant == "rtdetr" else "GDINO"
    group = execution["rtdetr_group"] if variant == "rtdetr" else execution["gdino_group"]
    engine_relative = execution["rtdetr_engine"] if variant == "rtdetr" else execution["gdino_engine"]
    engine_path = REPO / execution["engines_dir"] / engine_relative
    engine_path.parent.mkdir(parents=True, exist_ok=True)
    engine_was_preexisting = engine_path.is_file()
    stream_added = False
    consumer_started = False
    started_at = ""
    launch_count = 0
    build_trigger_add: dict[str, Any] | None = None
    first_build_runtime_log_sha256: str | None = None
    sensor = f"rtcv-model-variants-{variant}"
    camera_name = f"RTCV Model Variants {variant.upper()}"
    url = rtsp_url

    def launch() -> tuple[str, dict[str, Any]]:
        nonlocal launch_count
        run = core._docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "host",
                "--runtime",
                "nvidia",
                "--gpus",
                "device=0",
                "--entrypoint",
                "/bin/bash",
                "--label",
                "vss.thor.qualifier=rt-cv-model-variants",
                "-e",
                "HARDWARE_PROFILE=AGX-THOR",
                "-e",
                "DS_MODEL_FAMILY=rtdetr-gdino",
                "-e",
                f"MODEL_NAME_2D={model_name}",
                "-e",
                "NUM_SENSORS=1",
                "-e",
                "STREAM_TYPE=kafka",
                "-e",
                "DS_MESSAGE_RATE=1",
                "-e",
                "DS_TRACKER_REID=false",
                "-e",
                "DS_SHOW_SENSOR_ID=true",
                "-e",
                "DS_CONFIG_FILE=/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/configs/run_config-api-rtdetr-protobuf.txt",
                "-e",
                "DEEPSTREAM_ENABLE_SENSOR_ID_EXTRACTION=1",
                "-e",
                "GST_ENABLE_CUSTOM_PARSER_MODIFICATIONS=1",
                "-e",
                "OTEL_SDK_DISABLED=true",
                "-v",
                f"{REPO / execution['shared_start']}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-start.sh:ro",
                "-v",
                f"{REPO / execution['models_dir']}:/opt/storage:ro",
                "-v",
                f"{REPO / execution['models_dir'] / Path('rtdetr-its')}:/opt/storage/rtdetr-its:rw",
                "-v",
                f"{REPO / execution['engines_dir']}:/opt/engines:rw",
                "-v",
                f"{configs}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/mounted-configs:ro",
                "-v",
                f"{runtime_file}:/opt/fixtures/test.mp4:ro",
                contract["images"]["rt_cv"]["ref"],
                "-c",
                "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-start.sh",
            ],
            docker_commands,
            timeout=40,
        )
        if len(run.stdout.decode().strip()) != 64:
            raise QualificationError(f"{variant} qualifier container identity invalid")
        launch_count += 1
        deadline = time.monotonic() + (1500 if variant == "gdino" else 180)
        core._wait_http(endpoint, "/api/v1/ready", http_requests, deadline)
        row = core._inspect_container(name, docker_commands)
        state = row.get("State", {})
        if (
            row.get("Image") != contract["images"]["rt_cv"]["id"]
            or state.get("Running") is not True
            or state.get("OOMKilled") is not False
            or row.get("RestartCount") != 0
        ):
            raise QualificationError(f"{variant} container runtime identity drifted")
        return str(state.get("StartedAt")), _configuration_oracle(
            contract, variant, docker_commands
        )

    try:
        _progress(f"starting isolated Smart City {model_name} lane")
        if variant == "rtdetr" and not engine_was_preexisting:
            _progress("building the one-stream Thor RT-DETR TensorRT engine (bounded to 25 minutes)")
        if variant == "gdino" and not engine_was_preexisting:
            _progress("building the one-stream Thor GDINO TensorRT engine (bounded to 25 minutes)")
        started_at, configuration = launch()
        if variant == "rtdetr" and not engine_was_preexisting:
            build_trigger_add = core._stream_call(
                endpoint,
                "add",
                f"{sensor}-engine-build",
                f"{camera_name} Engine Build",
                url,
                http_requests,
            )
            stream_added = True
            _wait_engine_materialized(
                engine_path,
                50_000_000,
                name,
                docker_commands,
                time.monotonic() + 1500,
            )
            time.sleep(5)
            build_logs = core._docker(
                ["logs", "--since", started_at, name], docker_commands
            ).stdout
            if b"strongly typed network mode" not in build_logs or b"VPI_ERROR" in build_logs:
                raise QualificationError("RT-DETR first-build runtime log oracle failed")
            first_build_runtime_log_sha256 = _sha_bytes(build_logs)
            cleanup_count = len(cleanup_failures)
            core._remove_owned_container(name, docker_commands, cleanup_failures)
            if len(cleanup_failures) != cleanup_count:
                raise QualificationError("RT-DETR first-build container replacement failed")
            stream_added = False
            _progress("RT-DETR engine is cached; launching a fresh inference container")
            started_at, final_configuration = launch()
            if final_configuration != configuration:
                raise QualificationError("RT-DETR configuration drifted across first-build replacement")
            configuration = final_configuration

        _progress(f"Smart City {model_name} service is ready; starting custom-data inference")
        if publisher.poll() is not None:
            raise QualificationError("model-variants RTSP publisher exited before inference")
        _start_consumer(contract, group, docker_commands)
        consumer_started = True
        add = core._stream_call(endpoint, "add", sensor, camera_name, url, http_requests)
        stream_added = True
        metrics = core._wait_active_metrics(endpoint, http_requests, time.monotonic() + 180)
        detection = _finish_consumer(contract, docker_commands)
        consumer_started = False
        if publisher.poll() is not None:
            raise QualificationError("model-variants RTSP publisher exited during inference")
        remove = core._stream_call(endpoint, "remove", sensor, camera_name, url, http_requests)
        stream_added = False
        core._wait_stream_count(endpoint, 0, http_requests, time.monotonic() + 60)
        engine = _engine_identity(engine_path, 50_000_000)
        logs = core._docker(["logs", "--since", started_at, name], docker_commands).stdout
        expected_mode = b" -m 7 " if variant == "rtdetr" else b" -m 4 "
        if expected_mode not in logs or b"VPI_ERROR" in logs:
            raise QualificationError(f"{variant} runtime log oracle failed")
        _progress(f"Smart City {model_name} custom-data detection/tracking passed")
        return {
            "configuration": configuration,
            "engine": engine,
            "build_trigger_add": build_trigger_add,
            "first_build_container_replaced": build_trigger_add is not None,
            "first_build_runtime_log_sha256": first_build_runtime_log_sha256,
            "container_launch_count": launch_count,
            "add": add,
            "add_attempt_count": 2 if build_trigger_add is not None else 1,
            "active_metrics": metrics,
            "detection_tracking": detection,
            "remove": remove,
            "runtime_log_sha256": _sha_bytes(logs),
            "oom_killed": False,
            "restart_count": 0,
            "final_stream_count": 0,
        }
    finally:
        if stream_added:
            try:
                core._stream_call(
                    endpoint,
                    "remove",
                    sensor,
                    camera_name,
                    url,
                    http_requests,
                )
            except QualificationError:
                cleanup_failures.append(f"{variant}_stream_remove_failed")
        if consumer_started:
            core._remove_owned_container(execution["consumer"], docker_commands, cleanup_failures)
        core._remove_owned_container(name, docker_commands, cleanup_failures)


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    _verify_static(contract)
    execution = contract["execution"]
    docker_commands = [0]
    http_requests = [0]
    cleanup_failures: list[str] = []
    topic_created = False
    publisher: subprocess.Popen[bytes] | None = None
    publisher_terminated = False
    engine_root = REPO / execution["engines_dir"]
    engine_root.mkdir(parents=True, exist_ok=True)
    engine_paths = [engine_root / execution["rtdetr_engine"], engine_root / execution["gdino_engine"]]
    engine_preexisting = {path: path.is_file() for path in engine_paths}
    run_passed = False

    if shutil.disk_usage(REPO).free < execution["minimum_free_bytes"]:
        raise QualificationError("free-space safety margin is below 10 GiB")
    driver = core._docker(["info", "--format", "{{.CgroupDriver}}"], docker_commands).stdout.decode().strip()
    if driver != "cgroupfs":
        raise QualificationError("Docker cgroup driver must be cgroupfs on Thor")
    for name in (
        execution["container"],
        execution["consumer"],
        execution["mediamtx_container"],
    ):
        if not core._container_absent(name, docker_commands):
            raise QualificationError(f"owned qualifier container already exists: {name}")
    rt_cv_image = core._image_identity(
        contract["images"]["rt_cv"]["ref"], contract["images"]["rt_cv"]["id"], docker_commands
    )
    consumer_image = core._image_identity(
        contract["images"]["consumer"]["ref"], contract["images"]["consumer"]["id"], docker_commands
    )
    mediamtx_image = core._image_identity(
        contract["images"]["mediamtx"]["ref"],
        contract["images"]["mediamtx"]["id"],
        docker_commands,
    )
    main_before = core._snapshot_main(contract, docker_commands, http_requests)
    if main_before["stream_count"] != 0:
        raise QualificationError("main RT-CV must have zero streams for isolated proof")
    paused_before = core._paused_snapshot(contract, docker_commands)
    topics_before = core._topic_list(docker_commands)
    if execution["topic"] in topics_before:
        raise QualificationError("owned qualifier topic already exists")
    warehouse = _warehouse_evidence()
    _progress("validated the source-locked Warehouse RT-DETR runtime receipt")
    rtdetr: dict[str, Any] = {}
    gdino: dict[str, Any] = {}
    runtime_probe: dict[str, Any] = {}
    rtsp_probe: dict[str, Any] = {}
    mediamtx_transport: dict[str, bool] = {}
    runtime_bytes = b""

    try:
        create = core._docker(
            [
                "exec",
                "kafka",
                "kafka-topics",
                "--bootstrap-server",
                "localhost:9092",
                "--create",
                "--topic",
                execution["topic"],
                "--partitions",
                "1",
                "--replication-factor",
                "1",
            ],
            docker_commands,
        )
        if b"Created topic" not in create.stdout and b"Created topic" not in create.stderr:
            raise QualificationError("qualifier Kafka topic creation was not acknowledged")
        topic_created = True
        with tempfile.TemporaryDirectory(prefix="rt-cv-model-variants-") as temp_dir:
            temp = Path(temp_dir)
            configs = temp / "configs"
            _stage_configs(contract, configs)
            runtime_file = temp / "custom-runtime.mp4"
            runtime_bytes = core._generate_runtime_file(contract, runtime_file)
            runtime_probe = core._probe_media(
                str(runtime_file),
                rtsp=False,
                expected_duration=execution["runtime_file_duration_seconds"],
            )
            mediamtx = core._docker(
                [
                    "run",
                    "-d",
                    "--name",
                    execution["mediamtx_container"],
                    "--network",
                    "host",
                    "--label",
                    "vss.thor.qualifier=rt-cv-model-variants",
                    "-e",
                    f"MTX_RTSPADDRESS=127.0.0.1:{execution['rtsp_port']}",
                    "-e",
                    f"MTX_RTPADDRESS=127.0.0.1:{execution['rtp_port']}",
                    "-e",
                    f"MTX_RTCPADDRESS=127.0.0.1:{execution['rtcp_port']}",
                    "-e",
                    "MTX_RTMP=no",
                    "-e",
                    "MTX_HLS=no",
                    "-e",
                    "MTX_WEBRTC=no",
                    "-e",
                    "MTX_SRT=no",
                    "-e",
                    "MTX_MOQ=no",
                    contract["images"]["mediamtx"]["ref"],
                ],
                docker_commands,
            )
            if len(mediamtx.stdout.decode().strip()) != 64:
                raise QualificationError("model-variants MediaMTX identity invalid")
            core._wait_port(execution["rtsp_port"], time.monotonic() + 15)
            expected_listener = (
                f"127.0.0.1:{execution['rtp_port']} (UDP/RTP), "
                f"127.0.0.1:{execution['rtcp_port']} (UDP/RTCP)"
            ).encode()
            mediamtx_logs = b""
            listener_deadline = time.monotonic() + 5
            while expected_listener not in mediamtx_logs:
                log_result = core._docker(
                    ["logs", execution["mediamtx_container"]], docker_commands
                )
                mediamtx_logs = log_result.stdout + log_result.stderr
                if time.monotonic() >= listener_deadline:
                    break
                time.sleep(0.2)
            if expected_listener not in mediamtx_logs:
                raise QualificationError("MediaMTX dedicated RTP/RTCP listeners drifted")
            mediamtx_row = core._inspect_container(
                execution["mediamtx_container"], docker_commands
            )
            mediamtx_transport = {
                "host_network": mediamtx_row.get("HostConfig", {}).get("NetworkMode")
                == "host",
                "rtp_listener": expected_listener in mediamtx_logs,
                "rtcp_listener": expected_listener in mediamtx_logs,
                "server_ports_exact": expected_listener in mediamtx_logs,
            }
            if not all(mediamtx_transport.values()):
                raise QualificationError("MediaMTX UDP transport mapping drifted")
            rtsp_url = (
                f"rtsp://127.0.0.1:{execution['rtsp_port']}/rtcv-model-variants"
            )
            publisher = subprocess.Popen(
                [
                    contract["support"]["ffmpeg_path"],
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-re",
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(REPO / contract["assets"]["fixture"]["path"]),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-c:v",
                    "copy",
                    "-f",
                    "rtsp",
                    "-rtsp_transport",
                    "tcp",
                    rtsp_url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
            if publisher.poll() is not None:
                raise QualificationError("model-variants RTSP publisher exited early")
            probe_deadline = time.monotonic() + 15
            while True:
                try:
                    rtsp_probe = core._probe_media(rtsp_url, rtsp=True)
                    break
                except QualificationError:
                    if time.monotonic() >= probe_deadline:
                        raise
                    time.sleep(1)
            _progress("generated the bounded fixture and verified the paced loopback RTSP source")
            rtdetr = _run_lane(
                contract,
                "rtdetr",
                configs,
                runtime_file,
                rtsp_url,
                docker_commands,
                http_requests,
                cleanup_failures,
                publisher,
            )
            gdino = _run_lane(
                contract,
                "gdino",
                configs,
                runtime_file,
                rtsp_url,
                docker_commands,
                http_requests,
                cleanup_failures,
                publisher,
            )
        run_passed = True
    finally:
        core._remove_owned_container(execution["consumer"], docker_commands, cleanup_failures)
        core._remove_owned_container(execution["container"], docker_commands, cleanup_failures)
        if publisher is not None:
            publisher.terminate()
            try:
                publisher.wait(timeout=10)
            except subprocess.TimeoutExpired:
                publisher.kill()
                publisher.wait(timeout=5)
            publisher_terminated = publisher.poll() is not None
            if not publisher_terminated:
                cleanup_failures.append("rtsp_publisher_termination_failed")
        core._remove_owned_container(
            execution["mediamtx_container"], docker_commands, cleanup_failures
        )
        for group in (execution["rtdetr_group"], execution["gdino_group"]):
            core._delete_group(group, docker_commands)
        if topic_created:
            deleted = core._docker(
                [
                    "exec",
                    "kafka",
                    "kafka-topics",
                    "--bootstrap-server",
                    "localhost:9092",
                    "--delete",
                    "--topic",
                    execution["topic"],
                ],
                docker_commands,
                check=False,
            )
            if deleted.returncode != 0:
                cleanup_failures.append("topic_delete_failed")
        if not run_passed:
            for path in engine_paths:
                if (
                    not engine_preexisting[path]
                    and path.exists()
                    and (
                        path.is_symlink()
                        or not path.is_file()
                        or path.stat().st_size < 50_000_000
                    )
                ):
                    try:
                        path.unlink()
                    except OSError:
                        cleanup_failures.append(f"new_engine_cleanup_failed_{path.name}")

    deadline = time.monotonic() + 30
    while execution["topic"] in core._topic_list(docker_commands) and time.monotonic() < deadline:
        time.sleep(0.5)
    topic_absent = execution["topic"] not in core._topic_list(docker_commands)
    owned_absent = all(
        core._container_absent(name, docker_commands)
        for name in (
            execution["container"],
            execution["consumer"],
            execution["mediamtx_container"],
        )
    )
    time.sleep(1)
    main_after = core._snapshot_main(contract, docker_commands, http_requests)
    paused_after = core._paused_snapshot(contract, docker_commands)
    if cleanup_failures or not topic_absent or not owned_absent:
        raise QualificationError(f"exact qualifier cleanup failed: {cleanup_failures}")
    if main_after != main_before:
        raise QualificationError("main RT-CV snapshot changed during isolated proof")
    if paused_after != paused_before:
        raise QualificationError("paused workload state changed during isolated proof")
    free_after = shutil.disk_usage(REPO).free
    if free_after < execution["minimum_free_bytes"]:
        raise QualificationError("engine cache violated the 10 GiB free-space floor")
    duration = time.monotonic() - started
    if duration > execution["max_duration_seconds"]:
        raise QualificationError("runtime duration budget exceeded")
    if docker_commands[0] > execution["max_docker_commands"]:
        raise QualificationError("Docker command budget exceeded")
    if http_requests[0] > execution["max_http_requests"]:
        raise QualificationError("HTTP request budget exceeded")
    _verify_static(contract)

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha_file(CONTRACT_PATH),
        "runtime": {
            "duration_seconds": duration,
            "docker_cgroup_driver": driver,
            "docker_commands": docker_commands[0],
            "http_requests": http_requests[0],
            "free_bytes_after": free_after,
        },
        "images": {
            "rt_cv": rt_cv_image,
            "consumer": consumer_image,
            "mediamtx": mediamtx_image,
        },
        "fixture": {
            "generation_method_exact": True,
            "source_repetitions": execution["runtime_file_repetitions"],
            "content_sha256": _sha_bytes(runtime_bytes),
            "byte_count": len(runtime_bytes),
            **runtime_probe,
            "loopback_rtsp_codec_h264": rtsp_probe.get("codec_h264") is True,
            "loopback_rtsp_tcp_probe_passed": rtsp_probe.get("tcp_probe_passed") is True,
            "loopback_rtsp_publisher_running_during_inference": True,
            "loopback_rtsp_source_is_locked_fixture": True,
            "loopback_dynamic_source_host_network": mediamtx_transport.get("host_network") is True,
            "loopback_dynamic_source_udp_rtp_listener": mediamtx_transport.get("rtp_listener") is True,
            "loopback_dynamic_source_udp_rtcp_listener": mediamtx_transport.get("rtcp_listener") is True,
            "loopback_dynamic_source_server_ports_exact": mediamtx_transport.get("server_ports_exact") is True,
            "warehouse_sample_bundle": "excluded",
        },
        "warehouse_rtdetr": warehouse,
        "smart_city_rtdetr": rtdetr,
        "smart_city_gdino": gdino,
        "model_family_separation": {
            "three_distinct_detector_identities": True,
            "warehouse_rtdetr_not_substituted_for_smart_city": True,
            "smart_city_rtdetr_not_substituted_for_gdino": True,
            "separate_class_map_semantics_recorded": True,
        },
        "cleanup": {
            "failures": cleanup_failures,
            "owned_containers_absent": owned_absent,
            "owned_topic_absent": topic_absent,
            "consumer_groups_delete_attempted": True,
            "temporary_directory_removed": True,
            "main_rt_cv_preserved_exactly": main_after == main_before,
            "main_rt_cv_stream_count": main_after["stream_count"],
            "paused_workloads_preserved_exactly": paused_after == paused_before,
            "engine_cache_retained_for_local_reuse": True,
            "rtsp_publisher_terminated": publisher_terminated,
        },
        "policy": contract["policy"],
    }


def _validate_receipt(receipt: dict[str, Any]) -> None:
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda item: list(item.path))
    if errors:
        raise QualificationError(f"receipt schema validation failed: {errors[0].message}")
    raw = json.dumps(receipt, sort_keys=True)
    if re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", raw, re.I):
        raise QualificationError("receipt retained a raw request UUID")
    if "rtsp://" in raw or "file:///" in raw or "nvapi-" in raw:
        raise QualificationError("receipt retained a forbidden URL or credential")


def _write_receipt(receipt: dict[str, Any]) -> None:
    rendered = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=HERE, prefix=".runtime-receipt.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, RECEIPT_PATH)


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    execution = contract["execution"]
    free = shutil.disk_usage(REPO).free
    engines = {
        key: (REPO / execution["engines_dir"] / execution[key]).is_file()
        for key in ("rtdetr_engine", "gdino_engine")
    }
    blockers: list[str] = []
    if free < execution["minimum_free_bytes"]:
        blockers.append("free_space_below_10_gib")
    if any(
        not core._container_absent(name, [0])
        for name in (
            execution["container"],
            execution["consumer"],
            execution["mediamtx_container"],
        )
    ):
        blockers.append("owned_qualifier_container_exists")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "cached_source_models_exact": True,
        "engine_cache": engines,
        "free_bytes": free,
        "minimum_free_bytes": execution["minimum_free_bytes"],
        "writes_or_lifecycle_actions": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "execute"))
    parser.add_argument("--ack", default="")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)
    try:
        contract = _load_json(CONTRACT_PATH)
        if args.mode == "plan":
            print(json.dumps(_plan(contract), indent=2, sort_keys=True))
            return 0
        if args.ack != contract["execution"]["acknowledgement"]:
            raise QualificationError("exact runtime acknowledgement is required")
        receipt = _execute(contract)
        _validate_receipt(receipt)
        if args.write_receipt:
            _write_receipt(receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
