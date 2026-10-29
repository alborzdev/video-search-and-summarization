# SPDX-License-Identifier: Apache-2.0
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "identical_calibration",
    Path(__file__).parents[1] / "isaac_identical_calibration.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(tmp_path):
    camera = {
        "width": 960,
        "height": 540,
        "K": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "imageToGroundHomography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "classGroundPlaneWorldZM": {"person": 0.1},
        "validGroundPolygon": [[0, 0], [1, 0], [1, 1]],
    }
    before = {
        "schemaVersion": "city.isaac-camera-export.v1",
        "stage": "/scene/old.usda",
        "calibrationRevision": "old",
        "cameraOrder": list(m.CAMERAS),
        "cameras": {name: deepcopy(camera) for name in m.CAMERAS},
        "map": {"bounds": [-50, -50, 50, 50], "roads": [], "buildings": []},
        "groundWorldZM": 0,
        "navigationWorldZM": 0.1,
        "crosswalks": [{"id": "x", "points": [1, 2]}],
        "qualification": "Unchanged simulator algebraic geometry",
    }
    candidate = {
        **deepcopy(before),
        "stage": "/scene/new.usda",
        "calibrationRevision": "new",
    }
    registration = {
        name: {"id": source, "name": name}
        for name, source in zip(m.CAMERAS, ("sw", "ne"))
    }
    sources = [
        {
            **deepcopy(camera),
            "id": source,
            "name": name,
            "calibrationRevision": "old",
            "vssSensorId": source,
            "inputUri": "rtsp://local/" + source,
            "kind": "live",
            "processedPreview": {"dynamic": "stale"},
        }
        for name, source in zip(m.CAMERAS, ("sw", "ne"))
    ]
    site = {
        "id": "isaac-intersection-a",
        "mode": "live",
        "revision": 20,
        "sources": sources,
        "map": deepcopy(before["map"]),
        "groundWorldZM": 0.0,
        "fusion": {"enabled": False, "preserve": "operator choice"},
    }
    rules = {
        "revision": 30,
        "rules": [
            {
                "id": f"rule-{i}",
                "sourceId": ("sw", "ne")[i % 2],
                "calibrationRevision": "old",
                "enabled": i != 5,
                "revision": 30,
                "conditions": {"minimumDurationMs": 1777},
                "geometry": {"points": [[0.1, 0.2], [0.3, 0.4]]},
            }
            for i in range(14)
        ],
    }
    mobility = {
        "config": {
            "revision": 3,
            "movements": [{"entryRuleId": "rule-0", "exitRuleId": "rule-2"}],
            "crossings": [{"waitingRuleId": "rule-1", "crossingRuleId": "rule-3"}],
            "queues": [{"zoneRuleId": "rule-4", "spillbackDistanceM": 10}],
            "curbs": [{"zoneRuleId": "rule-6", "role": "general"}],
        }
    }
    archives = {
        "sources": {
            source["id"]: {
                key: source[key]
                for key in (
                    "id",
                    "name",
                    "width",
                    "height",
                    "vssSensorId",
                    "inputUri",
                    "kind",
                )
            }
            for source in sources
        },
        "calibrations": {
            source["id"]: {**deepcopy(camera), "calibrationRevision": "old"}
            for source in sources
        },
        "rules": {
            source["id"]: [
                deepcopy(rule)
                for rule in rules["rules"]
                if rule["sourceId"] == source["id"]
            ]
            for source in sources
        },
    }
    archives["rules"]["unrelated"] = [{"id": "other-rule", "enabled": False}]
    archives["calibrations"]["unrelated"] = {"calibrationRevision": "keep"}
    package = {
        "siteId": site["id"],
        "calibrationRevision": "old",
        "nativeProjectionPlaneWorldZM": 0,
        "navigationWorldZM": 0.1,
        "cameras": [
            {
                **deepcopy(camera),
                "sourceId": source["id"],
                "calibrationRevision": "old",
                "landmarks": [{"keep": 1}],
            }
            for source in sources
        ],
    }
    files = {
        "package.json": m.encoded(package),
        "tracker.yml": b"camera: /state/native/mv3dt-demo/camera-0.yml\n",
        "pub-sub.yml": b"topic: keep-the-peer-topic\n",
        "mqtt.ini": b"set-threaded=0\n",
        "camera-0.yml": b"matrix: unchanged\n",
        "camera-1.yml": b"matrix: unchanged\n",
    }
    tmp_path.mkdir(exist_ok=True)
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    profile = {
        "schemaVersion": "city.mv3dt-demo.v1",
        "enabled": True,
        "siteId": site["id"],
        "cameraOrder": ["sw", "ne"],
        "cameraCalibrations": {"sw": "old", "ne": "old"},
        "imageId": "sha256:" + "a" * 64,
        "trackerConfig": m.PREFIX + "tracker.yml",
        "fileHashes": {m.PREFIX + name: m.sha(data) for name, data in files.items()},
    }
    (tmp_path / "active.json").write_bytes(m.encoded(profile))
    (tmp_path / "manifest.json").write_bytes(
        m.encoded(
            {
                "inputSha256": m.sha(files["package.json"]),
                "trackerInputResolution": [640, 384],
                "runtimeQualified": True,
                "transportClockQualified": True,
            }
        )
    )
    return (
        before,
        candidate,
        site,
        rules,
        mobility,
        registration,
        archives,
        tmp_path,
        "sha256:" + "b" * 64,
        "new-stage",
    )


def test_only_revision_and_clone_references_change_and_inputs_remain_untouched(
    tmp_path,
):
    args = fixture(tmp_path)
    objects_before = deepcopy(args[:7])
    bytes_before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = m.prepare(*args)
    assert args[:7] == objects_before
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == bytes_before
    assert result["mobility"] == args[4]["config"]
    assert result["site"]["fusion"] == args[2]["fusion"]
    assert result["archives"]["rules"]["unrelated"] == args[6]["rules"]["unrelated"]
    assert result["archives"]["sources"] == args[6]["sources"]
    for old, new in zip(args[3]["rules"], result["rules"]["rules"]):
        assert new == {**old, "calibrationRevision": "new"}
    for name in ("camera-0.yml", "camera-1.yml", "pub-sub.yml", "mqtt.ini"):
        assert result["files"][name] == bytes_before[name]
    assert result["files"]["tracker.yml"] == bytes_before["tracker.yml"].replace(
        b"/state/native/mv3dt-demo/", b"/state/native/mv3dt-demo/new-stage/"
    )
    assert "processedPreview" not in result["site"]["sources"][0]
    assert result["summary"]["pinnedFileCount"] == 7
    manifest = json.loads(result["files"]["manifest.json"])
    assert (
        manifest["runtimeQualified"] is False
        and manifest["transportClockQualified"] is False
    )
    for relative, expected in result["profile"]["fileHashes"].items():
        assert (
            expected == hashlib.sha256(result["files"][Path(relative).name]).hexdigest()
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "tiny-pose",
        "map",
        "crosswalk",
        "qualification",
        "camera-order",
        "extra-field",
        "same-stage",
        "same-revision",
        "bad-rule-source",
        "stale-rule",
        "missing-rule",
        "missing-mobility-rule",
        "archive-camera",
        "archive-rule",
        "pinned-file",
        "bad-image",
        "bad-snapshot",
        "manifest",
        "native-camera",
    ],
)
def test_rejects_geometry_or_identity_changes(tmp_path, mutation):
    args = list(fixture(tmp_path))
    (
        before,
        candidate,
        _site,
        rules,
        mobility,
        _registration,
        archives,
        directory,
        _image,
        _snapshot,
    ) = args
    if mutation == "tiny-pose":
        candidate["cameras"]["cam_SW"]["K"][0][0] += 1e-12
    elif mutation == "map":
        candidate["map"]["bounds"][0] += 1
    elif mutation == "crosswalk":
        candidate["crosswalks"][0]["points"][0] += 1
    elif mutation == "qualification":
        candidate["qualification"] = "wrong"
    elif mutation == "camera-order":
        candidate["cameraOrder"].reverse()
    elif mutation == "extra-field":
        candidate["new"] = "field"
    elif mutation == "same-stage":
        candidate["stage"] = before["stage"]
    elif mutation == "same-revision":
        candidate["calibrationRevision"] = before["calibrationRevision"]
    elif mutation == "bad-rule-source":
        rules["rules"][0]["sourceId"] = "other"
    elif mutation == "stale-rule":
        rules["rules"][0]["calibrationRevision"] = "other"
    elif mutation == "missing-rule":
        rules["rules"].pop()
    elif mutation == "missing-mobility-rule":
        mobility["config"]["curbs"][0]["zoneRuleId"] = "missing"
    elif mutation == "archive-camera":
        archives["calibrations"]["sw"]["width"] = 1280
    elif mutation == "archive-rule":
        archives["rules"]["sw"][0]["enabled"] = False
    elif mutation == "pinned-file":
        (directory / "mqtt.ini").write_text("changed")
    elif mutation == "bad-image":
        args[8] = "some-mutable-tag"
    elif mutation == "bad-snapshot":
        args[9] = "../outside"
    elif mutation == "manifest":
        (directory / "manifest.json").write_text('{"inputSha256":"wrong"}')
    elif mutation == "native-camera":
        package = m.read(directory / "package.json")
        package["cameras"][0]["width"] = 1
        (directory / "package.json").write_bytes(m.encoded(package))
    with pytest.raises(ValueError):
        m.prepare(*args)


def test_exact_numeric_json_serialization_change_is_allowed_but_boolean_is_not():
    m.same({"x": [0.0, 1.0]}, {"x": [0, 1]}, "geometry")
    with pytest.raises(ValueError):
        m.same(True, 1, "geometry")
    with pytest.raises(ValueError):
        m.same(float("nan"), float("nan"), "geometry")


def test_review_is_new_hashed_artifact_and_unchanged_loader_accepts_cloned_profile(
    tmp_path,
):
    args = fixture(tmp_path / "source")
    result = m.prepare(*args)
    output = tmp_path / "review"
    m.write_review(output, result, {"active-profile": args[7] / "active.json"})
    receipt = m.read(output / "review-receipt.json")
    assert receipt["applied"] is False
    for relative, expected in receipt["outputSha256"].items():
        assert m.sha((output / relative).read_bytes()) == expected
    with pytest.raises(ValueError, match="new review"):
        m.write_review(output, result, {})
    # Install in an isolated test-only temporary tree, never the real runtime.
    import shutil

    state = tmp_path / "isolated/.spark/city/state"
    shutil.copytree(output / "native", state / "native")
    (state / "native/mv3dt-demo/active.json").write_bytes(m.encoded(result["profile"]))
    spec = importlib.util.spec_from_file_location(
        "unchanged_loader", Path(__file__).parents[1] / "mv3dt_demo_profile.py"
    )
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    profile = loader.load(tmp_path / "isolated", "spark")
    assert profile == result["profile"]
    assert loader.native_args(profile, result["site"], live=True)[0:2] == [
        "--tracker-mode",
        "mv3dt-demo",
    ]


def test_pinned_source_symlink_is_rejected(tmp_path):
    args = fixture(tmp_path)
    (tmp_path / "camera-0.yml").rename(tmp_path / "target.yml")
    (tmp_path / "camera-0.yml").symlink_to(tmp_path / "target.yml")
    with pytest.raises(ValueError, match="pinned file"):
        m.prepare(*args)


def test_paused_desired_sources_remain_paused_in_candidates(tmp_path):
    args = fixture(tmp_path)
    args[6]["sources"].clear()
    result = m.prepare(*args)
    assert result["archives"]["sources"] == {}
    assert result["summary"]["sourceArchiveState"] == "paused"


def test_partially_paused_pair_is_rejected(tmp_path):
    args = fixture(tmp_path)
    args[6]["sources"].pop("sw")
    with pytest.raises(ValueError, match="both camera"):
        m.prepare(*args)


def staged_fixture(tmp_path, *, pin_manifest=False):
    args = fixture(tmp_path)
    local_name = "tracker-local.yml"
    local_bytes = b"TrajectoryManagement:\n  enableReAssoc: 0\nReID:\n  reidType: 0\n"
    (tmp_path / local_name).write_bytes(local_bytes)
    profile = m.read(tmp_path / "active.json")
    profile.update(trackingArchitecture="nvdcf-local-then-mv3dt-v1",
                   localTrackerConfig=m.PREFIX + local_name,
                   sourceClockDiagnostics=False, muxSyncInputs=False,
                   muxMaxLatencyNs=0, muxSyncInputsNtpNs=0)
    profile["fileHashes"][m.PREFIX + local_name] = m.sha(local_bytes)
    if pin_manifest:
        profile["fileHashes"][m.PREFIX + "manifest.json"] = m.sha((tmp_path / "manifest.json").read_bytes())
    (tmp_path / "active.json").write_bytes(m.encoded(profile))
    return args


@pytest.mark.parametrize("pin_manifest", [False, True])
def test_staged_migration_keeps_both_identity_stages_and_clock_controls(tmp_path, pin_manifest):
    import shutil

    directory = tmp_path / "source"
    args = staged_fixture(directory, pin_manifest=pin_manifest)
    original = m.read(directory / "active.json")
    local_bytes = (directory / "tracker-local.yml").read_bytes()
    result = m.prepare(*args)
    assert result["summary"]["pinnedFileCount"] == 8
    assert result["profile"]["localTrackerConfig"] == m.PREFIX + "new-stage/tracker-local.yml"
    assert result["files"]["tracker-local.yml"] == local_bytes
    for key in ("sourceClockDiagnostics", "muxSyncInputs", "muxMaxLatencyNs", "muxSyncInputsNtpNs", "trackingArchitecture"):
        assert result["profile"][key] == original[key]
    output = tmp_path / "review"
    m.write_review(output, result, {"active-profile": directory / "active.json"})
    state = tmp_path / "isolated/.spark/city/state"
    shutil.copytree(output / "native", state / "native")
    (state / "native/mv3dt-demo/active.json").write_bytes(m.encoded(result["profile"]))
    spec = importlib.util.spec_from_file_location("staged_migration_loader", Path(__file__).parents[1] / "mv3dt_demo_profile.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    profile = loader.load(tmp_path / "isolated", "spark")
    native = loader.native_args(profile, result["site"], live=True)
    assert native[native.index("--local-tracker-config") + 1] == "/state/" + result["profile"]["localTrackerConfig"]
    assert "--source-clock-diagnostics" not in native and "--mux-sync-inputs" not in native


@pytest.mark.parametrize("mutation", ["missing-local-pin", "same-tracker", "different-architecture", "tampered-local", "extra-pinned-file"])
def test_staged_migration_refuses_incomplete_or_changed_local_identity_authority(tmp_path, mutation):
    args = staged_fixture(tmp_path, pin_manifest=True)
    profile = m.read(tmp_path / "active.json")
    if mutation == "missing-local-pin":
        profile["fileHashes"].pop(profile["localTrackerConfig"])
    elif mutation == "same-tracker":
        profile["localTrackerConfig"] = profile["trackerConfig"]
    elif mutation == "different-architecture":
        profile["trackingArchitecture"] = "unknown"
    elif mutation == "tampered-local":
        (tmp_path / "tracker-local.yml").write_text("unexpected changed policy")
    elif mutation == "extra-pinned-file":
        (tmp_path / "other.yml").write_bytes(b"other")
        profile["fileHashes"][m.PREFIX + "other.yml"] = m.sha(b"other")
    (tmp_path / "active.json").write_bytes(m.encoded(profile))
    with pytest.raises(ValueError):
        m.prepare(*args)


def test_explicit_complete_operator_rule_count_and_bad_count_rejected(tmp_path):
    args = fixture(tmp_path)
    for index in (14, 15):
        rule = {**deepcopy(args[3]["rules"][0]), "id": f"rule-{index}", "sourceId": ("sw", "ne")[index % 2]}
        args[3]["rules"].append(rule)
        args[6]["rules"][rule["sourceId"]].append(deepcopy(rule))
    with pytest.raises(ValueError, match="complete distinct"):
        m.prepare(*args)
    assert m.prepare(*args, expected_rule_count=16)["summary"]["rulesPreserved"] == 16
    for count in (0, True, 257):
        with pytest.raises(ValueError, match="bounded"):
            m.prepare(*args, expected_rule_count=count)
