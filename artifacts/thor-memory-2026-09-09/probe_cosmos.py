import argparse,base64,json,time,urllib.request,pathlib,threading,subprocess,importlib.util
parser=argparse.ArgumentParser();parser.add_argument('--label',default='cosmos');parser.add_argument('--floor',type=float,default=65);args=parser.parse_args();root=pathlib.Path(__file__).parent;done=threading.Event();samples=[]
def monitor():
 while not done.wait(1):
  m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1};g=m['MemAvailable']/1048576;samples.append(g)
  with (root/(args.label+'-inference-memory.jsonl')).open('a') as f:f.write(json.dumps({'time':time.time(),'available_gib':g})+'\n')
  if g<args.floor:subprocess.run(['docker','stop','-t','10','vss-memory-cosmos']);return
spec=importlib.util.spec_from_file_location('identity_probe','deploy/docker/thor-local/qualification/official-edge-model-identities-runtime/execute.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
contract=json.loads(pathlib.Path('deploy/docker/thor-local/qualification/official-edge-model-identities-runtime/contract.json').read_text());colors,_=module._vlm_payload(contract)
frames=[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode()}} for p in sorted((root/'frames').glob('warehouse-*.jpg'))]
video={'model':colors['model'],'messages':[{'role':'user','content':[{'type':'text','text':'These are four ordered frames from a warehouse video, sampled six seconds apart. Describe the people, vehicles, and their movements in at most three sentences. State only what is visible.'}]+frames}],'temperature':0,'max_tokens':256}
thread=threading.Thread(target=monitor);thread.start();results=[]
try:
 for repeat in range(3):
  for name,body in [('color_oracle',colors),('four_video_frames',video)]:
   start=time.monotonic();req=urllib.request.Request('http://127.0.0.1:8018/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(req,timeout=180) as response:r=json.load(response)
   text=r['choices'][0]['message'].get('content','');passed=bool(text) and r['choices'][0]['finish_reason']=='stop'
   if name=='color_oracle':
    expected=[p['name'] if 'name' in p else p.get('color','') for p in contract['semantic_contract']['vlm_composite_image']['panels']]
    expected=[x.lower() for x in expected if x];passed=passed and all(x in text.lower() for x in expected)
   result={'case':name,'repeat':repeat,'seconds':round(time.monotonic()-start,2),'passed':passed,'response':r};results.append(result);print(json.dumps(result),flush=True)
   assert passed,result
finally:
 done.set();thread.join();(root/(args.label+'-probes.json')).write_text(json.dumps({'results':results,'minimum_available_gib':min(samples) if samples else None},indent=2))
