#!/usr/bin/env python3
"""Five-minute traffic tracker probe, with verified CUDA configuration and cleanup."""
import argparse,json,pathlib,subprocess,time,urllib.request
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--label",choices=["cuda-detector", "cuda-combined", "cuda-full"],default="cuda-detector")
parser.add_argument("--floor",type=float,default=80)
args=parser.parse_args()
SID='a0d44114-9947-4edf-8355-14e5732999db';BASE='http://127.0.0.1:9010/api/v1';OUT=pathlib.Path('artifacts/reboot-2026-09-09');boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text()
config=subprocess.check_output(['docker','exec','vss-rtvi-cv-traffic','cat','/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_tracker_NvDCF_accuracy.yml'],text=True)
assert 'vpiBackend4DcfTracker: 1' in config and 'vpiBackend4DcfTracker: 2' not in config
streams=json.load(urllib.request.urlopen('http://127.0.0.1:30888/vst/api/v1/live/streams'));url=next(s[SID][0]['url'] for s in streams if SID in s)
def change(action):
 payload={'key':'sensor','value':{'camera_id':SID,'camera_name':'sample-sim-jaywalking.mp4','camera_url':url,'change':'camera_'+action,'metadata':{'resolution':'1920x1080','codec':'h264','framerate':30}},'headers':{'source':'vst'}}
 r=urllib.request.Request(BASE+'/stream/'+('add' if action=='add' else 'remove'),data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=20) as f:return f.status
change('add');start=time.time();rows=[];failure=None
try:
 while time.time()-start<300:
  available=next(int(l.split()[1])/1048576 for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
  if available<args.floor:raise RuntimeError(f'detector reserve below {args.floor} GiB')
  with urllib.request.urlopen(BASE+'/health/get-dsready-state',timeout=3) as r:assert r.status==200
  assert pathlib.Path('/proc/sys/kernel/random/boot_id').read_text()==boot
  row={'elapsed':round(time.time()-start),'available_gib':round(available,3)};rows.append(row)
  if len(rows)%6==1:print(json.dumps(row),flush=True)
  time.sleep(5)
except Exception as e:failure=str(e)
finally:
 try:change('remove')
 except Exception as e:print('Stop failed:',e);subprocess.run(['docker','stop','-t','2','vss-rtvi-cv-traffic'],timeout=10)
 result={'duration':round(time.time()-start),'failure':failure,'min_available_gib':min(x['available_gib'] for x in rows),'samples':rows}
 (OUT/(args.label+'-soak.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
 if failure:raise SystemExit(1)
