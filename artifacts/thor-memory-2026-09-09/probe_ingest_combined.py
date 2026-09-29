import json,pathlib,time,uuid,requests,math,datetime
root=pathlib.Path(__file__).parent;base='http://127.0.0.1:8100';video=pathlib.Path('deploy/docker/data-dir/videos/nvstreamer/warehouse_safety_0001.mp4');name='thor-memory-'+str(uuid.uuid4())+'.mp4';record={'filename':name};sensor=None
def save(): (root/('combined-ingest-'+name+'.json')).write_text(json.dumps(record,indent=2))
def call(method,url,**kw):
 r=requests.request(method,url if url.startswith('http') else base+url,timeout=620,**kw)
 if not r.ok:raise RuntimeError((r.status_code,r.text[:4000]))
 return r.json()
try:
 record['handshake']=call('POST','/api/v1/videos',json={'filename':name});save()
 headers={'nvstreamer-chunk-number':'1','nvstreamer-total-chunks':'1','nvstreamer-is-last-chunk':'true','nvstreamer-identifier':str(uuid.uuid4()),'nvstreamer-file-name':name}
 with video.open('rb') as f:record['upload']=call('POST',record['handshake']['url'],headers=headers,data={'filename':name,'metadata':json.dumps({'timestamp':datetime.datetime.now().replace(microsecond=0).isoformat()})},files={'mediaFile':(name,f,'video/mp4')})
 save();print(json.dumps(record['upload']),flush=True);sensor=record['upload']['sensorId'];record['sensor_id']=sensor;save()
 start=time.monotonic();record['complete']=call('POST',f'/api/v1/videos/{sensor}/complete',json={'filename':name,'analysisProfileId':'semantic-search'});record['complete_seconds']=time.monotonic()-start;save();print(json.dumps(record['complete']),flush=True)
 assert record['complete']['chunks_processed']>0,record['complete']
 def search(query):return call('POST','/api/v1/embed_search',json={'source_type':'video_file','params':{'query':query,'video_sources':json.dumps([sensor]),'top_k':'5','min_cosine_similarity':'0.0'}})
 deadline=time.monotonic()+120
 while True:
  record['relevant_search']=search('A warehouse worker wearing a yellow safety vest stands near a rolling ladder and shelves of boxes.');save()
  if record['relevant_search'].get('results'):break
  if time.monotonic()>deadline:raise RuntimeError('No indexed search results after 120 seconds')
  time.sleep(3)
 record['unrelated_search']=search('A dolphin swimming underwater in the ocean.');save()
 for r in record['relevant_search']['results']:
  assert r['sensor_id']==sensor and math.isfinite(r['similarity_score']) and r['start_time'] and r['end_time'],r
 record['playback_checks']=[]
 for hit in record['relevant_search']['results'][:1]:
  response=requests.get(hit['screenshot_url'],timeout=45);record['playback_checks'].append({'url':hit['screenshot_url'],'status':response.status_code,'content_type':response.headers.get('content-type'),'bytes':len(response.content)});save();assert response.ok and response.headers.get('content-type','').startswith('image/') and len(response.content)>1000,record['playback_checks']
 time.sleep(10)
 print(json.dumps({k:v['results'] for k,v in record.items() if k.endswith('search')}),flush=True)
finally:
 if sensor:
  record['cleanup']=call('DELETE',f'/api/v1/videos/{sensor}');save();print(json.dumps(record['cleanup']),flush=True);assert record['cleanup']['status']=='success',record['cleanup']
 else:save()
