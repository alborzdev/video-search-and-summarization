#!/usr/bin/env python3
"""CPU-only CLI rejection controls. Never initialize GStreamer or open sources."""
import json
from pathlib import Path
import subprocess

worker=Path(__file__).resolve().parents[1]/'city-worker'
base=[str(worker),'--source','camera=file:///does-not-exist.mp4','--output','/tmp/not-created-preview-observations']
controls={
    'zero-fps':['--preview-fps','0'],
    'over-limit-fps':['--preview-fps','31'],
    'non-integer-fps':['--preview-fps','15junk'],
    'negative-fps':['--preview-fps','-1'],
    'credential-url':['--preview-url','http://fixture:unused@127.0.0.1:9184/api/v1/city/preview'],
    'wrong-endpoint':['--preview-url','http://127.0.0.1:9184/api/v1/city/not-preview'],
    'header-newline':['--preview-url','http://127.0.0.1:9184/api/v1/city/preview','--model-revision','model\r\nInjected: fixture'],
}
for name,options in controls.items():
    result=subprocess.run(base+options,capture_output=True,text=True,timeout=5)
    assert result.returncode==1,(name,result.returncode)
    assert 'Starting RF-DETR' not in result.stderr,name
    assert 'must be' in result.stderr or 'safe bounded header' in result.stderr,name
help_result=subprocess.run([str(worker),'--help'],capture_output=True,text=True,timeout=5)
assert help_result.returncode==0 and all(flag in help_result.stdout for flag in ['--preview-url','--preview-fps','--preview-stats-file'])
print(json.dumps({'cpuOnly':True,'invalidPreviewOptionsRejectedBeforeGstreamer':list(controls),'helpPassed':True}))
