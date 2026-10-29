"""The city desktop path uses its own detector while keeping offline guards."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import offline


class CityOfflineTests(unittest.TestCase):
    def graph(self):
        graph = {'services': {name: {'environment': {
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'NIM_DISABLE_MODEL_DOWNLOAD': '1', 'RTVI_OFFLINE': 'true',
        }} for name in ('spark-llm', 'rtvi-embed', 'rtvi-vlm')}}
        graph['services']['streamprocessing-ms'] = {'entrypoint': ['launch_vst'],
            'environment': {'VST_INSTALL_ADDITIONAL_PACKAGES': 'false'}}
        graph['services']['vss-agent'] = {'image': 'cached-agent'}
        offline.b.booth_runtime_safety(graph)
        return graph

    def test_city_does_not_require_the_unrelated_warehouse_detector(self):
        settings = {'cached_models': True, 'detector_enabled': False}
        offline.validate_graph(settings, self.graph(), city=True)
        with self.assertRaises(RuntimeError):
            offline.validate_graph(settings, self.graph())

    def test_city_still_refuses_model_downloads_and_online_codec_installers(self):
        settings = {'cached_models': True, 'detector_enabled': False}
        for service, setting, value in [('rtvi-vlm', 'RTVI_OFFLINE', 'false'),
                                         ('spark-llm', 'NIM_DISABLE_MODEL_DOWNLOAD', '0'),
                                         ('streamprocessing-ms', 'VST_INSTALL_ADDITIONAL_PACKAGES', 'true')]:
            graph = copy.deepcopy(self.graph())
            graph['services'][service]['environment'][setting] = value
            with self.subTest(service=service), self.assertRaises(RuntimeError):
                offline.validate_graph(settings, graph, city=True)


if __name__ == '__main__':
    unittest.main()
