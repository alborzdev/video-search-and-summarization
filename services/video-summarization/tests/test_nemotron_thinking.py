"""CPU-only real LangChain payload and cached-tokenizer regression checks.

Uses the installed LVS dependency runtime; never sends an inference request.
"""
import json
import os
from pathlib import Path
import subprocess
import unittest

SOURCE = Path(__file__).parents[1] / 'src/llm_handler.py'
TEMPLATE = '/opt/nim/.cache/ngc/hub/models--nim--nvidia--nemotron-nano-9b-v2/snapshots/hf-nvfp4-v1/tokenizer_config.json'


class NemotronThinkingTests(unittest.TestCase):
    def test_real_client_payload_and_pinned_template(self):
        lvs = os.environ.get('LVS_TEST_CONTAINER', 'vss-lvs')
        nim = os.environ.get('NIM_TEST_CONTAINER', 'vss-spark-spark-llm-1')
        template = subprocess.run(['docker', 'exec', nim, 'python3', '-c',
            'import json; from pathlib import Path; print(json.loads(Path(' + repr(TEMPLATE) + ').read_text())["chat_template"])'],
            check=True, capture_output=True, text=True).stdout
        script = 'SOURCE = ' + repr(SOURCE.read_text()) + '\nTEMPLATE = ' + repr(template) + '\n' + r'''
import ast, copy, os, unittest
from types import SimpleNamespace
import json
os.environ['CA_RAG_ENABLE_WARMUP'] = 'false'
# Load the real client and tool code with registration decorators removed, so
# tests do not modify the live service registry (this is a private CPU process).
tree = ast.parse(SOURCE)
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        node.decorator_list = []
exec(compile(tree, 'candidate_llm_handler.py', 'exec'), globals())

class PayloadTests(unittest.TestCase):
    def client(self, model='nvidia/nemotron-nano-9b-v2', thinking=False, provider='openai'):
        tool = ChatOpenAITool(config=SimpleNamespace(params=LLMConfig(
            model=model, enable_thinking=thinking, provider=provider,
            base_url='http://127.0.0.1:1/v1', max_tokens=256)))
        return tool.llm.default

    def payload(self, client, messages):
        return client._get_request_payload(messages)

    def test_explicit_false_grounded_system_and_real_template(self):
        messages = [{'role':'system', 'content':'Summarize observed events. /think Keep citations.'},
                    {'role':'user', 'content':'A cart moves at 12:00.'}]
        before = copy.deepcopy(messages)
        for model in NEMOTRON_NANO_9B_V2_MODELS:
            with self.subTest(model=model):
                payload = self.payload(self.client(model=model), messages)
                self.assertEqual(payload['messages'][0]['content'], '/no_think\nSummarize observed events.  Keep citations.')
                self.assertEqual(payload['messages'][1], messages[1])
                self.assertEqual(payload['max_tokens'], 256)
                self.assertNotIn('disable_nemotron_thinking', payload)
                self.assertNotIn('extra_body', payload)
                print(json.dumps(payload['messages']))
        self.assertEqual(messages, before)

    def test_no_system_inserts_control_without_losing_user(self):
        messages = [{'role':'user', 'content':'Describe the scene.'}]
        payload = self.payload(self.client(provider='nim'), messages)
        self.assertEqual(payload['messages'], [{'role':'system', 'content':'/no_think'}, *messages])
        self.assertEqual(messages, [{'role':'user', 'content':'Describe the scene.'}])

    def test_default_true_and_other_models_unchanged(self):
        messages = [{'role':'system', 'content':'Keep instructions.'}, {'role':'user','content':'Hello.'}]
        for thinking in (None, True):
            self.assertEqual(self.payload(self.client(thinking=thinking), messages)['messages'], messages)
        self.assertEqual(self.payload(self.client(model='other-model'), messages)['messages'], messages)
        # Exact names only: related Nemotron generations do not inherit control.
        self.assertEqual(self.payload(self.client(model='nvidia/nemotron-3-nano'), messages)['messages'], messages)

    def test_existing_vllm_contract_is_preserved(self):
        payload = self.payload(self.client(model='other-model', provider='vllm'), [{'role':'user','content':'Hello.'}])
        self.assertEqual(payload['extra_body'], {'chat_template_kwargs': {'enable_thinking': False}})
        self.assertNotIn('/no_think', str(payload['messages']))

unittest.main()
'''
        result = subprocess.run(['docker', 'exec', '-i', lvs, 'python3', '-'],
                                input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Ran 4 tests', result.stderr)
        from jinja2 import Environment
        payloads = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('[')]
        self.assertEqual(len(payloads), 2)
        for messages in payloads:
            rendered = Environment().from_string(template).render(
                messages=messages, add_generation_prompt=True, bos_token='')
            self.assertTrue(rendered.endswith('<think></think>'), rendered[-120:])


if __name__ == '__main__':
    unittest.main()
