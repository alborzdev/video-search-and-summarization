import json,pathlib,time,subprocess,requests,datetime
root=pathlib.Path(__file__).parent;start=datetime.datetime.now(datetime.timezone.utc).isoformat();t=time.monotonic()
r=requests.post('http://127.0.0.1:8100/generate',json={'input_message':'Call vst_video_list to list the currently available recorded videos. Do not inspect or summarize footage. Report the returned names, or say no recordings if the tool returns none.'},timeout=240)
record={'http_status':r.status_code,'seconds':time.monotonic()-t,'body':r.text};(root/'combined-agent-probe.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True)
logs=subprocess.run(['docker','logs','--since',start,'--tail','400','vss-agent'],capture_output=True,text=True,timeout=15);(root/'combined-agent-probe.log').write_text(logs.stdout+logs.stderr);r.raise_for_status()
print('Tool execution log evidence must be reviewed before calling this a pass.',flush=True)
