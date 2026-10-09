#!/usr/bin/env python3
"""Persist Thor telemetry and stop VSS workloads before exhausting the reserve."""
import concurrent.futures,json,os,pathlib,signal,subprocess,threading,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/runtime-telemetry'; OUT.mkdir(exist_ok=True)
FLOOR=float(os.environ.get('VSS_MEMORY_FLOOR_GIB','48'))
TARGETS=['vss-agent','vss-vios-nvstreamer','vss-memory-embed','vss-memory-cosmos','vss-memory-nemotron','vss-rtvi-cv','vss-rtvi-cv-traffic','vss-lvs']
stop=threading.Event(); latest={'at':time.monotonic(),'line':''}
for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,lambda *_:stop.set())
def halt(name):
 try:
  r=subprocess.run(['docker','stop','-t','2',name],capture_output=True,text=True,timeout=5)
  return {'name':name,'code':r.returncode}
 except subprocess.TimeoutExpired:return {'name':name,'timeout':True}
def trip_reason(available_gib, thermal_age, floor=FLOOR):
 return 'reserve' if available_gib < floor else 'thermal_stall' if thermal_age > 10 else None

def guard_targets():
 project=os.environ.get('VSS_GUARD_PROJECT')
 if not project:return TARGETS
 result=subprocess.run(['docker','ps','--filter',f'label=com.docker.compose.project={project}','--format','{{.ID}}'],capture_output=True,text=True,timeout=5,check=True)
 return result.stdout.splitlines()

def persist(path, row, append=False):
 try:
  with path.open('a' if append else 'w') as stream:
   stream.write(json.dumps(row)+'\n');stream.flush();os.fsync(stream.fileno())
 except OSError as error:
  # Disk exhaustion must never prevent the guard from stopping workloads.
  print(json.dumps({'telemetry_error':type(error).__name__,'path':str(path)}),flush=True)

def trip(row, reason):
 event={**row,'reason':reason,'floor_gib':FLOOR}
 persist(OUT/'trip.json',event)
 print(json.dumps(event),flush=True)
 try:
  targets=guard_targets()
  with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,len(targets))) as pool:results=list(pool.map(halt,targets))
 except (OSError,subprocess.SubprocessError) as error:results=[{'error':type(error).__name__}]
 persist(OUT/'stop-results.json',results)
 return results

def main():
 thermal=subprocess.Popen(['tegrastats','--interval','1000'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
 def receive():
  for line in thermal.stdout:latest.update(at=time.monotonic(),line=line.strip())
 threading.Thread(target=receive,daemon=True).start()
 log=OUT/'samples.jsonl';tripped=False;tick=0;next_retry=0
 try:
  while not stop.wait(1):
   m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1}
   row={'time':time.time(),'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'available_gib':round(m['MemAvailable']/1048576,3),'free_gib':round(m['MemFree']/1048576,3),'slab_gib':round(m['Slab']/1048576,3),'thermal_age':round(time.monotonic()-latest['at'],2),'tegrastats':latest['line']}
   if tick%5==0:
    row['processes']=[]
    for p in pathlib.Path('/proc').glob('[0-9]*'):
     try:
      fields=(p/'stat').read_text().rsplit(')',1)[1].split();rss=int(fields[21])*os.sysconf('SC_PAGE_SIZE')
      if rss>256*1024**2 or fields[0]=='D':row['processes'].append({'pid':p.name,'name':(p/'comm').read_text().strip(),'state':fields[0],'rss_mib':round(rss/1024**2),'wchan':(p/'wchan').read_text().strip()})
     except (OSError,IndexError):pass
   try:
    if log.exists() and log.stat().st_size>32*1024**2:log.replace(OUT/'samples.previous.jsonl')
   except OSError as error:print(json.dumps({'rotation_error':type(error).__name__}),flush=True)
   persist(log,row,append=True)
   reason=trip_reason(row['available_gib'], row['thermal_age'])
   if reason and (not tripped or time.monotonic()>=next_retry):
    tripped=True;trip(row,reason)
    next_retry=time.monotonic()+10
   if not reason:tripped=False
   tick+=1
 finally:
  thermal.terminate()
  try:thermal.wait(3)
  except subprocess.TimeoutExpired:thermal.kill()
if __name__=='__main__':main()
