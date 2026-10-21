# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the actual DASH short-recording idle timer with closed-fragment fixtures."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HEADER = Path(__file__).resolve().parents[2] / 'src/framework/media/dash/dash_fragment_info.h'


class DashFragmentAgeTest(unittest.TestCase):
    def test_short_recording_age_tracks_the_latest_real_fragment(self):
        compiler = shutil.which('c++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++ compiler required')
        harness = r'''
#include "dash_fragment_info.h"
#include <cassert>
#include <iostream>
using namespace std::chrono_literals;
void u32(std::string& data, uint32_t n) {
    for (int shift : {24, 16, 8, 0}) data.push_back(static_cast<char>((n >> shift) & 255));
}
std::string box(const char* type, const std::string& body) {
    std::string result; u32(result, static_cast<uint32_t>(8 + body.size()));
    return result + std::string(type, 4) + body;
}
void fragment(const std::filesystem::path& path, std::chrono::seconds age) {
    // A closed two-second movie fragment: tfhd default sample duration1000,
    // trun sample count2, fallback media timescale1000.
    std::string tfhd; u32(tfhd, 8); u32(tfhd, 1); u32(tfhd, 1000);
    std::string trun; u32(trun, 0); u32(trun, 2);
    const auto bytes = box("moof", box("traf", box("tfhd", tfhd) + box("trun", trun)));
    std::ofstream(path, std::ios::binary).write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    std::filesystem::last_write_time(path, std::filesystem::file_time_type::clock::now() - age);
}
int main(int argc, char** argv) {
    assert(argc == 2);
    const std::filesystem::path root(argv[1]);
    const auto empty = vst::dash::publishedMedia(root);
    assert(empty.fragments == 0 && empty.secondsSinceNewestWrite == 0.0);
    fragment(root / "video_0_2.mp4", 10s);
    const auto old = vst::dash::publishedMedia(root);
    assert(old.fragments == 1 && old.seconds == 2.0);
    // libstdc++'s current file times are negative relative to its clock epoch.
    // A zero-initialized "newest" must not prevent observing any real mtime.
    assert(old.secondsSinceNewestWrite >= 9.0 && old.secondsSinceNewestWrite < 12.0);
    assert(old.seconds < 4.0 && old.secondsSinceNewestWrite >= 3.0);
    fragment(root / "video_0_3.mp4", 4s);
    const auto newer = vst::dash::publishedMedia(root);
    assert(newer.fragments == 2 && newer.seconds == 4.0);
    assert(newer.secondsSinceNewestWrite >= 3.0 && newer.secondsSinceNewestWrite < 6.0);
    fragment(root / "video_0_4.mp4", 0s);
    const auto active = vst::dash::publishedMedia(root);
    assert(active.secondsSinceNewestWrite >= 0.0 && active.secondsSinceNewestWrite < 2.0);
    // Non-media writes must not keep an exhausted recording looking active.
    std::ofstream(root / "status.mpd") << "manifest";
    std::filesystem::remove(root / "video_0_4.mp4");
    const auto withManifest = vst::dash::publishedMedia(root);
    assert(withManifest.secondsSinceNewestWrite >= 3.0);
    std::cout << "Real fragment ages and short-recording fallback verified\n";
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'fragment_age.cpp'
            binary = root / 'fragment_age'
            fixtures = root / 'fixtures'
            fixtures.mkdir()
            source.write_text(harness)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(HEADER.parent), str(source), '-o', str(binary)],
                           check=True, timeout=30)
            subprocess.run([str(binary), str(fixtures)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
