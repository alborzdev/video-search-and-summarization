"""Start named existing VSS containers sequentially and retain host memory samples."""
import argparse,json,pathlib,subprocess,time
p=argparse.ArgumentParser();p.add_argument('names',nargs='+');p.add_argument('--floor',type=float,default=70);p.add_argument('--timeout',type=float,default=180);args=p.parse_args();out=pathlib.Path(__file__).parent/'service-stages.jsonl'
def sample(name,status):
 m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1};r={'time':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'stage':name,'status':status,'available_gib':round(m['MemAvailable']/1048576,3),'used_gib':round((m['MemTotal']-m['MemAvailable'])/1048576,3)}
 with out.open('a') as f:f.write(json.dumps(r)+'\n')
 return r
for name in args.names:
 c=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
 if (c['Config'].get('Labels') or {}).get('com.docker.compose.project') not in ['mdx','vss-nvstreamer','thor-nvstreamer']:raise SystemExit('Not a known VSS project: '+name)
 if c['State']['Running']:print('Already running:',name,flush=True);continue
 print(json.dumps(sample(name,'before-start')),flush=True);subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL);deadline=time.monotonic()+args.timeout;ready_since=None;last=0
 try:
  while time.monotonic()<deadline:
   state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',name]));health=state.get('Health',{}).get('Status','running-unprobed');r=sample(name,health)
   if r['available_gib']<args.floor:raise RuntimeError('memory floor crossed')
   if not state['Running']:raise RuntimeError('container exited '+str(state['ExitCode']))
   if time.monotonic()-last>15:print(json.dumps(r),flush=True);last=time.monotonic()
   if health in ['healthy','running-unprobed']:
    ready_since=ready_since or time.monotonic()
    if time.monotonic()-ready_since>=20:print(json.dumps(sample(name,health+'-settled')),flush=True);break
   else:ready_since=None
   time.sleep(2)
  else:raise RuntimeError('readiness timeout')
 except BaseException:
  subprocess.run(['docker','stop','-t','15',name],timeout=25);raise
print('All requested stages settled; API-level validation is still required.',flush=True)
