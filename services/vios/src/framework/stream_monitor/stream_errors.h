// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <map>
#include <mutex>
#include <string>
#include <utility>

// RTSP callbacks run on different threads from the QoS reporter. Transfer an
// entire batch under one lock; never iterate or clear the shared map unlocked.
class StreamErrors {
public:
    using Batch = std::multimap<std::string, std::pair<std::string, std::string>, std::less<>>;
    void record(std::string uri, std::string error, std::string time) {
        std::lock_guard<std::mutex> lock(mutex_);
        pending_.emplace(std::move(uri), std::make_pair(std::move(error), std::move(time)));
    }
    Batch take() {
        Batch batch;
        std::lock_guard<std::mutex> lock(mutex_);
        batch.swap(pending_);
        return batch;
    }
private:
    std::mutex mutex_;
    Batch pending_;
};
