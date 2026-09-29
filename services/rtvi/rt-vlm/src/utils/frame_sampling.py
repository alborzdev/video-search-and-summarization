# SPDX-License-Identifier: Apache-2.0
"""Endpoint-aware plans for local MP4 sampling, without image decoding.

Targets retain both decoder PTS and playback time; callers must not interchange
these coordinates. Unsupported or incomplete discovery raises SamplingUnavailable.
"""
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path


class SamplingUnavailable(ValueError):
    """The input cannot provide a complete, trustworthy sampling plan."""


@dataclass(frozen=True)
class FrameTimestamp:
    decoder_ns: int
    stream_ns: int


def select_frame_targets(frames, start_ns: int, end_ns: int, count: int):
    """Choose distinct temporal samples in [start, end), always retaining the last.

    A one-frame budget selects the endpoint. Short/sparse clips return fewer
    targets rather than duplicating images. Integer arithmetic preserves ns PTS.
    """
    if count < 1 or end_ns <= start_ns:
        raise SamplingUnavailable("Positive count and nonempty interval required")
    ordered = sorted(set(frames), key=lambda frame: frame.stream_ns)
    eligible = [frame for frame in ordered if start_ns <= frame.stream_ns < end_ns]
    if not eligible:
        raise SamplingUnavailable("No video timestamps in the requested interval")
    if any(a.stream_ns == b.stream_ns for a, b in zip(eligible, eligible[1:])):
        raise SamplingUnavailable("Ambiguous presentation timestamps")
    if any(a.decoder_ns >= b.decoder_ns for a, b in zip(eligible, eligible[1:])):
        raise SamplingUnavailable("Nonmonotonic decoder timeline")
    if count == 1 or len(eligible) == 1:
        return (eligible[-1],)
    times = [frame.stream_ns for frame in eligible]
    last = times[-1]
    targets = []
    # Even temporal spacing over the actual eligible span, including endpoints.
    sample_count = min(count, len(eligible))
    for index in range(sample_count):
        target = times[0] + (last - times[0]) * index // (sample_count - 1)
        frame = eligible[bisect_left(times, target)]
        if not targets or targets[-1] != frame:
            targets.append(frame)
    return tuple(targets)


def discover_mp4_timestamps(file, *, timeout_seconds=2, max_bytes=64 * 1024**2,
                            max_packets=100_000):
    """Demux a bounded local MP4; never load a GPU decoder or contact a URL.

    Limits bound file size, retained timestamp count and the bus wait. They are
    not a hard process deadline for a wedged native plugin. No persistent cache.
    """
    path = Path(file)
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise SamplingUnavailable("Requires a local file within the discovery size limit")
    if timeout_seconds <= 0 or max_packets < 1:
        raise SamplingUnavailable("Positive discovery limits required")
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as error:
        raise SamplingUnavailable("GStreamer discovery bindings unavailable") from error
    Gst.init(None)
    pipeline = Gst.Pipeline.new("frame-timestamp-discovery")
    source = Gst.ElementFactory.make("filesrc")
    demux = Gst.ElementFactory.make("qtdemux")
    sink = Gst.ElementFactory.make("fakesink")
    if not all((pipeline, source, demux, sink)):
        raise SamplingUnavailable("MP4 discovery plugins unavailable")
    source.set_property("location", str(path.resolve()))
    sink.set_property("sync", False)
    sink.set_property("signal-handoffs", True)
    for element in (source, demux, sink):
        pipeline.add(element)
    source.link(demux)
    bus = pipeline.get_bus()
    frames, errors = [], []
    state = {"segment": None, "packets": 0}

    def fail(reason):
        if not errors:
            errors.append(reason)
            bus.post(Gst.Message.new_application(pipeline, Gst.Structure.new_empty("sampling-failed")))

    def pad_added(element, pad):
        if pad.get_name() == "video_0":
            pad.link(sink.get_static_pad("sink"))

    def event_probe(pad, info):
        event = info.get_event()
        if event.type == Gst.EventType.SEGMENT:
            segment = event.parse_segment()
            if segment.format != Gst.Format.TIME or segment.rate != 1 or segment.applied_rate != 1:
                fail("Unsupported video segment")
            state["segment"] = segment.copy()
        return Gst.PadProbeReturn.OK

    def handoff(element, buffer, pad):
        if errors:
            return
        state["packets"] += 1
        if state["packets"] > max_packets:
            fail("Video packet limit exceeded")
            return
        segment = state["segment"]
        if segment is None or buffer.pts == Gst.CLOCK_TIME_NONE:
            fail("Missing video presentation timestamp or segment")
            return
        stream_time = segment.to_stream_time(Gst.Format.TIME, buffer.pts)
        if stream_time != Gst.CLOCK_TIME_NONE:
            frames.append(FrameTimestamp(int(buffer.pts), int(stream_time)))

    demux.connect("pad-added", pad_added)
    sink.connect("handoff", handoff)
    sink.get_static_pad("sink").add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, event_probe)
    try:
        pipeline.set_state(Gst.State.PLAYING)
        message = bus.timed_pop_filtered(int(timeout_seconds * Gst.SECOND),
                                        Gst.MessageType.EOS | Gst.MessageType.ERROR | Gst.MessageType.APPLICATION)
        if errors:
            raise SamplingUnavailable(errors[0])
        if message is None or message.type != Gst.MessageType.EOS:
            raise SamplingUnavailable("MP4 discovery failed or timed out")
        if not frames:
            raise SamplingUnavailable("No video timestamps discovered")
        return tuple(frames)
    finally:
        pipeline.set_state(Gst.State.NULL)
