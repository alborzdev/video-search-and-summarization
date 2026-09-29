#!/usr/bin/env python3
"""Bounded live-embedding probe; stops its generation job on completion/failure."""
import argparse,json,pathlib,subprocess,threading,time,urllib.request
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--label",choices=["embedding", "embedding-detection", "embedding-detection-nemotron", "full"],default="embedding")
parser.add_argument("--floor",type=float,default=70)
args=parser.parse_args()
BASE='http://127.0.0.1:8017'; SID='a0d44114-9947-4edf-8355-14e5732999db'
OUT=pathlib.Path('artifacts/reboot-2026-09-09');OUT.mkdir(exist_ok=True)
def request(path,data=None,method=None):
 r=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(r,timeout=15) as f:
  raw=f.read(); return json.loads(raw) if raw else {'status':f.status}
streams=json.load(urllib.request.urlopen('http://127.0.0.1:30888/vst/api/v1/live/streams'))
url=next(s[SID][0]['url'] for s in streams if SID in s)
request('/v1/streams/add',{'streams':[{'liveStreamUrl':url,'description':'VST live stream','sensor_name':'sample-sim-jaywalking.mp4','id':SID}]})
model=request('/v1/models')['data'][0]['id']
start=time.time(); payload={'id':SID,'model':model,'stream':True,'chunk_duration':5}
p=subprocess.Popen(['curl','-sS','-N','--max-time','330','-H','Content-Type: application/json','-d',json.dumps(payload),BASE+'/v1/generate_video_embeddings'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
progress={'events':0,'last':start}
def read():
 for line in p.stdout:
  if line.startswith('data:') and line.strip()!='data: [DONE]':progress['events']+=1;progress['last']=time.time()
threading.Thread(target=read,daemon=True).start(); rows=[];failure=None
try:
 while time.time()-start<300:
  available=next(int(l.split()[1])/1048576 for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
  row={'elapsed':round(time.time()-start),'available_gib':round(available,3),'events':progress['events'],'event_age':round(time.time()-progress['last'],2)};rows.append(row)
  if available<args.floor:raise RuntimeError(f'probe reserve below {args.floor} GiB')
  if p.poll() is not None:raise RuntimeError('embedding response ended unexpectedly')
  if row['event_age']>30:raise RuntimeError('no embedding progress for 30 seconds')
  if len(rows)%15==1:print(json.dumps(row),flush=True)
  time.sleep(2)
except Exception as e:failure=str(e)
finally:
 try:request('/v1/generate_video_embeddings/'+SID,method='DELETE')
 except Exception as e:print('Stop request failed:',str(e),flush=True);subprocess.run(['docker','stop','-t','2','vss-memory-embed'],timeout=10)
 p.terminate()
 result={'started':start,'duration':round(time.time()-start),'failure':failure,'events':progress['events'],'min_available_gib':min(r['available_gib'] for r in rows),'samples':rows}
 (OUT/(args.label+'-soak.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
 if failure:raise SystemExit(1)
