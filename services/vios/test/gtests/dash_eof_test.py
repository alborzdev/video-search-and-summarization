# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile the real EOF callbacks without a GPU/GStreamer development image."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from dash_replay_sensor_type_test import definition

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'src/framework/media/video_source/senders/dash_packager_consumer.cpp'
HEADER = SOURCE.with_suffix('.h')


class DashEofTest(unittest.TestCase):
    def test_recorded_eof_flushes_existing_media_without_teardown(self):
        compiler = shutil.which('c++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++ compiler required')
        source = SOURCE.read_text()
        methods = '\n'.join(definition(source, name) for name in (
            'void DashPackagerConsumer::onLastFrame()',
            'void DashPackagerConsumer::sendEOS()',
        ))
        self.assertIn('void onLastFrame() override;', HEADER.read_text())
        harness = r'''
#include <cassert>
#include <cstdint>
#include <mutex>
struct GstElement { unsigned eos = 0; };
#define GST_APP_SRC(value) (value)
void gst_app_src_end_of_stream(GstElement* element) { ++element->eos; }
struct IMediaDataConsumer { virtual ~IMediaDataConsumer() = default; virtual void onLastFrame() {} };
struct DashPackagerConsumer : IMediaDataConsumer {
    struct Timeline { uint64_t framesPushed = 0; };
    std::mutex m_mutex;
    Timeline m_videoTimeline, m_audioTimeline;
    GstElement* m_videoAppsrc = nullptr;
    GstElement* m_audioAppsrc = nullptr;
    void onLastFrame() override;
    void sendEOS();
};
''' + methods + r'''
int main() {
    DashPackagerConsumer packager;
    GstElement video, audio;
    packager.m_videoAppsrc = &video;
    packager.m_audioAppsrc = &audio;
    IMediaDataConsumer& decoderConsumer = packager;
    // Empty/early-stopped sessions have no caps and must never finalize.
    decoderConsumer.onLastFrame();
    assert(video.eos == 0 && audio.eos == 0);
    packager.m_videoTimeline.framesPushed = 165;
    decoderConsumer.onLastFrame();
    assert(video.eos == 1 && audio.eos == 1);
    assert(packager.m_videoAppsrc == &video && packager.m_videoTimeline.framesPushed == 165);
    // EOF flushes, it does not destroy the viewer's media or reset counters.
    packager.m_videoAppsrc = nullptr;
    packager.m_audioAppsrc = nullptr;
    decoderConsumer.onLastFrame();
    assert(video.eos == 1 && audio.eos == 1);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            cpp, binary = path / 'dash_eof.cpp', path / 'dash_eof'
            cpp.write_text(harness)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            str(cpp), '-o', str(binary)], check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
