"""Copy a stopped local container into a separate, credential-free test definition."""
import argparse,json,subprocess,pathlib,yaml
p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('target');p.add_argument('--env',action='append',default=[]);args=p.parse_args()
c=json.loads(subprocess.check_output(['docker','inspect',args.source]))[0]
if c['State']['Running']:raise SystemExit('Source must be stopped')
h=c['HostConfig'];cfg=c['Config'];env={k:v for e in cfg['Env'] for k,_,v in [e.partition('=')]}
for k in list(env):
 if k.endswith(('_API_KEY','_TOKEN','_PASSWORD','_SECRET')):env[k]=''
for override in args.env:k,sep,v=override.partition('=');assert sep;env[k]=v
vols=[];ext={}
for m in c['Mounts']:
 if m['Type']=='bind':vols.append({'type':'bind','source':m['Source'],'target':m['Destination'],'read_only':not m['RW']})
 elif m['Type']=='volume':
  key='existing'+str(len(ext));ext[key]={'external':True,'name':m['Name']};vols.append({'type':'volume','source':key,'target':m['Destination'],'read_only':not m['RW']})
svc={'image':c['Image'],'container_name':args.target,'runtime':h['Runtime'],'restart':'no','oom_score_adj':500,'environment':env,'volumes':vols}
for key,val in [('entrypoint',cfg.get('Entrypoint')),('command',cfg.get('Cmd')),('working_dir',cfg.get('WorkingDir')),('user',cfg.get('User')),('extra_hosts',h.get('ExtraHosts'))]:
 if val:svc[key]=val
if h.get('IpcMode')=='host':svc['ipc']='host'
else:svc['shm_size']=h.get('ShmSize',67108864)
if h.get('ReadonlyRootfs'):svc['read_only']=True
if h.get('Tmpfs'):svc['tmpfs']=[k+':'+v for k,v in h['Tmpfs'].items()]
doc={'name':args.target,'services':{'test':svc}}
if ext:doc['volumes']=ext
if h['NetworkMode']=='host':svc['network_mode']='host'
else:
 svc['networks']=['existing'];doc['networks']={'existing':{'external':True,'name':h['NetworkMode']}}
 svc['ports']=[f"{binding.get('HostIp') or '127.0.0.1'}:{binding['HostPort']}:{port}" for port,bindings in (h.get('PortBindings') or {}).items() for binding in bindings]
path=pathlib.Path(__file__).parent/(args.target+'.yml');path.write_text(yaml.safe_dump(doc,sort_keys=False));path.chmod(0o600);print(path)
