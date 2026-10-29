#include <memory>
#include <iostream>
#include <string>
struct _GRegex;using GRegex=_GRegex;using GRegexCompileFlags=int;using GRegexMatchFlags=int;
extern "C" GRegex* g_regex_new(const char*,GRegexCompileFlags,GRegexMatchFlags,void*);
extern "C" int g_regex_match(const GRegex*,const char*,GRegexMatchFlags,void*);
extern "C" void g_regex_unref(GRegex*);
bool receipt(const std::string& response) {
  using ReceiptRegex=std::unique_ptr<GRegex,decltype(&g_regex_unref)>;
  // These two fixed patterns apply to every frame. Keep their existing match
  // semantics while avoiding compilation on each observation receipt.
  static const ReceiptRegex accepted_pattern(g_regex_new("\"accepted\"[[:space:]]*:[[:space:]]*true",GRegexCompileFlags(0),GRegexMatchFlags(0),nullptr),g_regex_unref);
  static const ReceiptRegex duplicate_pattern(g_regex_new("\"reason\"[[:space:]]*:[[:space:]]*\"duplicate-or-out-of-order\"",GRegexCompileFlags(0),GRegexMatchFlags(0),nullptr),g_regex_unref);
  if(!accepted_pattern||!duplicate_pattern) {std::cerr<<"Cannot initialize observation receipt patterns\n";return false;}
  const bool accepted=g_regex_match(accepted_pattern.get(),response.c_str(),GRegexMatchFlags(0),nullptr);
  const bool duplicate=g_regex_match(duplicate_pattern.get(),response.c_str(),GRegexMatchFlags(0),nullptr);
  return accepted||duplicate;
}
int main(){for(int i=0;i<1000;++i){
if(!receipt("{\"accepted\":true}"))return 1;
if(receipt("{\"accepted\":false}"))return 2;
if(!receipt("{\"accepted\":false,\"reason\":\"duplicate-or-out-of-order\"}"))return 3;
}std::cout<<"Exact cached receipt block: 3000 real GLib matches and C++ static ownership passed\n";}
