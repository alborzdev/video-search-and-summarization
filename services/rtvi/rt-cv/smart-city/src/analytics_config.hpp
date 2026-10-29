// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

namespace city {
struct ConfigIdentity {
  uint64_t device=0,inode=0,size=0;
  int64_t modified_seconds=0,modified_ns=0,changed_seconds=0,changed_ns=0;
  bool operator==(const ConfigIdentity& other) const {
    return device==other.device&&inode==other.inode&&size==other.size&&
      modified_seconds==other.modified_seconds&&modified_ns==other.modified_ns&&
      changed_seconds==other.changed_seconds&&changed_ns==other.changed_ns;
  }
  bool operator!=(const ConfigIdentity& other) const {return !(*this==other);}
};
inline ConfigIdentity config_identity(const struct stat& value) {
  return {uint64_t(value.st_dev),uint64_t(value.st_ino),uint64_t(value.st_size),
    value.st_mtim.tv_sec,value.st_mtim.tv_nsec,value.st_ctim.tv_sec,value.st_ctim.tv_nsec};
}
inline std::optional<ConfigIdentity> config_path_identity(const std::string& path) {
  struct stat value{};
  if(stat(path.c_str(),&value)!=0||!S_ISREG(value.st_mode))return std::nullopt;
  return config_identity(value);
}
struct ConfigGeneration {ConfigIdentity identity;std::string bytes;};
// Identity always describes the descriptor that supplied the bytes. In
// particular, replacing the watched path during this read cannot mark its new
// inode consumed. An in-place write is rejected rather than freezing a mix.
inline std::optional<ConfigGeneration> read_config_generation(const std::string& path,std::string& error,
    const std::function<void()>& after_open={},size_t maximum=8*1024*1024) {
  const int fd=open(path.c_str(),O_RDONLY|O_CLOEXEC);
  if(fd<0){error=std::strerror(errno);return std::nullopt;}
  struct Close {int fd;~Close(){close(fd);}} closed{fd};
  struct stat before{},after{};
  if(fstat(fd,&before)!=0||!S_ISREG(before.st_mode)){error="Configuration must be a readable regular file";return std::nullopt;}
  if(before.st_size<0||uint64_t(before.st_size)>maximum){error="Analytics configuration exceeds byte limit";return std::nullopt;}
  if(after_open)after_open();
  ConfigGeneration result{config_identity(before),{}};char buffer[8192];
  while(true) {
    const auto count=read(fd,buffer,sizeof(buffer));
    if(count<0){if(errno==EINTR)continue;error=std::strerror(errno);return std::nullopt;}
    if(!count)break;
    if(result.bytes.size()+size_t(count)>maximum){error="Analytics configuration exceeds byte limit";return std::nullopt;}
    result.bytes.append(buffer,size_t(count));
  }
  if(fstat(fd,&after)!=0||config_identity(after)!=result.identity||result.bytes.size()!=result.identity.size) {
    error="Analytics configuration changed during read; retrying";return std::nullopt;
  }
  return result;
}
struct ConfigSnapshot {
  ConfigIdentity identity;std::string path,revision,epoch;
  ~ConfigSnapshot(){if(!path.empty())unlink(path.c_str());}
};
struct ConfigAcknowledgement {std::string revision,epoch;};
// The caller serializes these operations. There are at most two owned files:
// the config currently used by the element and the newest queued generation.
class AnalyticsReload {
  std::unique_ptr<ConfigSnapshot> current_,pending_;
  std::string active_revision_="none";
  bool awaiting_processed_=false;
public:
  bool stage(const ConfigGeneration& generation,const std::string& revision,const std::string& epoch,std::string& error,
      const std::string& directory="") {
    pending_.reset();
    auto snapshot=std::make_unique<ConfigSnapshot>();snapshot->identity=generation.identity;
    snapshot->revision=revision;snapshot->epoch=epoch;
    std::error_code ec;
    const auto parent=directory.empty()?std::filesystem::temp_directory_path(ec):std::filesystem::path(directory);
    if(ec){error=ec.message();return false;}
    std::string pattern=(parent/"vss-city-analytics-XXXXXX.ini").string();
    const int fd=mkstemps(pattern.data(),4);
    if(fd<0){error=std::strerror(errno);return false;}
    snapshot->path=pattern;size_t written=0;bool success=true;
    while(written<generation.bytes.size()) {
      const auto count=write(fd,generation.bytes.data()+written,generation.bytes.size()-written);
      if(count<0&&errno==EINTR)continue;
      if(count<=0){error=std::strerror(errno);success=false;break;}
      written+=size_t(count);
    }
    if(close(fd)!=0){error=std::strerror(errno);success=false;}
    if(!success)return false;
    pending_=std::move(snapshot);return true;
  }
  template<class Apply> bool apply_pending(Apply apply) {
    if(!pending_)return false;
    // Retain the old file until the element has consumed its replacement.
    apply(pending_->path);
    current_=std::move(pending_);awaiting_processed_=true;return true;
  }
  std::optional<ConfigAcknowledgement> processed() {
    if(!awaiting_processed_)return std::nullopt;
    awaiting_processed_=false;active_revision_=current_->revision;
    return ConfigAcknowledgement{current_->revision,current_->epoch};
  }
  const std::string& revision() const {return active_revision_;}
  std::string epoch() const {return current_?current_->epoch:"none";}
  std::string acknowledgement_revision() const {return awaiting_processed_?current_->revision:active_revision_;}
  size_t snapshot_count() const {return size_t(bool(current_))+size_t(bool(pending_));}
};
}
