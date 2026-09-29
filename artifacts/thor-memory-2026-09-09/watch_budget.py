"""Temporary combined-trial watchdog; no periodic cache dropping."""
import argparse,json,pathlib,subprocess,time
p=argparse.ArgumentParser();p.add_argument('--floor',type=float,default=36);p.add_argument('--seconds',type=float,default=3600);args=p.parse_args();root=pathlib.Path(__file__).parent;deadline=time.monotonic()+args.seconds
names=['vss-memory-embed','vss-memory-nemotron','vss-memory-cosmos']
while time.monotonic()<deadline:
 m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1};g=m['MemAvailable']/1048576
 stale=time.time()-(root/'tegrastats.log').stat().st_mtime
 r={'time':time.time(),'available_gib':g,'thermal_sample_age_seconds':round(stale,2)}
 with (root/'combined-memory.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
 if g<args.floor or stale>20:
  r['stop_reason']='memory floor' if g<args.floor else 'thermal telemetry stalled';print(json.dumps(r),flush=True);(root/'combined-watchdog-stop.json').write_text(json.dumps(r,indent=2))
  for name in names:
   try:subprocess.run(['docker','stop','-t','8',name],timeout=12,capture_output=True)
   except subprocess.TimeoutExpired:pass
  raise SystemExit(2)
 time.sleep(1)
print('Trial watchdog duration ended; final state must be reviewed.',flush=True)
