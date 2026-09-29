import base64,json,pathlib,subprocess,time,urllib.request
root=pathlib.Path("/home/nvidia/cti-saa-thor/video-search-and-summarization")
subprocess.run(["systemctl","--user","is-active","--quiet","vss-memory-budget"],check=True)
def req(route,body=None):
 r=urllib.request.Request("http://127.0.0.1:8018"+route,data=None if body is None else json.dumps(body).encode(),headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(r,timeout=40) as s:return json.load(s)
def mem():return next(int(x.split()[1])/1048576 for x in pathlib.Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemAvailable:"))
assert req("/v1/stream/get-stream-info")["stream_count"]==0
model=req("/v1/models")["data"][0]["id"]
clip=root/"artifacts/demo-boundary-probe-2026-09-28/live-miss-5.mp4"
url="data:video/mp4;base64,"+base64.b64encode(clip.read_bytes()).decode()
prompt="Does any frame in this video show a box on the conveyor belt? Answer YES if at least one frame shows a box, otherwise NO. Answer YES or NO only."
rows=[]
for temperature,seed in [(0,42),(.4,1),(.4,1),(0,42)]:
 assert mem()>=49.3,"Insufficient headroom"
 body={"model":model,"messages":[{"role":"system","content":"Answer yes or no"},{"role":"user","content":[{"type":"video_url","video_url":{"url":url}},{"type":"text","text":prompt}]}],"max_tokens":128,"temperature":temperature,"seed":seed,"chunk_duration":0,"enable_audio":False,"enable_reasoning":False,"num_frames_per_second_or_fixed_frames_chunk":4,"use_fps_for_chunking":False,"vlm_input_width":512,"vlm_input_height":512}
 start=time.monotonic();reply=req("/v1/chat/completions",body)
 row={"temperature":temperature,"seed":seed,"answer":reply["choices"][0]["message"]["content"],"seconds":round(time.monotonic()-start,3),"availableGiB":mem()};rows.append(row);print(row,flush=True)
 (root/"docs/qa/demo-transformation-2026-09-28/seed-miss-recheck.json").write_text(json.dumps(rows,indent=2))
