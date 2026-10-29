// SPDX-License-Identifier: Apache-2.0
#include "../../src/framework/stream_monitor/stream_errors.h"
#include <atomic>
#include <cassert>
#include <set>
#include <thread>
#include <vector>

int main() {
    StreamErrors errors;
    std::atomic<int> finished{0};
    std::vector<std::thread> producers;
    for (int worker = 0; worker < 4; ++worker) producers.emplace_back([&, worker] {
        for (int n = 0; n < 10000; ++n)
            errors.record("offline-camera", std::to_string(worker * 10000 + n), "time");
        ++finished;
    });
    std::set<int> received;
    auto drain = [&] {
        const auto batch = errors.take();
        for (const auto& error : batch) assert(received.insert(std::stoi(error.second.first)).second);
    };
    while (finished.load() != 4) { drain(); std::this_thread::yield(); }
    for (auto& producer : producers) producer.join();
    drain();
    assert(received.size() == 40000);
    assert(errors.take().empty());
}
