import json,pathlib,time,uuid,requests,subprocess,threading,socket,urllib.parse
root=pathlib.Path(__file__).parent;name='thor-memory-live-'+str(uuid.uuid4());helper='vss-memory-live-publisher';record={'name':name};publisher=None;added=False;uid=None;response=None

def save(): (root/'combined-live-probe.json').write_text(json.dumps(record,indent=2))
def call(method,url,**kw):
 r=requests.request(method,url,timeout=180,**kw)
 if not r.ok:raise RuntimeError((r.status_code,r.text[:2000]))
 return r.json() if r.content else {'http_status':r.status_code}
try:
 subprocess.run(['docker','run','-d','--name',helper,'--network','mdx_default','sha256:35f9e8aefaca5352b5f4667c8cd529360a53a493c51fa639e8f5898c03bc0d06'],check=True,capture_output=True)
 ip=subprocess.check_output(['docker','inspect','--format','{{(index .NetworkSettings.Networks "mdx_default").IPAddress}}',helper],text=True).strip()
 for _ in range(20):
  try:
   with socket.create_connection((ip,8554),timeout=1):break
  except OSError:time.sleep(.5)
 url=f'rtsp://{ip}:8554/{name}';log=(root/'live-publisher.log').open('w');publisher=subprocess.Popen(['/usr/bin/ffmpeg','-hide_banner','-loglevel','error','-re','-stream_loop','-1','-i','deploy/docker/data-dir/videos/nvstreamer/warehouse_safety_0001.mp4','-an','-c:v','copy','-f','rtsp','-rtsp_transport','tcp',url],stdout=subprocess.DEVNULL,stderr=log);time.sleep(2);assert publisher.poll() is None
 record['add']=call('POST','http://127.0.0.1:8100/api/v1/rtsp-streams/add',json={'sensorUrl':url,'name':name,'analysisProfileId':'warehouse-safety'});save();print(json.dumps(record['add']),flush=True);assert record['add']['status']=='success',record['add'];added=True;uid=record['add']['sensorId']
 record['cv']=call('GET','http://127.0.0.1:9000/api/v1/stream/get-stream-info');record['embed']=call('GET','http://127.0.0.1:8017/v1/streams/get-stream-info');record['vlm']=call('GET','http://127.0.0.1:8018/v1/streams/get-stream-info');save()
 body={'id':uid,'model':'nim_nvidia_cosmos3-nano-reasoner_bf16-final','prompt':'Briefly describe only visible actions by the warehouse worker.','chunk_duration':5,'max_tokens':96,'temperature':0,'stream':True};record['caption_events']=[]
 response=requests.post('http://127.0.0.1:8018/v1/generate_captions',json=body,stream=True,timeout=(30,30));response.raise_for_status();deadline=time.monotonic()+60;overlap=None
 def agent():
  try:record['overlapping_agent']=call('POST','http://127.0.0.1:8100/generate',json={'input_message':'Use vst_video_list to list available video names. Do not analyze footage.'})
  except Exception as e:record['overlapping_agent_error']=str(e)
  save()
 overlap=threading.Thread(target=agent);overlap.start()
 for line in response.iter_lines(chunk_size=1,decode_unicode=True):
  if line and line.startswith('data:'):
   raw=line[5:].strip()
   if raw!='[DONE]':
    try:record['caption_events'].append(json.loads(raw));save()
    except ValueError:pass
  if time.monotonic()>deadline:break
 response.close();response=None;record['caption_stop']=call('DELETE','http://127.0.0.1:8018/v1/generate_captions/'+uid);overlap.join(190);assert not overlap.is_alive();save()
 record['detection_index']=call('POST','http://127.0.0.1:9200/mdx-raw-*/_search',json={'size':1,'query':{'bool':{'should':[{'term':{'sensorId':name}},{'term':{'sensorId.keyword':name}}],'minimum_should_match':1}},'_source':['sensorId','timestamp','objects.type','objects.confidence']});save()
 record['live_search']=call('POST','http://127.0.0.1:8100/api/v1/embed_search',json={'source_type':'rtsp','params':{'query':'A worker wearing a yellow safety vest in a warehouse.','video_sources':json.dumps([name]),'top_k':'5','min_cosine_similarity':'0.0'}});save();assert record['live_search'].get('results'),record['live_search'];print(json.dumps({'caption_events':len(record['caption_events']),'search_results':record['live_search']['results'],'agent_error':record.get('overlapping_agent_error')}),flush=True)
finally:
 if response:response.close()
 if added:
  try:record['cleanup']=call('DELETE','http://127.0.0.1:8100/api/v1/rtsp-streams/delete/'+urllib.parse.quote(name,safe=''))
  except Exception as e:record['cleanup_error']=str(e)
 if publisher:
  publisher.terminate()
  try:publisher.wait(8)
  except subprocess.TimeoutExpired:publisher.kill();publisher.wait()
 subprocess.run(['docker','rm','-f',helper],capture_output=True);save()
