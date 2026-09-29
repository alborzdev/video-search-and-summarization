"""CPU-only native timestamp-filter experiment; no production pipeline changes."""
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst
Gst.init(None)

def run(targets):
    pipeline = Gst.parse_launch('videotestsrc num-buffers=50 ! video/x-raw,width=16,height=16,framerate=10/1 ! timestampfilter name=selection send-eos-when-done=true ! fakesink name=output sync=false signal-handoffs=true')
    pipeline.get_by_name('selection').set_property('timestamps', ','.join(str(t) for t in targets))
    selected = []
    pipeline.get_by_name('output').connect('handoff', lambda sink, buffer, pad: selected.append(buffer.pts / 1e9))
    try:
        pipeline.set_state(Gst.State.PLAYING)
        message = pipeline.get_bus().timed_pop_filtered(5 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        assert message and message.type == Gst.MessageType.EOS, 'Native filter did not complete normally'
        return selected
    finally:
        pipeline.set_state(Gst.State.NULL)

baseline = run([i * 500_000_000 for i in range(10)])
endpoint_target = run([i * 500_000_000 for i in range(9)] + [4_900_000_000])
print({'baseline': baseline, 'known_endpoint_target': endpoint_target})
assert len(baseline) == len(endpoint_target) == 10
assert baseline[-1] == 4.5 and endpoint_target[-1] == 4.9
