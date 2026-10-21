# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile the production EOF enqueue/dispatch against deterministic FIFO fixtures."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from dash_replay_sensor_type_test import definition

SOURCE = (Path(__file__).resolve().parents[2]
          / 'src/framework/media/video_source/processors/transforms/ll_transform.cpp')


class DashTransformEofTest(unittest.TestCase):
    def test_eof_waits_for_inflight_and_queued_pictures_and_stays_private(self):
        compiler = shutil.which('c++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++ compiler required')
        source = SOURCE.read_text()
        enqueue = definition(source, 'void NvLLTransform::onLastFrame()')
        dispatch = definition(source, 'if (sink_frame->m_encoderMsgType == Last_Frame)')
        worker = definition(source, 'void NvLLTransform::doTransformTask()')
        self.assertLess(worker.index('if (m_stop)'), worker.index(dispatch))
        self.assertLess(worker.index(dispatch), worker.index('/* Get the buffer from sample */'))
        harness = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>
using namespace std::chrono_literals;
enum EncoderMsgType { Buffer, Exit, Reset, Last_Frame };
struct RawFrameParams { EncoderMsgType m_encoderMsgType = Buffer; int id = 0; };
struct Consumer {
    std::mutex mutex;
    std::condition_variable cv;
    bool blockFirst = false, entered = false, released = false;
    std::vector<int> events;
    void onFrame(const std::shared_ptr<RawFrameParams>& frame) {
        std::unique_lock<std::mutex> lock(mutex);
        if (blockFirst && frame->id == 1) {
            entered = true; cv.notify_all();
            assert(cv.wait_for(lock, 2s, [&] { return released; }));
        }
        events.push_back(frame->id);
    }
    void onLastFrame() { std::lock_guard<std::mutex> lock(mutex); events.push_back(99); }
};
struct NvLLTransform {
    std::shared_ptr<Consumer> m_consumer;
    std::queue<std::shared_ptr<RawFrameParams>> m_queue;
    std::mutex m_queueLock;
    std::condition_variable m_condVar;
    std::atomic<bool> m_stop{false}, m_flowData{false};
    void onLastFrame();
    void add(int id) { auto frame = std::make_shared<RawFrameParams>(); frame->id = id;
        std::lock_guard<std::mutex> lock(m_queueLock); m_queue.push(frame); }
    void drain() {
        while (true) {
            std::shared_ptr<RawFrameParams> sink_frame;
            { std::lock_guard<std::mutex> lock(m_queueLock);
              if (m_queue.empty()) break;
              sink_frame = m_queue.front(); m_queue.pop(); }
            if (m_stop) continue;
''' + dispatch + r'''
            if (m_consumer) m_consumer->onFrame(sink_frame);
        }
    }
};
''' + enqueue + r'''
int main() {
    NvLLTransform first, second;
    first.m_consumer = std::make_shared<Consumer>();
    second.m_consumer = std::make_shared<Consumer>();
    first.m_consumer->blockFirst = true;
    first.add(1); first.add(2); second.add(7);
    std::thread worker([&] { first.drain(); });
    { std::unique_lock<std::mutex> lock(first.m_consumer->mutex);
      assert(first.m_consumer->cv.wait_for(lock, 2s, [&] { return first.m_consumer->entered; })); }
    // The first picture is in flight and the second remains queued.
    first.onLastFrame();
    assert(first.m_flowData);
    { std::lock_guard<std::mutex> lock(first.m_consumer->mutex);
      assert(first.m_consumer->events.empty());
      first.m_consumer->released = true; }
    first.m_consumer->cv.notify_all();
    worker.join();
    assert((first.m_consumer->events == std::vector<int>{1, 2, 99}));
    assert(second.m_consumer->events.empty()); // no other viewer gets EOF
    second.drain();
    assert((second.m_consumer->events == std::vector<int>{7}));
    NvLLTransform stopped;
    stopped.m_consumer = std::make_shared<Consumer>(); stopped.m_stop = true;
    stopped.onLastFrame();
    assert(stopped.m_queue.empty() && !stopped.m_flowData);
    assert(stopped.m_consumer->events.empty());
    NvLLTransform empty;
    empty.onLastFrame(); empty.drain(); // missing consumer is safe
    assert(empty.m_queue.empty());
    NvLLTransform stoppedWithMarker;
    stoppedWithMarker.m_consumer = std::make_shared<Consumer>();
    stoppedWithMarker.onLastFrame(); stoppedWithMarker.m_stop = true;
    stoppedWithMarker.drain();
    assert(stoppedWithMarker.m_consumer->events.empty());
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            cpp, binary = path / 'transform_eof.cpp', path / 'transform_eof'
            cpp.write_text(harness)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
                            str(cpp), '-o', str(binary)], check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
