// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace city {
inline uint64_t output_unsigned(const std::string& text) {
  if(text.empty())throw std::runtime_error("Expected an unsigned decimal integer");
  uint64_t result=0;
  for(unsigned char c:text) {
    if(c<'0'||c>'9'||result>(std::numeric_limits<uint64_t>::max()-(c-'0'))/10)
      throw std::runtime_error("Invalid or overflowing unsigned decimal integer");
    result=result*10+(c-'0');
  }
  return result;
}
inline std::string output_json_string(const std::string& text) {
  std::string result="\"";const char* hex="0123456789abcdef";
  for(unsigned char c:text) {
    if(c=='"'||c=='\\'){result+='\\';result+=char(c);}
    else if(c<32){result+="\\u00";result+=hex[c>>4];result+=hex[c&15];}
    else result+=char(c);
  }
  return result+'"';
}
struct OutputGeneration {std::string name;uint64_t generation=0,device=0,inode=0;};
struct OutputManifest {
  uint64_t generation=0,max_bytes=0;unsigned retained_files=0;
  std::vector<OutputGeneration> files;
};
// A small strict reader for the canonical manifest emitted below. Rejecting an
// unknown/reordered schema is safer than guessing a generation after a crash.
class OutputManifestReader {
  const std::string& text_;size_t offset_=0;
  void space(){while(offset_<text_.size()&&std::isspace(static_cast<unsigned char>(text_[offset_])))++offset_;}
public:
  explicit OutputManifestReader(const std::string& text):text_(text){}
  bool take(char c){space();if(offset_<text_.size()&&text_[offset_]==c){++offset_;return true;}return false;}
  void need(char c){if(!take(c))throw std::runtime_error("Malformed observation rotation manifest");}
  std::string string() {
    need('"');std::string result;
    while(offset_<text_.size()) {
      unsigned char c=text_[offset_++];
      if(c=='"')return result;
      if(c<32)break;
      if(c=='\\') {
        if(offset_>=text_.size())break;
        c=text_[offset_++];
        if(c=='"'||c=='\\'||c=='/')result+=char(c);
        else if(c=='u'&&offset_+4<=text_.size()) {
          unsigned value=0;
          for(int i=0;i<4;i++) {
            const unsigned char digit=text_[offset_++];
            if(digit>='0'&&digit<='9')value=value*16+digit-'0';
            else if(digit>='a'&&digit<='f')value=value*16+digit-'a'+10;
            else throw std::runtime_error("Malformed manifest string escape");
          }
          if(value>127)throw std::runtime_error("Unsupported manifest string escape");
          result+=char(value);
        } else throw std::runtime_error("Malformed manifest string escape");
      } else result+=char(c);
    }
    throw std::runtime_error("Unterminated manifest string");
  }
  void key(const std::string& expected){if(string()!=expected)throw std::runtime_error("Unknown manifest schema");need(':');}
  uint64_t number(){space();const auto start=offset_;while(offset_<text_.size()&&text_[offset_]>='0'&&text_[offset_]<='9')++offset_;if(offset_-start>1&&text_[start]=='0')throw std::runtime_error("Invalid manifest number");return output_unsigned(text_.substr(start,offset_-start));}
  OutputManifest parse() {
    OutputManifest result;need('{');key("schemaVersion");
    if(string()!="city.observations.rotation.v1")throw std::runtime_error("Unknown observation manifest version");
    need(',');key("generation");result.generation=output_unsigned(string());
    need(',');key("maxBytes");result.max_bytes=number();
    need(',');key("retainedFiles");const auto retained=number();
    if(retained>8)throw std::runtime_error("Observation retention exceeds 8 previous files");
    result.retained_files=unsigned(retained);need(',');key("files");need('[');
    if(!take(']'))while(true) {
      if(result.files.size()>=9)throw std::runtime_error("Too many observation manifest files");
      OutputGeneration item;need('{');key("name");item.name=string();need(',');key("generation");item.generation=output_unsigned(string());
      need(',');key("device");item.device=output_unsigned(string());need(',');key("inode");item.inode=output_unsigned(string());need('}');
      result.files.push_back(std::move(item));if(take(']'))break;need(',');
    }
    need('}');space();if(offset_!=text_.size())throw std::runtime_error("Trailing manifest data");return result;
  }
};
inline std::string output_manifest_json(const OutputManifest& value) {
  std::ostringstream out;out<<"{\"schemaVersion\":\"city.observations.rotation.v1\",\"generation\":\""<<value.generation
    <<"\",\"maxBytes\":"<<value.max_bytes<<",\"retainedFiles\":"<<value.retained_files<<",\"files\":[";
  for(size_t index=0;index<value.files.size();index++) {
    const auto& item=value.files[index];if(index)out<<',';
    out<<"{\"name\":"<<output_json_string(item.name)<<",\"generation\":\""<<item.generation
      <<"\",\"device\":\""<<item.device<<"\",\"inode\":\""<<item.inode<<"\"}";
  }
  out<<"]}\n";return out.str();
}
class OutputDescriptor {
public:
  OutputDescriptor()=default;
  OutputDescriptor(const OutputDescriptor&)=delete;
  OutputDescriptor& operator=(const OutputDescriptor&)=delete;
  int value=-1;
  ~OutputDescriptor(){reset();}
  void reset(int next=-1){if(value>=0)close(value);value=next;}
};
class RollingOutput {
  std::filesystem::path path_,manifest_path_;OutputDescriptor lock_,output_;
  OutputManifest manifest_;uint64_t size_=0;
  [[noreturn]] static void failure(const std::string& message){throw std::runtime_error(message+": "+std::strerror(errno));}
  static void write_all(int fd,const std::string& value) {
    size_t offset=0;while(offset<value.size()) {
      const auto count=write(fd,value.data()+offset,value.size()-offset);
      if(count<0&&errno==EINTR)continue;
      if(count<=0)failure("Observation output write failed");
      offset+=size_t(count);
    }
  }
  std::filesystem::path file(size_t index) const {return index?std::filesystem::path(path_.string()+"."+std::to_string(index)):path_;}
  static struct stat checked_stat(const std::filesystem::path& path,uint64_t maximum) {
    struct stat value{};if(stat(path.c_str(),&value)!=0)failure("Missing observation generation");
    if(!S_ISREG(value.st_mode)||value.st_size<0||uint64_t(value.st_size)>maximum)
      throw std::runtime_error("Observation generation is not a regular file within its byte cap");
    if(value.st_size) {
      OutputDescriptor input;input.value=open(path.c_str(),O_RDONLY|O_CLOEXEC);if(input.value<0)failure("Cannot read observation boundary");
      char end=0;if(pread(input.value,&end,1,value.st_size-1)!=1)failure("Cannot read observation boundary");
      if(end!='\n')throw std::runtime_error("Observation generation ends with a partial record; refusing append");
    }
    return value;
  }
  void publish_manifest() {
    const auto temporary=manifest_path_.string()+".tmp";OutputDescriptor out;
    out.value=open(temporary.c_str(),O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC,0666);if(out.value<0)failure("Cannot create observation manifest");
    write_all(out.value,output_manifest_json(manifest_));if(fsync(out.value)!=0)failure("Cannot sync observation manifest");out.reset();
    if(rename(temporary.c_str(),manifest_path_.c_str())!=0)failure("Cannot commit observation manifest");
    OutputDescriptor directory;auto parent=path_.parent_path();if(parent.empty())parent=".";
    directory.value=open(parent.c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if(directory.value<0||fsync(directory.value)!=0)failure("Cannot sync observation generation directory");
  }
  void verify_family() const {
    auto parent=path_.parent_path();if(parent.empty())parent=".";
    const auto prefix=path_.filename().string()+".";
    for(const auto& entry:std::filesystem::directory_iterator(parent)) {
      const auto name=entry.path().filename().string();if(name.rfind(prefix,0)!=0)continue;
      const auto suffix=name.substr(prefix.size());
      if(!suffix.empty()&&std::all_of(suffix.begin(),suffix.end(),[](unsigned char c){return c>='0'&&c<='9';})) {
        bool known=false;for(const auto& item:manifest_.files)if(item.name==name)known=true;
        if(!known)throw std::runtime_error("Untracked observation generation; refusing to prune or repair");
      }
    }
  }
  void rotate() {
    if(manifest_.generation==std::numeric_limits<uint64_t>::max())throw std::runtime_error("Observation generation counter exhausted");
    if(fsync(output_.value)!=0)failure("Cannot seal observation generation");
    const size_t previous=manifest_.files.size()-1;
    if(previous==manifest_.retained_files&&unlink(file(previous).c_str())!=0)failure("Cannot remove oldest owned observation generation");
    for(size_t index=std::min<size_t>(previous+1,manifest_.retained_files);index>0;--index)
      if(rename(file(index-1).c_str(),file(index).c_str())!=0)failure("Cannot rotate observation generation");
    output_.reset(open(path_.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_APPEND|O_CLOEXEC,0666));
    if(output_.value<0)failure("Cannot create current observation generation");
    struct stat value{};if(fstat(output_.value,&value)!=0)failure("Cannot identify observation generation");
    ++manifest_.generation;
    manifest_.files.insert(manifest_.files.begin(),{path_.filename().string(),manifest_.generation,uint64_t(value.st_dev),uint64_t(value.st_ino)});
    if(manifest_.files.size()>size_t(manifest_.retained_files)+1)manifest_.files.pop_back();
    for(size_t index=0;index<manifest_.files.size();index++)manifest_.files[index].name=file(index).filename().string();
    size_=0;publish_manifest();
  }
public:
  RollingOutput(const std::string& path,uint64_t maximum,unsigned retained):path_(path),manifest_path_(path+".manifest.json") {
    if(!maximum||retained>8||path_.filename().empty())throw std::runtime_error("Rolling output needs a positive byte cap and 0..8 previous files");
    // The stable lock inode is never rotated or deleted. Keep it until after
    // the current output descriptor closes, including constructor failures.
    lock_.value=open((path+".lock").c_str(),O_WRONLY|O_CREAT|O_CLOEXEC,0666);
    if(lock_.value<0||flock(lock_.value,LOCK_EX|LOCK_NB)!=0)failure("Cannot exclusively lock observation output family");
    manifest_.max_bytes=maximum;manifest_.retained_files=retained;
    if(std::filesystem::exists(manifest_path_)) {
      if(std::filesystem::file_size(manifest_path_)>65536)throw std::runtime_error("Observation manifest exceeds byte limit");
      std::ifstream input(manifest_path_);std::string text((std::istreambuf_iterator<char>(input)),std::istreambuf_iterator<char>());
      const auto saved=OutputManifestReader(text).parse();
      if(saved.max_bytes!=maximum||saved.retained_files!=retained||!saved.generation||saved.files.empty()||
          saved.files.size()!=std::min<uint64_t>(saved.generation,uint64_t(retained)+1))
        throw std::runtime_error("Observation manifest retention or generation mismatch");
      for(size_t index=0;index<saved.files.size();index++) {
        const auto& item=saved.files[index];
        if(item.name!=file(index).filename().string()||item.generation!=saved.generation-index)
          throw std::runtime_error("Observation manifest names or generations are not contiguous");
        const auto value=checked_stat(file(index),maximum);
        if(item.device!=uint64_t(value.st_dev)||item.inode!=uint64_t(value.st_ino))
          throw std::runtime_error("Observation manifest inode mismatch; manual recovery required");
      }
      manifest_=saved;
    } else {
      if(std::filesystem::exists(path_)&&checked_stat(path_,maximum).st_size)
        throw std::runtime_error("Nonempty observation output has no trusted manifest; refusing append");
      manifest_.generation=1;verify_family();
    }
    verify_family();output_.value=open(path_.c_str(),O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC,0666);
    if(output_.value<0)failure("Cannot open current observation output");
    const auto value=checked_stat(path_,maximum);struct stat opened{};
    if(fstat(output_.value,&opened)!=0)failure("Cannot identify open observation output");
    if(value.st_dev!=opened.st_dev||value.st_ino!=opened.st_ino)throw std::runtime_error("Observation output changed while opening");
    size_=uint64_t(value.st_size);
    if(manifest_.files.empty()) {
      manifest_.files.push_back({path_.filename().string(),1,uint64_t(value.st_dev),uint64_t(value.st_ino)});publish_manifest();
    } else if(manifest_.files.front().device!=uint64_t(value.st_dev)||manifest_.files.front().inode!=uint64_t(value.st_ino))
      throw std::runtime_error("Observation output changed after manifest validation");
  }
  void write_record(const std::string& body) {
    if(body.empty()||body.find('\n')!=std::string::npos||body.size()>=manifest_.max_bytes)
      throw std::runtime_error("Observation record is empty, contains a newline, or exceeds output byte cap");
    const uint64_t bytes=uint64_t(body.size())+1;
    if(size_>manifest_.max_bytes-bytes)rotate();
    write_all(output_.value,body+'\n');size_+=bytes;
  }
  uint64_t generation() const {return manifest_.generation;}
};
}
