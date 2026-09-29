"""Exercise actual inspection orchestration without importing model dependencies."""
import ast
import asyncio
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import cast

source=Path('services/agent/src/vss_agents/api/evidence_analysis.py')
node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_inspect_evidence')
namespace=dict(asyncio=asyncio,os=os,cast=cast,logger=logging.getLogger('probe'),
               _caption_retriever=lambda:None,_fresh_inspection_is_available=AsyncMock(return_value=True),
               LLMFrameworkEnum=SimpleNamespace(LANGCHAIN='langchain'),EvidenceInspectionTool=object,
               _format_timestamp=str,_message_text=lambda x:x,VisualInspection=lambda **kw:SimpleNamespace(**kw))
exec(compile('from __future__ import annotations\n'+ast.unparse(node),str(source),'exec'),namespace)

async def run():
    for count,question in [(1,'Where does the person stand at the end?'),
                           (1,None),
                           (2,'Compare positions in E1 and E2.'),
                           (2,'Did the person touch the robot?'),
                           (2,None)]:
        tool=SimpleNamespace(ainvoke=AsyncMock(return_value='Visible observation.'))
        builder=SimpleNamespace(get_tool=AsyncMock(return_value=tool))
        clips=[SimpleNamespace(sensor_id=f'sensor-{i}',start_time=i,end_time=i+1,client_id=f'clip-{i}',
                               source_name=f'Source {i}',match_type='semantic') for i in range(count)]
        request=SimpleNamespace(question=question,query='Describe visible activity',evidence=clips)
        observed=[]
        inspections,warnings=await namespace['_inspect_evidence'](builder,request,observed.append)
        assert not warnings and len(inspections)==len(observed)==count
        assert tool.ainvoke.await_count==count
        for index,call in enumerate(tool.ainvoke.await_args_list):
            args=call.kwargs['input']
            assert args['sensor_id']==clips[index].sensor_id
            assert args['start_timestamp']==str(clips[index].start_time)
            assert args['end_timestamp']==str(clips[index].end_time)
            assert (question or request.query) in args['user_prompt']
            if count == 1 and question:
                assert request.query not in args['user_prompt']
            if count>1:
                assert f'Report only what is visible in E{index+1}' in args['user_prompt']
                assert 'No other clip is provided' in args['user_prompt']
                assert 'a separate step will compare the observations' in args['user_prompt']
    print('PASS: single, comparison, interaction and query-fallback question scopes; exact intervals and one call per clip')
asyncio.run(run())
