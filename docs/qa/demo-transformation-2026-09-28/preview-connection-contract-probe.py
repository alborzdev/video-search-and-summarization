import ast, asyncio, logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import HTTPException
from contextlib import nullcontext

source=Path('services/agent/src/vss_agents/api/rtsp_ingest.py').read_text()
names={'AddStreamRequest','AddStreamResponse','add_to_vst','create_rtsp_ingest_router'}
nodes=[n for n in ast.parse(source).body if isinstance(n,(ast.ClassDef,ast.AsyncFunctionDef,ast.FunctionDef)) and n.name in names]
class Router:
 def __init__(self):self.routes=[]
 def post(self,*a,**k):return lambda f:(self.routes.append(SimpleNamespace(endpoint=f)) or f)
 def delete(self,*a,**k):return lambda f:f
class CapacityError(Exception):pass
paused={}
profile=SimpleNamespace(id='semantic-search',name='Search',detection_enabled=False)
ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,model_validator=model_validator,Literal=Literal,
 APIRouter=Router,ServiceConfig=SimpleNamespace,HTTPException=HTTPException,asyncio=asyncio,
 WAREHOUSE_PROFILE_ID='warehouse-safety',SEMANTIC_PROFILE_ID='semantic-search',
 require_analysis_profile=lambda _:profile,detector_endpoint_for_profile=lambda *_:'',
 AnalysisProfileCapacityError=CapacityError,reserve_analysis_profile_capacity=Mock(return_value='reservation'),
 commit_analysis_profile_capacity_reservation=Mock(),release_analysis_profile_capacity_reservation=Mock(),
 set_source_kind=Mock(),set_source_paused=lambda i,v:paused.update({i:v}),
 forget_source_analysis_state=lambda i:paused.pop(i,None),logger=logging.getLogger('probe'),scrub_log=lambda v:v,
 TimeMeasure=lambda _:nullcontext(),_is_nvstream_url=lambda _:False)
code=compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])),'<actual-preview-source>','exec')
exec(code,ns)
ns["AddStreamRequest"].model_rebuild(_types_namespace=ns)
ns["AddStreamResponse"].model_rebuild(_types_namespace=ns)
async def main():
 ns['_source_catalog_lock']=asyncio.Lock()
 async def create(**kw):
  assert ns['_source_catalog_lock'].locked()
  return True,'OK','preview-source'
 async def proxy(**kw):
  assert paused['preview-source'] is True, 'must pause before proxy activation'
  return True,'OK','rtsp://proxy/preview'
 ns.update(vst_add_sensor=AsyncMock(side_effect=create),vst_add_proxy_stream=AsyncMock(side_effect=proxy),
  cleanup_vst_sensor=AsyncMock(),cleanup_vst_storage=AsyncMock(),
  add_to_rtvi_vlm=AsyncMock(),add_to_rtvi_cv=AsyncMock(),add_to_rtvi_embed=AsyncMock(),start_embedding_generation=AsyncMock())
 config=SimpleNamespace(enable_audio=False,vst_url='http://vst',vst_streamprocessor_url='http://proxy',delete_vst_storage_on_stream_remove=True)
 req=ns['AddStreamRequest'](sensorUrl='rtsp://source/replay',name='Recorded simulation',startAnalysis=False)
 endpoint=ns['create_rtsp_ingest_router'](config).routes[0].endpoint
 result=await endpoint(req)
 assert result.status=='success' and result.analysis_paused and result.sensor_id=='preview-source'
 assert paused['preview-source'] is True
 for name in ['add_to_rtvi_vlm','add_to_rtvi_cv','add_to_rtvi_embed','start_embedding_generation']:
  ns[name].assert_not_called()
 assert ns['AddStreamRequest'](sensorUrl='rtsp://source/replay',name='Legacy').start_analysis is True
 ns['vst_add_proxy_stream']=AsyncMock(return_value=(False,'proxy failed',None))
 result=await endpoint(req)
 assert result.status=='failure' and 'preview-source' not in paused
 ns['cleanup_vst_sensor'].assert_awaited_once()
 assert ns['release_analysis_profile_capacity_reservation'].call_count==2
 print('PASS: actual request models/registration/endpoint; pause before proxy, no model calls, failure cleanup, legacy default')
asyncio.run(main())
