# SPDX-License-Identifier: Apache-2.0
DS_ROOT ?= /opt/nvidia/deepstream/deepstream
CUDA_ROOT ?= /usr/local/cuda
CXX ?= g++
NVCC ?= $(CUDA_ROOT)/bin/nvcc
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra
INCLUDES = -I$(DS_ROOT)/sources/includes -I$(DS_ROOT)/sources/gst-plugins/gst-nvdspreprocess/include -I$(DS_ROOT)/includes -I$(CUDA_ROOT)/include -Isrc
GST_FLAGS = $(shell pkg-config --cflags gstreamer-1.0 gstreamer-video-1.0 gstreamer-app-1.0 gstreamer-rtp-1.0 glib-2.0 libcurl)
GST_LIBS = $(shell pkg-config --libs gstreamer-1.0 gstreamer-video-1.0 gstreamer-app-1.0 gstreamer-rtp-1.0 glib-2.0 libcurl)
CUDA_DS_LIBS = -L$(DS_ROOT)/lib -lnvdsgst_meta -lnvds_meta -lnvdsgst_helper
DS_LIBS = -L$(DS_ROOT)/lib -Wl,-rpath,$(DS_ROOT)/lib -lnvdsgst_meta -lnvds_meta -lnvdsgst_helper
all: city-worker libcity_parser.so libcity_preprocess.so
city-worker: src/city_worker.cpp src/detector_schedule.hpp src/rfdetr_core.hpp src/media_clock.hpp src/source_epoch.hpp src/source_clock_diagnostics.hpp src/native_capture_clock.hpp src/runtime_tuning.hpp src/preview_core.hpp src/analytics_config.hpp src/rolling_output.hpp src/tracker_3d.hpp src/tracker_diagnostics.hpp src/staged_tracking.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o $@ $(GST_LIBS) $(DS_LIBS) -pthread
libcity_parser.so: src/rfdetr_parser.cpp src/rfdetr_core.hpp
	$(CXX) $(CXXFLAGS) -shared -fPIC $(INCLUDES) $< -o $@
libcity_preprocess.so: src/rfdetr_preprocess.cu src/detector_schedule.hpp
	$(NVCC) -O2 -std=c++17 -diag-suppress 1217 -shared -Xcompiler -fPIC $(INCLUDES) $(filter-out -pthread,$(GST_FLAGS)) $< -o $@ $(CUDA_DS_LIBS)
test:
	$(CXX) $(CXXFLAGS) -Isrc tests/test_analytics_config.cpp -o /tmp/vss-city-analytics-config-test
	/tmp/vss-city-analytics-config-test
	$(CXX) $(CXXFLAGS) -Isrc tests/test_rolling_output.cpp -o /tmp/vss-city-rolling-output-test
	/tmp/vss-city-rolling-output-test
	$(CXX) $(CXXFLAGS) -Isrc tests/test_core.cpp -o /tmp/vss-city-core-test
	/tmp/vss-city-core-test
	$(CXX) $(CXXFLAGS) -Isrc tests/test_epoch.cpp -o /tmp/vss-city-epoch-test
	/tmp/vss-city-epoch-test
	$(CXX) $(CXXFLAGS) -Isrc tests/test_tuning.cpp -o /tmp/vss-city-tuning-test
	/tmp/vss-city-tuning-test
	$(CXX) $(CXXFLAGS) -Isrc tests/test_preview.cpp -o /tmp/vss-city-preview-test
	/tmp/vss-city-preview-test
clean:
	rm -f city-worker libcity_parser.so libcity_preprocess.so
.PHONY: all test clean
preprocess-test: tests/test_preprocess.cu src/rfdetr_preprocess.cu src/detector_schedule.hpp
	$(NVCC) -O2 -std=c++17 -diag-suppress 1217 $(INCLUDES) $(filter-out -pthread,$(GST_FLAGS)) $< -o $@ $(filter-out -pthread,$(GST_LIBS)) $(CUDA_DS_LIBS)
test-gpu: preprocess-test
	./preprocess-test
.PHONY: test-gpu
time-test: tests/test_time.cpp src/media_clock.hpp
	$(CXX) $(CXXFLAGS) -Isrc $(GST_FLAGS) $< -o $@ $(GST_LIBS)
test-time: time-test
	./time-test
.PHONY: test-time
preview-jpeg-test: tests/test_preview_jpeg.cpp src/preview_core.hpp
	$(CXX) $(CXXFLAGS) -DTEST_GST_PLUGIN_DIR='"$(shell pkg-config --variable=pluginsdir gstreamer-1.0)"' -Isrc $(GST_FLAGS) $< -o /tmp/vss-city-preview-jpeg-test $(GST_LIBS)
	/tmp/vss-city-preview-jpeg-test
.PHONY: preview-jpeg-test
frame-limit-test: tests/test_frame_limit.cpp src/city_worker.cpp src/preview_core.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-frame-limit-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-frame-limit-test
.PHONY: frame-limit-test
preview-sender-test: tests/test_preview_senders.cpp src/city_worker.cpp src/preview_core.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-preview-senders-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-preview-senders-test
.PHONY: preview-sender-test
rtsp-transport-test: tests/test_rtsp_transport.cpp src/city_worker.cpp
	$(CXX) $(CXXFLAGS) -DTEST_GST_PLUGIN_DIR='"$(shell pkg-config --variable=pluginsdir gstreamer-1.0)"' $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-rtsp-transport-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-rtsp-transport-test
.PHONY: rtsp-transport-test
parser-test: tests/test_parser.cpp src/rfdetr_parser.cpp src/rfdetr_core.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< -o /tmp/vss-city-parser-test
	/tmp/vss-city-parser-test
.PHONY: parser-test
tracker-diagnostics-test: tests/test_tracker_diagnostics.cpp src/city_worker.cpp src/tracker_diagnostics.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-tracker-diagnostics-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-tracker-diagnostics-test
.PHONY: tracker-diagnostics-test
staged-tracking-test: tests/test_staged_tracking.cpp src/city_worker.cpp src/staged_tracking.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-staged-tracking-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-staged-tracking-test
.PHONY: staged-tracking-test
source-clock-diagnostics-test: tests/test_source_clock_diagnostics.cpp src/city_worker.cpp src/source_clock_diagnostics.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-source-clock-diagnostics-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-source-clock-diagnostics-test
.PHONY: source-clock-diagnostics-test
native-capture-clock-test: tests/test_native_capture_clock.cpp src/city_worker.cpp src/native_capture_clock.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-native-capture-clock-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-native-capture-clock-test $(NATIVE_CAPTURE_FIXTURES)
.PHONY: native-capture-clock-test
scenario-boundary-test: tests/test_scenario_boundary.cpp src/city_worker.cpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-scenario-boundary-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-scenario-boundary-test
.PHONY: scenario-boundary-test
native-mv3dt-test: tests/test_native_mv3dt.cpp src/city_worker.cpp src/staged_tracking.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-native-mv3dt-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-native-mv3dt-test
.PHONY: native-mv3dt-test
detector-cadence-test: tests/test_detector_cadence.cpp src/city_worker.cpp src/detector_schedule.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-detector-cadence-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-detector-cadence-test
.PHONY: detector-cadence-test
trafficcam-parser-test: tests/test_trafficcam_parser.cpp src/rfdetr_parser.cpp src/rfdetr_core.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< -o /tmp/vss-city-trafficcam-parser-test
	/tmp/vss-city-trafficcam-parser-test
.PHONY: trafficcam-parser-test

live-source-queue-test: tests/test_live_source_queue.cpp src/city_worker.cpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-live-source-queue-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-live-source-queue-test
.PHONY: live-source-queue-test

webrtc-preview-test: tests/test_webrtc_preview.cpp src/city_worker.cpp src/preview_core.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(GST_FLAGS) $< -o /tmp/vss-city-webrtc-preview-test $(GST_LIBS) $(DS_LIBS) -pthread
	/tmp/vss-city-webrtc-preview-test
.PHONY: webrtc-preview-test
