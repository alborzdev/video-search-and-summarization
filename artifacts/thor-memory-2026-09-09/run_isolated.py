import argparse,json,pathlib,subprocess,time,urllib.request
p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--url',required=True);p.add_argument('--compose');p.add_argument('--start-existing',action='store_true');p.add_argument('--floor',type=float,default=80);p.add_argument('--timeout',type=float,default=600);p.add_argument('--allow-peer',action='append',default=[]);p.add_argument('--settle',type=float,default=30);args=p.parse_args()
root=pathlib.Path(__file__).parent;out=root/(args.name+'-samples.jsonl')
def sample(stage):
 m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1}
 dstate=[]
 for proc in pathlib.Path('/proc').glob('[0-9]*'):
  try:
   fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
   if fields[0]=='D':dstate.append({'pid':proc.name,'comm':(proc/'comm').read_text().strip(),'wchan':(proc/'wchan').read_text().strip()})
  except (OSError,IndexError):pass
 r={'time':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'stage':stage,'available_gib':round(m['MemAvailable']/1048576,3),'used_gib':round((m['MemTotal']-m['MemAvailable'])/1048576,3),'dstate':dstate}
 with out.open('a') as f:f.write(json.dumps(r)+'\n')
 return r
containers=json.loads(subprocess.check_output(['docker','inspect']+subprocess.check_output(['docker','ps','-q'],text=True).split()))
for c in containers:
 if c['HostConfig'].get('Runtime')=='nvidia' and c['Name'].lstrip('/') not in args.allow_peer:raise SystemExit('Isolation check failed: '+c['Name'])
if sample('baseline')['available_gib']<args.floor+15:raise SystemExit('Insufficient startup reserve')
if args.start_existing:subprocess.run(['docker','start',args.name],check=True)
else:subprocess.run(['docker','compose','-f',args.compose,'up','-d','--no-build','--pull','never'],check=True)
deadline=time.monotonic()+args.timeout;last=0;first_d=None;ready_since=None
try:
 while time.monotonic()<deadline:
  r=sample('loading');state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',args.name]))
  if r['available_gib']<args.floor:raise RuntimeError('memory floor crossed')
  bad=[x for x in r['dstate'] if any(s in x['comm'].lower() for s in ['nvfan','thermal','bpmp']) or 'bpmp' in x['wchan']]
  if bad:
   first_d=first_d or time.monotonic()
   if time.monotonic()-first_d>10:raise RuntimeError('persistent thermal/BPMP D state')
  else:first_d=None
  if not state['Running']:raise RuntimeError('container exited '+str(state.get('ExitCode')))
  ready=False
  try:
   with urllib.request.urlopen(args.url,timeout=2) as response:ready=response.status==200
  except Exception:pass
  if time.monotonic()-last>15:print(json.dumps(r),flush=True);last=time.monotonic()
  if ready:
   ready_since=ready_since or time.monotonic()
   if time.monotonic()-ready_since>=args.settle:
    print(json.dumps(sample('ready-settled')),flush=True);break
  else:ready_since=None
  time.sleep(2)
 else:raise RuntimeError('readiness timeout')
except BaseException:
 subprocess.run(['docker','stop','-t','15',args.name],timeout=25)
 raise
print('READY; model remains isolated for bounded inference probes',flush=True)
