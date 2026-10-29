"""Bounded GB10 numerical check against an independent CPU reference."""
import json
import os
from pathlib import Path
import sys
import time

if not os.environ.get('MOONDREAM_CHECK_LIBS'):
    site=Path(sys.prefix)/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    libs=sorted({str(p) for root in ('nvidia','nvpl') for p in (site/root).glob('**/lib') if p.is_dir()})
    os.environ['LD_LIBRARY_PATH']=':'.join(libs+[os.environ.get('LD_LIBRARY_PATH','')])
    os.environ['MOONDREAM_CHECK_LIBS']='1'
    os.execv(sys.executable,[sys.executable,*sys.argv])

root=Path(__file__).resolve().parents[2]
reserve=json.loads((root/'.spark/settings.json').read_text())['reserve_gib']
available=next(int(s.split()[1])/2**20 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))
if available<reserve+3:
    raise SystemExit('Need 3 GiB above the saved reserve for the small GPU check.')
import torch
from gb10_compat import fp8_moe_forward
from test_gb10_compat import interleave, oracle

torch.set_num_threads(2)
torch.manual_seed(47)
assert torch.cuda.get_device_capability()==(12,1)
records=[]
for tokens in (1,8,64):
    e,h,i,k=4,2048,1024,2
    x=(torch.randn(tokens,h)*.2).bfloat16()
    up=(torch.randn(e,2*i,h)*.05).to(torch.float8_e4m3fn)
    down=(torch.randn(e,h,i)*.05).to(torch.float8_e4m3fn)
    us=torch.rand(e,2*i)*.4+.1
    ds=torch.rand(e,h)*.4+.1
    ids=torch.randint(e,(tokens,k))
    routing=torch.rand(tokens,k)
    expected=oracle(x,ids,routing,up,down,us,ds)
    arrays=[x,ids,routing,interleave(up.view(torch.uint8),i),down.view(torch.uint8),interleave(us,i),ds]
    arrays=[v.cuda() for v in arrays]
    start=time.monotonic()
    actual=fp8_moe_forward(*arrays)
    torch.cuda.synchronize()
    elapsed=time.monotonic()-start
    actual=actual.cpu().float(); expected=expected.float()
    relative=((actual-expected).norm()/expected.norm()).item()
    cosine=torch.nn.functional.cosine_similarity(actual.flatten(),expected.flatten(),dim=0).item()
    records.append({'tokens':tokens,'experts':e,'hidden':h,'intermediate':i,'top_k':k,'relative_l2':relative,'cosine':cosine,'elapsed_s':elapsed,'max_abs':(actual-expected).abs().max().item()})
    assert relative<.01 and cosine>.999,records[-1]
    del arrays
print(json.dumps({'gpu':torch.cuda.get_device_name(),'passed':True,'cases':records,'cuda_peak_allocated_gib':torch.cuda.max_memory_allocated()/2**30},indent=2))
