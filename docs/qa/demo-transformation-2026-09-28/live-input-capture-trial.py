import argparse,concurrent.futures,datetime,json,pathlib,time,urllib.request,subprocess
base='http://127.0.0.1:9080/api/v1/realtime'; sid='6776f3a6-446f-4da8-832e-cfcf4507de8c'; tag='box_any_frame_qualification'
parser=argparse.ArgumentParser(description='Bounded live-input capture trial; requires a fresh capture directory.')
parser.add_argument('--output',type=pathlib.Path,required=True)
parser.add_argument('--chunk-seconds',type=int,choices=[5,10],default=10)
parser.add_argument('--duration-seconds',type=int,choices=[50,90],default=90)
args=parser.parse_args()
out=args.output
if out.exists():raise SystemExit('Refusing to overwrite an existing trial receipt')
if not out.parent.is_dir():raise SystemExit('Output parent directory must exist')
def req(url,method='GET',body=None,timeout=10):
 r=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),method=method,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=timeout) as f:return json.load(f)
def mem():return next(int(x.split()[1])/1048576 for x in pathlib.Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
def boot():return pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert subprocess.run(['systemctl','--user','is-active','--quiet','vss-memory-budget']).returncode == 0
sources=req('http://10.88.9.12:7777/vst/api/v1/live/streams')
matching=[stream for item in sources for stream in item.get(sid,[]) if stream.get('isMain')]
assert len(matching)==1
source_url=matching[0]['url']
container=json.loads(subprocess.check_output(['docker','inspect','vss-memory-cosmos']))[0]
capture_env=dict(value.split('=',1) for value in container['Config']['Env'] if '=' in value)
assert capture_env.get('RTVI_CAPTURE_SOURCE_URL')==source_url, 'Capture source differs from current VIOS source'
assert capture_env.get('RTVI_CAPTURE_INPUTS_DIR'), 'Capture directory not configured'
assert subprocess.run(['docker','exec','vss-memory-cosmos','test','!', '-e',capture_env['RTVI_CAPTURE_INPUTS_DIR']+'/.started']).returncode==0, 'Use a fresh capture directory'
subprocess.run(['ffprobe','-v','error','-rtsp_transport','tcp','-show_entries','stream=codec_name,width,height','-of','json',source_url],check=True,timeout=15)
assert not req(base)['rules']
assert req('http://127.0.0.1:8018/v1/stream/get-stream-info')['stream_count']==0
assert mem()>=49.3
payload={'sensor_id':sid,'sensor_name':'Conveyor — Recorded Simulation (RTSP Replay)','live_stream_url':source_url,'alert_type':tag,'prompt':'Does any frame in this video show a box on the conveyor belt? Answer YES if at least one frame shows a box, otherwise NO. Answer YES or NO only.','system_prompt':'Answer yes or no','chunk_duration':10,'chunk_overlap_duration':2,'num_frames_per_second_or_fixed_frames_chunk':4,'use_fps_for_chunking':False,'vlm_input_width':512,'vlm_input_height':512,'enable_reasoning':False,'enable_audio':False,'max_tokens':128}
payload['chunk_duration']=args.chunk_seconds
start=time.monotonic(); result={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':boot(),'profile':{k:v for k,v in payload.items() if k!='live_stream_url'},'samples':[],'cleanup':[]}; ids=set();first=None
pool=concurrent.futures.ThreadPoolExecutor(1); future=pool.submit(req,base,'POST',payload,65)
print(f'Trial started: {args.chunk_seconds}s cadence, {args.duration_seconds}s maximum after creation; stop below 48.75 GiB',flush=True)
try:
 while time.monotonic()-start<110:
  elapsed=time.monotonic()-start
  if future.done() and 'creation' not in result:
   result['creation']=future.result();ids.add(result['creation']['id']);first=time.monotonic();print('Created rule',result['creation']['id'],flush=True)
  available=mem();result['samples'].append({'elapsed':round(elapsed,2),'available_gib':round(available,3)})
  out.write_text(json.dumps(result,indent=2))
  if available<48.75:result['stop_reason']='early memory cutoff';break
  if boot()!=result['boot_id']:result['stop_reason']='boot changed';break
  if first and time.monotonic()-first>=args.duration_seconds:result['stop_reason']=f'{args.duration_seconds}-second limit';break
  time.sleep(1)
 else:result['stop_reason']='110-second deadline'
except Exception as e:result['error']=str(e)
finally:
 try:
  # Await the one in-flight create, then remove only this trial's exact tag/source.
  try:result.setdefault('creation',future.result(timeout=65))
  except Exception as e:result['creation_error']=str(e)
  ids.update(x['id'] for x in req(base)['rules'] if x.get('sensor_id')==sid and x.get('alert_type')==tag)
  for rid in ids:result['cleanup'].append({'id':rid,'result':req(base+'/'+rid,'DELETE',timeout=70)})
  result['remaining_rules']=req(base)['rules']
  result['stream_state']=req('http://127.0.0.1:8018/v1/stream/get-stream-info')
 except Exception as e:result['cleanup_error']=str(e)
 result['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();result['final_available_gib']=round(mem(),3);result['final_boot_id']=boot();out.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['samples','profile']}),flush=True)
 pool.shutdown(wait=True)
