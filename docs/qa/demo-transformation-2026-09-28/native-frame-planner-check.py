"""Exercise repository frame discovery in the installed GStreamer environment."""
import subprocess
from pathlib import Path

source = Path('services/rtvi/rt-vlm/src/utils/frame_sampling.py').read_text()
checks = r'''
import json,tempfile
file='/home/vst/vst_release/streamer_videos/qa-recovery-20260928.mp4'
frames=discover_mp4_timestamps(file)
targets=select_frame_targets(frames,0,5_000_000_000,10)
assert len(targets)==10 and targets[-1].stream_ns==4_900_000_000
checks=['warehouse_endpoint']
for label,path,kwargs in [
    ('missing_file','/tmp/nonexistent-frame-discovery-input',{}),
    ('size_limit',file,{'max_bytes':1}),
    ('packet_limit',file,{'max_packets':3}),
    ('invalid_deadline',file,{'timeout_seconds':0}),
]:
    try: discover_mp4_timestamps(path,**kwargs)
    except SamplingUnavailable: checks.append(label)
    else: raise AssertionError(label)
with tempfile.NamedTemporaryFile() as invalid:
    invalid.write(b'not a media container'); invalid.flush()
    try: discover_mp4_timestamps(invalid.name)
    except SamplingUnavailable: checks.append('invalid_container')
    else: raise AssertionError('invalid_container')
print(json.dumps({'passed':checks,'sampled_stream_ns':[f.stream_ns for f in targets]}))
'''
result = subprocess.run(['docker','exec','-i','vss-memory-cosmos','python3','-'],
                        input=source+'\n'+checks,text=True,capture_output=True,timeout=15)
if result.returncode:
    raise RuntimeError(result.stderr+result.stdout)
print(result.stdout,end='')
