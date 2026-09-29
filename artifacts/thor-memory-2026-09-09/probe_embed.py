import base64,json,time,urllib.request,urllib.error,pathlib,threading,subprocess,uuid,math,argparse
p=argparse.ArgumentParser();p.add_argument('--label',default='batch2');p.add_argument('--container',default='vss-memory-embed');p.add_argument('--floor',type=float,default=80);args=p.parse_args();root=pathlib.Path(__file__).parent;done=threading.Event();samples=[]
def monitor():
 while not done.wait(.5):
  m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1};g=m['MemAvailable']/1048576;samples.append(g)
  with (root/('embed-'+args.label+'-memory.jsonl')).open('a') as f:f.write(json.dumps({'time':time.time(),'available_gib':g})+'\n')
  if g<args.floor:subprocess.run(['docker','stop','-t','10',args.container]);return
thread=threading.Thread(target=monitor);thread.start();results=[];owned=[]
def call(path,body=None,method=None):
 req=urllib.request.Request('http://127.0.0.1:8017'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
 try:
  with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
 except urllib.error.HTTPError as e:
  body=e.read().decode()
  if method=='DELETE' and e.code==400 and 'No such resource' in body:return {'already_absent':True}
  raise
def vectors(value):
 found=[]
 if isinstance(value,dict):
  for k,v in value.items():
   if k=='embeddings' and isinstance(v,list) and v and isinstance(v[0],(float,int)):found.append(v)
   else:found+=vectors(v)
 elif isinstance(value,list):
  for v in value:found+=vectors(v)
 return found
try:
 model='cosmos-embed1-448p-anomaly-detection'
 for repeat in range(3):
  uid=str(uuid.uuid4());owned.append(uid)
  with (root/'owned-embedding-probes.jsonl').open('a') as ledger:ledger.write(json.dumps({'id':uid,'label':args.label})+'\n')
  body={'id':uid,'url':'data:video/mp4;base64,'+base64.b64encode(pathlib.Path('services/alert/warmup/test.mp4').read_bytes()).decode(),'media_type':'video','creation_time':'2025-01-01T00:00:00.000Z','model':model,'stream':False,'chunk_duration':5,'chunk_overlap_duration':1}
  for name,route,payload,expected in [('text','/v1/generate_text_embeddings',{'text_input':['a white car driving on a road','a person walking near a building'],'model':model},2),('video','/v1/generate_video_embeddings',body,3)]:
   start=time.monotonic();r=call(route,payload);vs=vectors(r);ok=len(vs)==expected and all(len(v)==768 and all(math.isfinite(x) for x in v) for v in vs)
   row={'case':name,'repeat':repeat,'seconds':round(time.monotonic()-start,2),'vectors':len(vs),'dimensions':[len(v) for v in vs],'passed':ok,'response_keys':list(r)};results.append(row);print(json.dumps(row),flush=True)
   if not ok:(root/'embed-unexpected-response.json').write_text(json.dumps(r));raise RuntimeError('embedding vector contract failed')
  call('/v1/files/'+uid,method='DELETE');owned.remove(uid)
finally:
 for uid in owned:
  try:call('/v1/files/'+uid,method='DELETE')
  except Exception as e:print('cleanup failed',uid,str(e),flush=True)
 done.set();thread.join();(root/('embed-'+args.label+'-probes.json')).write_text(json.dumps({'results':results,'minimum_available_gib':min(samples) if samples else None,'owned_remaining':owned},indent=2))
