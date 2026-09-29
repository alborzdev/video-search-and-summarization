#!/usr/bin/env python3
"""Operate the measured Thor VSS candidate without the legacy full-stack launcher."""
import argparse,json,os,pathlib,subprocess,sys,time,urllib.request
ROOT=pathlib.Path(__file__).resolve().parent
REPO=ROOT.parents[1]
BASE=['redis','vss-vios-postgres','kafka','elasticsearch','vss-graph-db',
 'vss-rtvi-cv','vss-rtvi-cv-traffic','vss-vios-sensor','vss-vios-streamprocessing',
 'vss-vios-ingress','vss-vios-sdr','vss-vios-mcp','logstash','vss-behavior-analytics',
 'vss-behavior-analytics-thor-candidates','vss-video-analytics-api','vss-va-mcp',
 'phoenix','prometheus','grafana','kibana','mdx-node-exporter-1','mdx-cadvisor-1',
 'tegrastats-exporter','vss-agent-ui','vss-haproxy-ingress']
MODELS=[('vss-memory-cosmos','isolated-cosmos.yml','http://127.0.0.1:8018/v1/health/ready'),
 ('vss-memory-nemotron','candidate-nemotron-32k.yml','http://127.0.0.1:30081/health'),
 ('vss-memory-embed','vss-memory-embed.yml','http://127.0.0.1:8017/v1/ready')]
TAIL=['vss-lvs','vss-alert-bridge','vss-agent']
LEGACY=['vss-rtvi-vlm','vss-nemotron-edge-4b','vss-rtvi-embed','mdx-evidence-clip-1']
NAMES=BASE+[x[0] for x in MODELS]+['vss-memory-support']+TAIL
PEERS=['vss-vios-nvstreamer','vss-rtvi-cv','vss-rtvi-cv-traffic','vss-vios-sensor','vss-vios-streamprocessing','tegrastats-exporter']+[x[0] for x in MODELS]
def run(args,**kwargs):return subprocess.run(args,cwd=REPO,check=True,**kwargs)
def available():return next(int(l.split()[1])/1048576 for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
def running():return set(subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines())
def healthy(url,timeout=5):
 try:
  with urllib.request.urlopen(url,timeout=timeout) as r:return r.status==200
 except Exception:return False
def elasticsearch_ready():
 try:
  with urllib.request.urlopen('http://127.0.0.1:9200/_cluster/health',timeout=5) as r:
   health=json.load(r)
  return health.get('status') in ('green','yellow') and health.get('unassigned_primary_shards')==0
 except Exception:return False
def public_ui_url():
 env=dict(line.split('=',1) for line in (REPO/'deploy/docker/thor-local/generated.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
 env.update(json.loads((ROOT/'lvs-compose-public-env.json').read_text()))
 return f"http://{env.get('VSS_PUBLIC_HOST', env.get('HOST_IP', 'localhost'))}:{env.get('VSS_PUBLIC_PORT', '7777')}/"
def status():
 containers=json.loads(subprocess.check_output(['docker','inspect']+NAMES));bad=[]
 for c in containers:
  state=c['State'];health=state.get('Health',{}).get('Status','running (no Docker health check)');name=c['Name'].lstrip('/');ok=state['Running'] and health not in ('unhealthy','starting');print(name,health if state['Running'] else state['Status'])
  if not ok:bad.append(name)
 if not elasticsearch_ready():bad.append('Elasticsearch primary-shard health')
 for name,_,url in MODELS:
  if not healthy(url):bad.append(name+' API')
 for name,url in [('Agent','http://127.0.0.1:8100/health'),('LVS','http://127.0.0.1:38111/v1/ready'),('Alert Bridge','http://127.0.0.1:9080/health'),('UI',public_ui_url()),('support','http://127.0.0.1:8098/health')]:
  # Source-mounted Next.js compiles the first page on demand (~8.5s measured).
  # Allow that cold page request without relaxing backend/model health probes.
  if not healthy(url,timeout=15 if name=='UI' else 5):bad.append(name+' API')
 print(f'{len(NAMES)} service roles; {available():.2f} GiB available; failures: {bad}')
 return not bad
def guard():
 if subprocess.run(['systemctl','--user','is-active','--quiet','vss-memory-budget']).returncode:
  run(['systemctl','--user','start','vss-memory-budget.service'])
def start():
 active=running()
 if active.intersection(LEGACY):raise SystemExit('Stop the original model/support containers before using this candidate: '+str(active.intersection(LEGACY)))
 guard()
 run([sys.executable,str(ROOT/'start_services.py'),*BASE,'--floor','48'])
 active=running()
 if not active.intersection(x[0] for x in MODELS) and available()<90:raise SystemExit('Cold model startup needs at least 90 GiB available after supporting services settle. Stop and reclaim first.')
 # Start both smaller models before Cosmos to retain isolated startup headroom.
 for name,compose,url in sorted(MODELS, key=lambda m: {'vss-memory-nemotron': 0, 'vss-memory-embed': 1, 'vss-memory-cosmos': 2}[m[0]]):
  if name in running():
   if not healthy(url):raise SystemExit(name+' is running but not ready; inspect before restarting')
   continue
  args=[sys.executable,str(ROOT/'run_isolated.py'),'--name',name,'--compose',str(ROOT/compose),'--url',url,'--floor','48','--timeout','600']
  for peer in PEERS:
   if peer!=name:args+=['--allow-peer',peer]
  run(args)
 run(['docker','compose','-f',str(ROOT/'vss-memory-support.yml'),'up','-d','--no-build','--pull','never'])
 cmd=json.loads((ROOT/'lvs-compose-command.json').read_text());env=dict(os.environ,**json.loads((ROOT/'lvs-compose-public-env.json').read_text()))
 run(cmd+['up','-d','--no-deps','--no-build','--pull','never','lvs-server'],env=env)
 deadline=time.monotonic()+180
 while not healthy('http://127.0.0.1:38111/v1/ready'):
  if time.monotonic()>deadline:raise SystemExit('LVS readiness timed out')
  time.sleep(2)
 run([sys.executable,str(ROOT/'start_services.py'),*TAIL,'--floor','48'])
 if not status():raise SystemExit('At least one service has not reached readiness; inspect its logs.')
def stop():
 subprocess.run(['systemctl','--user','stop','vss-memory-budget'],check=False)
 active=running()
 for name in list(reversed(NAMES))+LEGACY:
  if name in active:run(['docker','stop','-t','15',name])
 before=available()
 run(['docker','run','--rm','--network','none','-v','/proc/sys/vm/drop_caches:/host-drop-caches','--entrypoint','sh','redis:8.6.2-alpine','-c','echo 2 > /host-drop-caches'])
 print(f'VSS stopped, persistent data preserved. One-time idle reclaim: {before:.2f} -> {available():.2f} GiB available.')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['status','start','stop'])
 p.add_argument('--profile',choices=['core','full'],default='core',help='Core is the browser-development default; full includes both detectors and is not sustained-load qualified.')
 a=p.parse_args()
 if a.profile=='core' and a.action!='stop':
  detectors={'vss-rtvi-cv','vss-rtvi-cv-traffic'}
  BASE[:]=[name for name in BASE if name not in detectors]
  NAMES[:]=[name for name in NAMES if name not in detectors]
 if a.action=='status':raise SystemExit(0 if status() else 1)
 {'start':start,'stop':stop}[a.action]()
