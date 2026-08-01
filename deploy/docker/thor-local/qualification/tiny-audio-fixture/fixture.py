#!/usr/bin/env python3
"""Plan, generate, and verify one bounded known-speech H.264/AAC fixture.

The default action is an inert plan. Generation is acknowledgement-gated and
writes a new media file plus receipt only at an absolute path outside this
repository. Verification reads existing files and invokes ffprobe only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4].resolve(strict=True)
SCHEMA_PATH = LANE / "receipt.schema.json"
RECEIPT_SCHEMA_SHA256 = (
    "11b379f215d54ae6c7fdc42e5680059a69d2b5a41b162d257b313e9ad3f11793"
)

ACKNOWLEDGEMENT = (
    "I_ACKNOWLEDGE_GENERATING_ONE_TINY_AUDIO_FIXTURE_OUTSIDE_THE_REPOSITORY"
)
FIXTURE_ID = "vss-tiny-known-speech-h264-aac-v1"
PHRASE = "Attention operator. The blue crate is ready."
CAPABILITY_GAP_IDS = [
    "manifest-gap.audio-understanding.00-audio-aware-base-workflow",
    "manifest-gap.audio-understanding.01-audio-transcript-per-rt-vlm-chunk",
    "manifest-gap.audio-understanding.02-audio-aware-summarization-and-alerts",
]

WIDTH = 320
HEIGHT = 240
FRAME_RATE = "10/1"
DURATION_SECONDS = 6
SAMPLE_RATE_HZ = 48_000
CHANNELS = 1
MAX_MEDIA_BYTES = 2_000_000
MAX_RECEIPT_BYTES = 65_536
MAX_SCHEMA_BYTES = 65_536
MAX_PROBE_BYTES = 131_072
MAX_COMMAND_STDOUT_BYTES = 131_072
MAX_COMMAND_STDERR_BYTES = 16_384
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
SAFE_ENV = {
    "PATH": SAFE_PATH,
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
}
ALLOWED_TOOLS = {"ffmpeg", "ffprobe"}
TRUSTED_TOOL_ROOTS = tuple(
    dict.fromkeys(Path(item).resolve(strict=True) for item in SAFE_PATH.split(":"))
)


class FixtureError(RuntimeError):
    """The bounded fixture contract was not satisfied."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(64 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _strict_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise FixtureError(f"duplicate JSON key in {label}: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise FixtureError(f"JSON root must be an object in {label}")
    return value


def _load_schema() -> dict[str, Any]:
    try:
        descriptor = os.open(SCHEMA_PATH, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as exc:
        raise FixtureError(f"cannot open pinned receipt schema: {SCHEMA_PATH}") from exc
    try:
        initial = os.fstat(descriptor)
        if not stat.S_ISREG(initial.st_mode):
            raise FixtureError("receipt schema must be a regular non-symlink file")
        if initial.st_size <= 0 or initial.st_size > MAX_SCHEMA_BYTES:
            raise FixtureError("receipt schema size is outside the bounded contract")
        raw = _read_fd_bounded(descriptor, initial, "receipt schema")
        _assert_fd_stable(descriptor, initial, "receipt schema")
    finally:
        os.close(descriptor)
    actual_sha256 = _sha256_bytes(raw)
    if actual_sha256 != RECEIPT_SCHEMA_SHA256:
        raise FixtureError(f"receipt schema raw SHA-256 mismatch: {actual_sha256}")
    schema = _strict_json_bytes(raw, str(SCHEMA_PATH))
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_receipt(receipt: dict[str, Any]) -> None:
    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(receipt), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(item) for item in first.path)
        raise FixtureError(f"receipt schema violation at {location}: {first.message}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_new_output(raw: str) -> tuple[Path, Path]:
    output = Path(raw)
    if not output.is_absolute():
        raise FixtureError("--output must be an absolute path")
    if output.suffix.lower() != ".mp4" or output.name in {"", ".", ".."}:
        raise FixtureError("--output must name an .mp4 file")
    if (
        not output.name[0].isalnum()
        or not output.name.isascii()
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in output.name
        )
    ):
        raise FixtureError(
            "--output filename must use safe ASCII letters, digits, dot, dash, or underscore"
        )
    try:
        parent = output.parent.resolve(strict=True)
    except OSError as exc:
        raise FixtureError("output parent must already exist") from exc
    if not parent.is_dir():
        raise FixtureError("output parent must be a directory")
    output = parent / output.name
    if _is_within(output, REPO_ROOT):
        raise FixtureError("generation output must be outside the repository")
    receipt = output.with_name(output.name + ".receipt.json")
    for path in (output, receipt):
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        raise FixtureError(f"refusing to overwrite existing path: {path}")
    return output, receipt


def _open_read_file(
    raw: str, label: str, max_bytes: int
) -> tuple[Path, int, os.stat_result]:
    path = Path(raw)
    if not path.is_absolute():
        raise FixtureError(f"--{label} must be an absolute path")
    if not hasattr(os, "O_NOFOLLOW"):
        raise FixtureError("O_NOFOLLOW is required for read-only verification")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as exc:
        raise FixtureError(f"cannot read {label}: {path}") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise FixtureError(f"{label} must be a regular non-symlink file")
        if observed.st_size <= 0 or observed.st_size > max_bytes:
            raise FixtureError(f"{label} size is outside the bounded contract")
        return path, descriptor, observed
    except BaseException:
        os.close(descriptor)
        raise


def _stat_identity(observed: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _assert_fd_stable(
    descriptor: int, initial: os.stat_result, label: str
) -> os.stat_result:
    current = os.fstat(descriptor)
    if _stat_identity(current) != _stat_identity(initial):
        raise FixtureError(f"{label} changed during read-only verification")
    return current


def _read_fd_bounded(descriptor: int, observed: os.stat_result, label: str) -> bytes:
    data = os.pread(descriptor, observed.st_size + 1, 0)
    if len(data) != observed.st_size:
        raise FixtureError(f"{label} changed while it was read")
    return data


def _sha256_fd(descriptor: int, observed: os.stat_result, label: str) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < observed.st_size:
        block = os.pread(descriptor, min(64 * 1024, observed.st_size - offset), offset)
        if not block:
            raise FixtureError(f"{label} changed while it was hashed")
        digest.update(block)
        offset += len(block)
    if os.pread(descriptor, 1, observed.st_size):
        raise FixtureError(f"{label} grew while it was hashed")
    return digest.hexdigest()


def _resolve_tool(name: str) -> Path:
    candidate = shutil.which(name, path=SAFE_PATH)
    if candidate is None:
        raise FixtureError(f"required local tool not found in sanitized PATH: {name}")
    resolved = Path(candidate).resolve(strict=True)
    if resolved.name not in ALLOWED_TOOLS or not resolved.is_file():
        raise FixtureError(f"unexpected local tool resolution: {resolved}")
    if not any(_is_within(resolved, root) for root in TRUSTED_TOOL_ROOTS):
        raise FixtureError(f"tool resolved outside trusted sanitized roots: {resolved}")
    _validate_trusted_tool(resolved)
    if not os.access(resolved, os.X_OK):
        raise FixtureError(f"local tool is not executable: {resolved}")
    return resolved


def _validate_trusted_tool(resolved: Path) -> None:
    matching_roots = [root for root in TRUSTED_TOOL_ROOTS if _is_within(resolved, root)]
    if not matching_roots:
        raise FixtureError(f"tool is outside trusted sanitized roots: {resolved}")
    trusted_root = max(matching_roots, key=lambda item: len(item.parts))
    for candidate in (trusted_root, resolved):
        observed = candidate.stat()
        if observed.st_uid != 0 or observed.st_mode & 0o022:
            raise FixtureError(
                f"trusted tool path must be root-owned and not group/world writable: {candidate}"
            )


def _run_command(
    argv: Sequence[str], timeout_seconds: int, pass_fds: Sequence[int] = ()
) -> subprocess.CompletedProcess[str]:
    if not argv:
        raise FixtureError("empty subprocess command")
    executable = Path(argv[0])
    if not executable.is_absolute():
        raise FixtureError("only absolute local ffmpeg/ffprobe commands are allowed")
    try:
        resolved = executable.resolve(strict=True)
    except OSError as exc:
        raise FixtureError(f"cannot resolve local tool: {executable}") from exc
    if resolved.name not in ALLOWED_TOOLS or not any(
        _is_within(resolved, root) for root in TRUSTED_TOOL_ROOTS
    ):
        raise FixtureError("only trusted local ffmpeg/ffprobe commands are allowed")
    _validate_trusted_tool(resolved)
    inherited_fds = tuple(sorted(set(pass_fds)))
    if any(not isinstance(item, int) or item < 0 for item in inherited_fds):
        raise FixtureError("invalid inherited file descriptor")
    command = [str(resolved), *list(argv)[1:]]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(SAFE_ENV),
            cwd="/",
            shell=False,
            close_fds=True,
            pass_fds=inherited_fds,
            start_new_session=True,
        )
    except OSError as exc:
        raise FixtureError(f"failed to start {resolved.name}") from exc
    if process.stdout is None or process.stderr is None:  # pragma: no cover
        process.kill()
        process.wait()
        raise FixtureError("subprocess pipes were not created")

    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {
        "stdout": MAX_COMMAND_STDOUT_BYTES,
        "stderr": MAX_COMMAND_STDERR_BYTES,
    }
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + timeout_seconds
    failure: FixtureError | None = None
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = FixtureError(
                    f"{resolved.name} exceeded {timeout_seconds}s timeout"
                )
                break
            for key, _mask in selector.select(min(remaining, 0.1)):
                label = key.data
                buffer = buffers[label]
                limit = limits[label]
                chunk = os.read(
                    key.fileobj.fileno(), min(65_536, limit - len(buffer) + 1)
                )
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                buffer.extend(chunk)
                if len(buffer) > limit:
                    failure = FixtureError(
                        f"{resolved.name} {label} exceeded {limit}-byte capture limit"
                    )
                    break
            if failure is not None:
                break
    finally:
        selector.close()
        if failure is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
        for stream in (process.stdout, process.stderr):
            if not stream.closed:
                stream.close()
        try:
            returncode = process.wait(timeout=2)
        except subprocess.TimeoutExpired as exc:  # pragma: no cover
            process.kill()
            process.wait()
            raise FixtureError(f"could not reap {resolved.name}") from exc
    if failure is not None:
        raise failure

    stdout = bytes(buffers["stdout"]).decode("utf-8", errors="replace")
    stderr = bytes(buffers["stderr"]).decode("utf-8", errors="replace")
    completed = subprocess.CompletedProcess(command, returncode, stdout, stderr)
    if returncode != 0:
        detail = stderr[-2000:].strip()
        raise FixtureError(f"{resolved.name} failed with {returncode}: {detail}")
    return completed


def _ffmpeg_argv(ffmpeg: Path, output: Path) -> list[str]:
    video_source = f"color=c=0x102030:s={WIDTH}x{HEIGHT}:r=10:d={DURATION_SECONDS}"
    audio_source = f"flite=text='{PHRASE}':voice=slt"
    overlay = (
        "drawtext=text='KNOWN SPEECH AUDIO FIXTURE':fontcolor=white:fontsize=20:"
        "x=(w-text_w)/2:y=(h-text_h)/2"
    )
    return [
        str(ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-protocol_whitelist",
        "file,pipe",
        "-f",
        "lavfi",
        "-i",
        video_source,
        "-f",
        "lavfi",
        "-i",
        audio_source,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        overlay,
        "-af",
        f"apad=whole_dur={DURATION_SECONDS}",
        "-t",
        str(DURATION_SECONDS),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-g",
        "10",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-b:a",
        "64k",
        "-ar",
        str(SAMPLE_RATE_HZ),
        "-ac",
        str(CHANNELS),
        "-movflags",
        "+faststart",
        str(output),
    ]


def _ffprobe_argv(ffprobe: Path, media_reference: str) -> list[str]:
    entries = (
        "format=duration,format_name,size:"
        "stream=index,codec_type,codec_name,profile,width,height,pix_fmt,"
        "r_frame_rate,sample_rate,channels,channel_layout,duration"
    )
    return [
        str(ffprobe),
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-show_entries",
        entries,
        "-of",
        "json",
        media_reference,
    ]


def _duration_ms(value: Any, label: str) -> int:
    try:
        milliseconds = round(float(value) * 1000)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FixtureError(f"invalid {label} duration") from exc
    if not 5_500 <= milliseconds <= 6_100:
        raise FixtureError(f"{label} duration is outside 5.5-6.1 seconds")
    return milliseconds


def _normalize_probe(raw: dict[str, Any], actual_size: int) -> dict[str, Any]:
    format_value = raw.get("format")
    streams = raw.get("streams")
    if not isinstance(format_value, dict) or not isinstance(streams, list):
        raise FixtureError("ffprobe JSON lacks format or streams")
    try:
        reported_size = int(format_value.get("size"))
    except (TypeError, ValueError) as exc:
        raise FixtureError("ffprobe format size is invalid") from exc
    if reported_size != actual_size:
        raise FixtureError("ffprobe size differs from filesystem size")
    format_names = sorted(set(str(format_value.get("format_name", "")).split(",")))
    if "mp4" not in format_names:
        raise FixtureError("fixture is not reported as MP4")
    if len(streams) != 2:
        raise FixtureError(
            "fixture must contain exactly one video and one audio stream"
        )
    by_type: dict[str, dict[str, Any]] = {}
    for item in streams:
        if not isinstance(item, dict):
            raise FixtureError("ffprobe stream record is invalid")
        stream_type = item.get("codec_type")
        if stream_type not in {"video", "audio"} or stream_type in by_type:
            raise FixtureError("fixture must contain unique video and audio streams")
        by_type[stream_type] = item
    if set(by_type) != {"video", "audio"}:
        raise FixtureError("fixture must contain one video and one audio stream")

    video = by_type["video"]
    audio = by_type["audio"]
    if video.get("codec_name") != "h264":
        raise FixtureError("video codec must be H.264")
    if (video.get("width"), video.get("height"), video.get("pix_fmt")) != (
        WIDTH,
        HEIGHT,
        "yuv420p",
    ):
        raise FixtureError(
            "video geometry or pixel format differs from fixture contract"
        )
    try:
        rate = Fraction(str(video.get("r_frame_rate")))
    except (ValueError, ZeroDivisionError) as exc:
        raise FixtureError("video frame rate is invalid") from exc
    if rate != Fraction(10, 1):
        raise FixtureError("video frame rate must be 10 fps")

    if audio.get("codec_name") != "aac":
        raise FixtureError("audio codec must be AAC")
    try:
        sample_rate = int(audio.get("sample_rate"))
        channels = int(audio.get("channels"))
    except (TypeError, ValueError) as exc:
        raise FixtureError("audio sample rate or channel count is invalid") from exc
    if sample_rate != SAMPLE_RATE_HZ or channels != CHANNELS:
        raise FixtureError("audio must be 48 kHz mono")
    video_profile = video.get("profile")
    audio_profile = audio.get("profile")
    channel_layout = audio.get("channel_layout")
    if not isinstance(video_profile, str) or not video_profile:
        raise FixtureError("video profile is absent")
    if audio_profile != "LC":
        raise FixtureError("AAC profile must be exactly LC")
    if channel_layout != "mono":
        raise FixtureError("audio channel layout must be mono")
    try:
        video_index = int(video.get("index"))
        audio_index = int(audio.get("index"))
    except (TypeError, ValueError) as exc:
        raise FixtureError("stream index is invalid") from exc

    return {
        "format_names": format_names,
        "duration_ms": _duration_ms(format_value.get("duration"), "container"),
        "streams": [
            {
                "index": video_index,
                "codec_type": "video",
                "codec_name": "h264",
                "profile": video_profile,
                "width": WIDTH,
                "height": HEIGHT,
                "pix_fmt": "yuv420p",
                "r_frame_rate": FRAME_RATE,
                "duration_ms": _duration_ms(
                    video.get("duration", format_value.get("duration")), "video"
                ),
            },
            {
                "index": audio_index,
                "codec_type": "audio",
                "codec_name": "aac",
                "profile": audio_profile,
                "sample_rate_hz": SAMPLE_RATE_HZ,
                "channels": CHANNELS,
                "channel_layout": channel_layout,
                "duration_ms": _duration_ms(
                    audio.get("duration", format_value.get("duration")), "audio"
                ),
            },
        ],
    }


def _probe(
    ffprobe: Path,
    media_reference: str,
    actual_size: int,
    pass_fds: Sequence[int] = (),
) -> dict[str, Any]:
    completed = _run_command(
        _ffprobe_argv(ffprobe, media_reference),
        timeout_seconds=10,
        pass_fds=pass_fds,
    )
    encoded = completed.stdout.encode("utf-8")
    if len(encoded) > MAX_PROBE_BYTES:
        raise FixtureError("ffprobe output exceeds bounded JSON limit")
    return _normalize_probe(_strict_json_bytes(encoded, "ffprobe output"), actual_size)


def _recipe_sha256() -> str:
    argv = _ffmpeg_argv(Path("/LOCAL_FFMPEG"), Path("/ABSOLUTE_OUTPUT.mp4"))
    payload = json.dumps(argv[1:], ensure_ascii=True, separators=(",", ":")).encode()
    return _sha256_bytes(payload)


def _build_receipt(
    media_name: str,
    media_size: int,
    media_sha256: str,
    probe: dict[str, Any],
    ffmpeg: Path,
    ffprobe: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_id": FIXTURE_ID,
        "purpose": "candidate_input_only",
        "capability_gap_ids": list(CAPABILITY_GAP_IDS),
        "phrase": {
            "text": PHRASE,
            "utf8_sha256": _sha256_bytes(PHRASE.encode("utf-8")),
        },
        "generator": {
            "recipe_sha256": _recipe_sha256(),
            "receipt_schema_sha256": RECEIPT_SCHEMA_SHA256,
            "video_source": "lavfi-color-plus-drawtext",
            "audio_source": "lavfi-flite",
            "tool_provenance": {
                "ffmpeg": {
                    "path": str(ffmpeg),
                    "sha256": _sha256_file(ffmpeg),
                },
                "ffprobe": {
                    "path": str(ffprobe),
                    "sha256": _sha256_file(ffprobe),
                },
            },
        },
        "media": {
            "filename": media_name,
            "sha256": media_sha256,
            "size_bytes": media_size,
            "max_size_bytes": MAX_MEDIA_BYTES,
        },
        "probe": probe,
        "safety": {
            "generated_outside_repository": True,
            "warehouse_data_used": False,
            "network_used": False,
            "docker_used": False,
            "model_loaded": False,
            "subprocesses": ["ffmpeg", "ffprobe"],
        },
    }


def _write_new_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "inert_plan",
        "fixture_id": FIXTURE_ID,
        "writes": False,
        "subprocesses": False,
        "acknowledgement_required": ACKNOWLEDGEMENT,
        "output_requirement": "absolute_new_mp4_path_outside_repository",
        "receipt_suffix": ".receipt.json",
        "maximum_media_bytes": MAX_MEDIA_BYTES,
        "duration_seconds": DURATION_SECONDS,
        "video": "H.264 320x240 yuv420p 10fps",
        "audio": "AAC-LC 48kHz mono generated by lavfi flite",
        "phrase": PHRASE,
        "capability_gap_ids": list(CAPABILITY_GAP_IDS),
        "boundary": "candidate fixture only; no VSS runtime capability is qualified",
    }


def generate(raw_output: str, acknowledgement: str) -> dict[str, Any]:
    if acknowledgement != ACKNOWLEDGEMENT:
        raise FixtureError("exact generation acknowledgement is required")
    output, receipt_path = _validate_new_output(raw_output)
    ffmpeg = _resolve_tool("ffmpeg")
    ffprobe = _resolve_tool("ffprobe")
    work_root = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.work.", dir=str(output.parent))
    )
    partial_media = work_root / "fixture.partial.mp4"
    partial_receipt = work_root / "fixture.receipt.partial.json"
    try:
        _run_command(_ffmpeg_argv(ffmpeg, partial_media), timeout_seconds=30)
        partial_media_stat = partial_media.lstat()
        if not stat.S_ISREG(partial_media_stat.st_mode) or stat.S_ISLNK(
            partial_media_stat.st_mode
        ):
            raise FixtureError("ffmpeg output is not a regular non-symlink file")
        if (
            partial_media_stat.st_size <= 0
            or partial_media_stat.st_size > MAX_MEDIA_BYTES
        ):
            raise FixtureError("generated media size is outside the bounded contract")
        probe = _probe(ffprobe, str(partial_media), partial_media_stat.st_size)
        receipt = _build_receipt(
            output.name,
            partial_media_stat.st_size,
            _sha256_file(partial_media),
            probe,
            ffmpeg,
            ffprobe,
        )
        _validate_receipt(receipt)
        receipt_bytes = (
            json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        if len(receipt_bytes) > MAX_RECEIPT_BYTES:
            raise FixtureError("receipt exceeds bounded JSON limit")
        _write_new_file(partial_receipt, receipt_bytes)

        try:
            os.link(partial_media, output, follow_symlinks=False)
        except FileExistsError as exc:
            raise FixtureError(
                f"media publication collided with existing path: {output}"
            ) from exc
        except OSError as exc:
            raise FixtureError(f"media publication failed: {output}") from exc
        try:
            os.link(partial_receipt, receipt_path, follow_symlinks=False)
        except FileExistsError as exc:
            raise FixtureError(
                "receipt publication collided after media publication; no unsafe pathname "
                f"rollback was attempted at {output}, and the existing receipt was unchanged"
            ) from exc
        except OSError as exc:
            raise FixtureError(
                "receipt publication failed after media publication; no unsafe pathname "
                f"rollback was attempted at {output}"
            ) from exc
        return receipt
    finally:
        partial_media.unlink(missing_ok=True)
        partial_receipt.unlink(missing_ok=True)
        try:
            work_root.rmdir()
        except OSError:
            # Never recursively remove unexpected content from the output parent.
            pass


def verify(raw_media: str, raw_receipt: str) -> dict[str, Any]:
    media, media_fd, media_initial = _open_read_file(
        raw_media, "media", MAX_MEDIA_BYTES
    )
    receipt_path: Path | None = None
    receipt_fd: int | None = None
    try:
        receipt_path, receipt_fd, receipt_initial = _open_read_file(
            raw_receipt, "receipt", MAX_RECEIPT_BYTES
        )
        receipt_bytes = _read_fd_bounded(receipt_fd, receipt_initial, "receipt")
        receipt = _strict_json_bytes(receipt_bytes, str(receipt_path))
        _validate_receipt(receipt)
        if receipt["media"]["filename"] != media.name:
            raise FixtureError(
                "receipt media filename does not match the supplied media"
            )
        if receipt["media"]["size_bytes"] != media_initial.st_size:
            raise FixtureError("receipt media size does not match")
        digest = _sha256_fd(media_fd, media_initial, "media")
        if receipt["media"]["sha256"] != digest:
            raise FixtureError("receipt media SHA-256 does not match")
        ffprobe = _resolve_tool("ffprobe")
        observed_probe = _probe(
            ffprobe,
            f"/proc/self/fd/{media_fd}",
            media_initial.st_size,
            pass_fds=(media_fd,),
        )
        if receipt["probe"] != observed_probe:
            raise FixtureError(
                "receipt stream probe does not match current read-only probe"
            )
        _assert_fd_stable(media_fd, media_initial, "media")
        _assert_fd_stable(receipt_fd, receipt_initial, "receipt")
        if _sha256_fd(media_fd, media_initial, "media") != digest:
            raise FixtureError("media content changed during read-only verification")
        if _read_fd_bounded(receipt_fd, receipt_initial, "receipt") != receipt_bytes:
            raise FixtureError("receipt content changed during read-only verification")
    finally:
        if receipt_fd is not None:
            os.close(receipt_fd)
        os.close(media_fd)
    return {
        "schema_version": 1,
        "mode": "read_only_verify",
        "fixture_id": FIXTURE_ID,
        "verified": True,
        "media_sha256": digest,
        "phrase_utf8_sha256": receipt["phrase"]["utf8_sha256"],
        "writes": False,
        "subprocesses": ["ffprobe"],
        "boundary": "fixture integrity only; no VSS runtime capability is qualified",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan", help="print the inert plan (default)")

    generate_parser = subparsers.add_parser(
        "generate", help="generate one bounded fixture"
    )
    generate_parser.add_argument("--output", required=True)
    generate_parser.add_argument("--acknowledge", required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="read-only receipt/media verification"
    )
    verify_parser.add_argument("--media", required=True)
    verify_parser.add_argument("--receipt", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {None, "plan"}:
            result = plan()
        elif args.command == "generate":
            result = generate(args.output, args.acknowledge)
        elif args.command == "verify":
            result = verify(args.media, args.receipt)
        else:  # pragma: no cover - argparse owns this boundary
            raise FixtureError(f"unknown command: {args.command}")
    except FixtureError as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
