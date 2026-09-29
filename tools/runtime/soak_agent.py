#!/usr/bin/env python3
"""Bounded agent-managed traffic ingestion check; always pause on exit."""
import datetime,json,pathlib,subprocess,time,urllib.request
BASE='http://127.0.0.1:8100';SID='a0d44114-9947-4edf-8355-14e5732999db';OUT=pathlib.Path('artifacts/reboot-2026-09-09')
def req(url,data=None):
 r=urllib.request.Request(url,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=30) as f:return json.load(f)
def action(a):return req(BASE+'/api/v1/rtsp-streams/'+SID+'/analysis',{'name':'sample-sim-jaywalking.mp4','action':a})
subprocess.run(['systemctl','--user','is-active','--quiet','vss-memory-budget'],check=True)
start=time.time();since=datetime.datetime.now(datetime.timezone.utc).isoformat();rows=[];failure=None
try:
 response=action('resume');assert response['analysisActive'],response
 while time.time()-start<300:
  m=next(int(l.split()[1])/1048576 for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
  if m<48:raise RuntimeError('diagnostic reserve crossed')
  result=req('http://127.0.0.1:9200/mdx-embed-filtered-*/_search',{'size':0,'query':{'range':{'timestamp':{'gte':since}}},'aggs':{'latest':{'max':{'field':'timestamp'}}}})
  count=result['hits']['total']['value'];latest=result['aggregations']['latest']['value'];age=time.time()-latest/1000 if latest else time.time()-start
  if age>35:raise RuntimeError('fresh embedding output stalled')
  row={'elapsed':round(time.time()-start),'available_gib':round(m,3),'fresh_embeddings':count,'output_age':round(age,1)};rows.append(row)
  if len(rows)%6==1:print(json.dumps(row),flush=True)
  time.sleep(5)
except Exception as e:failure=str(e)
finally:
 try:paused=action('pause');assert paused['state']=='paused',paused
 except Exception as e:failure=f'{failure or ""} Pause failed: {e}';subprocess.run(['docker','stop','-t','2','vss-agent','vss-memory-embed','vss-rtvi-cv-traffic'],timeout=15)
 result={'started':start,'duration':round(time.time()-start),'failure':failure,'min_available_gib':min((r['available_gib'] for r in rows),default=None),'samples':rows};(OUT/'agent-cuda-soak.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
 if failure:raise SystemExit(1)
