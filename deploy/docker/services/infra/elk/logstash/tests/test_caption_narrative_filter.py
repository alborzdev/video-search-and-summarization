"""Execute the real caption Ruby filter with a source-scoped protobuf fixture.

LOGSTASH_TEST_CONTAINER=logstash selects an already-running CPU-only JRuby
runtime. The test starts no service and sends no Kafka or Elasticsearch writes.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('LOGSTASH_TEST_CONTAINER'), 'Select an existing Logstash JRuby runtime')
class CaptionNarrativeFilterTests(unittest.TestCase):
    def run_filter(self, fixtures):
        pipeline = Path(__file__).parents[1] / 'pipelines/kafka/mdx-lvs-logstash.conf'
        code = re.search(r"ruby\s*\{.*?code => '(.*?)'\s*\}", pipeline.read_text(), re.S).group(1)
        # A tiny Event adapter exercises the actual pipeline code, including
        # nested metadata routing; no implementation copy is used.
        harness = r'''require "json"
class Event
  attr_reader :data
  def initialize(data); @data=data; end
  def keys(path); path.start_with?("[") ? path.scan(/\[([^\]]+)\]/).flatten : [path]; end
  def get(path); keys(path).inject(@data) { |v,k| v.is_a?(Hash) ? v[k] : (v.is_a?(Array) ? v[k.to_i] : nil) }; end
  def set(path,value)
    parts=keys(path); last=parts.pop
    target=parts.inject(@data) { |v,k| v[k] ||= {} }; target[last]=value
  end
  def remove(path); @data.delete(path); end
  def cancel; @data["cancelled"]=true; end
end
results=JSON.parse(%s).map do |fixture|
  event=Event.new(fixture)
%s
  event.data
end
puts JSON.generate(results)
''' % (json.dumps(json.dumps(fixtures)), code)
        result = subprocess.run(['docker', 'exec', '-i', '-e', 'JAVA_HOME=/usr/share/logstash/jdk', os.environ['LOGSTASH_TEST_CONTAINER'],
                                 '/usr/share/logstash/vendor/jruby/bin/jruby', '-J-Xmx128m', '-'],
                                input=harness, text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def fixture(self):
        return {
            'info': {'streamId': 'hospital-camera-a', 'chunkIdx': '7', 'file': 'rtsp://local/hospital-camera-a'},
            'llm': {'queries': [{'id': 'exact-request:7'}]},
            'text': '[{"start_time":"2026-10-01T19:05:48.207Z","end_time":"2026-10-01T19:06:10.740Z","type":"visible people","description":"Two people walk past a cart."}]',
            'timestamp': {'seconds': 1790881548, 'nanos': 207000000},
            'end': {'seconds': 1790881570, 'nanos': 740000000},
            'vector': [0.5] * 1024,
        }

    def test_narrative_preserves_text_scope_times_and_id_without_synthetic_vector(self):
        fixture = self.fixture()
        document = self.run_filter([fixture])[0]
        self.assertNotIn('vector', document)
        self.assertEqual(document['text'], fixture['text'])
        self.assertEqual(document['metadata']['source'], fixture['info']['file'])
        metadata = document['metadata']['content_metadata']
        self.assertEqual(metadata['uuid'], 'hospital-camera-a')
        self.assertEqual(metadata['doc_type'], 'raw_events')
        self.assertEqual(metadata['doc_i'], '7')
        self.assertAlmostEqual(metadata['start_ntp_float'], 1790881548.207, places=3)
        self.assertAlmostEqual(metadata['end_ntp_float'], 1790881570.740, places=3)
        self.assertEqual(document['@metadata']['collection'], 'default_hospital_camera_a')
        self.assertEqual(document['@metadata']['es_id'], 'default_hospital_camera_a:hospital-camera-a:raw_events:7')

    def test_live_wrong_date_object_and_fenced_array_use_decoded_bounds(self):
        fixtures = []
        caption = {"start_time": "2026-04-30T10:39:20.934Z", "end_time": "2026-10-01T18:15:18.736Z",
                   "type": "scene observation", "description": "Two people walk past a cart."}
        for text in [json.dumps(caption), "```json\n" + json.dumps([caption]) + "\n```"]:
            fixture = self.fixture()
            fixture["sensor"] = {"type": "Camera"}
            fixture["text"] = text
            fixtures.append(fixture)
        for document in self.run_filter(fixtures):
            events = json.loads(document['text'])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['start_time'], '2026-10-01T19:05:48.207Z')
            self.assertEqual(events[0]['end_time'], '2026-10-01T19:06:10.740Z')
            self.assertEqual(events[0]['description'], caption['description'])
            self.assertEqual(events[0]['type'], caption['type'])
            self.assertEqual(document['metadata']['content_metadata']['caption_timestamps'], 'decoded_chunk')

    def test_empty_flushes_cancel_and_invalid_json_is_not_narrative_coverage(self):
        fixtures = []
        for text in ['', '  ', 'null', '[]', '{}', '{"description":']:
            fixture = self.fixture()
            fixture['sensor'] = {'type': 'Camera'}
            fixture['text'] = text
            fixtures.append(fixture)
        documents = self.run_filter(fixtures)
        self.assertTrue(all(document.get('cancelled') for document in documents[:-1]))
        self.assertEqual(documents[-1]['metadata']['content_metadata']['doc_type'], 'caption_errors')
        self.assertEqual(documents[-1]['metadata']['content_metadata']['caption_error'], 'invalid_caption_json')

    def test_recorded_seconds_preserved_and_missing_live_bounds_marked(self):
        recorded = self.fixture()
        recorded['sensor'] = {'type': 'Video'}
        recorded['text'] = '[{"start_time":0.5,"end_time":8.25,"type":"motion","description":"A cart rolls."}]'
        live = self.fixture()
        live['sensor'] = {'type': 'Camera'}
        del live['end']
        documents = self.run_filter([recorded, live])
        self.assertEqual(documents[0]['text'], recorded['text'])
        self.assertEqual(documents[0]['metadata']['content_metadata']['doc_type'], 'raw_events')
        self.assertEqual(documents[1]['metadata']['content_metadata']['doc_type'], 'caption_errors')

    def test_request_ids_retain_sessions_and_redelivery_is_idempotent(self):
        first = self.fixture()
        first['info']['requestId'] = 'request-a'
        second = self.fixture()
        second['info']['requestId'] = 'request-b'
        summary = self.fixture()
        summary['info'].update(doc_type='aggregated_summary', requestId='request-a', collection_name='summary_collection')
        documents = self.run_filter([first, second, first, summary])
        ids = [document['@metadata']['es_id'] for document in documents]
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual(ids[0], ids[2])
        self.assertTrue(ids[0].endswith(':raw_events:request-a:7'))
        self.assertEqual(ids[3], 'summary_collection:hospital-camera-a:aggregated_summary:7')


if __name__ == '__main__':
    unittest.main()
