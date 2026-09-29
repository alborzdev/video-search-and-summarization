"""Host memory and thermal-liveness guard for the measured VSS configuration."""
import json,pathlib,subprocess,time,threading,signal
ROOT=pathlib.Path(__file__).resolve().parent
MODELS=['vss-memory-embed','vss-memory-nemotron','vss-memory-cosmos']
FLOOR=36
last=[time.monotonic()];done=threading.Event()
thermal=subprocess.Popen(['tegrastats','--interval','1000'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
def receive():
 for line in thermal.stdout:
  last[0]=time.monotonic()
threading.Thread(target=receive,daemon=True).start()
def end(*_):done.set()
signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
try:
 while not done.wait(2):
  mem={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(l.split())>1};available=mem['MemAvailable']/1048576
  reason='memory reserve below 36 GiB' if available<FLOOR else ('thermal telemetry stalled' if time.monotonic()-last[0]>20 else None)
  if reason:
   event={'time':time.time(),'reason':reason,'available_gib':available};print(json.dumps(event),flush=True);(ROOT/'runtime-guard-stop.json').write_text(json.dumps(event,indent=2))
   for name in MODELS:
    try:subprocess.run(['docker','stop','-t','8',name],timeout=12,capture_output=True)
    except subprocess.TimeoutExpired:pass
   break
finally:
 thermal.terminate()
 try:thermal.wait(3)
 except subprocess.TimeoutExpired:thermal.kill()
