// SPDX-License-Identifier: Apache-2.0
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>
int main(int argc, char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0", "", TRUE);
  g_setenv("GST_PLUGIN_PATH_1_0", "", TRUE);
  g_setenv("GST_REGISTRY", "/tmp/city-rtsp-transport-registry.bin", TRUE);
  gst_init(&argc, &argv);
  GError* error = nullptr;
  auto* plugin = gst_plugin_load_file(TEST_GST_PLUGIN_DIR "/libgstrtsp.so", &error);
  assert(plugin && !error);
  auto* source = gst_element_factory_make("rtspsrc", "test-source"); assert(source);
  source_setup(nullptr, source, nullptr);
  guint protocols = 0, latency = 0;
  g_object_get(source, "protocols", &protocols, "latency", &latency, nullptr);
  assert(protocols == 4 && latency == 200);
  App app;app.options.source_clock_diagnostics=true;
  source_setup(nullptr,source,&app);
  gboolean reference_meta=FALSE;g_object_get(source,"add-reference-timestamp-meta",&reference_meta,nullptr);
  assert(reference_meta&&!app.failed);
  gst_object_unref(source); gst_object_unref(plugin);
  std::cout << "Actual RTSP source uses TCP only, 200 ms latency and explicit reference metadata diagnostics\n";
}
