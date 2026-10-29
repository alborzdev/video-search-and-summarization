# Worker timestamp and input alignment audit

October 26, 2026. Read-only review of the running staged tracker image
`sha256:e362f9f63ce450d1def2d14b01648a8563f52fc4494f9814d232d7af72f1a23d`.
No worker, source, model, mux setting or runtime was changed by this review.

**Follow-up status:** the later
[actual worker proof](qa/smart-city-2026-10-26/source-clock-actual-worker-proof.json)
closed the missing measurement below. It retained 317 frames per camera with
all four exact source/PTS reference stages present. SDK NTP agreed with the
same-buffer RTCP reference within 3.555 microseconds absolute in that cohort.
The earlier persistent offset was already absent after the diagnostic restart,
before mux changes. Its historical cause remains unknown. This page preserves
the earlier source audit and proposed diagnostic method. The later PTS-sync
startup trial failed and was rolled back to the diagnostics-on baseline with
synchronization disabled; the [failure receipt](qa/smart-city-2026-10-26/source-clock-pts-sync-failure.json)
records the exact settings and recovery. Missing/delayed RTCP and reconnect
robustness, display performance and combined acceptance remain separate.

## Result

At the source-audit checkpoint, evidence did not identify a proven timestamp
correction bug. It identified an input alignment question and a missing
measurement inside the worker. The follow-up above now supplies the measured
mapping result without changing its clock basis.

The separate encoded-only clients saw the same native render tick at both camera
endpoints. Their measured same-render RTCP differences were about 29.4 ms at the
origin and 14.4 ms at the actual VIOS inputs. VIOS receive delay was at most about
57 ms at the 90th percentile in the bounded window. These results do not explain
the worker's approximately 450 ms difference. However, these clients were not
probes inside the worker; they cannot prove which access unit its decoder and
mux used.

The exact receipts are
[origin capture](qa/smart-city-2026-10-26/staged-native-origin-capture-clock.json),
[VIOS capture](qa/smart-city-2026-10-26/staged-vios-input-capture-clock.json) and
[source audit](qa/smart-city-2026-10-26/staged-worker-ntp-source-audit.json).

## Installed properties at the initial audit

`/proc/1/maps` and a read-only `gst-inspect-1.0 nvstreammux` agree that the worker
uses the **legacy** DeepStream 9.2 `libnvdsgst_multistream.so`. It does not use the
open new-mux implementation. At that checkpoint, the worker did not set the four properties below.

| Property | Actual legacy type and units | Installed default |
| --- | --- | --- |
| `frame-duration` | Unsigned 64-bit integer, milliseconds | Frame-rate correction disabled. The getter prints `18446744073709`, the internal `GST_CLOCK_TIME_NONE` divided by one million; its description calls this `-1`. |
| `sync-inputs` | Boolean | `false` |
| `sync-inputs-ntp` | Signed integer, nanoseconds, 0 through 2147483647 | `0` |
| `max-latency` | Unsigned integer, nanoseconds, 0 through 4294967295 | `0` |

Thus, setting `frame-duration=-1` is expected to leave the present behavior
unchanged. The proposed automatic-frame-rate-correction cause needs evidence;
automatic mode is not the current installed default. The source supplied for
the separate new mux also starts with correction disabled. Do not treat that
source as a proof of every internal legacy implementation detail.

NVIDIA documents both the disabled correction default and the separate PTS/NTP
input synchronization properties. These are different controls: calculating a
timestamp does not establish that two selected frames were captured together.
See the official [legacy mux properties](https://docs.nvidia.com/deepstream/9.2/text/DS_plugin_gst-nvstreammux)
and [NTP timestamp modes](https://docs.nvidia.com/deepstream/9.2/text/DS_NTP_Timestamp).

## Worker path at the initial audit

Deployed source snapshot:
`.spark/city/runtime/staged-tracker-candidate-20261026/src/city_worker.cpp`.
The normal source location is
`services/rtvi/rt-cv/smart-city/src/city_worker.cpp`; later candidate edits there
do not change the reviewed snapshot. The QA receipt pins its SHA256.

* Lines 703–710 set RTSP latency to 200 ms, force TCP and call
  `configure_source_for_ntp_sync` on each actual `rtspsrc`.
* Lines 910–913 set a two-source live mux with `attach-sys-ts=false`.
  The deployed command uses a 10000-microsecond batch timeout.
* Lines 971–992 put each decoder behind a separate four-buffer queue, followed
  by GPU upload and the mux. These queues do not discard old buffers. The live
  source pacing identity does not synchronize the two cameras.
* Lines 666–669 return immediately from `source_clock_probe` for live sources.
  There is currently no independent reference timestamp in that path.
* Lines 480–483 export `NvDsFrameMeta.ntp_timestamp` as `sourceTimeNs` when it is
  available. This is the SDK result, not an independently captured source clock.
* The deployed command uses `--cpu-decode`. Its decoder can have its own retained
  frames, in addition to the explicit queues. This review did not measure that
  delay or change decoder settings.

The legacy mux normally selects frames by round robin unless input synchronization
is enabled. A source that starts several render ticks later, or retains a longer
queue, can therefore contribute a different capture time even when both source
frame counters advance at similar rates. This is a source-supported candidate
cause, not a measured queue diagnosis.

## SDK clock path

The installed `nvdsgstutils.h:58` declares the public
`configure_source_for_ntp_sync` helper. Its implementation source is not supplied.
Read-only inspection of the exact installed helper binary showed:

* Entry `0x61c0` subscribes to `deep-element-added` on `rtspsrc` or `uridecodebin`.
* Callback `0x6000` recognizes each RTP jitter buffer. It sets mode 4, one
  fast-start packet and `max-rtcp-rtp-time-diff=-1`, then observes `handle-sync`.
* Callback `0x5cf0` uses the SR RTP position, RTP clock rate and jitter-buffer
  base time to reconstruct the SR's buffer PTS. It passes that mapping with the
  sender's Unix NTP value through an `nvds-ntp-sync` query.

That helper path is not a read of `GstReferenceTimestampMeta`. The public GStreamer
1.24.2 source shows that jitter-buffer output PTS can also include stream and
buffering offsets. This is one reason to compare the exact same access unit's
reference time with SDK time, rather than assuming PTS is an independent proof.
See [offset application](https://github.com/GStreamer/gstreamer/blob/1.24.2/subprojects/gst-plugins-good/gst/rtpmanager/gstrtpjitterbuffer.c#L3649-L3663)
and [SR synchronization data](https://github.com/GStreamer/gstreamer/blob/1.24.2/subprojects/gst-plugins-good/gst/rtpmanager/gstrtpjitterbuffer.c#L4391-L4476).

The supplied **new-mux** source is at
`/opt/nvidia/deepstream/deepstream-9.2/sources/gst-plugins/gst-nvmultistream2/`:

| File and lines | Relevant behavior |
| --- | --- |
| `gstnvstreammux_ntp.cpp:121–159` | Keeps the first SR mapping and then a pending next mapping. |
| `gstnvstreammux_ntp.cpp:163–194` | Checks a new mapping and conditionally applies frame-rate correction; the disabled mode skips the frame-rate adjustment. |
| `gstnvstreammux_ntp.cpp:247–249` | Reconstructs NTP from the SR Unix time minus its mapped PTS plus the current buffer PTS. |
| `gstnvstreammux.cpp:331–358` | Obtains upstream SR mapping, then calculates per-buffer NTP. |
| `gstnvstreammux.cpp:1773–1796` | Defines synchronization separately from frame-duration correction. |

The QA receipt pins hashes of these source files, the public header, helper
binary and actual legacy mux binary.

## Bounded output observation

This review read at most the final 8 MiB and retained 500 observation rows. Among
197 adjacent NE-then-SW serialization pairs:

| Measure | Median | 95th percentile |
| --- | --- | --- |
| SW minus NE SDK NTP | 452.733 ms | 504.555 ms |
| SW minus NE raw source PTS | 452.344 ms | 504.166 ms |
| SW minus NE source frame counter | -1 | 0 |

The per-source `NTP - raw PTS` bases differed by only about 0.39 ms. This favors
investigating selection and queue age, but it does not prove clock correctness:
both values still come from the worker's reconstructed clock path. Adjacent
serialization is not a separately exported batch identity.

## Original bounded trial plan

1. Add default-off diagnostics in the worker. Observe an actual source reference
   timestamp or native SEI at the parsed access unit, after decode, before mux,
   and after the mux. Join only by exact source/session and original PTS, with
   bounded storage and explicit missing/ambiguous counts. Record actual host
   arrival time at each stage. Do not change timestamps while measuring them.
2. If SDK NTP disagrees with the same access unit's independent reference, fix
   the demonstrated mapping or metadata propagation fault. If a reference is
   absent after decode/upload, report that absence and keep the parsed-AU proof;
   do not manufacture a reference.
3. If mapping is correct but selected frames have different capture times, try
   the documented mux synchronization controls in a separate reversible profile.
   An initial NTP pairing window is 50000000 ns. Keep the existing map guards.
   Choose any additional latency from measured pre-mux and processing delay,
   rather than from network delay alone. Record dropped frames and resulting
   rate. A smoother pair can require discarding old frames.
4. Preserve the original profile and compare exact source clocks, preview/map
   identity, per-camera rate and native association coverage. Do not replace
   source capture time with the host's current time or subtract a fitted offset
   to make the existing guard pass.

The pipeline owner subsequently deployed the diagnostic path and retained the
follow-up proof above. This source audit did not activate that candidate and
does not qualify a synchronization fix or identify the historic offset's cause.
