"""Run the real async adapter method with a recording engine, without GPU imports."""
import ast
import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

SOURCE = Path(__file__).resolve().parents[2] / 'src/models/vllm_compatible/vllm_compatible_model.py'


class IntegrationTests(unittest.TestCase):
    def test_capture_is_optional_and_failures_do_not_change_inference(self):
        tree=ast.parse(SOURCE.read_text())
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='process_async_vllm')
        import os
        namespace={'CPU_COPY_OTHER_THREAD':True,'asyncio':asyncio,'os':os,'logger':Mock(),'TimeMeasure':lambda label:nullcontext()}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(SOURCE),'exec'),namespace)
        source='rtsp://camera.test/live/one'
        for enabled,fail,file in [(False,False,source),(True,False,source),(True,True,source),
                                  (True,False,'rtsp://camera.test/live/other'),(True,False,'clip.mp4'),(True,False,None)]:
            eligible=enabled and file==source
            with self.subTest(enabled=enabled,fail=fail,file=file):
                frames=np.zeros((4,2,2,3),dtype=np.uint8)
                # Exercise the adapter's actual asynchronous CPU-copy boundary.
                # A tensor stand-in keeps this test runnable without CUDA/PyTorch.
                tensor=SimpleNamespace(cpu=Mock(return_value=SimpleNamespace(numpy=lambda:frames)))
                inputs={'multi_modal_data':{'video':[(tensor,{'fps':.4})]},'prompt_token_ids':[1,2]}
                calls=[]
                async def generate(value,**kwargs):
                    calls.append((value,kwargs))
                    yield SimpleNamespace(outputs=[SimpleNamespace(text='YES')])
                model=SimpleNamespace(_llm=SimpleNamespace(generate=generate),_inflight_req_ids=['one'],
                    _vlm_model_type='test',_model_architecture='test',_postprocess_vllm=lambda *args:'YES')
                helper=SimpleNamespace(capture_input=Mock(return_value=Path('/capture/one')),
                    capture_response=Mock())
                if fail:helper.capture_input.side_effect=OSError('disk full')
                params=SimpleNamespace(seed=42,temperature=0,ignore_eos=False)
                with patch.dict(os.environ,{'RTVI_CAPTURE_INPUTS_DIR':'/capture' if enabled else '', 'RTVI_CAPTURE_SOURCE_URL':source}), patch.dict('sys.modules',{'utils.input_capture':helper}):
                    result=asyncio.run(namespace['process_async_vllm'](model,inputs,params,[0,2.5,5,7.5],'one',chunk=SimpleNamespace(file=file)))
                self.assertEqual(result,'YES')
                self.assertIs(calls[0][0],inputs)
                tensor.cpu.assert_called_once_with()
                self.assertIs(calls[0][0]['multi_modal_data']['video'][0][0],frames)
                self.assertIs(calls[0][1]['sampling_params'],params)
                self.assertEqual(model._inflight_req_ids,[])
                self.assertEqual(helper.capture_input.call_count,int(eligible))
                self.assertEqual(helper.capture_response.call_count,int(eligible and not fail))
                if eligible and not fail:
                    self.assertIs(helper.capture_input.call_args.args[2],frames)
                    metadata=helper.capture_input.call_args.args[3]
                    self.assertEqual(metadata['sampling']['seed'],42)
                    self.assertEqual(metadata['frame_times'],[0,2.5,5,7.5])
                    self.assertEqual(helper.capture_response.call_args.args[1]['outputs'],['YES'])


if __name__=='__main__':unittest.main()
