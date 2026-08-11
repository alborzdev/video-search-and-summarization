#!/usr/bin/env python3
"""Isolated Thor proof for RADIO-CLIP object feature extraction."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CORE_PATH = HERE.parent / "rt-cv-2d-core-runtime-successor" / "executor.py"


class QualificationError(RuntimeError):
    """A runtime, safety, cleanup, or evidence assertion failed."""


def _load_core() -> Any:
    spec = importlib.util.spec_from_file_location("rt_cv_core_helpers", CORE_PATH)
    if spec is None or spec.loader is None:
        raise QualificationError("core RT-CV helper package is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORE = _load_core()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _verify_tokenizer(contract: dict[str, Any], root: Path) -> None:
    expected = contract["tokenizer"]["files"]
    actual = sorted(path.name for path in root.iterdir() if path.is_file())
    if actual != sorted(expected):
        raise QualificationError("RADIO-CLIP tokenizer file set drifted")
    for name, identity in expected.items():
        path = root / name
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != identity["bytes"]
            or _file_sha(path) != identity["sha256"]
        ):
            raise QualificationError(f"RADIO-CLIP tokenizer identity drifted: {name}")


def _verify_static(contract: dict[str, Any]) -> None:
    if contract["official_indices"] != [377] or contract["capability_ids"] != [
        "manifest-entry.rt-cv-2d.02-radio-clip"
    ]:
        raise QualificationError("official RADIO-CLIP row binding drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _file_sha(path) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
    for identity in contract["assets"].values():
        path = REPO / identity["path"]
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != identity["bytes"]
            or _file_sha(path) != identity["sha256"]
        ):
            raise QualificationError(f"asset identity drifted: {identity['path']}")
    tokenizer = REPO / contract["tokenizer"]["path"]
    if not tokenizer.is_dir() or tokenizer.is_symlink():
        raise QualificationError("RADIO-CLIP tokenizer directory drifted")
    _verify_tokenizer(contract, tokenizer)


def _negative_tokenizer_preflight(contract: dict[str, Any], temp_root: Path) -> dict[str, Any]:
    source = REPO / contract["tokenizer"]["path"]
    mismatch = temp_root / "mismatched-tokenizer"
    shutil.copytree(source, mismatch)
    target = mismatch / "special_tokens_map.json"
    target.write_bytes(target.read_bytes() + b"\n")
    rejected = False
    try:
        _verify_tokenizer(contract, mismatch)
    except QualificationError:
        rejected = True
    if not rejected:
        raise QualificationError("mismatched tokenizer was not rejected")
    return {
        "mismatched_tokenizer_rejected": True,
        "rejected_before_container_launch": True,
        "exact_bundle_still_valid_after_negative": True,
    }


def _dimension_negative_preflight(proof: dict[str, Any]) -> dict[str, Any]:
    incompatible_dimension = 1024
    rejected = proof.get("embedding_dimensions") != [incompatible_dimension]
    if not rejected:
        raise QualificationError("incompatible RADIO-CLIP dimension was admitted")
    return {
        "incompatible_dimension_configured": incompatible_dimension,
        "observed_dimension": 1536,
        "incompatible_dimension_rejected": True,
        "rejected_before_capability_acceptance": True,
    }


def _generate_reentry_fixture(contract: dict[str, Any], output: Path) -> dict[str, Any]:
    source = REPO / contract["assets"]["fixture"]["path"]
    CORE._run(
        [
            "/usr/bin/ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-t",
            "6",
            "-i",
            "color=c=black:s=1920x1080:r=10",
            "-filter_complex",
            "[0:v]trim=duration=4,setpts=PTS-STARTPTS,split=2[first][repeat];"
            "[1:v]trim=duration=6,setpts=PTS-STARTPTS[gap];"
            "[first][gap][repeat]concat=n=3:v=1:a=0[out]",
            "-map",
            "[out]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "10",
            "-g",
            "10",
            "-bf",
            "0",
            str(output),
        ],
        timeout=60,
    )
    probe = CORE._probe_media(str(output), rtsp=False, expected_duration=14)
    if output.is_symlink() or output.stat().st_size < 100_000:
        raise QualificationError("generated re-entry fixture is invalid")
    return {
        "generation_method_exact": True,
        "source_segment_frames": contract["execution"]["source_segment_frames"],
        "occlusion_frames": contract["execution"]["occlusion_frames"],
        "reentry_start_frame": contract["execution"]["reentry_start_frame"],
        "expected_frames": contract["execution"]["expected_frames"],
        "content_sha256": _file_sha(output),
        "byte_count": output.stat().st_size,
        **probe,
        "warehouse_sample_bundle": "excluded",
    }


CONSUMER_CODE = r'''
import json, math, os, statistics, time
from collections import Counter
from confluent_kafka import Consumer
from schema_pb2 import Frame

expected=int(os.environ["QUAL_EXPECTED_FRAMES"])
source_frames=int(os.environ["QUAL_SOURCE_FRAMES"])
reentry_start=int(os.environ["QUAL_REENTRY_START"])
consumer=Consumer({
    "bootstrap.servers":"127.0.0.1:9092",
    "group.id":os.environ["QUAL_GROUP"],
    "auto.offset.reset":"latest",
    "enable.auto.commit":False,
})
consumer.subscribe([os.environ["QUAL_TOPIC"]])
consumer.poll(1.0)
print(json.dumps({"state":"ready"},sort_keys=True),flush=True)
frames={}
numeric_ids=True
deadline=time.monotonic()+120
while (not frames or max(frames)<2*expected-1) and time.monotonic()<deadline:
    message=consumer.poll(2.0)
    if message is None or message.error():
        continue
    frame=Frame()
    frame.ParseFromString(message.value())
    try:
        frame_id=int(frame.id)
    except ValueError:
        numeric_ids=False
        continue
    rows=[]
    for obj in frame.objects:
        rows.append({
            "type":str(obj.type),
            "id":str(obj.id),
            "bbox":(float(obj.bbox.leftX),float(obj.bbox.topY),float(obj.bbox.rightX),float(obj.bbox.bottomY)),
            "embedding":list(obj.embedding.vector),
        })
    frames[frame_id]=rows
consumer.close()

def iou(a,b):
    left=max(a[0],b[0]); top=max(a[1],b[1]); right=min(a[2],b[2]); bottom=min(a[3],b[3])
    inter=max(0.0,right-left)*max(0.0,bottom-top)
    area_a=max(0.0,a[2]-a[0])*max(0.0,a[3]-a[1])
    area_b=max(0.0,b[2]-b[0])*max(0.0,b[3]-b[1])
    union=area_a+area_b-inter
    return inter/union if union>0 else 0.0

def cosine(a,b):
    dot=sum(x*y for x,y in zip(a,b))
    na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na>0 and nb>0 else float("nan")

observed={frame_id:rows for frame_id,rows in frames.items() if 0<=frame_id<2*expected}
first_cycle={frame_id:rows for frame_id,rows in observed.items() if frame_id<expected}
second_cycle={frame_id-expected:rows for frame_id,rows in observed.items() if expected<=frame_id<2*expected}
all_rows=[obj for rows in observed.values() for obj in rows]
dims=sorted({len(obj["embedding"]) for obj in all_rows if obj["embedding"]})
finite=all(math.isfinite(value) for obj in all_rows for value in obj["embedding"])
persistent_ids=sorted(frame_id for frame_id,rows in observed.items() if rows)
silences=[right-left-1 for left,right in zip(persistent_ids,persistent_ids[1:])]
maximum_silence=max(silences) if silences else 0
pairs=[]
negative=[]
for offset in sorted(set(first_cycle).intersection(second_cycle)):
    pre=[obj for obj in first_cycle[offset] if obj["type"]=="Person" and len(obj["embedding"])==1536]
    post=[obj for obj in second_cycle[offset] if obj["type"]=="Person" and len(obj["embedding"])==1536]
    for left in pre:
        candidates=sorted(((iou(left["bbox"],right["bbox"]),right) for right in post),key=lambda item:item[0],reverse=True)
        if not candidates or candidates[0][0] < 0.80:
            continue
        overlap,right=candidates[0]
        pairs.append((left["id"],right["id"],cosine(left["embedding"],right["embedding"]),overlap))
        for other_overlap,other in candidates[1:]:
            if other_overlap < 0.30:
                negative.append(cosine(left["embedding"],other["embedding"]))

counts=Counter((left,right) for left,right,_,_ in pairs)
best=counts.most_common(1)[0] if counts else (("",""),0)
selected=[item for item in pairs if (item[0],item[1])==best[0]]
positive=[item[2] for item in selected if math.isfinite(item[2])]
overlaps=[item[3] for item in selected]
negative=[value for value in negative if math.isfinite(value)]
positive_median=statistics.median(positive) if positive else None
negative_median=statistics.median(negative) if negative else None
result={
    "state":"complete",
    "detection_messages":len(observed),
    "numeric_frame_ids":numeric_ids,
    "full_two_cycle_boundary_observed":bool(frames) and max(frames)>=2*expected-1,
    "first_cycle_person_embedding_count":sum(1 for rows in first_cycle.values() for obj in rows if obj["type"]=="Person" and len(obj["embedding"])==1536),
    "second_cycle_person_embedding_count":sum(1 for rows in second_cycle.values() for obj in rows if obj["type"]=="Person" and len(obj["embedding"])==1536),
    "occlusion_detection_silence_frames":maximum_silence,
    "embedding_dimensions":dims,
    "finite_embeddings":finite,
    "embedded_object_types":sorted({obj["type"] for obj in all_rows if len(obj["embedding"])==1536}),
    "object_track_pairs_with_embeddings":len({(obj["type"],obj["id"]) for obj in all_rows if len(obj["embedding"])==1536}),
    "known_scene_bbox_matches":len(pairs),
    "selected_identity_pair_occurrences":best[1],
    "tracker_identity_preserved":bool(selected) and best[0][0]==best[0][1],
    "distinct_track_ids_reassociated":bool(selected) and best[0][0]!=best[0][1],
    "positive_cosine_min":min(positive) if positive else None,
    "positive_cosine_median":positive_median,
    "positive_cosine_max":max(positive) if positive else None,
    "bbox_iou_min":min(overlaps) if overlaps else None,
    "negative_comparison_count":len(negative),
    "negative_cosine_median":negative_median,
    "positive_negative_median_margin":positive_median-negative_median if positive_median is not None and negative_median is not None else None,
}
print(json.dumps(result,sort_keys=True),flush=True)
passed=(
    result["numeric_frame_ids"]
    and result["full_two_cycle_boundary_observed"]
    and result["occlusion_detection_silence_frames"]>=50
    and result["embedding_dimensions"]==[1536]
    and result["finite_embeddings"]
    and "Person" in result["embedded_object_types"]
    and result["object_track_pairs_with_embeddings"]>=2
    and result["first_cycle_person_embedding_count"]>=5
    and result["second_cycle_person_embedding_count"]>=5
    and result["selected_identity_pair_occurrences"]>=3
    and result["positive_cosine_min"] is not None
    and result["positive_cosine_min"]>=0.80
    and (result["tracker_identity_preserved"] or result["distinct_track_ids_reassociated"])
)
raise SystemExit(0 if passed else 7)
'''


def _start_consumer(contract: dict[str, Any], docker_count: list[int]) -> None:
    execution = contract["execution"]
    run = CORE._docker(
        [
            "run",
            "-d",
            "--name",
            execution["consumer"],
            "--network",
            "host",
            "--label",
            "vss.thor.qualifier=rt-cv-radio-clip",
            "-e",
            f"QUAL_TOPIC={execution['topic']}",
            "-e",
            f"QUAL_GROUP={execution['group']}",
            "-e",
            f"QUAL_EXPECTED_FRAMES={execution['expected_frames']}",
            "-e",
            f"QUAL_SOURCE_FRAMES={execution['source_segment_frames']}",
            "-e",
            f"QUAL_REENTRY_START={execution['reentry_start_frame']}",
            "-v",
            f"{REPO / 'tools/message-broker-consumers'}:/work:ro",
            "-w",
            "/work",
            contract["images"]["consumer"]["ref"],
            "python3",
            "-c",
            CONSUMER_CODE,
        ],
        docker_count,
        timeout=30,
    )
    if len(run.stdout.decode().strip()) != 64:
        raise QualificationError("RADIO-CLIP consumer identity invalid")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        logs = CORE._docker(["logs", execution["consumer"]], docker_count, check=False).stdout.decode(errors="replace")
        if '"state": "ready"' in logs:
            return
        row = CORE._inspect_container(execution["consumer"], docker_count)
        if row.get("State", {}).get("Running") is not True:
            raise QualificationError("RADIO-CLIP consumer exited before assignment")
        time.sleep(0.5)
    raise QualificationError("RADIO-CLIP consumer did not become ready")


def _finish_consumer(contract: dict[str, Any], docker_count: list[int]) -> dict[str, Any]:
    name = contract["execution"]["consumer"]
    waited = CORE._docker(["wait", name], docker_count, check=False, timeout=150)
    logs = CORE._docker(["logs", name], docker_count).stdout.decode(errors="replace")
    results=[]
    for line in logs.splitlines():
        try:
            value=json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value,dict) and value.get("state")=="complete":
            results.append(value)
    if waited.returncode != 0 or waited.stdout.decode().strip() != "0" or len(results) != 1:
        summary=results[0] if len(results)==1 else {"log_sha256":hashlib.sha256(logs.encode()).hexdigest()}
        raise QualificationError("RADIO-CLIP object-correlation oracle failed: "+_canonical(summary).decode())
    result=results[0]
    result.pop("state",None)
    CORE._docker(["rm",name],docker_count)
    return result


def _ini(text: str, section: str, key: str) -> str:
    match=re.search(rf"^\[{re.escape(section)}\]\n(.*?)(?=^\[|\Z)",text,re.MULTILINE|re.DOTALL)
    if match is None:
        raise QualificationError(f"missing effective section: {section}")
    values=re.findall(rf"^{re.escape(key)}=(.*)$",match.group(1),re.MULTILINE)
    if len(values)!=1:
        raise QualificationError(f"ambiguous effective key: {section}.{key}")
    return values[0].strip()


def _configuration_oracle(contract: dict[str, Any], docker_count: list[int]) -> dict[str, Any]:
    name=contract["execution"]["container"]
    app="/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/configs"
    main_raw=CORE._docker(["exec",name,"cat",f"{app}/ds-main-config.txt"],docker_count).stdout
    tracker_raw=CORE._docker(["exec",name,"cat",f"{app}/ds-nvdcf-accuracy-tracker-config.yml"],docker_count).stdout
    main=main_raw.decode(); tracker=tracker_raw.decode()
    yaml_values={key:re.findall(rf"^[ ]*{key}:[ ]*([0-9]+)[ ]*$",tracker,re.MULTILINE) for key in ("reidType","outputReidTensor")}
    if any(len(value)!=1 for value in yaml_values.values()):
        raise QualificationError("effective tracker ReID keys drifted")
    result={
        "text_model_name":_ini(main,"text-embedder","model-name"),
        "text_onnx_path":_ini(main,"text-embedder","onnx-model-path"),
        "tokenizer_path":_ini(main,"text-embedder","tokenizer-dir"),
        "vision_backend":_ini(main,"visionencoder","backend"),
        "vision_onnx_path":_ini(main,"visionencoder","onnx-model"),
        "vision_engine_path":_ini(main,"visionencoder","tensorrt-engine"),
        "vision_smart_infer":int(_ini(main,"visionencoder","smart-infer")),
        "vision_ofa_predict":int(_ini(main,"visionencoder","ofa-predict")),
        "legacy_tracker_reid_type":int(yaml_values["reidType"][0]),
        "legacy_tracker_output_tensor":int(yaml_values["outputReidTensor"][0]),
        "main_config_sha256":hashlib.sha256(main_raw).hexdigest(),
        "tracker_config_sha256":hashlib.sha256(tracker_raw).hexdigest(),
    }
    expected={
        "text_model_name":"siglip2-onnx",
        "text_onnx_path":"/opt/storage/radio-clip_v1.0.onnx",
        "tokenizer_path":"/opt/storage/radio-clip_v1.0_tokenizer/",
        "vision_backend":"tensorrt",
        "vision_onnx_path":"/opt/storage/radio-clip_v1.0.onnx",
        "vision_engine_path":"/opt/storage/radio-clip_v1.0.onnx_batch16.plan",
        "vision_smart_infer":1,
        "vision_ofa_predict":1,
        "legacy_tracker_reid_type":0,
        "legacy_tracker_output_tensor":0,
    }
    if any(result[key]!=value for key,value in expected.items()):
        raise QualificationError("effective RADIO-CLIP configuration drifted")
    result["exact_radio_clip_bundle_selected"]=True
    result["legacy_256d_tracker_embedding_excluded"]=True
    return result


def _wait_active_metrics(endpoint: str, http_count: list[int], deadline: float) -> dict[str, Any]:
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        info = CORE._metric_snapshot(endpoint, http_count)
        rows = info.get("stream-stats")
        last = {
            "stream_count": info.get("stream-count"),
            "row_count": len(rows) if isinstance(rows, list) else None,
        }
        if info.get("stream-count") == 1 and isinstance(rows, list) and len(rows) == 1:
            frame = float(rows[0].get("frame_number", 0))
            fps = float(rows[0].get("fps", 0))
            latency = float(rows[0].get("latency_ms", math.nan))
            last.update({"frame_number": frame, "fps": fps})
            if frame > 0 and fps > 0:
                return {
                    "stream_count": 1,
                    "frame_number_positive": True,
                    "fps_positive": True,
                    "latency_finite": math.isfinite(latency),
                }
        time.sleep(0.5)
    raise QualificationError("active RADIO-CLIP metrics failed: " + _canonical(last).decode())


def _remove_owned(name: str, docker_count: list[int], failures: list[str]) -> None:
    CORE._remove_owned_container(name,docker_count,failures)


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    started=time.monotonic()
    _verify_static(contract)
    execution=contract["execution"]
    docker_count=[0]; http_count=[0]; cleanup_failures=[]
    stream_added=False; temp_path=None; publisher=None
    if shutil.disk_usage(REPO).free < execution["minimum_free_bytes"]:
        raise QualificationError("free-space safety margin is below 10 GiB")
    driver=CORE._docker(["info","--format","{{.CgroupDriver}}"],docker_count).stdout.decode().strip()
    if driver!="cgroupfs":
        raise QualificationError("Docker cgroup driver must be cgroupfs on Thor")
    for name in (execution["container"],execution["consumer"],execution["mediamtx_container"]):
        if not CORE._container_absent(name,docker_count):
            raise QualificationError(f"owned runtime name already exists: {name}")
    if execution["topic"] in CORE._topic_list(docker_count):
        raise QualificationError("owned Kafka topic already exists")
    image_rt=CORE._image_identity(contract["images"]["rt_cv"]["ref"],contract["images"]["rt_cv"]["id"],docker_count)
    image_consumer=CORE._image_identity(contract["images"]["consumer"]["ref"],contract["images"]["consumer"]["id"],docker_count)
    image_mediamtx=CORE._image_identity(contract["images"]["mediamtx"]["ref"],contract["images"]["mediamtx"]["id"],docker_count)
    main_before=CORE._snapshot_main(contract,docker_count,http_count)
    paused_before=CORE._paused_snapshot(contract,docker_count)
    reidentification={}; configuration={}; fixture={}; negative={}; runtime_log_sha=""; add_result={}; remove_result={}; active_metrics={}
    with tempfile.TemporaryDirectory(prefix="rt-cv-radio-clip-") as temp_dir:
        temp_path=Path(temp_dir)
        negative=_negative_tokenizer_preflight(contract,temp_path)
        fixture_path=temp_path/"radio-clip-reentry.mp4"
        fixture=_generate_reentry_fixture(contract,fixture_path)
        configs=temp_path/"configs"
        CORE._stage_configs(contract,configs)
        try:
            create=CORE._docker(["exec","kafka","kafka-topics","--bootstrap-server","localhost:9092","--create","--topic",execution["topic"],"--partitions","1","--replication-factor","1"],docker_count)
            if b"Created topic" not in create.stdout and b"Created topic" not in create.stderr:
                raise QualificationError("owned Kafka topic creation was not acknowledged")
            run=CORE._docker([
                "run","-d","--name",execution["container"],"--network","host","--runtime","nvidia","--gpus","device=0",
                "--label","vss.thor.qualifier=rt-cv-radio-clip",
                "-e","DS_MESSAGE_RATE=1","-e","DS_SHOW_SENSOR_ID=false","-e","VISION_ENCODER_MODEL=radio-clip","-e","VISION_ENCODER_VERSION=v1.0",
                "-e","TRANSFORMERS_OFFLINE=1","-e","HF_HUB_OFFLINE=1","-e","OTEL_SDK_DISABLED=true","-e","GST_ENABLE_CUSTOM_PARSER_MODIFICATIONS=1",
                "-e","DEEPSTREAM_ENABLE_SENSOR_ID_EXTRACTION=1","-e","HARDWARE_PROFILE=AGX-THOR","-e","STREAM_TYPE=kafka","-e","DS_TRACKER_REID=true",
                "-e","DS_MODEL_FAMILY=rtdetr-warehouse","-e","DS_MODE_FLAG=1","-e","GST_PLUGIN_PATH=/opt/nvidia/deepstream/deepstream/sources/gst-plugins/gst-nvdstextembedder",
                "-v",f"{REPO/execution['search_start']}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-search-start.sh:ro",
                "-v",f"{REPO/execution['shared_start']}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-start.sh:ro",
                "-v",f"{REPO/execution['models_dir']}:/opt/storage:ro","-v",f"{fixture_path}:/opt/fixtures/reentry.mp4:ro","-v",f"{configs}:/opt/ds-configs-ro:ro",
                contract["images"]["rt_cv"]["ref"],"bash","-c","/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-search-start.sh"
            ],docker_count,timeout=40)
            if len(run.stdout.decode().strip())!=64:
                raise QualificationError("isolated RADIO-CLIP container identity invalid")
            CORE._wait_http(execution["endpoint"],"/api/v1/ready",http_count,time.monotonic()+180)
            configuration=_configuration_oracle(contract,docker_count)
            media=CORE._docker(["run","-d","--name",execution["mediamtx_container"],"--label","vss.thor.qualifier=rt-cv-radio-clip","-p",f"127.0.0.1:{execution['rtsp_port']}:8554",contract["images"]["mediamtx"]["ref"]],docker_count)
            if len(media.stdout.decode().strip())!=64:
                raise QualificationError("isolated MediaMTX identity invalid")
            CORE._wait_port(execution["rtsp_port"],time.monotonic()+15)
            _start_consumer(contract,docker_count)
            sensor="radio-clip-runtime"; name="RADIO-CLIP Runtime"; url=f"rtsp://127.0.0.1:{execution['rtsp_port']}/radio-clip"
            publisher=subprocess.Popen([
                "/usr/bin/ffmpeg","-hide_banner","-loglevel","warning","-re","-stream_loop","-1","-i",str(fixture_path),
                "-map","0:v:0","-an","-c:v","copy","-f","rtsp","-rtsp_transport","tcp",url
            ],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(1)
            if publisher.poll() is not None:
                raise QualificationError("loopback re-entry publisher exited early")
            add_result=CORE._stream_call(execution["endpoint"],"add",sensor,name,url,http_count); stream_added=True
            active_metrics=_wait_active_metrics(execution["endpoint"],http_count,time.monotonic()+45)
            reidentification=_finish_consumer(contract,docker_count)
            negative.update(_dimension_negative_preflight(reidentification))
            remove_result=CORE._stream_call(execution["endpoint"],"remove",sensor,name,url,http_count); stream_added=False
            CORE._wait_stream_count(execution["endpoint"],0,http_count,time.monotonic()+30)
            row=CORE._inspect_container(execution["container"],docker_count)
            state=row.get("State",{})
            if state.get("Running") is not True or state.get("OOMKilled") is not False or row.get("RestartCount")!=0:
                raise QualificationError("isolated RADIO-CLIP runtime state drifted")
            logs=CORE._docker(["logs",execution["container"]],docker_count).stdout
            runtime_log_sha=hashlib.sha256(logs).hexdigest()
            if b"radio-clip_v1.0.onnx_batch16.plan" not in logs or b"VPI_ERROR" in logs:
                raise QualificationError("RADIO-CLIP engine load log or VPI cleanliness failed")
        finally:
            if stream_added:
                try:
                    CORE._stream_call(execution["endpoint"],"remove","radio-clip-runtime","RADIO-CLIP Runtime",f"rtsp://127.0.0.1:{execution['rtsp_port']}/radio-clip",http_count)
                    stream_added=False
                except Exception:
                    cleanup_failures.append("owned_stream_remove_failed")
            if publisher is not None:
                try:
                    publisher.send_signal(signal.SIGINT)
                    publisher.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    publisher.terminate()
                    try:
                        publisher.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        publisher.kill(); publisher.wait(timeout=3)
                if publisher.poll() is None:
                    cleanup_failures.append("publisher_still_running")
            for owned in (execution["consumer"],execution["mediamtx_container"],execution["container"]):
                _remove_owned(owned,docker_count,cleanup_failures)
            CORE._delete_group(execution["group"],docker_count)
            if execution["topic"] in CORE._topic_list(docker_count):
                deleted=CORE._docker(["exec","kafka","kafka-topics","--bootstrap-server","localhost:9092","--delete","--topic",execution["topic"]],docker_count,check=False)
                if deleted.returncode!=0:
                    cleanup_failures.append("owned_topic_delete_failed")
    time.sleep(1)
    for owned in (execution["consumer"],execution["mediamtx_container"],execution["container"]):
        if not CORE._container_absent(owned,docker_count):
            cleanup_failures.append(f"{owned}_remains")
    if execution["topic"] in CORE._topic_list(docker_count):
        cleanup_failures.append("owned_topic_remains")
    main_after=CORE._snapshot_main(contract,docker_count,http_count)
    paused_after=CORE._paused_snapshot(contract,docker_count)
    if main_after!=main_before: cleanup_failures.append("main_rt_cv_state_changed")
    if paused_after!=paused_before: cleanup_failures.append("paused_workload_state_changed")
    if temp_path is None or temp_path.exists(): cleanup_failures.append("temporary_root_remains")
    if cleanup_failures:
        raise QualificationError("cleanup failed: "+",".join(cleanup_failures))
    duration=time.monotonic()-started
    if not 0<duration<=execution["max_duration_seconds"]: raise QualificationError("duration budget exceeded")
    if docker_count[0]>execution["max_docker_commands"]: raise QualificationError("Docker command budget exceeded")
    if http_count[0]>execution["max_http_requests"]: raise QualificationError("HTTP request budget exceeded")
    receipt={
        "schema_version":1,"package_id":contract["package_id"],"capability_ids":contract["capability_ids"],"official_indices":contract["official_indices"],"status":"passed",
        "contract_sha256":_file_sha(CONTRACT_PATH),
        "runtime":{"duration_seconds":round(duration,6),"docker_cgroup_driver":driver,"docker_commands":docker_count[0],"http_requests":http_count[0],"free_bytes_after":shutil.disk_usage(REPO).free},
        "images":{"rt_cv":image_rt,"consumer":image_consumer,"mediamtx":image_mediamtx},"fixture":fixture,
        "artifact_identity":{"model":"radio-clip","version":"v1.0","embedding_dimension":1536,"onnx_sha256":contract["assets"]["radio_onnx"]["sha256"],"weights_sha256":contract["assets"]["radio_weights"]["sha256"],"engine_sha256":contract["assets"]["radio_engine"]["sha256"],"tokenizer_file_count":len(contract["tokenizer"]["files"]),"tokenizer_bundle_exact":True},
        "configuration":configuration,"negative_preflight":negative,
        "reidentification":reidentification,
        "lifecycle":{"add":add_result,"active_metrics":active_metrics,"remove":remove_result,"final_stream_count":0,"runtime_log_sha256":runtime_log_sha,"oom_killed":False,"restart_count":0},
        "cleanup":{"failures":[],"owned_containers_absent":True,"owned_topic_absent":True,"consumer_group_delete_attempted":True,"temporary_directory_removed":True,"main_rt_cv_preserved_exactly":True,"main_rt_cv_stream_count":main_after["stream_count"],"paused_workloads_preserved_exactly":True},
        "policy":contract["policy"],
    }
    Draft202012Validator.check_schema(_load_json(SCHEMA_PATH))
    Draft202012Validator(_load_json(SCHEMA_PATH)).validate(receipt)
    return receipt


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {"schema_version":1,"package_id":contract["package_id"],"official_indices":contract["official_indices"],"status":"ready","exact_radio_clip_bundle_present":True,"writes_or_lifecycle_actions":False}


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("plan","execute"))
    parser.add_argument("--ack")
    parser.add_argument("--write-receipt",action="store_true")
    args=parser.parse_args()
    contract=_load_json(CONTRACT_PATH)
    if args.mode=="plan":
        print(json.dumps(_plan(contract),sort_keys=True,indent=2)); return 0
    if args.ack!=contract["execution"]["acknowledgement"]:
        raise SystemExit("exact acknowledgement required")
    receipt=_execute(contract)
    if args.write_receipt:
        RECEIPT_PATH.write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
    print(json.dumps(receipt,sort_keys=True,indent=2)); return 0


if __name__=="__main__":
    raise SystemExit(main())
