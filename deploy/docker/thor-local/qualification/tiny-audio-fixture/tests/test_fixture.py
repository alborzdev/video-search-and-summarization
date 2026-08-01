from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from jsonschema import Draft202012Validator
import pytest

LANE = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "tiny_audio_fixture_test", LANE / "fixture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXTURE = load_module()
FAKE_MEDIA = b"bounded-fake-h264-aac-media"


def fake_probe(size: int = len(FAKE_MEDIA)) -> dict:
    return {
        "format": {
            "duration": "6.000000",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "size": str(size),
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "profile": "Constrained Baseline",
                "width": 320,
                "height": 240,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "10/1",
                "duration": "6.000000",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "profile": "LC",
                "sample_rate": "48000",
                "channels": 1,
                "channel_layout": "mono",
                "duration": "6.000000",
            },
        ],
    }


def install_fake_tools(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def resolve(name: str) -> Path:
        return Path("/usr/bin") / name

    def run(argv, timeout_seconds, pass_fds=()):
        command = list(argv)
        calls.append(
            {
                "argv": command,
                "timeout_seconds": timeout_seconds,
                "pass_fds": tuple(pass_fds),
            }
        )
        if Path(command[0]).name == "ffmpeg":
            Path(command[-1]).write_bytes(FAKE_MEDIA)
            stdout = ""
        else:
            if pass_fds:
                size = os.fstat(pass_fds[0]).st_size
            else:
                size = Path(command[-1]).stat().st_size
            stdout = json.dumps(fake_probe(size))
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(FIXTURE, "_resolve_tool", resolve)
    monkeypatch.setattr(FIXTURE, "_run_command", run)
    return calls


def generate_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls = install_fake_tools(monkeypatch)
    output = tmp_path / "known-speech.mp4"
    receipt = FIXTURE.generate(str(output), FIXTURE.ACKNOWLEDGEMENT)
    receipt_path = output.with_name(output.name + ".receipt.json")
    return output, receipt_path, receipt, calls


def make_fake_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    tool = tmp_path / "ffprobe"
    tool.write_text("#!/usr/bin/python3\n" + body, encoding="utf-8")
    tool.chmod(0o700)
    monkeypatch.setattr(FIXTURE, "TRUSTED_TOOL_ROOTS", (tmp_path.resolve(),))
    monkeypatch.setattr(FIXTURE, "_validate_trusted_tool", lambda _path: None)
    return tool


def test_default_action_is_inert_plan(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        FIXTURE,
        "_resolve_tool",
        lambda _name: pytest.fail("inert plan resolved a binary"),
    )
    monkeypatch.setattr(
        FIXTURE.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("inert plan invoked a subprocess"),
    )
    assert FIXTURE.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "inert_plan"
    assert result["writes"] is False
    assert result["subprocesses"] is False
    assert result["acknowledgement_required"] == FIXTURE.ACKNOWLEDGEMENT


@pytest.mark.parametrize("acknowledgement", ["", "yes", "I_ACKNOWLEDGE"])
def test_generate_requires_exact_acknowledgement(
    tmp_path, monkeypatch, acknowledgement
) -> None:
    monkeypatch.setattr(
        FIXTURE,
        "_resolve_tool",
        lambda _name: pytest.fail("invalid acknowledgement resolved a binary"),
    )
    output = tmp_path / "known-speech.mp4"
    with pytest.raises(FIXTURE.FixtureError, match="exact generation acknowledgement"):
        FIXTURE.generate(str(output), acknowledgement)
    assert list(tmp_path.iterdir()) == []


def test_generate_requires_absolute_safe_outside_repo_output(tmp_path) -> None:
    for output in [
        "relative.mp4",
        str(FIXTURE.REPO_ROOT / "forbidden.mp4"),
        str(tmp_path / "unsafe name.mp4"),
        str(tmp_path / "wrong.mkv"),
    ]:
        with pytest.raises(FIXTURE.FixtureError):
            FIXTURE.generate(output, FIXTURE.ACKNOWLEDGEMENT)


def test_generate_rejects_symlinked_parent_resolving_into_repository(tmp_path) -> None:
    linked_parent = tmp_path / "repo-link"
    linked_parent.symlink_to(FIXTURE.REPO_ROOT, target_is_directory=True)
    with pytest.raises(FIXTURE.FixtureError, match="outside the repository"):
        FIXTURE.generate(str(linked_parent / "forbidden.mp4"), FIXTURE.ACKNOWLEDGEMENT)


def test_generate_never_overwrites_media_or_receipt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        FIXTURE,
        "_resolve_tool",
        lambda _name: pytest.fail("overwrite refusal resolved a binary"),
    )
    output = tmp_path / "known-speech.mp4"
    output.write_bytes(b"operator-owned")
    with pytest.raises(FIXTURE.FixtureError, match="refusing to overwrite"):
        FIXTURE.generate(str(output), FIXTURE.ACKNOWLEDGEMENT)
    assert output.read_bytes() == b"operator-owned"

    output.unlink()
    receipt = output.with_name(output.name + ".receipt.json")
    receipt.write_bytes(b"operator-owned-receipt")
    with pytest.raises(FIXTURE.FixtureError, match="refusing to overwrite"):
        FIXTURE.generate(str(output), FIXTURE.ACKNOWLEDGEMENT)
    assert receipt.read_bytes() == b"operator-owned-receipt"


def test_mocked_generate_emits_strict_bounded_receipt_and_safe_commands(
    tmp_path, monkeypatch
) -> None:
    output, receipt_path, receipt, calls = generate_mocked(tmp_path, monkeypatch)
    schema = json.loads((LANE / "receipt.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(receipt)) == []
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    assert output.read_bytes() == FAKE_MEDIA
    assert receipt["media"]["size_bytes"] == len(FAKE_MEDIA)
    assert receipt["media"]["sha256"] == FIXTURE._sha256_bytes(FAKE_MEDIA)
    assert receipt["phrase"] == {
        "text": FIXTURE.PHRASE,
        "utf8_sha256": FIXTURE._sha256_bytes(FIXTURE.PHRASE.encode("utf-8")),
    }
    assert receipt["capability_gap_ids"] == FIXTURE.CAPABILITY_GAP_IDS
    assert receipt["probe"]["streams"][1]["profile"] == "LC"
    assert receipt["generator"]["receipt_schema_sha256"] == (
        FIXTURE.RECEIPT_SCHEMA_SHA256
    )
    assert set(receipt["generator"]["tool_provenance"]) == {"ffmpeg", "ffprobe"}
    for name, provenance in receipt["generator"]["tool_provenance"].items():
        tool = Path(provenance["path"])
        assert tool.name == name
        assert provenance["sha256"] == FIXTURE._sha256_file(tool)
    assert [Path(call["argv"][0]).name for call in calls] == ["ffmpeg", "ffprobe"]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "known-speech.mp4",
        "known-speech.mp4.receipt.json",
    ]

    ffmpeg = calls[0]["argv"]
    joined = " ".join(ffmpeg)
    assert "color=" in joined
    assert "drawtext=" in joined
    assert "flite=" in joined
    assert (
        "http://" not in joined and "https://" not in joined and "rtsp://" not in joined
    )
    assert "-n" in ffmpeg
    assert ffmpeg[-1].endswith(".partial.mp4")

    assert calls[0]["pass_fds"] == ()
    assert calls[1]["pass_fds"] == ()


def test_failed_ffmpeg_leaves_no_output_or_work_directory(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(FIXTURE, "_resolve_tool", lambda name: Path("/usr/bin") / name)

    def fail(_argv, timeout_seconds, pass_fds=()):
        del timeout_seconds, pass_fds
        raise FIXTURE.FixtureError("ffmpeg failed with 1: expected failure")

    monkeypatch.setattr(FIXTURE, "_run_command", fail)
    with pytest.raises(FIXTURE.FixtureError, match="ffmpeg failed"):
        FIXTURE.generate(str(tmp_path / "known-speech.mp4"), FIXTURE.ACKNOWLEDGEMENT)
    assert list(tmp_path.iterdir()) == []


def test_command_uses_sanitized_environment_literal_argv_and_trusted_root(
    tmp_path, monkeypatch
) -> None:
    tool = make_fake_tool(
        tmp_path,
        monkeypatch,
        "import json, os, sys\n"
        "print(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ), 'cwd': os.getcwd()}))\n",
    )
    literal = "; touch /tmp/never-executed"
    completed = FIXTURE._run_command([str(tool), literal], timeout_seconds=2)
    observed = json.loads(completed.stdout)
    assert observed == {"argv": [literal], "env": FIXTURE.SAFE_ENV, "cwd": "/"}


def test_command_rejects_non_tool_and_untrusted_tool_paths(
    tmp_path, monkeypatch
) -> None:
    with pytest.raises(FIXTURE.FixtureError, match="trusted local"):
        FIXTURE._run_command(["/usr/bin/true"], timeout_seconds=1)

    tool = tmp_path / "ffprobe"
    tool.write_text("#!/usr/bin/python3\n", encoding="utf-8")
    tool.chmod(0o700)
    monkeypatch.setattr(FIXTURE.shutil, "which", lambda *_args, **_kwargs: str(tool))
    with pytest.raises(FIXTURE.FixtureError, match="outside trusted"):
        FIXTURE._resolve_tool("ffprobe")

    monkeypatch.setattr(FIXTURE, "TRUSTED_TOOL_ROOTS", (tmp_path.resolve(),))
    with pytest.raises(FIXTURE.FixtureError, match="root-owned"):
        FIXTURE._validate_trusted_tool(tool.resolve())


def test_command_timeout_kills_and_reaps_process(tmp_path, monkeypatch) -> None:
    tool = make_fake_tool(tmp_path, monkeypatch, "import time\ntime.sleep(10)\n")
    started = time.monotonic()
    with pytest.raises(FIXTURE.FixtureError, match="exceeded .* timeout"):
        FIXTURE._run_command([str(tool)], timeout_seconds=0.1)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    ("stream", "body", "expected"),
    [
        (
            "stdout",
            f"import os\nos.write(1, b'x' * {FIXTURE.MAX_COMMAND_STDOUT_BYTES + 1})\n",
            "stdout exceeded",
        ),
        (
            "stderr",
            f"import os\nos.write(2, b'x' * {FIXTURE.MAX_COMMAND_STDERR_BYTES + 1})\n",
            "stderr exceeded",
        ),
    ],
)
def test_command_output_flood_is_killed_at_hard_capture_limit(
    tmp_path, monkeypatch, stream, body, expected
) -> None:
    del stream
    tool = make_fake_tool(tmp_path, monkeypatch, body)
    with pytest.raises(FIXTURE.FixtureError, match=expected):
        FIXTURE._run_command([str(tool)], timeout_seconds=2)


def test_final_receipt_schema_raw_sha_is_pinned() -> None:
    raw = (LANE / "receipt.schema.json").read_bytes()
    assert FIXTURE._sha256_bytes(raw) == FIXTURE.RECEIPT_SCHEMA_SHA256
    assert FIXTURE._load_schema()["$schema"].endswith("draft/2020-12/schema")


def test_schema_pin_rejects_raw_drift_symlink_and_oversize(
    tmp_path, monkeypatch
) -> None:
    original = (LANE / "receipt.schema.json").read_bytes()

    drifted = tmp_path / "drifted.schema.json"
    drifted.write_bytes(original + b" ")
    monkeypatch.setattr(FIXTURE, "SCHEMA_PATH", drifted)
    with pytest.raises(FIXTURE.FixtureError, match="raw SHA-256 mismatch"):
        FIXTURE._load_schema()

    linked = tmp_path / "linked.schema.json"
    linked.symlink_to(LANE / "receipt.schema.json")
    monkeypatch.setattr(FIXTURE, "SCHEMA_PATH", linked)
    with pytest.raises(FIXTURE.FixtureError, match="cannot open pinned"):
        FIXTURE._load_schema()

    oversized = tmp_path / "oversized.schema.json"
    oversized.write_bytes(b"x" * (FIXTURE.MAX_SCHEMA_BYTES + 1))
    monkeypatch.setattr(FIXTURE, "SCHEMA_PATH", oversized)
    with pytest.raises(FIXTURE.FixtureError, match="schema size"):
        FIXTURE._load_schema()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("{", "invalid JSON"),
        ('{"format": {}, "format": {}, "streams": []}', "duplicate JSON key"),
        ("x" * (FIXTURE.MAX_PROBE_BYTES + 1), "bounded JSON limit"),
    ],
)
def test_probe_rejects_malformed_duplicate_and_oversize_output(
    monkeypatch, payload, expected
) -> None:
    monkeypatch.setattr(
        FIXTURE,
        "_run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["ffprobe"], 0, stdout=payload, stderr=""
        ),
    )
    with pytest.raises(FIXTURE.FixtureError, match=expected):
        FIXTURE._probe(Path("/usr/bin/ffprobe"), "/local.mp4", len(FAKE_MEDIA))


def probe_drift_cases() -> list[dict]:
    cases = []

    extra_stream = fake_probe()
    extra_stream["streams"].append(copy.deepcopy(extra_stream["streams"][0]))
    cases.append(extra_stream)

    for stream_index, key, value in [
        (0, "codec_name", "hevc"),
        (0, "width", 640),
        (0, "pix_fmt", "nv12"),
        (0, "r_frame_rate", "30/1"),
        (1, "codec_name", "opus"),
        (1, "profile", "HE-AAC"),
        (1, "sample_rate", "44100"),
        (1, "channels", 2),
        (1, "channel_layout", "stereo"),
        (1, "index", "invalid"),
    ]:
        drifted = fake_probe()
        drifted["streams"][stream_index][key] = value
        cases.append(drifted)

    duration = fake_probe()
    duration["format"]["duration"] = "30"
    cases.append(duration)

    size = fake_probe()
    size["format"]["size"] = "999"
    cases.append(size)
    return cases


@pytest.mark.parametrize("drifted", probe_drift_cases())
def test_probe_rejects_stream_and_property_drift(drifted) -> None:
    with pytest.raises(FIXTURE.FixtureError):
        FIXTURE._normalize_probe(drifted, len(FAKE_MEDIA))


def test_receipt_schema_rejects_extra_fields_phrase_or_stream_drift(
    tmp_path, monkeypatch
) -> None:
    _output, _receipt_path, receipt, _calls = generate_mocked(tmp_path, monkeypatch)
    Draft202012Validator.check_schema(FIXTURE._load_schema())
    mutations = []

    extra = copy.deepcopy(receipt)
    extra["unexpected"] = True
    mutations.append(extra)

    phrase = copy.deepcopy(receipt)
    phrase["phrase"]["text"] = "different speech"
    mutations.append(phrase)

    codec = copy.deepcopy(receipt)
    codec["probe"]["streams"][1]["codec_name"] = "opus"
    mutations.append(codec)

    profile = copy.deepcopy(receipt)
    profile["probe"]["streams"][1]["profile"] = "HE-AAC"
    mutations.append(profile)

    swapped_tool = copy.deepcopy(receipt)
    swapped_tool["generator"]["tool_provenance"]["ffmpeg"]["path"] = swapped_tool[
        "generator"
    ]["tool_provenance"]["ffprobe"]["path"]
    mutations.append(swapped_tool)

    hash_value = copy.deepcopy(receipt)
    hash_value["media"]["sha256"] = "0" * 64
    # Structurally valid but caught by read-only verification; keep it separate.
    FIXTURE._validate_receipt(hash_value)

    for mutation in mutations:
        with pytest.raises(FIXTURE.FixtureError, match="receipt schema violation"):
            FIXTURE._validate_receipt(mutation)


def test_verify_is_read_only_and_detects_hash_drift(tmp_path, monkeypatch) -> None:
    output, receipt_path, receipt, calls = generate_mocked(tmp_path, monkeypatch)
    original_media = output.read_bytes()
    original_receipt = receipt_path.read_bytes()
    calls.clear()

    result = FIXTURE.verify(str(output), str(receipt_path))
    assert result == {
        "schema_version": 1,
        "mode": "read_only_verify",
        "fixture_id": FIXTURE.FIXTURE_ID,
        "verified": True,
        "media_sha256": receipt["media"]["sha256"],
        "phrase_utf8_sha256": receipt["phrase"]["utf8_sha256"],
        "writes": False,
        "subprocesses": ["ffprobe"],
        "boundary": "fixture integrity only; no VSS runtime capability is qualified",
    }
    assert output.read_bytes() == original_media
    assert receipt_path.read_bytes() == original_receipt
    assert [Path(call["argv"][0]).name for call in calls] == ["ffprobe"]
    assert calls[0]["pass_fds"]
    assert calls[0]["argv"][-1] == f"/proc/self/fd/{calls[0]['pass_fds'][0]}"

    output.write_bytes(b"tampered")
    with pytest.raises(FIXTURE.FixtureError, match="size does not match"):
        FIXTURE.verify(str(output), str(receipt_path))


def test_verify_rejects_symlinks_before_invoking_ffprobe(tmp_path, monkeypatch) -> None:
    output, receipt_path, _receipt, calls = generate_mocked(tmp_path, monkeypatch)
    calls.clear()
    linked = tmp_path / "linked.mp4"
    linked.symlink_to(output)
    with pytest.raises(FIXTURE.FixtureError, match="cannot read media"):
        FIXTURE.verify(str(linked), str(receipt_path))
    assert calls == []


def test_verify_uses_pinned_media_fd_when_path_is_replaced(
    tmp_path, monkeypatch
) -> None:
    output, receipt_path, receipt, _calls = generate_mocked(tmp_path, monkeypatch)
    original = tmp_path / "original-inode.mp4"

    def replace_path(_ffprobe, media_reference, actual_size, pass_fds=()):
        assert media_reference == f"/proc/self/fd/{pass_fds[0]}"
        assert os.fstat(pass_fds[0]).st_size == actual_size
        output.rename(original)
        output.write_bytes(b"replacement-path-content")
        return receipt["probe"]

    monkeypatch.setattr(FIXTURE, "_probe", replace_path)
    with pytest.raises(FIXTURE.FixtureError, match="changed during"):
        FIXTURE.verify(str(output), str(receipt_path))
    assert output.read_bytes() == b"replacement-path-content"
    assert original.read_bytes() == FAKE_MEDIA


def test_verify_rejects_same_inode_content_change_during_probe(
    tmp_path, monkeypatch
) -> None:
    output, receipt_path, receipt, _calls = generate_mocked(tmp_path, monkeypatch)

    def mutate_inode(_ffprobe, _media_reference, _actual_size, pass_fds=()):
        assert pass_fds
        with output.open("r+b") as handle:
            handle.write(b"X")
            handle.flush()
            os.fsync(handle.fileno())
        return receipt["probe"]

    monkeypatch.setattr(FIXTURE, "_probe", mutate_inode)
    with pytest.raises(FIXTURE.FixtureError, match="changed during|content changed"):
        FIXTURE.verify(str(output), str(receipt_path))


def test_media_publication_eexist_race_preserves_competing_file(
    tmp_path, monkeypatch
) -> None:
    install_fake_tools(monkeypatch)
    output = tmp_path / "known-speech.mp4"
    real_link = FIXTURE.os.link

    def collide(source, destination, **kwargs):
        if Path(destination) == output:
            output.write_bytes(b"competing-media")
            raise FileExistsError("simulated EEXIST")
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(FIXTURE.os, "link", collide)
    with pytest.raises(FIXTURE.FixtureError, match="media publication collided"):
        FIXTURE.generate(str(output), FIXTURE.ACKNOWLEDGEMENT)
    assert output.read_bytes() == b"competing-media"
    assert not output.with_name(output.name + ".receipt.json").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name]


def test_first_publication_failure_rolls_back_only_owned_work_directory(
    tmp_path, monkeypatch
) -> None:
    install_fake_tools(monkeypatch)
    output = tmp_path / "known-speech.mp4"

    def fail_link(_source, _destination, **_kwargs):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(FIXTURE.os, "link", fail_link)
    with pytest.raises(FIXTURE.FixtureError, match="media publication failed"):
        FIXTURE.generate(str(output), FIXTURE.ACKNOWLEDGEMENT)
    assert list(tmp_path.iterdir()) == []


def test_receipt_publication_eexist_never_deletes_competitor_or_published_media(
    tmp_path, monkeypatch
) -> None:
    install_fake_tools(monkeypatch)
    output = tmp_path / "known-speech.mp4"
    receipt_path = output.with_name(output.name + ".receipt.json")
    real_link = FIXTURE.os.link
    calls = 0

    def collide(source, destination, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            receipt_path.write_bytes(b"competing-receipt")
            raise FileExistsError("simulated EEXIST")
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(FIXTURE.os, "link", collide)
    with pytest.raises(FIXTURE.FixtureError, match="no unsafe pathname rollback"):
        FIXTURE.generate(str(output), FIXTURE.ACKNOWLEDGEMENT)
    assert output.read_bytes() == FAKE_MEDIA
    assert receipt_path.read_bytes() == b"competing-receipt"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        output.name,
        receipt_path.name,
    ]


@pytest.mark.skipif(
    os.environ.get("VSS_RUN_TINY_AUDIO_FIXTURE_INTEGRATION") != "1",
    reason="set VSS_RUN_TINY_AUDIO_FIXTURE_INTEGRATION=1 for local ffmpeg integration",
)
def test_optional_local_ffmpeg_integration(tmp_path) -> None:
    output = tmp_path / "known-speech-integration.mp4"
    receipt = FIXTURE.generate(str(output), FIXTURE.ACKNOWLEDGEMENT)
    receipt_path = output.with_name(output.name + ".receipt.json")
    verified = FIXTURE.verify(str(output), str(receipt_path))
    assert verified["verified"] is True
    assert receipt["probe"]["streams"][0]["codec_name"] == "h264"
    assert receipt["probe"]["streams"][1]["codec_name"] == "aac"
    assert receipt["probe"]["streams"][1]["profile"] == "LC"
    assert output.stat().st_size <= FIXTURE.MAX_MEDIA_BYTES
