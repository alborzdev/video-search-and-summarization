"""Prompt contracts without loading the GPU or context-manager dependencies."""
import ast
import logging
import os
from pathlib import Path
import unittest
from unittest.mock import patch


class LiveCaptionPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / 'src/via_stream_handler.py'
        tree = ast.parse(source.read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ViaStreamHandler')
        method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == '_create_vlm_prompt')
        namespace = {'os': os, 'logger': logging.getLogger('caption-prompt-test')}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        cls.prompt = staticmethod(namespace['_create_vlm_prompt'])

    def create(self, live=True, **kwargs):
        return self.prompt(None, '', True, ['cart'], ['visible people'], 'hospital corridor', is_livestream=live, **kwargs)

    def test_live_prompt_fits_bounded_json_and_uses_observed_times(self):
        with patch.dict(os.environ, {}, clear=True):
            prompt = self.create()
        self.assertIn('exactly one concise event', prompt)
        self.assertIn('at most 35 words', prompt)
        self.assertIn('first and last observed frame timestamps', prompt)
        self.assertIn('verbatim in ISO 8601', prompt)
        self.assertIn('complete JSON only', prompt)
        self.assertIn('start_time, end_time, type, description', prompt)
        self.assertIn('only visible evidence', prompt)
        self.assertNotIn('2026-04-30', prompt)
        self.assertNotIn('#(MANDATORY)', prompt)
        self.assertIn('hospital corridor', prompt)
        self.assertIn('visible people', prompt)

    def test_file_prompt_retains_relative_seconds_contract(self):
        with patch.dict(os.environ, {}, clear=True):
            prompt = self.create(live=False)
        self.assertIn("'seconds' for time depiction", prompt)
        self.assertIn('t_start', prompt)
        self.assertNotIn('observed frame timestamps', prompt)

    def test_operator_override_and_unstructured_prompt_remain_authoritative(self):
        with patch.dict(os.environ, {'LVS_PROMPT_VLM_STRUCTURED_OUTPUT': 'Custom output for {scenario}: {events}'}, clear=True):
            prompt = self.create()
        self.assertIn('Custom output for hospital corridor: visible people', prompt)
        self.assertNotIn('exactly one concise event', prompt)
        self.assertEqual(self.prompt(None, 'Describe motion.', False, [], [], '', is_livestream=True), 'Describe motion.')


if __name__ == '__main__':
    unittest.main()
