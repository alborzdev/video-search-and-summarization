"""CPU-only endpoint experiment. Requires host FFmpeg and running Cosmos container.
Generates tiny fixtures in temporary storage; never imports models or edits runtime.
"""
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

GST_PROBE = r'''
import gi,json,sys,time
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None)
pipeline=Gst.Pipeline.new('endpoint')
source=Gst.ElementFactory.make('filesrc'); source.set_property('location',sys.argv[1])
demux=Gst.ElementFactory.make('qtdemux')
sink=Gst.ElementFactory.make('fakesink'); sink.set_property('sync',False); sink.set_property('signal-handoffs',True)
for e in (source,demux,sink): pipeline.add(e)
source.link(demux)
def pad_added(element,pad):
    if pad.get_name().startswith('video_') and not sink.get_static_pad('sink').is_linked(): pad.link(sink.get_static_pad('sink'))
demux.connect('pad-added',pad_added)
pts=[]; segments=[]
sink.connect('handoff',lambda sink,buffer,pad:pts.append(buffer.pts))
def event_probe(pad,info):
    event=info.get_event()
    if event.type == Gst.EventType.SEGMENT:
        segment=event.parse_segment(); segments.append({'start':segment.start,'time':segment.time,'stop':segment.stop})
    return Gst.PadProbeReturn.OK
sink.get_static_pad('sink').add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM,event_probe)
start=time.monotonic()
try:
    pipeline.set_state(Gst.State.PLAYING)
    message=pipeline.get_bus().timed_pop_filtered(5*Gst.SECOND,Gst.MessageType.ERROR|Gst.MessageType.EOS)
    assert message and message.type==Gst.MessageType.EOS, str(message.parse_error() if message else 'timeout')
finally: pipeline.set_state(Gst.State.NULL)
print(json.dumps({'pts_ns':pts,'segments':segments,'elapsed_ms':round((time.monotonic()-start)*1000,3)}))
'''

def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout

def check(path, name):
    def ffprobe(kind, field):
        start=time.monotonic()
        result=json.loads(command(['ffprobe','-v','error','-threads','1','-select_streams','v:0',
                                  '-show_entries',f'{kind}={field}','-of','json',str(path)]))
        return [round(float(row[field])*1e9) for row in result[kind+'s'] if field in row], round((time.monotonic()-start)*1000,3)
    packets,packet_ms=ffprobe('packet','pts_time')
    frames,frame_ms=ffprobe('frame','best_effort_timestamp_time')
    target='/tmp/vss-endpoint-probe-'+uuid.uuid4().hex+'.mp4'
    try:
        command(['docker','cp',str(path),'vss-memory-cosmos:'+target])
        native_start=time.monotonic()
        native=json.loads(command(['docker','exec','vss-memory-cosmos','python3','-c',GST_PROBE,target]))
        native_wall_ms=round((time.monotonic()-native_start)*1000,3)
    finally:
        command(['docker','exec','-u','0','vss-memory-cosmos','rm','-f',target])
    segment=native['segments'][-1]
    normalized=[p-segment['start']+segment['time'] for p in native['pts_ns']]
    assert sorted(normalized)==sorted(frames), 'Native stream-time / decoded-frame mismatch'
    chunk_ends=[]
    start=min(frames)
    for low,high in ((start,start+2.5e9),(start+2.5e9,start+5e9)):
        decoded=max((p for p in frames if low <= p < high), default=None)
        demuxed=max((p for p in normalized if low <= p < high), default=None)
        assert decoded == demuxed, 'Chunk endpoint mismatch'
        chunk_ends.append(decoded / 1e9 if decoded is not None else None)
    result={'case':name,'decoded_frames':len(frames),'packet_max_s':max(packets)/1e9,
            'decoded_last_s':max(frames)/1e9,'native_raw_max_s':max(native['pts_ns'])/1e9,
            'native_stream_time_max_s':max(normalized)/1e9,'native_segment':segment,
            'packet_ms':packet_ms,'decoded_ms':frame_ms,'native_ms':native['elapsed_ms'],'native_process_wall_ms':native_wall_ms,
            'half_open_chunk_endpoints_s':chunk_ends,
            'packet_matches_decoded':max(packets)==max(frames)}
    assert result['packet_matches_decoded'], result
    return result

with tempfile.TemporaryDirectory(prefix='vss-endpoint-') as directory:
    results=[]
    for name,extra in [('cfr-bframes',[]),('vfr-bframes',['-vf',"select='not(mod(n,3))+eq(n,49)'",'-fps_mode','vfr']),('offset-bframes',['-vf','setpts=PTS+2/TB'])]:
        path=Path(directory)/(name+'.mp4')
        command(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=10:duration=5',*extra,
                 '-c:v','libx264','-threads','1','-bf','3','-g','20','-y',str(path)])
        results.append(check(path,name))
    results.append(check(Path('deploy/docker/data-dir/data_log/vst/clip_storage/qa-recovery-20260928.mp4'),'warehouse-recording'))
    print(json.dumps(results,indent=2))
