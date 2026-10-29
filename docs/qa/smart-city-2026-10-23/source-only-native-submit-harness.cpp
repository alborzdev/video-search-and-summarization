#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>
struct Source { bool recorded=false; };
struct App { struct {std::vector<Source> sources{{}};bool realtime=true;unsigned queue_limit=2;} options;
std::mutex mutex;std::condition_variable changed;std::atomic<bool> stopping{false},failed{false};
std::deque<std::string> queue;uint64_t enqueued=0,peak_queue=0,backpressure_waits=0;void* loop=nullptr;};
void g_main_loop_quit(void*) {}
void submit(App* app,std::string body) {
  std::unique_lock<std::mutex> lock(app->mutex);
  // A callback can have entered before shutdown. Do not enqueue after the
  // publisher has observed stopping with an empty queue and exited.
  if(app->stopping||app->failed)return;
  const bool recorded=std::all_of(app->options.sources.begin(),app->options.sources.end(),
      [](const Source& source){return source.recorded;});
  if(!app->options.realtime&&recorded) {
    // Offline file evaluation is lossless and may run slower than inference.
    // Propagate bounded backpressure upstream instead of discarding event data.
    if(app->queue.size()>=app->options.queue_limit)++app->backpressure_waits;
    app->changed.wait(lock,[&]{return app->stopping||app->failed||app->queue.size()<app->options.queue_limit;});
    if(app->stopping||app->failed)return;
  }
  if(app->queue.size()>=app->options.queue_limit) {
    // Stop visibly rather than silently drop frames used for durable crossing rules.
    std::cerr<<"Observation consumer cannot keep up: bounded queue exhausted\n";
    app->failed=true;g_main_loop_quit(app->loop);return;
  }
  app->queue.push_back(std::move(body));++app->enqueued;
  app->peak_queue=std::max<uint64_t>(app->peak_queue,app->queue.size());app->changed.notify_all();
}
int main(){
for(bool stopping:{false,true}) for(bool realtime:{false,true}) {
App app;app.options.realtime=realtime;app.stopping=stopping;app.failed=!stopping;
submit(&app,"frame");
if(!app.queue.empty()||app.enqueued){std::cerr<<"FAIL: frame enqueued after stop/failure\n";return 1;}
}
App active;submit(&active,"first");submit(&active,"second");
if(active.enqueued!=2||active.queue.size()!=2||active.peak_queue!=2)return 2;
submit(&active,"overflow");if(!active.failed||active.queue.size()!=2)return 3;
std::cout<<"Exact production submit(): stop/failure gate and live queue bound passed\n";
}
