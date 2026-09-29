import argparse,json,pathlib,time,uuid,requests
p=argparse.ArgumentParser();p.add_argument('--repeat',type=int,default=3);a=p.parse_args();root=pathlib.Path(__file__).parent;base='http://127.0.0.1:38111';video=pathlib.Path('deploy/docker/data-dir/videos/nvstreamer/warehouse_safety_0001.mp4');results=[]
def call(method,path,**kw):
 r=requests.request(method,base+path,timeout=600,**kw);r.raise_for_status();return r.json()
baseline=call('GET','/files?purpose=vision');(root/'lvs-files-before.json').write_text(json.dumps(baseline,indent=2))
try:
 for i in range(a.repeat):
  uid=str(uuid.uuid4());name='thor-memory-'+uid;record={'id':uid,'repeat':i};results.append(record);(root/'lvs-owned-ids.json').write_text(json.dumps([x['id'] for x in results]))
  try:
   with video.open('rb') as f:record['upload']=call('POST','/files',data={'purpose':'vision','media_type':'video','id':uid,'sensor_name':name},files={'file':(name+'.mp4',f,'video/mp4')})
   assert record['upload']['id']==uid,record['upload']
   body={'id':uid,'model':'nim_nvidia_cosmos3-nano-reasoner_bf16-final','prompt':'Describe the visible actions in chronological order. Include the beginning and ending events and do not invent objects.','scenario':'A worker in a warehouse near boxes and a rolling ladder.','events':['visible actions by the warehouse worker'],'objects_of_interest':['worker','boxes','rolling ladder'],'chunk_duration':5,'max_tokens':128,'temperature':0.0,'top_p':1.0,'seed':1,'override_vlm_prompt':True,'enable_vlm_structured_output':False,'enable_qa':False}
   start=time.monotonic();record['summary']=call('POST','/v1/summarize',json=body);record['seconds']=time.monotonic()-start;r=record['summary'];u=r.get('usage',{})
   assert r['object']=='summarization.completion' and r['choices'][0]['message']['content'] and u.get('total_chunks_processed',0)>0 and u.get('summary_requests',0)>0 and u.get('summary_tokens',0)>0,r
   print(json.dumps(record),flush=True)
  finally:
   record['cleanup']=call('DELETE','/files/'+uid);assert record['cleanup'].get('deleted') is True,record['cleanup']
   (root/'combined-lvs-probes.json').write_text(json.dumps(results,indent=2))
finally:
 (root/'lvs-files-after.json').write_text(json.dumps(call('GET','/files?purpose=vision'),indent=2))
