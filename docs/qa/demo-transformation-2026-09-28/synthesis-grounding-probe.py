import ast,asyncio,os,re,json,logging,time
from pathlib import Path
from types import SimpleNamespace as NS
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage,HumanMessage
p=Path('/vss-agent/thor-local-src/vss_agents/api/evidence_analysis.py'); tree=ast.parse(p.read_text()); names={'_synthesize_inspections','_synthesis_prompt','_extract_json_object','_message_text'}
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
prompt=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SYNTHESIS_SYSTEM_PROMPT' for t in n.targets))
module=ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[]))
ns={'asyncio':asyncio,'os':os,'re':re,'json':json,'logger':logging.getLogger('probe'),'SystemMessage':SystemMessage,'HumanMessage':HumanMessage,'SYNTHESIS_SYSTEM_PROMPT':prompt,'LLMFrameworkEnum':NS(LANGCHAIN='test'),'_asks_for_cross_clip_identity':lambda *a:False,'_format_timestamp':str,'_timeline':lambda *a:[],'EvidenceClaim':lambda **k:NS(**k),'EvidenceAnalysisResponse':lambda **k:NS(**k),'_degraded_response':lambda *a:NS(status='degraded',summary=str(a[-1]))}
exec(compile(module,str(p),'exec'),ns)
llm=ChatOpenAI(model='nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8',base_url='http://127.0.0.1:30081/v1',api_key='local',temperature=0,max_tokens=160,extra_body={'chat_template_kwargs':{'enable_thinking':False}})
class Builder:
 async def get_llm(self,*a,**k):return llm
async def run():
 os.environ['LLM_MODEL_TYPE']='vllm'
 cases=[
  ('position', ['A person is standing beside green steps holding a box.','A person is standing on the top platform holding a box.'], 'Compare final positions in E1 and E2.', ['beside','on','platform']),
  ('boundary', ['A person remains outside the marked area.','A person stands inside the marked area.'], 'Where is the person relative to the marked area in each clip?', ['outside','inside']),
  ('holding', ['A person stops walking while still holding a box.','A person continues walking while still holding a box.'], 'Does either observation show the person releasing the box?', ['holding']),
  ('completion', ['A person approaches a doorway but does not enter it.','A person walks through a doorway and is inside by the final frame.'], 'Compare whether entry is completed in E1 and E2.', ['E1','E2']),
 ]
 for name,texts,question,required in cases:
  req=NS(query='fixture comparison',question=question,evidence=[None,None])
  obs=[NS(evidence_id=f'E{i}',source_name='Test fixture',start_time='start',end_time='end',match_type='test',observation=t,inspection_source='fresh_cosmos_inspection') for i,t in enumerate(texts,1)]
  start=time.monotonic(); result=await ns['_synthesize_inspections'](Builder(),req,obs,[])
  print(json.dumps({'case':name,'inputs':texts,'question':question,'status':result.status,'summary':result.summary,'seconds':round(time.monotonic()-start,3)}),flush=True)
  assert result.status=='complete' and all(word.lower() in result.summary.lower() for word in required)
asyncio.run(run())
