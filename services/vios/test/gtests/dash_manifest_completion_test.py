# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile the production manifest path against real closed/truncated MP4 boxes."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from dash_replay_sensor_type_test import definition

ROOT = Path(__file__).resolve().parents[2]
HTTP = ROOT / 'src/framework/web/DashHttpHandler.cpp'
MEDIA = ROOT / 'src/framework/media/dash'


class DashManifestCompletionTest(unittest.TestCase):
    def test_only_acknowledged_complete_tail_becomes_finite_replay(self):
        compiler = shutil.which('c++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++ compiler required')
        source = HTTP.read_text()
        names = ('uint32_t readBigEndianUint32(', 'uint64_t readFragmentDuration(',
                 'bool hasCompleteMediaFragment(', 'class SegmentDurations',
                 'uint32_t mediaTimescale(', 'void replaceAll(', 'std::string attributeValue(',
                 'std::string representationIdBefore(', 'void replaceAttribute(',
                 'void setMinimumUpdatePeriodSeconds(', 'void setMinimumUpdatePeriod(',
                 'void updatePublishTime(', 'bool shiftAvailabilityStart(',
                 'void setTimeShiftBufferDepth(', 'void setSuggestedPresentationDelay(',
                 'void addUtcTiming(', 'uint64_t applyMeasuredSegmentTimeline(',
                 'void anchorAvailabilityToFirstSegment(', 'void setAvailabilityTimeOffset(',
                 'void setTagAttribute(', 'void finalizeReplayManifest(', 'void normalizeLiveManifest(')
        methods = '\n'.join(definition(source, name) + (';' if name.startswith('class') else '')
                            for name in names)
        constants = '\n'.join(re.findall(r'^constexpr[^\n]+;', source, re.M))
        harness = r'''
#include "dash_fragment_info.h"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <ctime>
#include <iomanip>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string_view>
#include <unordered_map>
''' + constants + '\n' + methods + r'''
void u32(std::string& data, uint32_t n) {
    for (int shift : {24,16,8,0}) data.push_back(static_cast<char>((n >> shift) & 255));
}
std::string box(const char* type, const std::string& body) {
    std::string result; u32(result, static_cast<uint32_t>(body.size() + 8));
    return result + std::string(type,4) + body;
}
void fragment(const std::filesystem::path& path, uint32_t millis, bool complete=true) {
    std::string tfhd; u32(tfhd,8); u32(tfhd,1); u32(tfhd,millis);
    std::string trun; u32(trun,0); u32(trun,1);
    auto bytes = box("moof",box("traf",box("tfhd",tfhd) + box("trun",trun)));
    // A truncated sized mdat must never pass the production HTTP media guard.
    bytes += complete ? box("mdat","payload") : std::string("\0\0\0\x20mdat",8);
    std::ofstream(path,std::ios::binary).write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}
std::string mpd() {
    return R"(<MPD type="dynamic" availabilityStartTime="2025-01-01T00:00:00Z" publishTime="2025-01-01T00:00:00Z" minimumUpdatePeriod="PT1S" suggestedPresentationDelay="PT3S" timeShiftBufferDepth="PT90S"><Period id="p"><AdaptationSet><Representation id="video_0"><SegmentTemplate media="video_0_$Number$.mp4" duration="2"/></Representation></AdaptationSet></Period></MPD>)";
}
int main(int argc, char** argv) {
    assert(argc==2); const std::filesystem::path root(argv[1]);
    fragment(root/"video_0_1.mp4",2000);
    fragment(root/"video_0_2.mp4",2000);
    fragment(root/"video_0_3.mp4",1500,false);
    bool ready=true;
    auto measured=SegmentDurations::instance().refresh(root,true,&ready);
    assert(!ready && measured.size()==2);
    auto broken=mpd(); normalizeLiveManifest(broken,root,true,true);
    assert(broken.find("type=\"dynamic\"")!=std::string::npos);
    assert(broken.find("mediaPresentationDuration")==std::string::npos);
    assert(!hasCompleteMediaFragment(root/"video_0_3.mp4"));
    fragment(root/"video_0_3.mp4",1500);
    assert(hasCompleteMediaFragment(root/"video_0_3.mp4"));
    // A complete-looking highest file is still potentially growing until the
    // downstream pipeline acknowledges EOS. Neither live nor replay may cache it.
    auto running=mpd(); normalizeLiveManifest(running,root,true,false);
    assert(running.find("type=\"dynamic\"")!=std::string::npos);
    assert(running.find("d=\"1500\"")==std::string::npos);
    auto live=mpd(); normalizeLiveManifest(live,root,false,true);
    assert(live.find("type=\"dynamic\"")!=std::string::npos);
    assert(live.find("d=\"1500\"")==std::string::npos);
    auto completed=mpd(); normalizeLiveManifest(completed,root,true,true);
    assert(completed.find("type=\"static\"")!=std::string::npos);
    assert(completed.find("mediaPresentationDuration=\"PT5.500000S\"")!=std::string::npos);
    assert(completed.find("duration=\"PT5.500000S\"")!=std::string::npos);
    assert(completed.find("<S t=\"4000\" d=\"1500\"/>")!=std::string::npos);
    for(const char* name : {"availabilityStartTime=","minimumUpdatePeriod=","publishTime=",
                           "suggestedPresentationDelay=","timeShiftBufferDepth="})
        assert(completed.find(name)==std::string::npos);
    assert(SegmentDurations::instance().startTicks(root,3,2000)==4000);
    assert(SegmentDurations::instance().startTicks(root,4,2000)==5500);
    // A separate one-fragment finite replay needs no artificial successor.
    const auto single=root/"single"; std::filesystem::create_directory(single);
    fragment(single/"video_0_1.mp4",1500);
    auto shortClip=mpd(); normalizeLiveManifest(shortClip,single,true,true);
    assert(shortClip.find("mediaPresentationDuration=\"PT1.500000S\"")!=std::string::npos);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            cpp, binary, fixtures = path / 'completion.cpp', path / 'completion', path / 'media'
            fixtures.mkdir()
            cpp.write_text(harness)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-I', str(MEDIA), str(cpp), '-o', str(binary)], check=True, timeout=30)
            subprocess.run([str(binary), str(fixtures)], check=True, timeout=5)

    def test_completion_is_handed_off_only_for_the_owning_replay_asset(self):
        manager = (MEDIA / 'dash_session_manager.cpp').read_text()
        asset = definition(manager, 'DashAssetResult DashSessionManager::resolveAsset(')
        self.assertIn('result.finished = session->replay && session->packager->finalized();', asset)
        self.assertIn('asset.replay, asset.finished', HTTP.read_text())


if __name__ == '__main__':
    unittest.main()
