// SPDX-License-Identifier: Apache-2.0
// Real libcurl senders against a delayed loopback HTTP peer. CPU only: no source,
// inference element, GStreamer initialization, GPU surface or CUDA context.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>
#include <netinet/in.h>
#include <sys/socket.h>

int main() {
  assert(curl_global_init(CURL_GLOBAL_DEFAULT)==CURLE_OK);
  const int server=socket(AF_INET,SOCK_STREAM,0);assert(server>=0);
  sockaddr_in address{};address.sin_family=AF_INET;address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  assert(bind(server,reinterpret_cast<sockaddr*>(&address),sizeof(address))==0);
  socklen_t length=sizeof(address);assert(getsockname(server,reinterpret_cast<sockaddr*>(&address),&length)==0);
  assert(listen(server,2)==0);
  std::mutex mutex;std::condition_variable changed;bool slow_received=false,release_slow=false;
  std::array<std::thread,2> peers;
  std::thread acceptor([&] {
    for(size_t i=0;i<2;i++) {
      const int client=accept(server,nullptr,nullptr);assert(client>=0);
      peers[i]=std::thread([&,client] {
        char chunk[4096];std::string request;
        while(request.find("\r\n\r\n")==std::string::npos) {
          const auto n=recv(client,chunk,sizeof(chunk),0);assert(n>0);request.append(chunk,n);
          assert(request.size()<16384);
        }
        const auto body_end=request.find("\r\n\r\n")+4+4; // Controlled four-byte JPEG body.
        while(request.size()<body_end) {
          const auto n=recv(client,chunk,sizeof(chunk),0);assert(n>0);request.append(chunk,n);
        }
        if(request.find("X-City-Source-Id: slow")!=std::string::npos) {
          std::unique_lock<std::mutex> lock(mutex);slow_received=true;changed.notify_all();
          assert(changed.wait_for(lock,std::chrono::seconds(2),[&]{return release_slow;}));
        }
        const std::string response="HTTP/1.1 201 Created\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
        assert(send(client,response.data(),response.size(),MSG_NOSIGNAL)==ssize_t(response.size()));
        close(client);
      });
    }
  });
  App app;app.options.preview_url="http://127.0.0.1:"+std::to_string(ntohs(address.sin_port))+"/api/v1/city/preview";
  auto packet=[&](size_t source,const char* id) {
    city::PreviewPacket result;result.source_index=source;result.provenance={id,"epoch","model",1,123,100,100};
    result.jpeg={255,216,255,217};result.encoded_steady_ns=steady_ns();return result;
  };
  {
    std::lock_guard<std::mutex> lock(app.preview_mutex);
    app.preview_outbox.push(packet(0,"slow"));
  }
  app.preview_senders[0]=std::thread(preview_send_loop,&app,0);
  {
    std::unique_lock<std::mutex> lock(mutex);
    assert(changed.wait_for(lock,std::chrono::seconds(1),[&]{return slow_received;}));
  }
  // The source0 POST is now held by its server, not just by a synthetic mutex.
  const auto started=std::chrono::steady_clock::now();
  app.preview_senders[1]=std::thread(preview_send_loop,&app,1);
  {
    std::lock_guard<std::mutex> lock(app.preview_mutex);
    app.preview_outbox.push(packet(1,"fast"));
  }
  app.preview_changed.notify_all();
  while(!app.previews[1].published && std::chrono::steady_clock::now()-started<std::chrono::milliseconds(400))
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  const bool independent=app.previews[1].published==1 && app.previews[0].published==0;
  {
    std::lock_guard<std::mutex> lock(mutex);release_slow=true;
  }
  changed.notify_all();
  acceptor.join();for(auto& peer:peers)if(peer.joinable())peer.join();close(server);
  while(!app.previews[0].published && std::chrono::steady_clock::now()-started<std::chrono::milliseconds(450))
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  app.stopping=true;app.preview_changed.notify_all();
  for(auto& sender:app.preview_senders)if(sender.joinable())sender.join();
  assert(independent);assert(app.previews[0].published==1&&app.previews[1].published==1);
  assert(app.previews[0].post_duration.snapshot().count==1&&app.previews[1].post_duration.snapshot().count==1);
  curl_global_cleanup();
  std::cout<<"Real per-source libcurl senders publish the fast camera while the other HTTP POST is held; bounded shutdown and timing counts passed\n";
}
