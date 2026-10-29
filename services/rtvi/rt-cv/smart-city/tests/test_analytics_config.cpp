// SPDX-License-Identifier: Apache-2.0
#include "analytics_config.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
#include <iterator>

namespace fs=std::filesystem;
std::string contents(const fs::path& path) {
  std::ifstream input(path);return {(std::istreambuf_iterator<char>(input)),std::istreambuf_iterator<char>()};
}
void put(const fs::path& path,const std::string& value){std::ofstream out(path);out<<value;out.close();assert(out);}
size_t files(const fs::path& path){return std::distance(fs::directory_iterator(path),fs::directory_iterator());}
int main() {
  std::string pattern=(fs::temp_directory_path()/"city-analytics-cpu-XXXXXX").string();
  const auto* created=mkdtemp(pattern.data());assert(created);const fs::path root=created;
  struct Cleanup {fs::path path;~Cleanup(){fs::remove_all(path);}} cleanup{root};
  const auto watched=root/"analytics.ini",replacement=root/"replacement.ini",snapshots=root/"snapshots";
  fs::create_directory(snapshots);std::string error;
  const std::string a="# city-rules-revision=A\n[property]\nconfig-width=100\nconfig-height=100\n";
  const std::string b="# city-rules-revision=B\n[property]\nconfig-width=200\nconfig-height=200\n";
  put(watched,a);
  const auto first=city::read_config_generation(watched,error);assert(first&&first->bytes==a);
  put(replacement,b);fs::last_write_time(replacement,fs::last_write_time(watched));fs::rename(replacement,watched);
  // Replacing A after its read, even preserving mtime, must leave B unseen.
  assert(city::config_path_identity(watched)!=first->identity);
  const auto second=city::read_config_generation(watched,error);assert(second&&second->bytes==b);
  assert(second->identity==*city::config_path_identity(watched));
  // Replacement while the descriptor is open either yields coherent old bytes
  // or detects its changed ctime and retries. It never labels B consumed as A.
  put(replacement,a);
  const auto raced=city::read_config_generation(watched,error,[&]{fs::rename(replacement,watched);});
  assert(!raced||(raced->bytes==b&&raced->identity!=*city::config_path_identity(watched)));
  const auto newest=city::read_config_generation(watched,error);assert(newest&&newest->bytes==a);
  assert(!city::read_config_generation(watched,error,[&]{put(watched,b+"changed");}));
  assert(!city::read_config_generation(watched,error,{},1));
  assert(!city::read_config_generation(root,error));

  {
    city::AnalyticsReload reload;
    assert(reload.stage(*first,"A","epoch-A",error,snapshots));
    assert(reload.snapshot_count()==1&&files(snapshots)==1);
    assert(reload.revision()=="none"&&!reload.processed());
    fs::path applied;
    assert(reload.apply_pending([&](const std::string& path){applied=path;assert(contents(path)==a);}));
    assert(reload.revision()=="none"&&reload.epoch()=="epoch-A");
    // A later queued config cannot steal A's post-process acknowledgement.
    assert(reload.stage(*second,"B","epoch-B",error,snapshots));
    auto ack=reload.processed();assert(ack&&ack->revision=="A"&&ack->epoch=="epoch-A");
    assert(reload.revision()=="A"&&!reload.processed());
    // A source can stall indefinitely while arbitrarily many edits arrive.
    // Exactly current+latest pending files survive; none becomes active early.
    for(int number=0;number<1000;number++) {
      assert(reload.stage(*second,"B-"+std::to_string(number),"epoch-B",error,snapshots));
      assert(reload.snapshot_count()==2&&files(snapshots)==2);
      assert(fs::exists(applied)&&!reload.processed()&&reload.revision()=="A");
    }
    assert(reload.apply_pending([&](const std::string& path){assert(fs::exists(applied)&&contents(path)==b);}));
    assert(!fs::exists(applied)&&reload.snapshot_count()==1&&files(snapshots)==1);
    assert(reload.revision()=="A"&&reload.acknowledgement_revision()=="B-999");
    ack=reload.processed();assert(ack&&ack->revision=="B-999"&&ack->epoch=="epoch-B");
    assert(reload.revision()=="B-999"&&!reload.processed());
  }
  assert(files(snapshots)==0);
  std::cout<<"Coherent config generations, replacement races, bounded snapshots and post-update acknowledgements passed\n";
}
