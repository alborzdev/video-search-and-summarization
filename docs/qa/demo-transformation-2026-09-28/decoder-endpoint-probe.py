"""Bounded low-resolution hardware decoder/filter probe; no VLM or service edits."""
import ast
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

CODE = r'''
import gi,json,sys
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None)
pipeline=Gst.parse_launch('filesrc name=input ! qtdemux ! h264parse ! nvv4l2decoder ! queue ! timestampfilter name=selection send-eos-when-done=true ! fakesink name=output sync=false signal-handoffs=true')
pipeline.get_by_name('input').set_property('location',sys.argv[1])
pipeline.get_by_name('selection').set_property('timestamps',sys.argv[2])
pts=[]; segments=[]
pipeline.get_by_name('output').connect('handoff',lambda sink,buffer,pad:pts.append(buffer.pts))
def segment_probe(pad,info):
    event=info.get_event()
    if event.type==Gst.EventType.SEGMENT:
        s=event.parse_segment(); segments.append({'start':s.start,'time':s.time,'stop':s.stop})
        pipeline.get_by_name('selection').set_property('timestamps',sys.argv[2])
    return Gst.PadProbeReturn.OK
pipeline.get_by_name('selection').get_static_pad('sink').add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM,segment_probe)
try:
    if len(sys.argv)>3:
        pipeline.set_state(Gst.State.PAUSED)
        status,current,pending=pipeline.get_state(5*Gst.SECOND)
        assert status!=Gst.StateChangeReturn.FAILURE, 'Preroll failed'
        assert pipeline.seek_simple(Gst.Format.TIME,Gst.SeekFlags.FLUSH|Gst.SeekFlags.ACCURATE,int(sys.argv[3])), 'Seek failed'
        pts.clear()
    pipeline.set_state(Gst.State.PLAYING)
    message=pipeline.get_bus().timed_pop_filtered(5*Gst.SECOND,Gst.MessageType.ERROR|Gst.MessageType.EOS)
    assert message and message.type==Gst.MessageType.EOS, str(message.parse_error() if message else 'timeout')
finally: pipeline.set_state(Gst.State.NULL)
print('PROBE_JSON='+json.dumps({'pts_ns':pts,'segments':segments}))
'''

def command(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=15)
    if result.returncode: raise RuntimeError(result.stderr+result.stdout)
    return result.stdout

def available():
    line=next(x for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
    return int(line.split()[1])/1024**2

planner_source = Path('services/rtvi/rt-vlm/src/utils/frame_sampling.py').read_text()
selector_path = Path('services/rtvi/rt-vlm/src/vlm_pipeline/video_file_frame_getter.py')
selector_class = next(node for node in ast.parse(selector_path.read_text()).body
                      if isinstance(node, ast.ClassDef) and node.name == 'DefaultFrameSelector')
planner_code = planner_source + "\nfrom collections import deque\nfrom types import SimpleNamespace\nimport logging,sys,json\nChunkInfo=object\nlogger=logging.getLogger('probe')\n" + ast.unparse(selector_class) + "\nframes=discover_mp4_timestamps(sys.argv[1])\nselector=DefaultFrameSelector(int(sys.argv[4]))\nselector.set_chunk(SimpleNamespace(start_pts=int(sys.argv[2]),end_pts=int(sys.argv[3]),pts_offset_ns=0,file=sys.argv[1]))\nselector.set_file_timestamps(frames)\nprint(json.dumps(list(selector._selected_pts_array)))"
results=[]
with tempfile.TemporaryDirectory(prefix='vss-decode-endpoint-') as directory:
    for name,extra,shift,start in [
        ('cfr-bframes',[],200_000_000,0),
        ('vfr-bframes',['-vf',"select='not(mod(n,3))+eq(n,49)'",'-fps_mode','vfr'],600_000_000,0),
        ('offset-bframes',['-vf','setpts=PTS+2/TB'],200_000_000,2_000_000_000),
    ]:
        path=Path(directory)/(name+'.mp4')
        command(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x128:rate=10:duration=5',*extra,
                 '-c:v','libx264','-threads','1','-bf','3','-g','20','-y',str(path)])
        remote='/tmp/vss-decode-endpoint-'+uuid.uuid4().hex+'.mp4'
        try:
            command(['docker','cp',str(path),'vss-memory-cosmos:'+remote])
            # Exercise the repository planner on each generated file before decoding.
            def plan(low, high, count):
                return json.loads(command(['docker','exec','vss-memory-cosmos','python3','-c',planner_code,remote,str(low),str(high),str(count)]))
            full_targets = plan(start, start+5_000_000_000, 10)
            seek_targets = plan(start+2_500_000_000, start+5_000_000_000, 5)
            for mode,targets,seek in [
                ('baseline',[i*500_000_000 for i in range(10)],None),
                ('endpoint',full_targets,None),
                ('seek-endpoint',seek_targets,start+2_500_000_000),
            ]:
                before=available()
                assert before>=48.5, f'Insufficient diagnostic headroom: {before:.2f} GiB'
                output=command(['docker','exec','vss-memory-cosmos','python3','-c',CODE,remote,','.join(map(str,targets)),*([str(seek)] if seek is not None else [])])
                data=json.loads(next(line.removeprefix('PROBE_JSON=') for line in output.splitlines() if line.startswith('PROBE_JSON=')))
                result={'case':name,'mode':mode,'memory_before_gib':round(before,3),'memory_after_gib':round(available(),3),**data}
                if mode!='baseline':
                    assert data['pts_ns'][-1]==shift+4_900_000_000, result
                    assert len(data['pts_ns'])==len(targets), result
                results.append(result)
                print(json.dumps(result),flush=True)
        finally:
            command(['docker','exec','-u','0','vss-memory-cosmos','rm','-f',remote])
