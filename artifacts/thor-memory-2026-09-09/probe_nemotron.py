import argparse,json,time,urllib.request,pathlib,threading,subprocess
parser=argparse.ArgumentParser();parser.add_argument('--floor',type=float,default=80);parser.add_argument('--label',default='nemotron-probes-no-thinking');parser.add_argument('--context-lines',type=int,default=900);args=parser.parse_args();root=pathlib.Path(__file__).parent;done=threading.Event();samples=[]
def monitor():
 while not done.wait(1):
  m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1}
  g=m['MemAvailable']/1048576;samples.append(g)
  if g<args.floor:subprocess.run(['docker','stop','-t','10','vss-memory-nemotron']);return
thread=threading.Thread(target=monitor);thread.start()
cases=[('short',{'messages':[{'role':'user','content':'Reply with just the number: what is 20 plus 22?'}],'max_tokens':128}),('tool',{'messages':[{'role':'user','content':'Use lookup_video to get metadata for demo.mp4. Call the tool now.'}],'tools':[{'type':'function','function':{'name':'lookup_video','description':'Look up video metadata','parameters':{'type':'object','properties':{'filename':{'type':'string'}},'required':['filename']}}}],'tool_choice':'auto','max_tokens':256}),('long_context',{'messages':[{'role':'user','content':('Frame observation: one person walks past a stationary forklift.\n'*args.context_lines)+'Summarize the common observation in one sentence.'}],'max_tokens':128})]
results=[]
try:
 for repeat in range(2):
  for name,body in cases:
   body.update(model='nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8',temperature=0,chat_template_kwargs={'enable_thinking':False})
   start=time.monotonic();req=urllib.request.Request('http://127.0.0.1:30081/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(req,timeout=180) as response:r=json.load(response)
   msg=r['choices'][0]['message'];passed=(bool(msg.get('tool_calls')) and msg['tool_calls'][0]['function']['name']=='lookup_video') if name=='tool' else (msg.get('content','').strip()=='42' if name=='short' else bool(msg.get('content')) and r['choices'][0]['finish_reason']=='stop')
   result={'case':name,'repeat':repeat,'seconds':round(time.monotonic()-start,2),'passed':passed,'usage':r.get('usage'),'message':msg};results.append(result);print(json.dumps(result),flush=True)
   assert passed,result
finally:
 done.set();thread.join();(root/(args.label+'.json')).write_text(json.dumps({'results':results,'minimum_available_gib':min(samples) if samples else None},indent=2))
