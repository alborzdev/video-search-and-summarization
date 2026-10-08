import importlib.util
import base64
import io
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('thor_bootstrap_test', Path(__file__).with_name('bootstrap.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class ThorBootstrapTest(unittest.TestCase):
    def test_detector_builder_refuses_low_headroom_or_active_models(self):
        with patch.object(b, 'doctor'), patch.object(b, 'require_guard'), \
                patch.object(b, 'settings', return_value={'detector_enabled': True}), \
                patch.object(b.shared, 'available', return_value=89), patch.object(b, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, '90 GiB'):
                b.build_detector_engine()
            run.assert_not_called()
        with patch.object(b, 'doctor'), patch.object(b, 'require_guard'), \
                patch.object(b, 'settings', return_value={'detector_enabled': True}), \
                patch.object(b.shared, 'available', return_value=100), \
                patch.object(b, 'run', return_value=subprocess.CompletedProcess([], 0, 'model-id\n')), \
                patch.object(b, 'stage_detector') as stage:
            with self.assertRaisesRegex(RuntimeError, 'Stop the three model services'):
                b.build_detector_engine()
            stage.assert_not_called()

    def test_detector_builder_stops_and_removes_temporary_limit_on_readiness_failure(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(b, 'STATE', Path(temporary)), \
                patch.object(b, 'doctor'), patch.object(b, 'require_guard'), \
                patch.object(b, 'settings', return_value={'detector_enabled': True}), \
                patch.object(b.shared, 'available', return_value=100), patch.object(b, 'stage_detector'), \
                patch.object(b, 'run', return_value=subprocess.CompletedProcess([], 0, '')) as run, \
                patch.object(b, 'await_service', side_effect=[None, None, RuntimeError('not ready')]):
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                b.build_detector_engine()
            self.assertEqual(run.call_args.args[0][-2:], ['stop', 'thor-perception'])
            self.assertFalse((b.STATE / 'compose-detector-build.json').exists())

    def test_detector_http_success_requires_actual_pipeline_readiness(self):
        for payload, expected in [
            ({'health-info': {'ds-ready': 'YES'}}, 0),
            ({'health-info': {'ds-ready': 'NO'}}, 1),
            ({'status': 'HTTP/1.1 200 OK'}, 1),
        ]:
            with self.subTest(payload=payload), patch('urllib.request.urlopen',
                    return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(SystemExit) as result:
                    exec(b.DETECTOR_HEALTH_PROBE, {})
                self.assertEqual(result.exception.code, expected)

    def test_embedding_auxiliary_bundle_rejects_changed_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / 'deploy/docker/thor-current'
            destination.mkdir(parents=True)
            for source in (b.ROOT / 'deploy/docker/thor-current/embedding-auxiliary').iterdir():
                (destination / 'embedding-auxiliary').mkdir(exist_ok=True)
                (destination / 'embedding-auxiliary' / source.name).write_bytes(source.read_bytes())
            (destination / 'embedding-auxiliary.lock.json').write_bytes(
                (b.ROOT / 'deploy/docker/thor-current/embedding-auxiliary.lock.json').read_bytes())
            with patch.object(b, 'ROOT', root):
                folder = b.verify_embedding_auxiliary()
                config = folder / 'config.json'
                body = config.read_bytes()
                config.write_bytes(b'x' + body[1:])
                with self.assertRaisesRegex(RuntimeError, 'configuration changed'):
                    b.verify_embedding_auxiliary()
                config.write_bytes(body)
                reference = (b.BERT_REVISION + '\n').encode()
                (folder / 'refs-main').write_bytes(reference)
                lock_path = destination / 'embedding-auxiliary.lock.json'
                lock = json.loads(lock_path.read_text())
                for entry in lock['files']:
                    if entry['path'] == 'refs-main':
                        entry.update(size=len(reference), sha256=hashlib.sha256(reference).hexdigest())
                lock_path.write_text(json.dumps(lock))
                with self.assertRaisesRegex(RuntimeError, 'cache reference changed'):
                    b.verify_embedding_auxiliary()

    def test_cache_provision_preserves_active_volume_and_rejects_other_projects(self):
        graph = {'volumes': {name: {'name': b.PROJECT + '_' + name}
                 for name in ('rtvi-hf-cache', 'rtvi-triton-model-repo')}}
        replies = [subprocess.CompletedProcess([], 0, 'container-id\n'),
                   subprocess.CompletedProcess([], 0, json.dumps([{'Mounts': [
                       {'Type': 'volume', 'Name': b.PROJECT + '_rtvi-hf-cache'}]}])),
                   subprocess.CompletedProcess([], 0)]
        with patch.object(b, 'run', side_effect=replies) as run:
            b.provision_model_caches(graph)
        mutation = run.call_args_list[-1].args[0]
        self.assertTrue(any('src=vss-thor_rtvi-triton-model-repo' in str(arg) for arg in mutation))
        self.assertFalse(any('src=vss-thor_rtvi-hf-cache' in str(arg) for arg in mutation))
        graph['volumes']['rtvi-hf-cache']['name'] = 'unrelated-cache'
        with patch.object(b, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'outside the Thor candidate'):
                b.provision_model_caches(graph)
            run.assert_not_called()

    def test_image_build_failure_stops_before_the_next_shared_base_build(self):
        services = {'pulled': {'image': 'cached'}, 'embed': {'build': {'context': 'source'}},
                    'vlm': {'build': {'context': 'source'}}}
        with patch.object(b, 'run', side_effect=subprocess.CalledProcessError(1, ['build'])) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                b.build_services(services)
        self.assertEqual(len(run.call_args_list), 1)
        self.assertEqual(run.call_args.args[0][-3:], ['build', '--pull', 'embed'])

    def test_parallel_image_staging_rejected_before_transfer_or_context_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'compose.json').write_text(json.dumps({'services': {}}))
            with (state / 'image-stage.lock').open('a') as lease:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(b, 'STATE', state), patch.object(b, 'doctor'), \
                        patch.object(b, 'require_guard'), patch.object(b.shutil, 'disk_usage',
                        return_value=Mock(free=300 * 1024**3)), \
                        patch.object(b, 'run', return_value=subprocess.CompletedProcess([], 0, '')), \
                        patch.object(b, 'stage_images') as stage:
                    with self.assertRaisesRegex(RuntimeError, 'Another image staging'):
                        b.stage()
                    stage.assert_not_called()

    def test_app_stage_reuses_ready_models_without_recreating_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            models = ['thor-llm', 'rtvi-embed', 'rtvi-vlm']
            graph = {'services': {name: {} for name in models + ['lvs-server']}}
            (state / 'compose.json').write_text(json.dumps(graph))
            with patch.object(b, 'STATE', state), patch.object(b, 'doctor'), patch.object(b, 'require_guard'), \
                    patch.object(b.shared, 'available', return_value=100), \
                    patch.object(b.shared, 'startup_order', return_value=['rtvi-vlm', 'rtvi-embed', 'lvs-server']), \
                    patch.object(b, 'await_service') as ready, \
                    patch.object(b, 'run', return_value=subprocess.CompletedProcess([], 0, 'model-id')) as run:
                b.startup('app')
                mutations = [call.args[0] for call in run.call_args_list if 'up' in call.args[0]]
                self.assertEqual([args[-1] for args in mutations], ['lvs-server'])
                self.assertTrue(all(name in [c.args[0] for c in ready.call_args_list] for name in models))

            with patch.object(b, 'STATE', state), patch.object(b, 'doctor'), patch.object(b, 'require_guard'), \
                    patch.object(b, 'await_service'), \
                    patch.object(b, 'run', return_value=subprocess.CompletedProcess([], 0, '')) as run:
                with self.assertRaisesRegex(RuntimeError, 'validate thor-llm before the app'):
                    b.startup('app')
                self.assertFalse(any('up' in call.args[0] or 'start' in call.args[0]
                                     for call in run.call_args_list))

    def test_embedding_staging_resumes_and_publishes_only_the_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, data = root / 'state', root / 'data'
            state.mkdir()
            (state / 'compose.json').write_text(json.dumps({'services': {'rtvi-embed': {}}}))
            staging = data / 'models/embed-staging'
            staging.mkdir(parents=True)
            (staging / 'model.bin.partial').write_bytes(b'go')
            content = {'model.bin': b'good', 'config.json': b'{}'}
            entries = [{'path': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                       for name, body in content.items()]
            transfers = []

            def run(args, **_):
                if args[0] == 'curl':
                    transfers.append(args[-1])
                    self.assertIn('/resolve/' + b.EMBED_REVISION + '/', args[-1])
                    partial = Path(args[args.index('--output') + 1])
                    body = content[partial.name.removesuffix('.partial')]
                    offset = partial.stat().st_size if partial.exists() else 0
                    with partial.open('ab') as stream:
                        stream.write(body[offset:])
                    self.assertFalse((data / 'models/rtvi-ngc' / b.EMBED.split('/')[-1]).exists())
                return subprocess.CompletedProcess(args, 0, '')

            with patch.object(b, 'STATE', state), patch.object(b, 'require_thor'), patch.object(b, 'require_guard'), \
                    patch.object(b, 'settings', return_value={'data_dir': str(data)}), \
                    patch.object(b, 'embedding_entries', return_value=entries), patch.object(b, 'run', side_effect=run):
                b.stage_embed()
                b.stage_embed()
            folder = data / 'models/rtvi-ngc' / b.EMBED.split('/')[-1]
            self.assertEqual((folder / 'model.bin').read_bytes(), b'good')
            self.assertFalse(staging.exists())
            self.assertEqual(len(transfers), 2)

    def test_embedding_verification_rejects_changed_bytes_extra_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / 'model'
            entry = {'path': 'model', 'size': 4, 'sha256': hashlib.sha256(b'good').hexdigest()}
            with patch.object(b, 'embedding_entries', return_value=[entry]):
                path.write_bytes(b'good')
                b.verify_embed(folder)
                path.write_bytes(b'evil')
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    b.verify_embed(folder)
                path.write_bytes(b'good')
                (folder / 'unreviewed').write_bytes(b'other')
                with self.assertRaisesRegex(RuntimeError, 'membership'):
                    b.verify_embed(folder)
                (folder / 'unreviewed').unlink()
                path.unlink()
                path.symlink_to(folder / 'missing')
                with self.assertRaisesRegex(RuntimeError, 'Invalid embedding'):
                    b.verify_embed(folder)

    def test_cosmos_short_and_interrupted_responses_resume_without_publishing_early(self):
        with tempfile.TemporaryDirectory() as temporary:
            partial, final = Path(temporary) / 'model.partial', Path(temporary) / 'model'
            digest = hashlib.sha256(b'good').hexdigest()
            entry = {'path': 'model', 'size': 4, 'sha256': digest}
            encoded = base64.b64encode(bytes.fromhex(digest)).decode()
            metadata = {'filepath': ['model'], 'urls': ['https://objects.example/model'],
                        'sha256_base64': [encoded]}
            opener = Mock(open=lambda *_args, **_kwargs: io.BytesIO(json.dumps(metadata).encode()))
            calls = []

            class Interrupted(io.BytesIO):
                def read(self, *_):
                    raise b.http.client.IncompleteRead(b'o')

            def objects(request, **_):
                self.assertFalse(final.exists())
                self.assertIsNone(request.get_header('Authorization'))
                calls.append(request.get_header('Range'))
                if len(calls) == 1:
                    stream = io.BytesIO(b'g')  # EOF before the promised full file.
                    stream.status, stream.headers = 200, {}
                elif len(calls) == 2:
                    stream = Interrupted()
                    stream.status, stream.headers = 206, {'Content-Range': 'bytes 1-3/4'}
                else:
                    stream = io.BytesIO(b'od')
                    stream.status, stream.headers = 206, {'Content-Range': 'bytes 2-3/4'}
                return stream

            with patch.object(b.urllib.request, 'build_opener', return_value=opener), \
                    patch.object(b.urllib.request, 'urlopen', side_effect=objects), patch.object(b.time, 'sleep'):
                b.download_cosmos_file('https://metadata.example/versions/model', 'secret', entry,
                                       {'sha256_base64': encoded}, partial, final)
            self.assertEqual(calls, [None, 'bytes=1-', 'bytes=2-'])
            self.assertEqual(final.read_bytes(), b'good')

    def test_cosmos_resume_rejects_wrong_range_and_complete_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            partial, final = Path(temporary) / 'model.partial', Path(temporary) / 'model'
            partial.write_bytes(b'go')
            entry = {'path': 'model', 'size': 4, 'sha256': hashlib.sha256(b'good').hexdigest()}
            encoded = base64.b64encode(bytes.fromhex(entry['sha256'])).decode()
            metadata = {'filepath': ['model'], 'urls': ['https://objects.example/model'],
                        'sha256_base64': [encoded]}
            opener = Mock(open=lambda *_args, **_kwargs: io.BytesIO(json.dumps(metadata).encode()))
            response = io.BytesIO(b'od')
            response.status, response.headers = 206, {'Content-Range': 'bytes 0-1/4'}
            with patch.object(b.urllib.request, 'build_opener', return_value=opener), \
                    patch.object(b.urllib.request, 'urlopen', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'unexpected resume range'):
                    b.download_cosmos_file('https://metadata.example/versions/model', 'secret', entry,
                                           {'sha256_base64': encoded}, partial, final)
            self.assertEqual(partial.read_bytes(), b'go')
            partial.write_bytes(b'evil')
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                b.download_cosmos_file('https://metadata.example/versions/model', 'secret', entry,
                                       {'sha256_base64': encoded}, partial, final)
            self.assertFalse(final.exists())

    def test_cosmos_cache_lease_prevents_two_writers(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(b, 'require_thor'), \
                patch.object(b, 'settings', return_value={'data_dir': temporary}), \
                patch.object(b, 'stage_cosmos_snapshot') as transfer:
            models = Path(temporary) / 'models'
            models.mkdir()
            with (models / '.cosmos-stage.lock').open('a') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError, 'owns this cache'):
                    b.stage_cosmos()
                transfer.assert_not_called()
            b.stage_cosmos()
            transfer.assert_called_once()

    def test_cosmos_resume_keeps_credentials_on_metadata_api_and_verifies_published_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            key = home / '.config/cti-vss/ngc-api-key'
            key.parent.mkdir(parents=True)
            key.write_text('test-secret')
            data = home / 'data'
            staging = data / 'models/cosmos-staging'
            staging.mkdir(parents=True)
            (staging / 'model.bin.partial').write_bytes(b'go')
            digest = hashlib.sha256(b'good').hexdigest()
            encoded = base64.b64encode(bytes.fromhex(digest)).decode()
            entries = [{'type': 'file', 'path': 'model.bin', 'size': 4, 'sha256': digest}]

            def response(payload, status=200, headers=None):
                stream = io.BytesIO(payload)
                stream.status, stream.headers = status, headers or {}
                return stream

            def metadata(request, **_):
                self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
                if '?' in request.full_url:
                    body = {'filepath': ['model.bin'], 'urls': ['https://objects.example/model'],
                            'sha256_base64': [encoded]}
                else:
                    body = {'modelFiles': [{'path': 'model.bin', 'sizeInBytes': 4, 'sha256_base64': encoded}],
                            'paginationInfo': {'totalResults': 1}}
                return response(json.dumps(body).encode())

            def object_store(request, **_):
                self.assertEqual(request.full_url, 'https://objects.example/model')
                self.assertIsNone(request.get_header('Authorization'))
                self.assertEqual(request.get_header('Range'), 'bytes=2-')
                return response(b'od', 206, {'Content-Range': 'bytes 2-3/4'})

            opener = Mock(open=metadata)
            with patch.object(b, 'require_thor'), patch.object(b, 'settings', return_value={'data_dir': str(data)}), \
                    patch.object(b, 'cosmos_entries', return_value=entries), patch.object(Path, 'home', return_value=home), \
                    patch.object(b.urllib.request, 'build_opener', return_value=opener), \
                    patch.object(b.urllib.request, 'urlopen', side_effect=object_store):
                b.stage_cosmos()
            self.assertEqual((data / 'models/rtvi-ngc' / b.VLM / 'model.bin').read_bytes(), b'good')
            self.assertFalse(staging.exists())

    def test_build_snapshot_includes_only_copy_inputs_and_refreshes_deleted_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'repo'
            state = root / '.thor'
            state.mkdir(parents=True)
            (state / 'credential').write_text('private-must-never-enter-context')
            source = root / 'services/overlay'
            source.mkdir(parents=True)
            (source / 'keep.py').write_text('original')
            (source / 'remove.py').write_text('obsolete')
            services = {}
            for name in ('alert-bridge', 'lvs-server'):
                dockerfile = root / 'deploy' / f'Dockerfile.{name}'
                dockerfile.parent.mkdir(exist_ok=True)
                dockerfile.write_text('FROM scratch\nCOPY services/overlay/*.py /app/\n')
                services[name] = {'build': {'dockerfile': str(dockerfile.relative_to(root))}}
            with patch.object(b, 'ROOT', root), patch.object(b, 'STATE', state):
                b.prepare_build_contexts(services)
                for service in services.values():
                    context = Path(service['build']['context'])
                    self.assertFalse((context / '.thor').exists())
                    self.assertEqual((context / 'services/overlay/keep.py').read_text(), 'original')
                (source / 'remove.py').unlink()
                (source / 'keep.py').write_text('updated')
                b.prepare_build_contexts(services)
                for service in services.values():
                    context = Path(service['build']['context'])
                    self.assertFalse((context / 'services/overlay/remove.py').exists())
                    self.assertEqual((context / 'services/overlay/keep.py').read_text(), 'updated')
                (source / 'redirect.py').symlink_to(state / 'credential')
                with self.assertRaisesRegex(RuntimeError, 'regular file'):
                    b.prepare_build_contexts(services)

    def test_cuda_lookup_patch_preserves_elf_layout_and_rejects_changed_vendor_binary(self):
        spec = importlib.util.spec_from_file_location('cuda_soname_patch',
            b.ROOT / 'deploy/docker/thor-local/vios-codecs/resolve-cuda-soname.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'launch_vst'
            original = b'\x7fELFprefix' + adapter.ABSOLUTE + b'suffix'
            path.write_bytes(original)
            adapter.patch(path)
            self.assertEqual(len(path.read_bytes()), len(original))
            self.assertTrue(path.read_bytes().endswith(b'suffix'))
            self.assertIn(adapter.SONAME, path.read_bytes())
            for content in (b'not ELF' + adapter.ABSOLUTE,
                            b'\x7fELF' + adapter.ABSOLUTE * 2, b'\x7fELFchanged'):
                path.write_bytes(content)
                with self.assertRaisesRegex(RuntimeError, 'Unexpected VIOS'):
                    adapter.patch(path)
                self.assertEqual(path.read_bytes(), content)

    def test_image_staging_refuses_missing_guard_before_build_or_pull(self):
        with patch.object(b, 'doctor'), patch.object(b, 'require_guard',
                side_effect=RuntimeError('guard inactive')), patch.object(b, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'guard inactive'):
                b.stage()
            run.assert_not_called()

    def test_completed_interrupted_download_publishes_only_after_hash_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            partial, final = Path(temporary) / 'model.partial', Path(temporary) / 'model'
            expected = hashlib.sha256(b'good').hexdigest()
            partial.write_bytes(b'go')
            self.assertFalse(b.publish_complete_partial(partial, final, 4, expected))
            self.assertFalse(final.exists())
            partial.write_bytes(b'evil')
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                b.publish_complete_partial(partial, final, 4, expected)
            self.assertFalse(final.exists())
            partial.write_bytes(b'good')
            self.assertTrue(b.publish_complete_partial(partial, final, 4, expected))
            self.assertEqual(final.read_bytes(), b'good')
            self.assertFalse(partial.exists())

    def test_optional_detector_isolated_and_mode_preserved(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(b, 'STATE', Path(temporary)):
            b.render('192.0.2.40', cached_models=True, detector_enabled=True)
            services = json.loads((b.STATE / 'compose.json').read_text())['services']
            detector = services['thor-perception']
            self.assertEqual(detector['environment']['VSS_DETECTOR_PLATFORM'], 'thor')
            self.assertEqual(detector['image'], b.CV_IMAGE)
            self.assertEqual(detector['healthcheck']['test'], ['CMD', 'python3', '-c', b.DETECTOR_HEALTH_PROBE])
            self.assertEqual(detector['depends_on']['broker-health-check']['condition'],
                             'service_completed_successfully')
            self.assertFalse(detector['image'].endswith('-sbsa'))
            self.assertTrue(any(m['source'].endswith('/models/thor-detector') for m in detector['volumes']))
            self.assertEqual(services['vss-agent']['environment']['VSS_WAREHOUSE_MAX_SOURCES'], '1')
            b.render()
            self.assertTrue(b.settings()['detector_enabled'])
            self.assertTrue(b.settings()['cached_models'])
            self.assertEqual(b.settings()['host_ip'], '192.0.2.40')
            b.render('192.0.2.40', detector_enabled=False)
            self.assertNotIn('thor-perception', json.loads((b.STATE / 'compose.json').read_text())['services'])

    def test_mode_change_preserves_external_data_root(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as data, \
                patch.object(b, 'STATE', Path(temporary)):
            b.render('192.0.2.40', data_dir=data, gateway='192.0.2.1')
            b.render(cached_models=True)
            self.assertEqual(b.settings()['data_dir'], data)
            self.assertEqual(b.settings()['gateway'], '192.0.2.1')

    def test_render_isolated_exact_models_and_safe_startup(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(b, 'STATE', Path(temporary)):
            with patch.dict(os.environ, {'NGC_API_KEY': 'credential-must-never-be-rendered',
                                         'HARDWARE_PROFILE': 'DGX-SPARK', 'HOST_IP': '10.0.0.99'}):
                b.render('192.0.2.40', gateway='172.17.0.1')
            text = (b.STATE / 'compose.json').read_text()
            graph = json.loads(text)
            services = graph['services']
            self.assertNotIn('credential-must-never-be-rendered', text)
            self.assertNotIn('10.0.0.99', text)
            self.assertNotIn('-sbsa', text)
            self.assertNotIn('spark-llm', services)
            self.assertEqual(services['thor-llm']['image'], b.LLM_IMAGE)
            self.assertIn('@sha256:', services['evidence-clip']['build']['args']['PYTHON_BASE_IMAGE'])
            self.assertEqual(services['vss-agent']['environment']['LLM_NAME'], b.LLM)
            self.assertEqual(services['rtvi-vlm']['build']['args']['BASE_IMAGE'], b.VLM_IMAGE)
            self.assertEqual(services['rtvi-embed']['build']['args']['BASE_IMAGE'], b.EMBED_IMAGE)
            self.assertEqual(services['rtvi-vlm']['environment']['VLLM_KV_CACHE_MEMORY_BYTES'], '3221225472')
            self.assertEqual(services['rtvi-vlm']['command'], ['python3', '/opt/thor/cosmos-launcher.py'])
            self.assertTrue(any(m['target'] == '/opt/thor/cosmos-launcher.py'
                                and m.get('read_only') for m in services['rtvi-vlm']['volumes']))
            self.assertIn('/usr/local/bin/thor-startup-gate.py', services['rtvi-vlm']['entrypoint'])
            self.assertEqual(services['rtvi-embed']['environment']['VLM_BATCH_SIZE'], '2')
            self.assertEqual(services['rtvi-embed']['environment']['HF_HUB_OFFLINE'], '1')
            for role in ('rtvi-embed', 'rtvi-vlm'):
                self.assertEqual(services[role]['environment']['RTVI_GPU_RESIZE_INTERPOLATION'], 'nearest')
            self.assertEqual(services['rtvi-embed']['environment']['NGC_API_KEY'], '')
            self.assertTrue(any('/models--bert-base-uncased/snapshots/' + b.BERT_REVISION in m['target']
                                and m.get('read_only') for m in services['rtvi-embed']['volumes']))
            for name in ('rtvi-embed', 'rtvi-vlm'):
                mount = next(m for m in services[name]['volumes']
                             if m['target'] == '/opt/nvidia/rtvi/.rtvi/ngc_model_cache')
                self.assertEqual(mount['type'], 'bind')
                self.assertTrue(mount['source'].endswith('/models/rtvi-ngc'))
            self.assertEqual(services['lvs-server']['environment']['VSS_EXTRA_ARGS'], '--max-live-streams 2')
            self.assertEqual(services['lvs-server'].get('command'), None)
            self.assertEqual(services['vss-ui']['environment']['HARDWARE_PROFILE'], 'AGX-THOR')
            self.assertNotIn('SPARK_CAPACITY_URL', services['vss-ui']['environment'])
            self.assertEqual(services['vss-ui']['mem_limit'], '4g')
            self.assertEqual(services['cadvisor']['mem_limit'], '1g')
            self.assertEqual(services['tegrastats-exporter']['mem_limit'], '256m')
            self.assertEqual(services['vss-ui']['environment']['TEGRASTATS_METRICS_URL'],
                             'http://172.17.0.1:19101/metrics')
            self.assertTrue(any(m['source'].endswith('/thor-local/observability/prometheus.yml')
                                for m in services['prometheus']['volumes']))
            self.assertIn('--nvidia-smi', services['tegrastats-exporter']['command'])
            self.assertTrue(all(service['restart'] == 'no' for service in services.values()))
            self.assertFalse(any(name.startswith('perception-') for name in services))
            self.assertEqual(json.loads((b.STATE / 'settings.json').read_text())['reserve_gib'], 48)
            self.assertEqual((b.STATE / 'compose.json').stat().st_mode & 0o777, 0o600)
            for service in services.values():
                self.assertTrue(all(name in services for name in service.get('depends_on', {})))
            b.render('192.0.2.40', cached_models=True)
            cached = json.loads((b.STATE / 'compose.json').read_text())['services']
            for name in ('rtvi-embed', 'rtvi-vlm'):
                self.assertEqual(cached[name]['environment']['NGC_API_KEY'], '')
                self.assertEqual(cached[name]['environment']['HF_HUB_OFFLINE'], '1')
                cache = next(m for m in cached[name]['volumes']
                             if m['target'] == '/opt/nvidia/rtvi/.rtvi/ngc_model_cache')
                self.assertTrue(cache['read_only'])
            self.assertEqual(cached['rtvi-vlm']['environment']['VLM_RUNTIME_STATE_DIR'],
                             '/tmp/huggingface/thor-cosmos-runtime')

    def test_refuses_other_hardware_before_runtime_changes(self):
        with patch.object(b, 'run', return_value=subprocess.CompletedProcess([], 0, 'NVIDIA GB10\n')):
            with self.assertRaisesRegex(RuntimeError, 'non-Thor'):
                b.require_thor()

    def test_guard_for_wrong_project_or_lower_reserve_is_rejected(self):
        for environment in ('VSS_MEMORY_FLOOR_GIB=36 VSS_GUARD_PROJECT=vss-thor',
                            'VSS_MEMORY_FLOOR_GIB=48 VSS_GUARD_PROJECT=historical'):
            with self.subTest(environment=environment), patch.object(b, 'run',
                    return_value=subprocess.CompletedProcess([], 0, environment)):
                with self.assertRaisesRegex(RuntimeError, 'correct project'):
                    b.require_guard()

    def test_model_verification_rejects_extra_files(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(b, 'STATE', Path(temporary)):
            data = b.STATE / 'data'
            model = data / 'models/nemotron'
            model.mkdir(parents=True)
            (b.STATE / 'settings.json').write_text(json.dumps({'data_dir': str(data)}))
            (model / 'untrusted-code.py').write_text('pass')
            with self.assertRaisesRegex(RuntimeError, 'membership'):
                b.verify_model()

    def test_cosmos_checksum_change_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / 'model.bin'
            path.write_bytes(b'good')
            entries = [{'path': 'model.bin', 'type': 'file', 'size': 4,
                        'sha256': hashlib.sha256(b'good').hexdigest()}]
            with patch.object(b, 'cosmos_entries', return_value=entries):
                b.verify_cosmos(folder)
                path.write_bytes(b'evil')
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    b.verify_cosmos(folder)
                path.unlink()
                other = folder.parent / (folder.name + '-other.bin')
                try:
                    other.write_bytes(b'good')
                    path.symlink_to(other)
                    with self.assertRaisesRegex(RuntimeError, 'symlink'):
                        b.verify_cosmos(folder)
                finally:
                    other.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
