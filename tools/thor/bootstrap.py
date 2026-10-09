#!/usr/bin/env python3
"""Fresh-checkout Thor candidate using the September bounded-memory recipe.

This does not override the older official-edge launcher's safety fuse. Runtime
acceptance is new evidence, separate from the historical recovery receipts.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import http.client
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import secrets
import shutil
import shlex
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.thor'
PROJECT = 'vss-thor'
DEFAULT_RESERVE_GIB = 48
LLM = 'nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8'
REVISION = '3fe6dab75665a93884214ad4b1b95cf02717d081'
VLM = 'nim_nvidia_cosmos3-nano-reasoner_bf16-final'
EMBED = 'nvidia/Cosmos-Embed1-448p-anomaly-detection'
EMBED_REVISION = '3b1455ed97c7b1d5419c0c3129b7199ca4cd9382'
BERT_REVISION = '86b5e0934494bd15c9632b12f734a8a67f723594'
LLM_IMAGE = 'ghcr.io/nvidia-ai-iot/vllm@sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8'
VLM_IMAGE = 'nvcr.io/nvidia/vss-core/vss-rt-vlm@sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504'
EMBED_IMAGE = 'nvcr.io/nvidia/vss-core/vss-rt-embed@sha256:978ef47aca4eca1e158b587a962b23a5bd9b7a3e717e61763b5c15e7228a1438'
CV_IMAGE = 'nvcr.io/nvidia/vss-core/vss-rt-cv@sha256:de60ab521868db1ae37ea91b5afbe198ac62ee3ed95fcf9def5fbc77123f72c6'
DETECTOR_HEALTH_PROBE = (
    "import json,urllib.request; "
    "response=urllib.request.urlopen('http://127.0.0.1:9000/api/v1/health/get-dsready-state',timeout=3); "
    "payload=json.load(response); "
    "raise SystemExit(0 if payload.get('health-info',{}).get('ds-ready')=='YES' else 1)"
)
sys.path.insert(0, str(ROOT / 'tools/spark'))
spec = importlib.util.spec_from_file_location('thor_shared_helpers', ROOT / 'tools/spark/bootstrap.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
import history_metadata


def run(command, **kwargs):
    return subprocess.run([str(value) for value in command], check=True, **kwargs)


def clean_env():
    return {key: value for key, value in os.environ.items()
            if key in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'XDG_RUNTIME_DIR')}


def compose(*args):
    return ['docker', 'compose', '--project-name', PROJECT, '-f', STATE / 'compose.json', *args]


def settings():
    return json.loads((STATE / 'settings.json').read_text())


def memory_reserve():
    saved = settings() if (STATE / 'settings.json').exists() else {}
    return shared.validate_reserve(saved.get('reserve_gib', DEFAULT_RESERVE_GIB))


def prepare_build_contexts(services):
    """Snapshot literal COPY inputs without traversing private runtime data.

    BuildKit's wildcard COPY traversal can touch unreadable database trees even
    with ignore files. These two source overlays need only the named inputs.
    Refresh snapshots before each build so source changes are included.
    """
    for name in ('alert-bridge', 'lvs-server'):
        build = services[name]['build']
        dockerfile = Path(build['dockerfile'])
        context = STATE / 'build-contexts' / name
        if context.is_symlink():
            raise RuntimeError('Build context cannot be a symlink')
        # This directory contains generated source copies only. Removing it
        # prevents deleted repository files from surviving a later snapshot.
        if context.exists():
            shutil.rmtree(context)
        context.mkdir(parents=True, exist_ok=True)
        for line in (ROOT / dockerfile).read_text().splitlines():
            if not line.startswith('COPY '):
                continue
            fields = shlex.split(line)[1:]
            while fields and fields[0].startswith('--'):
                fields.pop(0)
            if len(fields) < 2:
                raise RuntimeError(f'Unsupported COPY in {dockerfile}')
            for pattern in fields[:-1]:
                if '$' in pattern or Path(pattern).is_absolute() or '..' in Path(pattern).parts:
                    raise RuntimeError(f'Unsupported build source {pattern}')
                matches = list(ROOT.glob(pattern))
                if not matches:
                    raise RuntimeError(f'Missing build source {pattern}')
                for source in matches:
                    if not source.is_file() or source.is_symlink() or source.resolve() != source:
                        raise RuntimeError(f'Build source must be a regular file: {source}')
                    target = context / source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        target = context / dockerfile
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / dockerfile, target)
        ignore = ROOT / (str(dockerfile) + '.dockerignore')
        if ignore.exists():
            shutil.copyfile(ignore, context / ignore.relative_to(ROOT))
        build['context'] = str(context)


def require_thor():
    result = run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                 capture_output=True, text=True, timeout=15)
    if 'THOR' not in result.stdout.upper():
        raise RuntimeError('Refusing runtime changes on a non-Thor GPU.')


def doctor():
    require_thor()
    info = json.loads(run(['docker', 'info', '--format', '{{json .}}'],
                         capture_output=True, text=True, timeout=15).stdout)
    blockers = []
    if 'nvidia' not in info['Runtimes']:
        blockers.append('NVIDIA container runtime is not registered')
    if info['CgroupDriver'] != 'cgroupfs':
        blockers.append('Apply the reviewed host-cgroupfs-remediation transaction')
    for name, required in {'vm/max_map_count': 262144, 'net/core/rmem_max': 5242880,
                           'net/core/wmem_max': 5242880}.items():
        if int((Path('/proc/sys') / name).read_text()) < required:
            blockers.append(f'{name} must be at least {required}')
    if shared.available() < memory_reserve():
        blockers.append(f'Less than the configured {memory_reserve():g} GiB reserve is available')
    if blockers:
        raise RuntimeError('; '.join(blockers))
    print(f'Thor host prerequisites pass; {shared.available():.2f} GiB available. '
          'Application and driver compatibility still require runtime tests.')


def render(host_ip=None, data_dir=None, gateway=None, cached_models=None, detector_enabled=None, reserve_gib=None):
    saved = settings() if (STATE / 'settings.json').exists() else {}
    reserve = memory_reserve() if reserve_gib is None else shared.validate_reserve(reserve_gib)
    host_ip = host_ip or saved.get('host_ip', '127.0.0.1')
    gateway = gateway or saved.get('gateway', '172.17.0.1')
    if cached_models is None:
        cached_models = saved.get('cached_models', False)
    if detector_enabled is None:
        detector_enabled = saved.get('detector_enabled', False)
    ipaddress.IPv4Address(host_ip)
    ipaddress.IPv4Address(gateway)
    data = Path(data_dir or saved.get('data_dir') or STATE / 'data').expanduser().resolve()
    if data == ROOT or (ROOT in data.parents and STATE not in data.parents):
        raise RuntimeError('Use .thor/data or a data directory outside the checkout.')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    graph_password = STATE / 'graph-password'
    if not graph_password.exists():
        shared.private_write(graph_password, secrets.token_hex(24))
    values = dict(
        HARDWARE_PROFILE='AGX-THOR', COMPOSE_PROFILES='bp_developer_thor_full_2d',
        COMPOSE_PROJECT_NAME=PROJECT, VSS_APPS_DIR=str(ROOT / 'deploy/docker'), VSS_REPO_ROOT=str(ROOT),
        VSS_DATA_DIR=str(data), MODEL_ROOT_DIR=str(data / 'models'),
        HOST_IP=host_ip, EXTERNAL_IP=host_ip, THOR_LOCAL_MODEL_BIND_HOST=gateway,
        LLM_NAME=LLM, LLM_BASE_URL='http://127.0.0.1:30081', LLM_MODEL_TYPE='vllm',
        VLM_MODE='local_shared', VLM_NAME=VLM, VLM_MODEL_TYPE='rtvi', VLM_BASE_URL='http://127.0.0.1:8018',
        RTVI_VLM_BASE_IMAGE=VLM_IMAGE, RTVI_VLM_BASE_URL='http://127.0.0.1:8018', RTVI_VLM_ENDPOINT='',
        RTVI_VLM_MODEL_TO_USE='cosmos-reason3',
        RTVI_VLM_MODEL_PATH='/opt/nvidia/rtvi/.rtvi/ngc_model_cache/' + VLM if cached_models
                            else 'ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final',
        RTVI_EMBED_BASE_IMAGE=EMBED_IMAGE,
        RTVI_VLLM_GPU_MEMORY_UTILIZATION='0.30', RTVI_VLLM_MAX_NUM_SEQS='1',
        RTVI_VLM_MAX_MODEL_LEN='16384', RTVI_VLM_MAX_GENERATION_TOKENS='4096', RTVI_EMBED_BATCH_SIZE='2',
        RTVI_EMBED_KAFKA_ENABLED='true', RTVI_EMBED_KAFKA_TOPIC='mdx-embed', LVS_TAG='3.2.1',
        VSS_AGENT_HOST='127.0.0.1', VSS_AGENT_BACKEND_HOST='127.0.0.1', VSS_UI_PORT='3001',
        COSMOS_EMBED_ENDPOINT='http://127.0.0.1:8017', ELASTIC_SEARCH_ENDPOINT='http://127.0.0.1:9200',
        NEXT_PUBLIC_APP_TITLE='LOCAL VIDEO INTELLIGENCE', NEXT_PUBLIC_APP_SUBTITLE='ANVIL T5 · JETSON THOR',
        ALERT_ALWAYS_ON_ENABLED='false', GRAPH_DB_PASSWORD=graph_password.read_text().strip(),
        NPM_CONFIG_REGISTRY='https://registry.npmmirror.com',
        NGC_API_KEY='', NGC_CLI_API_KEY='', NVIDIA_API_KEY='', HF_TOKEN='', OPENAI_API_KEY='local')
    template = (ROOT / 'deploy/docker/developer-profiles/dev-profile-thor-full/.env').read_text()
    for key, value in values.items():
        if any(c in value for c in "\n\r'"):
            raise RuntimeError(f'Unsupported character in {key}')
        line = f"{key}='{value}'"
        if re.search(r'^' + key + '=', template, re.M):
            template = re.sub(r'^' + key + '=.*$', lambda _: line, template, flags=re.M)
        else:
            template += '\n' + line + '\n'
    env_path = STATE / 'generated.env'
    shared.private_write(env_path, template)
    graph = json.loads(run(['docker', 'compose', '--env-file', env_path,
        '-f', ROOT / 'deploy/docker/compose.yml', '-f', ROOT / 'deploy/docker/thor-local/compose.yml',
        'config', '--format', 'json'], env=clean_env(), capture_output=True, text=True).stdout)
    services = graph['services']
    services['evidence-clip']['build'].setdefault('args', {})['PYTHON_BASE_IMAGE'] = \
        'python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c'
    # The host tegrastats executable and its loader/libs are already mounted.
    # This observer needs only Python's standard library, not the agent image.
    services['tegrastats-exporter'].update(
        image='python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c',
        runtime='nvidia', mem_limit='256m', memswap_limit='256m',
        environment={'NVIDIA_VISIBLE_DEVICES': 'all', 'NVIDIA_DRIVER_CAPABILITIES': 'utility'})
    services['tegrastats-exporter']['command'] += ['--nvidia-smi', '/usr/sbin/nvidia-smi']
    observer = services['tegrastats-exporter']
    observer['command'][observer['command'].index('--bind-address') + 1] = gateway
    observer['healthcheck']['test'] = ['CMD', '/usr/local/bin/python3', '-c',
        f"import urllib.request; urllib.request.urlopen('http://{gateway}:19101/readyz', timeout=3)"]
    for mount in services['prometheus']['volumes']:
        if mount['target'] == '/etc/prometheus/prometheus.yml':
            mount['source'] = str(ROOT / 'deploy/docker/thor-local/observability/prometheus.yml')
    services['streamprocessing-ms']['build']['args'].update(
        CODEC_LOCK_PATH='deploy/docker/thor-current/codecs.lock.json',
        CODEC_BUNDLE_PATH='deploy/docker/thor-current/vios-codecs/bundle')
    # Stage the core first. Detector enablement follows isolated CUDA probes.
    for name in list(services):
        if name.startswith('perception-'):
            del services[name]
    vst_config = json.loads((ROOT / 'deploy/docker/thor-local/vios/vst_config.json').read_text())
    vst_config['network']['rtsp_streaming_over_tcp'] = True
    # A newly registered source must wait for explicit, bounded capture selection.
    vst_config['data']['always_recording'] = False
    shared.private_write(STATE / 'vst-config.json', json.dumps(vst_config, indent=2))
    for service in services.values():
        for mount in service.get('volumes', []):
            if mount.get('target') == '/home/vst/vst_release/configs/vst_config.json':
                mount['source'] = str(STATE / 'vst-config.json')
    services['logstash'].setdefault('volumes', []).append({
        'type': 'bind', 'source': str(ROOT / 'deploy/docker/spark/logstash-bootstrap.rb'),
        'target': '/usr/share/logstash/lib/bootstrap/environment.rb', 'read_only': True})
    services['rtvi-vlm']['environment'].update(
        VLM_RUNTIME_STATE_DIR='/tmp/huggingface/thor-cosmos-runtime',
        VLLM_KV_CACHE_MEMORY_BYTES='3221225472', VLLM_ENFORCE_EAGER='true',
        VLLM_MAX_NUM_SEQS='1', VLLM_MM_PROCESSOR_CACHE_GB='0',
        VLLM_DISABLE_MM_PREPROCESSOR_CACHE='true', VLLM_MAX_NUM_BATCHED_TOKENS='4096')
    # Preserve the shared Kafka startup gate; only Cosmos's pinned vendor
    # launcher is adapted to avoid a second private MPS daemon on this GPU.
    services['rtvi-vlm']['command'] = ['python3', '/opt/thor/cosmos-launcher.py']
    services['rtvi-vlm']['volumes'].append({
        'type': 'bind', 'source': str(ROOT / 'tools/thor/cosmos_launcher.py'),
        'target': '/opt/thor/cosmos-launcher.py', 'read_only': True,
        'bind': {'create_host_path': False}})
    for name in ('rtvi-embed', 'rtvi-vlm'):
        services[name]['environment'].update(RTVI_GPU_RESIZE_INTERPOLATION='nearest',
            RTVI_OFFLINE='true' if cached_models else 'false',
            HF_HUB_OFFLINE='1' if cached_models else '0', TRANSFORMERS_OFFLINE='1' if cached_models else '0',
            NGC_API_KEY='' if cached_models else '${NGC_API_KEY:-}')
        for mount in services[name].get('volumes', []):
            if mount.get('target') == '/opt/nvidia/rtvi/.rtvi/ngc_model_cache':
                mount.clear()
                mount.update(type='bind', source=str(data / 'models/rtvi-ngc'),
                             target='/opt/nvidia/rtvi/.rtvi/ngc_model_cache',
                             read_only=bool(cached_models or name == 'rtvi-embed'))
    services['rtvi-embed']['environment']['MODEL_PATH'] = \
        '/opt/nvidia/rtvi/.rtvi/ngc_model_cache/' + EMBED.split('/')[-1]
    auxiliary = verify_embedding_auxiliary()
    hf_root = '/tmp/huggingface/hub/models--bert-base-uncased'
    services['rtvi-embed']['volumes'].extend([
        {'type': 'bind', 'source': str(auxiliary / 'config.json'),
         'target': hf_root + '/snapshots/' + BERT_REVISION + '/config.json',
         'read_only': True, 'bind': {'create_host_path': False}},
        {'type': 'bind', 'source': str(auxiliary / 'refs-main'),
         'target': hf_root + '/refs/main', 'read_only': True,
         'bind': {'create_host_path': False}}])
    # Both the embedding weights and its QFormer configuration are staged.
    services['rtvi-embed']['environment'].update(HF_HOME='/tmp/huggingface',
        HF_HUB_CACHE='/tmp/huggingface/hub', HUGGINGFACE_HUB_CACHE='/tmp/huggingface/hub',
        TRANSFORMERS_CACHE='/tmp/huggingface/hub', HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1', NGC_API_KEY='', RTVI_OFFLINE='true')
    model_root = data / 'models/nemotron'
    services['thor-llm'] = {
        'image': LLM_IMAGE, 'runtime': 'nvidia', 'network_mode': 'host', 'shm_size': '2g',
        'environment': {'NVIDIA_VISIBLE_DEVICES': '0', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                        'VLLM_CACHE_ROOT': '/cache/vllm'},
        'volumes': [{'type': 'bind', 'source': str(model_root), 'target': '/models/nemotron', 'read_only': True,
                     'bind': {'create_host_path': False}},
                    {'type': 'bind', 'source': str(data / 'models/vllm-cache'), 'target': '/cache'}],
        'entrypoint': ['python3', '-m', 'vllm.entrypoints.openai.api_server'],
        'command': ['--model', '/models/nemotron', '--tokenizer', '/models/nemotron',
                    '--served-model-name', LLM, '--trust-remote-code', '--host', '127.0.0.1', '--port', '30081',
                    '--enforce-eager', '--gpu-memory-utilization', '0.12',
                    '--kv-cache-memory-bytes', '2147483648', '--max-model-len', '32768',
                    '--max-num-seqs', '1', '--max-num-batched-tokens', '2048',
                    '--enable-auto-tool-choice', '--tool-call-parser', 'qwen3_coder'],
        'healthcheck': {'test': ['CMD', 'curl', '-f', 'http://127.0.0.1:30081/health'],
                        'interval': '15s', 'timeout': '5s', 'retries': 80, 'start_period': '120s'}}
    agent = services['vss-agent']
    agent['command'] = ['serve', '--config_file', '/vss-agent/deploy/docker/spark/config.yml',
                        '--host', '127.0.0.1', '--port', '8100']
    agent['environment'].update(VSS_AGENT_CONFIG_FILE='/vss-agent/deploy/docker/spark/config.yml',
        VSS_WAREHOUSE_RTVI_CV_URL='', VSS_TRAFFIC_RTVI_CV_URL='', VSS_OBJECT_APPEARANCE_ENABLED='false',
        VST_CLIP_FALLBACK_URL='http://127.0.0.1:8098',
        VST_CLIP_FALLBACK_MEDIA_URL=f'http://{host_ip}:7777/api/vision/evidence-media',
        EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY='true')
    if detector_enabled:
        services['thor-perception'] = {
            'image': CV_IMAGE,
            'container_name': 'vss-rtvi-cv', 'network_mode': 'host', 'runtime': 'nvidia',
            'working_dir': '/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app',
            'entrypoint': [], 'command': ['bash', '/opt/spark/detector-start.sh'],
            'mem_limit': '6g', 'memswap_limit': '6g', 'shm_size': '2g', 'cpus': 4,
            'environment': {'HARDWARE_PROFILE': 'AGX-THOR', 'VSS_DETECTOR_PLATFORM': 'thor',
                'NVIDIA_VISIBLE_DEVICES': '0', 'DS_MODEL_FAMILY': 'rtdetr-warehouse',
                'DS_MODE_FLAG': '1', 'DS_MESSAGE_RATE': '1', 'DS_TRACKER_REID': 'false',
                'DS_SHOW_SENSOR_ID': 'false', 'NUM_SENSORS': '1', 'STREAM_TYPE': 'kafka',
                'DEEPSTREAM_ENABLE_SENSOR_ID_EXTRACTION': '1',
                'GST_ENABLE_CUSTOM_PARSER_MODIFICATIONS': '1', 'OTEL_SDK_DISABLED': 'true'},
            'volumes': [
                {'type': 'bind', 'source': str(ROOT / 'deploy/docker/spark'),
                 'target': '/opt/spark', 'read_only': True},
                {'type': 'bind', 'source': str(ROOT / 'deploy/docker/industry-profiles/warehouse-operations/warehouse-2d-app/deepstream/configs'),
                 'target': '/opt/spark-detector-templates', 'read_only': True},
                {'type': 'bind', 'source': str(data / 'models/thor-detector'), 'target': '/opt/storage'}],
            'depends_on': {'broker-health-check': {'condition': 'service_completed_successfully'}},
            'healthcheck': {'test': ['CMD', 'python3', '-c', DETECTOR_HEALTH_PROBE],
                'interval': '15s', 'timeout': '5s', 'retries': 60, 'start_period': '120s'}}
        agent['environment'].update(VSS_WAREHOUSE_RTVI_CV_URL='http://127.0.0.1:9000',
            VSS_OBJECT_APPEARANCE_ENABLED='true', VSS_WAREHOUSE_MAX_SOURCES='1')
        services['vss-ui']['environment']['RTVI_CV_HEALTH_URL'] = 'http://127.0.0.1:9000/api/v1/health/get-dsready-state'
    services['vss-va-mcp']['command'] = ['mcp', 'serve', '--config_file',
        '/vss-agent/deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/va_mcp_server_config.yml',
        '--host', '127.0.0.1', '--port', '9901']
    services['lvs-server']['environment'].update(LVS_LLM_BASE_URL='http://127.0.0.1:30081/v1',
        LVS_LLM_MODEL_NAME=LLM, VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME=VLM,
        VIA_VLM_ENDPOINT='http://127.0.0.1:8018/v1/', LVS_EMB_DIMENSIONS='768')
    services['lvs-server']['environment']['VSS_EXTRA_ARGS'] = '--max-live-streams 2'
    services['alert-bridge']['healthcheck'] = {
        'test': ['CMD', '/usr/local/bin/python', '-c',
                 'import json,urllib.request; '
                 'r=urllib.request.urlopen("http://127.0.0.1:9080/health",timeout=3); '
                 'assert r.status==200 and json.load(r).get("status")=="ok"; r.close()'],
        'interval': '15s', 'timeout': '5s', 'retries': 6, 'start_period': '30s'}
    token = history_metadata.token_value(STATE)
    services['evidence-clip']['environment']['HISTORY_METADATA_TOKEN'] = token
    services['evidence-clip'].setdefault('volumes', []).append({
        'type': 'bind', 'source': str(ROOT / 'deploy/docker/thor-local/evidence-clip/server.py'),
        'target': '/app/server.py', 'read_only': True})
    services['history-maintenance'] = history_metadata.compose_service(graph, ROOT, token=token)
    services['vss-ui']['environment'].update(HARDWARE_PROFILE='AGX-THOR', HISTORY_METADATA_TOKEN=token,
        TEGRASTATS_METRICS_URL=f'http://{gateway}:19101/metrics')
    if 'cadvisor' in services:
        services['cadvisor'].update(mem_limit='1g', memswap_limit='1g')
        command = services['cadvisor'].get('command', [])
        for index, argument in enumerate(command):
            if argument.startswith('--disable_metrics=') and 'disk' not in argument.split('=', 1)[1].split(','):
                command[index] += ',disk'
    # A fresh installation uses source HMR immediately. A full UI build is
    # needed only when deliberately preparing the packaged fallback.
    ui = services['vss-ui']
    ui.pop('build', None)
    ui.update(image='node:22.22.3-bookworm-slim', runtime='runc', user=f'65532:{os.getgid()}',
        working_dir='/workspace/apps/nv-metropolis-bp-vss-ui',
        entrypoint=['/bin/sh', '-ec'],
        command=['umask 0002; exec node ../../node_modules/next/dist/bin/next dev --turbopack -H 0.0.0.0 -p 3001'],
        mem_limit='4g', memswap_limit='4g')
    ui['environment'].update(NODE_ENV='development', NODE_OPTIONS='--max-old-space-size=2048',
        NEXT_TELEMETRY_DISABLED='1')
    ui['volumes'] += [
        {'type': 'bind', 'source': str(ROOT / 'services/ui'), 'target': '/workspace'},
        {'type': 'bind', 'source': str(STATE / 'ui-next'),
         'target': '/workspace/apps/nv-metropolis-bp-vss-ui/.next'}]
    for name, service in services.items():
        service.pop('profiles', None)
        service['restart'] = 'no'
        service.get('deploy', {}).pop('restart_policy', None)
        if service.get('build'):
            service['image'] = f'vss-thor-{name}:source'
        service.setdefault('group_add', []).append(str(os.getgid()))
        for dependency in list(service.get('depends_on', {})):
            if dependency not in services:
                del service['depends_on'][dependency]
        for mount in service.get('volumes', []):
            if mount.get('type') == 'bind' and mount.get('source', '').startswith(str(data) + '/'):
                mount.setdefault('bind', {})['create_host_path'] = False
    services['broker-health-check']['depends_on'] = {
        'kafka': {'condition': 'service_healthy'},
        'kafka-topic-init-container': {'condition': 'service_completed_successfully'}}
    prepare_build_contexts(services)
    shared.booth_runtime_safety(graph, state=STATE, hardware='AGX-THOR')
    encoded = re.sub(r'(?<!\$)\$(?!\$)', lambda _: '$$', json.dumps(graph, indent=2))
    encoded = encoded.replace('$${NGC_API_KEY:-}', '${NGC_API_KEY:-}')
    shared.private_write(STATE / 'compose.json', encoded + '\n')
    shared.private_write(STATE / 'settings.json', json.dumps(dict(host_ip=host_ip, gateway=gateway,
        data_dir=str(data), reserve_gib=reserve, cached_models=cached_models, detector_enabled=detector_enabled), indent=2))
    run(compose('config', '--quiet'), env=clean_env())
    print(f'Rendered {len(services)} Thor services. No models or services have been started.')


def install_guard():
    require_thor()
    unit = Path.home() / '.config/systemd/user/vss-memory-budget.service'
    unit.parent.mkdir(parents=True, exist_ok=True)
    if any(c in str(ROOT) for c in '\n"%'):
        raise RuntimeError('Unsupported systemd checkout path')
    unit.write_text(f'''[Unit]
Description=Thor VSS diagnostic memory and thermal guard
[Service]
ExecStart=/usr/bin/python3 "{ROOT / 'tools/runtime/guard.py'}"
Environment=VSS_MEMORY_FLOOR_GIB={memory_reserve():g}
Environment=VSS_GUARD_PROJECT={PROJECT}
Restart=on-failure
RestartSec=2
[Install]
WantedBy=default.target
''')
    run(['systemctl', '--user', 'daemon-reload'])
    run(['systemctl', '--user', 'enable', '--now', unit.name])
    run(['systemctl', '--user', 'restart', unit.name])


def model_entries():
    lock = json.loads((ROOT / 'deploy/docker/thor-local/official-edge/artifacts.lock.json').read_text())
    artifact = lock['artifacts']['edge4b']
    if artifact['identity'] != {'repository': LLM, 'revision': REVISION}:
        raise RuntimeError('Nemotron artifact identity differs from the reviewed Thor contract')
    return artifact['tree']['entries']


def verify_model():
    folder = Path(settings()['data_dir']) / 'models/nemotron'
    entries = model_entries()
    expected = {entry['path'] for entry in entries}
    actual = {str(path.relative_to(folder)) for path in folder.rglob('*') if path.is_file()}
    if actual != expected:
        raise RuntimeError('Nemotron file membership differs from the reviewed model lock')
    for entry in entries:
        path = folder / entry['path']
        if path.is_symlink() or path.stat().st_size != entry['resolved_size']:
            raise RuntimeError(f'Invalid Nemotron file: {entry["path"]}')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['resolved_sha256']:
            raise RuntimeError(f'Nemotron checksum mismatch: {entry["path"]}')
    print(f'Exact Nemotron revision and {len(entries)} model file hashes verified.')


def publish_complete_partial(partial, final, size, expected_sha256):
    """Recover a download interrupted after its last byte, before publication."""
    if partial.is_symlink():
        raise RuntimeError('Refusing a symlink in model staging')
    if not partial.exists() or partial.stat().st_size < size:
        return False
    with partial.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if partial.stat().st_size != size or digest != expected_sha256:
        raise RuntimeError(f'Completed partial checksum mismatch: {partial.name}')
    partial.chmod(0o644)
    partial.replace(final)
    return True


def embedding_entries():
    lock = json.loads((ROOT / 'deploy/docker/thor-current/embedding.lock.json').read_text())
    if lock.get('schema_version') != 1 or (lock['repository'], lock['revision']) != (EMBED, EMBED_REVISION):
        raise RuntimeError('Embedding snapshot identity differs from the Thor contract')
    entries = lock['files']
    names = [entry['path'] for entry in entries]
    if len(set(names)) != len(names) or any('/' in name or name in ('', '.', '..') for name in names):
        raise RuntimeError('Embedding lock must contain unique flat file paths')
    return entries


def verify_embed(folder=None):
    verify_embedding_auxiliary()
    folder = folder or Path(settings()['data_dir']) / 'models/rtvi-ngc' / EMBED.split('/')[-1]
    entries = embedding_entries()
    if folder.is_symlink() or {str(path.relative_to(folder)) for path in folder.rglob('*')} != \
            {entry['path'] for entry in entries}:
        raise RuntimeError('Embedding snapshot membership differs from the model lock')
    for entry in entries:
        path = folder / entry['path']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['size']:
            raise RuntimeError(f'Invalid embedding file: {entry["path"]}')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                raise RuntimeError(f'Embedding checksum mismatch: {entry["path"]}')
    print(f'Exact embedding revision and {len(entries)} file hashes verified.', flush=True)


def verify_embedding_auxiliary():
    root = ROOT / 'deploy/docker/thor-current'
    lock = json.loads((root / 'embedding-auxiliary.lock.json').read_text())
    if lock['repository'] != 'google-bert/bert-base-uncased' or \
            lock['revision'] != BERT_REVISION or lock['requested_alias'] != 'bert-base-uncased':
        raise RuntimeError('Embedding QFormer configuration identity changed')
    if len(lock['files']) != 3 or {entry['path'] for entry in lock['files']} != \
            {'config.json', 'LICENSE', 'refs-main'}:
        raise RuntimeError('Embedding auxiliary lock membership changed')
    folder = root / 'embedding-auxiliary'
    if folder.is_symlink() or {p.name for p in folder.iterdir()} != {'config.json', 'LICENSE', 'refs-main'}:
        raise RuntimeError('Embedding auxiliary bundle membership changed')
    for entry in lock['files']:
        if entry['path'] not in ('config.json', 'LICENSE', 'refs-main'):
            raise RuntimeError('Invalid embedding auxiliary file path')
        path = folder / entry['path']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['size'] or \
                hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError('Embedding auxiliary configuration changed')
    if (folder / 'refs-main').read_text() != BERT_REVISION:
        raise RuntimeError('Embedding auxiliary cache reference changed')
    return folder


def stage_embed():
    require_thor()
    require_guard()
    services = json.loads((STATE / 'compose.json').read_text())['services']
    models = [name for name in ('thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception') if name in services]
    if run(compose('ps', '--status', 'running', '-q', *models), capture_output=True, text=True).stdout.strip():
        raise RuntimeError('Stop AI models before staging the embedding cache')
    models_root = Path(settings()['data_dir']) / 'models'
    models_root.mkdir(parents=True, exist_ok=True)
    lease = models_root / '.embed-stage.lock'
    if lease.is_symlink():
        raise RuntimeError('Embedding staging lock cannot be a symlink')
    with lease.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another embedding staging process owns this cache') from error
        final = models_root / 'rtvi-ngc' / EMBED.split('/')[-1]
        if final.exists():
            verify_embed(final)
            return
        temporary = models_root / 'embed-staging'
        if temporary.is_symlink():
            raise RuntimeError('Embedding staging directory cannot be a symlink')
        temporary.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(temporary).free < 10 * 1024**3:
            raise RuntimeError('Need 10 GiB free for embedding staging')

        def download(entry):
            name = entry['path']
            path = temporary / name
            if path.is_symlink():
                raise RuntimeError('Embedding staging file cannot be a symlink')
            if path.exists():
                with path.open('rb') as stream:
                    if path.stat().st_size == entry['size'] and \
                            hashlib.file_digest(stream, 'sha256').hexdigest() == entry['sha256']:
                        return
                raise RuntimeError(f'Existing embedding file changed: {name}')
            partial = path.with_name(name + '.partial')
            if publish_complete_partial(partial, path, entry['size'], entry['sha256']):
                return
            print(f'Staging pinned embedding file: {name} ({entry["size"]} bytes)', flush=True)
            run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '5',
                 '--retry-delay', '2', '--continue-at', '-', '--output', partial,
                 f'https://huggingface.co/{EMBED}/resolve/{EMBED_REVISION}/{name}'])
            if not publish_complete_partial(partial, path, entry['size'], entry['sha256']):
                raise RuntimeError(f'Embedding transfer incomplete: {name}; partial bytes preserved')

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(download, embedding_entries()))
        verify_embed(temporary)
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(final)
        print('Verified embedding cache published; no AI service was started.', flush=True)


def stage_model():
    require_thor()
    folder = Path(settings()['data_dir']) / 'models/nemotron'
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < 10 * 1024**3:
        raise RuntimeError('Need 10 GiB free for the pinned Nemotron snapshot')
    for entry in model_entries():
        name = entry['path']
        path = folder / name
        if '/' in name or name.startswith('.') and name != '.gitattributes':
            raise RuntimeError('Unsupported path in pinned Nemotron lock')
        if path.is_symlink():
            raise RuntimeError('Refusing a symlink in the flat Nemotron staging directory')
        if path.is_file() and path.stat().st_size == entry['resolved_size']:
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == entry['resolved_sha256']:
                    continue
            raise RuntimeError(f'Existing model file changed: {name}')
        partial = folder.parent / (name + '.partial')
        if publish_complete_partial(partial, path, entry['resolved_size'], entry['resolved_sha256']):
            continue
        url = f'https://huggingface.co/{LLM}/resolve/{REVISION}/{name}'
        print(f'Staging pinned Nemotron file: {name}', flush=True)
        run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '5',
             '--retry-delay', '2', '--continue-at', '-', '--output', partial, url])
        with partial.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if partial.stat().st_size != entry['resolved_size'] or digest != entry['resolved_sha256']:
            raise RuntimeError(f'Downloaded model checksum mismatch: {name}')
        partial.chmod(0o644)
        partial.replace(path)
    verify_model()


def cosmos_entries():
    lock = json.loads((ROOT / 'deploy/docker/thor-local/official-edge/artifacts.lock.json').read_text())
    artifact = lock['artifacts']['cosmos3_nano_bf16']
    if artifact['identity'] != {'artifact_id': 'ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final'}:
        raise RuntimeError('Cosmos identity differs from the reviewed Thor contract')
    return artifact['tree']['entries']


def verify_cosmos(folder=None):
    folder = folder or Path(settings()['data_dir']) / 'models/rtvi-ngc' / VLM
    entries = cosmos_entries()
    expected = {entry['path'] for entry in entries}
    actual = {str(path.relative_to(folder)) for path in folder.rglob('*')}
    if actual != expected:
        raise RuntimeError('Cosmos file membership differs from the reviewed model lock')
    for entry in entries:
        path = folder / entry['path']
        if path.is_symlink():
            raise RuntimeError('Refusing a symlink in the Cosmos snapshot')
        if entry['type'] == 'directory':
            if not path.is_dir():
                raise RuntimeError('Cosmos directory differs from the reviewed lock')
            continue
        if not path.is_file() or path.stat().st_size != entry['size']:
            raise RuntimeError(f'Invalid Cosmos file: {entry["path"]}')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                raise RuntimeError(f'Cosmos checksum mismatch: {entry["path"]}')
    print('Exact Cosmos BF16 snapshot membership and all file hashes verified.', flush=True)


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def download_cosmos_file(api, key, entry, remote, partial, path, attempts=8):
    """Resume short or interrupted responses; publish only exact verified bytes."""
    name = entry['path']
    opener = urllib.request.build_opener(NoCredentialRedirect)
    for attempt in range(attempts):
        if publish_complete_partial(partial, path, entry['size'], entry['sha256']):
            return
        offset = partial.stat().st_size if partial.exists() else 0
        try:
            # Refresh the signed URL for every attempt; only metadata receives the key.
            download_api = api.replace('/versions/', '/') + '/files?' + urllib.parse.urlencode({'path': name})
            with opener.open(urllib.request.Request(download_api,
                    headers={'Authorization': 'Bearer ' + key}), timeout=30) as response:
                metadata = json.load(response)
            if metadata.get('filepath') != [name] or len(metadata.get('urls', [])) != 1 or \
                    metadata.get('sha256_base64') != [remote['sha256_base64']]:
                raise RuntimeError('NGC direct-download metadata differs from the reviewed file')
            location = metadata['urls'][0]
            if urllib.parse.urlsplit(location).scheme != 'https':
                raise RuntimeError('NGC returned a non-HTTPS download URL')
            response = urllib.request.urlopen(urllib.request.Request(location,
                headers={'Range': f'bytes={offset}-'} if offset else {}), timeout=60)
            with response:
                append = response.status == 206
                if append:
                    span = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not span or int(span[1]) != offset or int(span[3]) != entry['size'] or \
                            not offset <= int(span[2]) < entry['size']:
                        raise RuntimeError('NGC returned an unexpected resume range')
                elif response.status != 200:
                    raise RuntimeError('NGC returned an unexpected object response')
                written = offset if append else 0
                with partial.open('ab' if append else 'wb') as stream:
                    while True:
                        interrupted = False
                        try:
                            block = response.read(1024 * 1024)
                        except http.client.IncompleteRead as error:
                            block, interrupted = error.partial, True
                        if written + len(block) > entry['size']:
                            raise RuntimeError('NGC object exceeds the reviewed file size')
                        stream.write(block)
                        written += len(block)
                        if interrupted or not block:
                            break
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504):
                # Do not disclose signed URLs or credentials through exception text.
                raise RuntimeError(f'Cosmos request failed (HTTP {error.code}): {name}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            pass
        if publish_complete_partial(partial, path, entry['size'], entry['sha256']):
            return
        received = partial.stat().st_size if partial.exists() else 0
        print(f'Cosmos transfer incomplete: {name} ({received}/{entry["size"]} bytes, '
              f'attempt {attempt + 1}/{attempts})', flush=True)
        if attempt + 1 < attempts:
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f'Cosmos transfer exhausted bounded retries: {name}; partial bytes preserved')


def stage_detector():
    """Stage the published warehouse ONNX, never a Spark TensorRT engine."""
    require_thor()
    folder = Path(settings()['data_dir']) / 'models/thor-detector'
    folder.mkdir(parents=True, exist_ok=True)
    name = 'rtdetr_warehouse_v1.0.2.fp16.onnx'
    expected = '0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267'
    final = folder / name
    if final.is_symlink():
        raise RuntimeError('Refusing a symlink for the detector model')
    if final.exists():
        with final.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise RuntimeError('Existing detector model checksum changed')
        print('Published RT-DETR ONNX checksum verified; no detector started.')
        return
    if shutil.disk_usage(folder).free < 2 * 1024**3:
        raise RuntimeError('Need 2 GiB free to stage the detector ONNX')
    key = (Path.home() / '.config/cti-vss/ngc-api-key').read_text().strip()
    api = 'https://api.ngc.nvidia.com/v2/org/nvidia/team/tao/models/rtdetr_2d_warehouse'
    version = 'deployable_rn50_v1.0.2'
    authenticated = urllib.request.build_opener(NoCredentialRedirect)
    with authenticated.open(urllib.request.Request(f'{api}/versions/{version}/files',
            headers={'Authorization': 'Bearer ' + key}), timeout=30) as response:
        listing = json.load(response)
    entry = next((row for row in listing['modelFiles'] if row['path'] == name), None)
    if entry is None or base64.b64decode(entry['sha256_base64']).hex() != expected:
        raise RuntimeError('Published detector metadata differs from its reviewed checksum')
    partial = final.with_name(name + '.partial')
    if publish_complete_partial(partial, final, entry['sizeInBytes'], expected):
        print('Published RT-DETR ONNX checksum verified; no detector started.')
        return
    offset = partial.stat().st_size if partial.exists() else 0
    download_api = f'{api}/{version}/files?' + urllib.parse.urlencode({'path': name})
    with authenticated.open(urllib.request.Request(download_api,
            headers={'Authorization': 'Bearer ' + key}), timeout=30) as response:
        download = json.load(response)
    if download.get('filepath') != [name] or len(download.get('urls', [])) != 1 or \
            download.get('sha256_base64') != [entry['sha256_base64']]:
        raise RuntimeError('Detector direct-download metadata differs from its reviewed checksum')
    location = download['urls'][0]
    if urllib.parse.urlsplit(location).scheme != 'https':
        raise RuntimeError('NGC returned a non-HTTPS download URL')
    # Only the metadata API receives the key; object storage receives no credentials.
    response = urllib.request.urlopen(urllib.request.Request(location,
        headers={'Range': f'bytes={offset}-'} if offset else {}), timeout=60)
    append = offset and response.status == 206
    if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
        response.close()
        raise RuntimeError('NGC returned an unexpected resume range')
    print(f'Staging published detector ONNX ({entry["sizeInBytes"]} bytes)', flush=True)
    with response, partial.open('ab' if append else 'wb') as stream:
        while block := response.read(1024 * 1024):
            stream.write(block)
    with partial.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if partial.stat().st_size != entry['sizeInBytes'] or digest != expected:
        raise RuntimeError('Detector ONNX checksum mismatch')
    partial.chmod(0o644)
    partial.replace(final)
    print('Published RT-DETR ONNX checksum verified; no detector started.', flush=True)


def stage_cosmos():
    require_thor()
    models = Path(settings()['data_dir']) / 'models'
    models.mkdir(parents=True, exist_ok=True)
    lock = models / '.cosmos-stage.lock'
    if lock.is_symlink():
        raise RuntimeError('Cosmos staging lock cannot be a symlink')
    with lock.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another Cosmos staging process owns this cache') from error
        stage_cosmos_snapshot()


def stage_cosmos_snapshot():
    require_thor()
    parent = Path(settings()['data_dir']) / 'models/rtvi-ngc'
    final = parent / VLM
    if final.exists():
        verify_cosmos(final)
        return
    temporary = parent.parent / 'cosmos-staging'
    temporary.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(temporary).free < 25 * 1024**3:
        raise RuntimeError('Need 25 GiB free for the pinned Cosmos snapshot')
    key = (Path.home() / '.config/cti-vss/ngc-api-key').read_text().strip()
    api = 'https://api.ngc.nvidia.com/v2/org/nim/team/nvidia/models/cosmos3-nano-reasoner/versions/bf16-final'
    authenticated = urllib.request.build_opener(NoCredentialRedirect)
    with authenticated.open(urllib.request.Request(api + '/files',
            headers={'Authorization': 'Bearer ' + key}), timeout=30) as response:
        listing = json.load(response)
    entries = cosmos_entries()
    files = {entry['path']: entry for entry in entries if entry['type'] == 'file'}
    remote = {entry['path']: entry for entry in listing['modelFiles']}
    if listing['paginationInfo']['totalResults'] != len(remote) or remote.keys() != files.keys():
        raise RuntimeError('NGC Cosmos file listing differs from the reviewed artifact lock')
    for name, entry in files.items():
        if remote[name]['sizeInBytes'] != entry['size'] or \
                base64.b64decode(remote[name]['sha256_base64']).hex() != entry['sha256']:
            raise RuntimeError('NGC Cosmos metadata differs from the reviewed artifact lock')
    def download(entry):
        relative = PurePosixPath(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Unsafe path in Cosmos artifact lock')
        path = temporary / relative
        if path.is_symlink():
            raise RuntimeError('Refusing a symlink in Cosmos staging')
        if entry['type'] == 'directory':
            path.mkdir(parents=True, exist_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if path.stat().st_size != entry['size'] or digest != entry['sha256']:
                raise RuntimeError('Existing Cosmos staging file changed')
            return
        partial = path.with_name(path.name + '.partial')
        if publish_complete_partial(partial, path, entry['size'], entry['sha256']):
            return
        print(f'Staging pinned Cosmos file: {relative} ({entry["size"]} bytes)', flush=True)
        download_cosmos_file(api, key, entry, remote[str(relative)], partial, path)
    large = []
    for entry in entries:
        if entry['type'] == 'file' and entry['size'] >= 1024**3:
            large.append(entry)
        else:
            download(entry)
    # Four model shards, four small streaming buffers; each path has one owner.
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, large))
    verify_cosmos(temporary)
    parent.mkdir(parents=True, exist_ok=True)
    temporary.rename(final)
    print('Verified Cosmos cache atomically published; no inference service was started.', flush=True)


def stage():
    doctor()
    require_guard()
    if shutil.disk_usage(STATE).free < 200 * 1024**3:
        raise RuntimeError('Initial Thor staging requires at least 200 GiB free')
    services = json.loads((STATE / 'compose.json').read_text())['services']
    models = [name for name in ('thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception') if name in services]
    active = run(compose('ps', '--status', 'running', '-q', *models),
                 capture_output=True, text=True).stdout
    if active.strip():
        raise RuntimeError('Stop the AI model workloads before image staging or builds')
    lease = STATE / 'image-stage.lock'
    if lease.is_symlink():
        raise RuntimeError('Image staging lock cannot be a symlink')
    with lease.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another image staging process owns this candidate') from error
        stage_images(services)


def build_services(services):
    # COMPOSE_PARALLEL_LIMIT does not make one multi-target Bake invocation
    # serial. Give shared NVIDIA layers one build owner at a time instead.
    for name, service in services.items():
        if service.get('build'):
            run(compose('build', '--pull', name), env=clean_env())


def stage_images(services):
    shared.stage_codec_wheel(STATE)
    run([sys.executable, ROOT / 'tools/thor/restore_codecs.py'])
    run(['bash', ROOT / 'deploy/docker/thor-local/vios-mcp/stage-wheelhouse.sh'])
    pack = ROOT / 'deploy/docker/services/infra/elk/logstash/offline-packs/logstash-codec-protobuf-1.3.0-logstash-9.3.3.zip'
    run([sys.executable, pack.parent.parent / 'verify-protobuf-offline-pack.py', pack,
         str(pack) + '.sha256', str(pack) + '.expected.sha256'])
    # Shared NVCR layers should have one image pull owner at a time. Parallel
    # Compose pulls otherwise create persistent content-writer contention.
    run(compose('pull', '--ignore-buildable'), env={**clean_env(), 'COMPOSE_PARALLEL_LIMIT': '1'})
    prepare_build_contexts(services)
    build_services(services)
    print('Backend images staged. Model and application qualification remains pending.')


def provision():
    graph = json.loads((STATE / 'compose.json').read_text())
    data = Path(settings()['data_dir'])
    data.mkdir(parents=True, exist_ok=True)
    paths = sorted(shared.data_roots(graph, data))
    active = run(compose('ps', '--status', 'running', '-q'), capture_output=True, text=True).stdout.splitlines()
    protected = set()
    if active:
        for container in json.loads(run(['docker', 'inspect', *active], capture_output=True, text=True).stdout):
            protected.update(Path(mount['Source']) for mount in container['Mounts'] if mount['Type'] == 'bind')
    records = []
    for path in paths:
        if path.resolve() != path:
            raise RuntimeError('Data-directory paths cannot redirect through symlinks')
        path.mkdir(parents=True, exist_ok=True)
        if any(path == source or path in source.parents or source in path.parents for source in protected):
            # Re-running the support stage must not change an active database's
            # socket directory or the UI's already-mounted history roots.
            continue
        # Runtime data only. Never recursively chown source or model files.
        uid = 65532 if path.name in ('vision-history', 'vision-rules', 'vision-investigations', 'agent-reports') else 1000
        if path.name == 'vllm-cache':
            uid = 0
        records.append([str(path.relative_to(data)), uid, os.getgid()])
    provision_model_caches(graph)
    if not records:
        return
    run(['docker', 'run', '--rm', '--network', 'none', '--runtime', 'runc', '--user', '0:0',
         '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
         '-v', f'{data}:/data', '--entrypoint', 'node', 'node:22.22.3-bookworm-slim', '-e',
         "const fs=require('fs'); for(const [rel,uid,gid] of JSON.parse(process.argv[1])){"
         "const p='/data/'+rel; if(fs.lstatSync(p).isSymbolicLink())throw Error('symlink');"
         "fs.chownSync(p,uid,gid);fs.chmodSync(p,0o2770);}", json.dumps(records)])


def provision_model_caches(graph):
    """Prepare only inactive candidate cache-volume roots for RTVI UID 1001."""
    names = []
    for key in ('rtvi-hf-cache', 'rtvi-triton-model-repo'):
        name = graph['volumes'][key]['name']
        if name != PROJECT + '_' + key:
            raise RuntimeError('Refusing to change a model cache outside the Thor candidate')
        names.append(name)
    active = run(compose('ps', '--status', 'running', '-q'),
                 capture_output=True, text=True).stdout.splitlines()
    protected = set()
    if active:
        for container in json.loads(run(['docker', 'inspect', *active],
                capture_output=True, text=True).stdout):
            protected.update(mount['Name'] for mount in container['Mounts'] if mount['Type'] == 'volume')
    inactive = [name for name in names if name not in protected]
    if not inactive:
        return
    command = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
        '--runtime', 'runc', '--user', '0:0', '--memory', '128m', '--memory-swap', '128m', '--cpus', '1']
    for index, name in enumerate(inactive):
        command += ['--mount', f'type=volume,src={name},dst=/cache{index}']
    command += ['--entrypoint', 'python3',
        'python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c',
        '-c', 'import os; ' + '; '.join(
            f"os.chown('/cache{index}',1001,1001); os.chmod('/cache{index}',0o2770)"
            for index in range(len(inactive)))]
    run(command)


def require_guard():
    run(['systemctl', '--user', 'is-active', '--quiet', 'vss-memory-budget.service'])
    environment = run(['systemctl', '--user', 'show', 'vss-memory-budget.service',
                       '--property=Environment', '--value'], capture_output=True, text=True, timeout=10).stdout
    values = dict(item.split('=', 1) for item in shlex.split(environment) if '=' in item)
    if values.get('VSS_MEMORY_FLOOR_GIB') != f'{memory_reserve():g}' or values.get('VSS_GUARD_PROJECT') != PROJECT:
        raise RuntimeError(f'Install the Thor candidate guard with the configured {memory_reserve():g} GiB floor and correct project')
    sample_path = ROOT / 'artifacts/runtime-telemetry/samples.jsonl'
    if not sample_path.is_file():
        raise RuntimeError('Thor guard has not yet produced live telemetry')
    with sample_path.open('rb') as stream:
        stream.seek(max(0, sample_path.stat().st_size - 65536))
        tail = stream.read().splitlines()
    row = json.loads(tail[-1])
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if row.get('boot_id') != boot or not 0 <= time.time() - row['time'] < 5 or row['thermal_age'] > 5:
        raise RuntimeError('Thor guard memory/thermal telemetry is stale')


def await_service(service, one_shot=False):
    deadline = time.monotonic() + (1800 if service in ('thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception') else 300)
    while time.monotonic() < deadline:
        require_guard()
        if shared.available() < memory_reserve():
            run(compose('stop'), timeout=120)
            raise RuntimeError(f'{memory_reserve():g} GiB configured reserve crossed; the candidate was stopped')
        cid = run(compose('ps', '-a', '-q', service), capture_output=True, text=True, timeout=15).stdout.strip()
        if cid:
            state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', cid],
                                  capture_output=True, text=True, timeout=15).stdout)
            if one_shot and state['Status'] == 'exited' and state['ExitCode'] == 0:
                return
            if state['Status'] in ('exited', 'dead', 'removing') or state.get('Health', {}).get('Status') == 'unhealthy':
                raise RuntimeError(f'{service} failed: {state["Status"]}; inspect its bounded Docker logs')
            if not one_shot and state['Status'] == 'running' and state.get('Health', {}).get('Status', 'healthy') == 'healthy':
                return
        time.sleep(3)
    raise RuntimeError(f'{service} readiness deadline exceeded')


def build_detector_engine():
    """Compile the native engine in isolation, then stop its larger builder."""
    doctor()
    require_guard()
    if not settings().get('detector_enabled'):
        raise RuntimeError('Stage the detector artifacts and render with --detector first')
    if shared.available() < 90:
        raise RuntimeError('Isolated detector engine build needs at least 90 GiB available')
    active = run(compose('ps', '--status', 'running', '-q',
                        'thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception'),
                 capture_output=True, text=True, timeout=15).stdout.strip()
    if active:
        raise RuntimeError('Stop the three model services and detector before building its engine')
    stage_detector()  # Verify the published ONNX before starting any GPU work.
    await_service('kafka')
    await_service('broker-health-check', one_shot=True)
    override = STATE / 'compose-detector-build.json'
    shared.private_write(override, json.dumps({'services': {'thor-perception': {
        'mem_limit': '8g', 'memswap_limit': '8g',
    }}}))
    try:
        run(compose('-f', override, 'up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                    'thor-perception'), env=clean_env())
        await_service('thor-perception')
        engine = Path(settings()['data_dir']) / 'models/thor-detector' / (
            'rtdetr_warehouse_v1.0.2.fp16.onnx_b1_gpu0_fp16.engine')
        if not engine.is_file() or not engine.stat().st_size:
            raise RuntimeError('Detector became ready without a persisted native engine')
    finally:
        # Never leave the build limit active during combined inference.
        run(compose('-f', override, 'stop', 'thor-perception'), timeout=120)
        override.unlink(missing_ok=True)
    print('Native detector engine ready; builder stopped. Start the normal 6 GiB detector stage next.')


def startup(stage_name):
    doctor()
    require_guard()
    graph = json.loads((STATE / 'compose.json').read_text())
    services = graph['services']
    model_names = ['thor-llm', 'rtvi-embed', 'rtvi-vlm']
    detector_names = ['thor-perception'] if 'thor-perception' in services else []
    app_names = ['lvs-server', 'alert-bridge', 'vss-agent', 'vss-va-mcp', 'history-maintenance',
                 'vss-ui', 'vss-haproxy-ingress']
    if stage_name == 'support':
        provision()
        selected = [name for name in services if name not in model_names + detector_names + app_names]
        # The bounded telemetry observer does not start any AI model.
    elif stage_name == 'app':
        selected = app_names
        for peer in model_names:
            cid = run(compose('ps', '-q', peer), capture_output=True, text=True, timeout=15).stdout.strip()
            if not cid:
                raise RuntimeError(f'Start and validate {peer} before the app stage')
            await_service(peer)
        run([sys.executable, ROOT / 'tools/thor/history_metadata.py', 'start'])
    elif stage_name == 'thor-perception':
        if not detector_names:
            raise RuntimeError('Render with --detector only after staging its model and image')
        selected = detector_names
        model = Path(settings()['data_dir']) / 'models/thor-detector/rtdetr_warehouse_v1.0.2.fp16.onnx'
        with model.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != '0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267':
                raise RuntimeError('RT-DETR model does not match its published checksum')
        engine = model.with_name(model.name + '_b1_gpu0_fp16.engine')
        if not engine.is_file() or not engine.stat().st_size:
            raise RuntimeError('Build the native engine in isolation with build-detector-engine first')
        if shared.available() < memory_reserve() + 15:
            raise RuntimeError('Detector engine startup needs the reserve plus 15 GiB of headroom')
    else:
        selected = [stage_name]
        previous = model_names[:model_names.index(stage_name)]
        for peer in previous:
            cid = run(compose('ps', '-q', peer), capture_output=True, text=True, timeout=15).stdout.strip()
            if not cid:
                raise RuntimeError(f'Start and validate {peer} before {stage_name}')
            await_service(peer)
        if stage_name == 'thor-llm':
            verify_model()
            active = run(compose('ps', '--status', 'running', '-q', *model_names),
                         capture_output=True, text=True, timeout=15).stdout.strip()
            if not active and shared.available() < 90:
                raise RuntimeError('Cold model startup needs at least 90 GiB available after support settles')
        if stage_name == 'rtvi-vlm':
            verify_cosmos()
        if stage_name == 'rtvi-embed':
            verify_embed()
            provision_model_caches(graph)
        if shared.available() < memory_reserve() + 15:
            raise RuntimeError('Model startup needs the reserve plus 15 GiB of allocation headroom')
    order = shared.startup_order(services, selected, [], [])
    excluded = set(model_names + detector_names + app_names) - set(selected)
    one_shots = shared.completed_services(graph)
    environment = clean_env()
    if stage_name == 'rtvi-vlm' and not settings()['cached_models']:
        key_path = Path.home() / '.config/cti-vss/ngc-api-key'
        environment['NGC_API_KEY'] = key_path.read_text().strip()
    for name in order:
        if name in excluded:
            if stage_name == 'app' and name in model_names:
                # Dependency traversal includes the already-gated models.
                # Validate them in place; never recreate them during app startup.
                await_service(name)
                continue
            raise RuntimeError(f'Stage {stage_name} unexpectedly depends on gated workload {name}')
        print(f'Starting {name}; {shared.available():.2f} GiB available', flush=True)
        require_guard()
        run(compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', name), env=environment)
        await_service(name, name in one_shots)
    print(f'{stage_name} stage passed Docker readiness; functional acceptance remains pending.')


def verify():
    require_guard()
    probes = {'llm': 'http://127.0.0.1:30081/v1/models',
              'vlm': 'http://127.0.0.1:8018/v1/health/ready',
              'embed': 'http://127.0.0.1:8017/v1/ready',
              'agent': 'http://127.0.0.1:8100/health',
              'lvs': 'http://127.0.0.1:38111/v1/ready',
              'alert-bridge': 'http://127.0.0.1:9080/health',
              'vios': 'http://127.0.0.1:30888/vst/api/v1/sensor/list',
              'evidence': 'http://127.0.0.1:8098/health',
              'history': 'http://127.0.0.1:8101/health',
              'history-metadata': 'http://127.0.0.1:8102/health',
              'ui': f'http://{settings()["host_ip"]}:7777/'}
    if settings().get('detector_enabled'):
        probes['detector'] = 'http://127.0.0.1:9000/api/v1/health/get-dsready-state'
    failures = []
    for name, url in probes.items():
        try:
            with urllib.request.urlopen(url, timeout=15 if name == 'ui' else 5) as response:
                payload = response.read()
                if response.status != 200:
                    failures.append(name)
                elif name == 'llm' and LLM not in {row['id'] for row in json.loads(payload)['data']}:
                    failures.append('llm model identity')
                elif name == 'detector' and json.loads(payload).get('health-info', {}).get('ds-ready') != 'YES':
                    failures.append('detector pipeline readiness')
        except (OSError, ValueError, KeyError, TypeError):
            failures.append(name)
    try:
        with urllib.request.urlopen('http://127.0.0.1:9200/_cluster/health', timeout=5) as response:
            cluster = json.load(response)
        if cluster.get('status') not in ('yellow', 'green') or cluster.get('unassigned_primary_shards') != 0:
            failures.append('Elasticsearch primary-shard health')
    except (OSError, ValueError):
        failures.append('Elasticsearch primary-shard health')
    receipt = {'time': time.time(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'available_gib': shared.available(), 'reserve_gib': memory_reserve(), 'failed_probes': failures,
               'qualification': 'Health only; real clip inference and browser acceptance remain required'}
    shared.private_write(STATE / 'health-receipt.json', json.dumps(receipt, indent=2))
    if failures:
        raise RuntimeError('Failed health probes: ' + ', '.join(failures))
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['doctor', 'render', 'install-guard', 'stage-model', 'verify-model',
                                         'stage-cosmos', 'verify-cosmos', 'stage-embed', 'verify-embed',
                                         'stage-detector', 'build-detector-engine', 'stage', 'start', 'verify'])
    parser.add_argument('--host-ip')
    parser.add_argument('--gateway')
    parser.add_argument('--data-dir')
    parser.add_argument('--reserve-gib', type=float)
    parser.add_argument('--cached-models', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--detector', action=argparse.BooleanOptionalAction, dest='detector_enabled', default=None)
    parser.add_argument('--stage', choices=['support', 'thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception', 'app'], default='support')
    args = parser.parse_args()
    if args.action == 'render':
        render(args.host_ip, args.data_dir, args.gateway, args.cached_models, args.detector_enabled, args.reserve_gib)
    elif args.reserve_gib is not None:
        parser.error('--reserve-gib is only supported with render')
    elif args.action == 'start':
        startup(args.stage)
    else:
        {'doctor': doctor, 'install-guard': install_guard, 'stage-model': stage_model,
         'verify-model': verify_model, 'stage-cosmos': stage_cosmos,
         'stage-embed': stage_embed, 'verify-embed': verify_embed,
         'verify-cosmos': verify_cosmos, 'stage-detector': stage_detector,
         'build-detector-engine': build_detector_engine,
         'stage': stage, 'verify': verify}[args.action]()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
