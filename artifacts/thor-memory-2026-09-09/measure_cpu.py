import json, pathlib, subprocess, time
out=pathlib.Path(__file__).parent/'cpu-stages.jsonl'
names=['redis','vss-vios-postgres','kafka','elasticsearch','vss-graph-db']
def snap(stage,status):
 d={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>=2}
 row={'time':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'stage':stage,'status':status,'available_gib':round(d['MemAvailable']/1048576,3),'used_gib':round((d['MemTotal']-d['MemAvailable'])/1048576,3),'free_gib':round(d['MemFree']/1048576,3)}
 with out.open('a') as f:f.write(json.dumps(row)+'\n')
 print(json.dumps(row),flush=True)
 return row
snap('baseline','VSS stopped; one-shot shrinker reclaim completed')
for name in names:
 subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL)
 deadline=time.monotonic()+180
 while True:
  state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',name]))
  status=state.get('Health',{}).get('Status',state['Status'])
  row=snap(name,status)
  if row['available_gib']<80 or not state['Running']:
   subprocess.run(['docker','stop','-t','20',name]); raise SystemExit('Stopped: reserve or process exit')
  if status=='healthy':break
  if time.monotonic()>deadline:raise SystemExit('Readiness timeout: '+name)
  time.sleep(5)
 time.sleep(10)
 snap(name,'healthy + 10-second settle')
print('CPU infrastructure stages complete',flush=True)
