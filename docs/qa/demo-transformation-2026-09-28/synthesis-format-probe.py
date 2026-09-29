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
 os.environ['LLM_MODEL_TYPE']='vllm'; req=NS(query='warehouse activity',question='Compare final positions in E1 and E2.',evidence=[None,None])
 obs=[NS(evidence_id=f'E{i}',source_name='Test fixture',start_time='start',end_time='end',match_type='test',observation=t,inspection_source='fresh_cosmos_inspection') for i,t in enumerate(['A person is standing beside green steps holding a box.','A person is standing on the top platform holding a box.'],1)]
 start=time.monotonic(); result=await ns['_synthesize_inspections'](Builder(),req,obs,[]); print(json.dumps({'status':result.status,'summary':result.summary,'seconds':round(time.monotonic()-start,3)})); assert result.status=='complete'
asyncio.run(run())
