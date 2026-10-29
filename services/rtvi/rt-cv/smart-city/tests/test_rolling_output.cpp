// SPDX-License-Identifier: Apache-2.0
#include "rolling_output.hpp"
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <iterator>

namespace fs=std::filesystem;
std::string contents(const fs::path& path) {
  std::ifstream input(path);return {(std::istreambuf_iterator<char>(input)),std::istreambuf_iterator<char>()};
}
void put(const fs::path& path,const std::string& value){std::ofstream out(path);out<<value;out.close();assert(out);}
template<class Function> void rejects(Function call){bool failed=false;try{call();}catch(const std::runtime_error&){failed=true;}assert(failed);}
city::OutputManifest manifest(const fs::path& path){const auto text=contents(path.string()+".manifest.json");return city::OutputManifestReader(text).parse();}
std::string row(unsigned number){return "{\"n\":"+std::to_string(number)+"}";}
int main() {
  std::string pattern=(fs::temp_directory_path()/"city-rolling-cpu-XXXXXX").string();
  const auto* created=mkdtemp(pattern.data());assert(created);const fs::path root=created;
  struct Cleanup {fs::path path;~Cleanup(){fs::remove_all(path);}} cleanup{root};
  const auto live=root/"live-observations.ndjson",historical=root/"observations-existing-receipt.ndjson";
  put(historical,"historical evidence\n");
  {
    city::RollingOutput output(live,20,2);
    rejects([&]{city::RollingOutput second_writer(live,20,2);});
    for(unsigned number=0;number<14;number++) {
      output.write_record(row(number));const auto saved=manifest(live);
      assert(saved.generation==output.generation()&&saved.max_bytes==20&&saved.retained_files==2&&saved.files.size()<=3);
      for(size_t index=0;index<saved.files.size();index++) {
        const auto path=root/saved.files[index].name;const auto bytes=contents(path);
        assert(bytes.size()<=20&&!bytes.empty()&&bytes.back()=='\n');
        struct stat value{};assert(stat(path.c_str(),&value)==0);
        assert(saved.files[index].generation==saved.generation-index);
        assert(saved.files[index].device==uint64_t(value.st_dev)&&saved.files[index].inode==uint64_t(value.st_ino));
      }
    }
    assert(output.generation()==7);
  }
  {
    city::RollingOutput restarted(live,20,2);assert(restarted.generation()==7);
    restarted.write_record(row(14));restarted.write_record(row(15));assert(restarted.generation()==8);
  }
  assert(contents(live.string()+".2")==row(10)+'\n'+row(11)+'\n');
  assert(contents(live.string()+".1")==row(12)+'\n'+row(13)+'\n');
  assert(contents(live)==row(14)+'\n'+row(15)+'\n');
  assert(contents(historical)=="historical evidence\n");
  assert(!fs::exists(live.string()+".3")&&!fs::exists(live.string()+".manifest.json.tmp"));
  assert(fs::exists(live.string()+".lock"));
  // The exact cap accepts a complete line. Oversized records fail before any
  // rotation or write, and do not prune historical or current evidence.
  const auto exact=root/"exact.ndjson";
  {
    city::RollingOutput output(exact,8,0);output.write_record(row(0));assert(fs::file_size(exact)==8);
    rejects([&]{output.write_record("12345678");});assert(contents(exact)==row(0)+'\n');
    output.write_record(row(1));assert(output.generation()==2&&!fs::exists(exact.string()+".1"));
    rejects([&]{output.write_record("bad\nrecord");});
  }
  {
    city::RollingOutput restarted(exact,8,0);assert(restarted.generation()==2);
  }
  // Append startup never guesses through partial records, cap violations,
  // unknown generations, bad manifests, or a rename-before-manifest crash.
  const auto partial=root/"partial.ndjson";
  {city::RollingOutput output(partial,32,2);output.write_record(row(0));}
  put(partial,contents(partial)+"{partial");const auto partial_bytes=contents(partial);
  rejects([&]{city::RollingOutput output(partial,32,2);});assert(contents(partial)==partial_bytes);
  const auto oversized=root/"oversized.ndjson";
  {city::RollingOutput output(oversized,16,2);output.write_record(row(0));}
  put(oversized,contents(oversized)+"01234567890123456789\n");const auto oversized_bytes=contents(oversized);
  rejects([&]{city::RollingOutput output(oversized,16,2);});assert(contents(oversized)==oversized_bytes);
  const auto untrusted=root/"untrusted.ndjson";put(untrusted,row(0)+'\n');
  rejects([&]{city::RollingOutput output(untrusted,32,2);});assert(contents(untrusted)==row(0)+'\n');
  const auto malformed=root/"malformed.ndjson";
  {city::RollingOutput output(malformed,32,2);output.write_record(row(0));}
  put(malformed.string()+".manifest.json","{bad json");
  rejects([&]{city::RollingOutput output(malformed,32,2);});assert(contents(malformed)==row(0)+'\n');
  const auto crash=root/"crash.ndjson";
  {city::RollingOutput output(crash,32,2);output.write_record(row(0));}
  fs::rename(crash,crash.string()+".1");put(crash,"");
  rejects([&]{city::RollingOutput output(crash,32,2);});assert(contents(crash.string()+".1")==row(0)+'\n');
  assert(fs::file_size(crash)==0);
  const auto extra=root/"extra.ndjson";
  {city::RollingOutput output(extra,32,2);output.write_record(row(0));}
  put(extra.string()+".7",row(1)+'\n');rejects([&]{city::RollingOutput output(extra,32,2);});
  assert(contents(extra.string()+".7")==row(1)+'\n');
  auto invalid=manifest(live);invalid.files[0].name="../outside.ndjson";
  put(live.string()+".manifest.json",city::output_manifest_json(invalid));
  rejects([&]{city::RollingOutput output(live,20,2);});
  assert(city::output_unsigned("268435456")==268435456);
  rejects([]{city::output_unsigned("-1");});rejects([]{city::output_unsigned("18446744073709551616");});
  rejects([&]{city::RollingOutput output(root/"invalid.ndjson",0,2);});
  rejects([&]{city::RollingOutput output(root/"invalid.ndjson",32,9);});
  std::cout<<"Bounded complete-record rotation, monotonic manifests, append restarts and fail-closed recovery passed\n";
}
