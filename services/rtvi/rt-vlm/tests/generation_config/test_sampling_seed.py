"""Exercise production SamplingParams construction without importing a GPU engine."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'src/models/vllm_compatible/vllm_compatible_model.py'


class SamplingSeedTest(unittest.TestCase):
    def test_seed_reaches_all_engine_sampling_boundaries(self):
        tree = ast.parse(SOURCE.read_text())
        boundaries = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = next((i for i, stmt in enumerate(node.body)
                          if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'sp_kwargs' for t in stmt.targets)), None)
            if start is None:
                continue
            end = next(i for i in range(start, len(node.body)) if isinstance(node.body[i], ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'vllm_sampling_params' for t in node.body[i].targets))
            boundaries.append((node.name, ast.Module(body=node.body[start:end + 1], type_ignores=[])))
        self.assertEqual(len(boundaries), 3)
        for name, module in boundaries:
            for seed in (0, 1, 42):
                with self.subTest(path=name, seed=seed):
                    config = SimpleNamespace(seed=seed, min_tokens=None, ignore_eos=False)
                    namespace = dict(config=config, generation_params=dict(temperature=.4, top_p=.8, top_k=20,
                        max_new_tokens=128, repetition_penalty=1.1),
                        os=SimpleNamespace(getenv=lambda key, default: default), SamplingParams=lambda **kwargs: kwargs)
                    exec(compile(module, str(SOURCE), 'exec'), namespace)
                    self.assertEqual(namespace['vllm_sampling_params'].get('seed'), seed)


if __name__ == '__main__':
    unittest.main()
