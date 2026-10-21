# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile the production sensor lookup without a full VIOS/GPU toolchain.

Uploaded MP4 timestamps are relative. Recorded RTSP timestamps are already
absolute, so classifying every file:// replay as an uploaded file corrupts
their timebase. Exercise the actual lookup for both kinds of sensor.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "src/framework/media/dash/dash_session_manager.cpp"


def definition(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("Unclosed definition: " + signature)


class DashReplaySensorTypeTest(unittest.TestCase):
    def test_resolves_actual_owning_sensor_type_and_handles_removal(self):
        compiler = shutil.which("c++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("C++ compiler required")
        method = definition(SOURCE.read_text(), "std::string DashSessionManager::findSensorType")
        harness = r'''
#include <cassert>
#include <map>
#include <memory>
#include <mutex>
#include <string>
struct SensorInfo { std::string type; };
namespace nv_vms {
struct DeviceManager {
    std::map<std::string, std::shared_ptr<SensorInfo>> streams;
    std::mutex* sessionMutex;
    std::shared_ptr<SensorInfo> searchSensor(const std::string& streamId) {
        // Sensor lookup may acquire its own locks; do not nest the DASH lock.
        assert(sessionMutex->try_lock());
        sessionMutex->unlock();
        const auto found = streams.find(streamId);
        return found == streams.end() ? nullptr : found->second;
    }
};
}
struct DashSessionManager {
    mutable std::mutex m_mutex;
    std::weak_ptr<nv_vms::DeviceManager> m_deviceManager;
    std::string findSensorType(const std::string& streamId) const;
};
''' + method + r'''
int main() {
    DashSessionManager sessions;
    assert(sessions.findSensorType("file-stream").empty());
    auto manager = std::make_shared<nv_vms::DeviceManager>();
    manager->sessionMutex = &sessions.m_mutex;
    manager->streams["file-stream"] = std::make_shared<SensorInfo>(SensorInfo{"sensor_file"});
    manager->streams["rtsp-recording"] = std::make_shared<SensorInfo>(SensorInfo{"sensor_rtsp"});
    sessions.m_deviceManager = manager;
    assert(sessions.findSensorType("file-stream") == "sensor_file");
    assert(sessions.findSensorType("rtsp-recording") == "sensor_rtsp");
    assert(sessions.findSensorType("removed-stream").empty());
    manager.reset();
    assert(sessions.findSensorType("file-stream").empty());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dash_sensor_test.cpp"
            binary = Path(directory) / "dash_sensor_test"
            source.write_text(harness)
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=5)

    def test_replay_passes_resolved_type_to_source_before_construction(self):
        replay = definition(SOURCE.read_text(), "DashStartResult DashSessionManager::startReplay")
        assignment = 'opts["sensor_type"] = findSensorType(streamId);'
        self.assertEqual(replay.count(assignment), 1)
        self.assertLess(replay.index(assignment), replay.index("std::make_shared<CommonVideoSource>"))
        self.assertNotIn('opts["sensor_type"] = SENSOR_TYPE_FILE', replay)


if __name__ == "__main__":
    unittest.main()
