#!/usr/bin/env python3
"""Fresh-checkout Spark candidate: render, stage, start serially, and verify.

No Thor generated environment, caches, image IDs or external volumes are used.
Target qualification is recorded separately; rendering is not deployment proof.
"""
import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark'
# API identity exposed by the pinned Spark NIM, distinct from its image name.
LLM = 'nvidia/nemotron-nano-9b-v2'
VLM = 'nim_nvidia_cosmos3-nano-reasoner_bf16-final'
PROFILE = 'bp_developer_thor_full_2d'
DEFAULT_RESERVE_GIB = 48
# Initial peak estimates; record target measurements before tuning these.
MODEL_STARTUP_HEADROOM_GIB = {'spark-llm': 24, 'rtvi-embed': 20, 'rtvi-vlm': 24}
# The first GB10 engine build lowered MemAvailable by about 5.6 GiB. Allow
# 6 GiB before startup; the user's runtime reserve itself remains unchanged.
DETECTOR_STARTUP_HEADROOM_GIB = 6
MODEL_CACHE_ROOTS = {
    'spark-llm': ['/opt/nim/.cache/ngc'],
    'rtvi-embed': ['/opt/nvidia/rtvi/.rtvi/ngc_model_cache', '/tmp/triton_model_repo'],
    'rtvi-vlm': ['/opt/nvidia/rtvi/.rtvi/ngc_model_cache'],
}

# GB10 CUDA allocations can fail while MemAvailable includes reclaimable file
# cache. Once each model is loaded, advise away only its candidate cache files.
# This needs no sudo, keeps the files, and leaves other applications untouched.
CACHE_RECLAIM_SCRIPT = '''
import json, os, re, sys
from pathlib import Path
def memory():
    value = Path('/proc/meminfo').read_text()
    return {key: round(int(re.search(r'^' + key + r':\\s+(\\d+)', value, re.M)[1]) / 1048576, 3)
            for key in ('MemFree', 'MemAvailable', 'Cached')}
before = memory()
seen, advised_bytes = set(), 0
for root_arg in sys.argv[1:]:
    root = Path(root_arg).resolve()
    for candidate in root.rglob('*'):
        path = candidate.resolve()
        if not path.is_relative_to(root) or not path.is_file() or path in seen:
            continue
        seen.add(path)
        size = path.stat().st_size
        if size < 1048576:
            continue
        with path.open('rb') as file:
            os.posix_fadvise(file.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        advised_bytes += size
print(json.dumps({'before_gib': before, 'after_gib': memory(), 'advised_bytes': advised_bytes}))
'''


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def available():
    return int(re.search(r'^MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text(), re.M)[1]) / 1048576


def validate_reserve(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 128:
        raise RuntimeError('Runtime reserve must be a finite number between 0 and 128 GiB.')
    return value


def memory_reserve():
    settings = STATE / 'settings.json'
    if not settings.exists():
        return DEFAULT_RESERVE_GIB
    return validate_reserve(json.loads(settings.read_text()).get('reserve_gib', DEFAULT_RESERVE_GIB))


def model_admission_gib(service):
    return memory_reserve() + MODEL_STARTUP_HEADROOM_GIB[service]


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        f.write(value)
    path.chmod(0o600)


def compose(*args):
    return ['docker', 'compose', '--project-name', 'vss-spark', '-f', STATE / 'compose.json', *args]


def doctor():
    if platform.machine() != 'aarch64':
        raise RuntimeError('Spark requires Linux aarch64.')
    gpu = run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True).stdout
    if 'GB10' not in gpu.upper():
        raise RuntimeError('Refusing runtime changes: this is not a DGX Spark / GB10. Render is allowed on other hosts.')
    run(['docker', 'info'], stdout=subprocess.DEVNULL)
    cv = run(['docker', 'compose', 'version', '--short'], capture_output=True, text=True).stdout.strip()
    version = tuple(map(int, re.findall(r'\d+', cv)[:3]))
    if version < (2, 39, 1):
        raise RuntimeError('Docker Compose >= 2.39.1 required for includes/override tags.')
    if int(Path('/proc/sys/vm/max_map_count').read_text()) < 262144:
        raise RuntimeError('Set vm.max_map_count >= 262144 before Elasticsearch (see handoff).')
    reserve = memory_reserve()
    if available() < reserve:
        raise RuntimeError(f'Need at least {reserve:g} GiB MemAvailable for the configured runtime reserve.')
    print(f'Spark preflight passed; {available():.1f} GiB available; {reserve:g} GiB runtime reserve. Driver/Docker versions still require comparison with NVIDIA prerequisites.')


def render(host_ip, data_dir, gateway, npm_registry='https://registry.npmjs.org', reserve_gib=None, cached_models=None, detector_enabled=None):
    reserve = memory_reserve() if reserve_gib is None else validate_reserve(reserve_gib)
    if cached_models is None:
        settings_path = STATE / 'settings.json'
        cached_models = json.loads(settings_path.read_text()).get('cached_models', False) if settings_path.exists() else False
    if not isinstance(cached_models, bool):
        raise RuntimeError('cached_models must be a boolean.')
    if detector_enabled is None:
        settings_path = STATE / 'settings.json'
        detector_enabled = json.loads(settings_path.read_text()).get('detector_enabled', False) if settings_path.exists() else False
    if not isinstance(detector_enabled, bool):
        raise RuntimeError('detector_enabled must be a boolean.')
    ipaddress.IPv4Address(host_ip)
    ipaddress.IPv4Address(gateway)
    registry = urllib.parse.urlsplit(npm_registry)
    if registry.scheme != 'https' or not registry.hostname or registry.username or registry.password or registry.query or registry.fragment:
        raise RuntimeError('Use an HTTPS npm registry URL without credentials, query, or fragment.')
    data = Path(data_dir).expanduser().resolve()
    if data == ROOT or ROOT in data.parents and not str(data).startswith(str(STATE) + '/'):
        raise RuntimeError('Use .spark/data or a data directory outside the checkout.')
    STATE.mkdir(exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    password_path = STATE / 'graph-password'
    if not password_path.exists():
        private_write(password_path, secrets.token_hex(24))
    values = dict(
        HARDWARE_PROFILE='DGX-SPARK', COMPOSE_PROFILES=PROFILE, COMPOSE_PROJECT_NAME='vss-spark',
        VSS_APPS_DIR=str(ROOT / 'deploy/docker'), VSS_REPO_ROOT=str(ROOT), VSS_DATA_DIR=str(data),
        HOST_IP=host_ip, EXTERNAL_IP=host_ip, THOR_LOCAL_MODEL_BIND_HOST=gateway,
        LLM_NAME=LLM, LLM_BASE_URL='http://127.0.0.1:30081', LLM_MODEL_TYPE='openai',
        VLM_MODE='local_shared', VLM_NAME=VLM, VLM_MODEL_TYPE='rtvi', VLM_BASE_URL='http://127.0.0.1:8018',
        RTVI_VLM_IMAGE_TAG='3.2.1-sbsa', RTVI_VLM_BASE_IMAGE='nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.1-sbsa',
        RTVI_EMBED_TAG='3.2.1-sbsa', RTVI_EMBED_BASE_IMAGE='nvcr.io/nvidia/vss-core/vss-rt-embed:3.2.1-sbsa',
        RTVI_VLM_BASE_URL='http://127.0.0.1:8018', RTVI_VLM_ENDPOINT='', RTVI_VLM_MODEL_TO_USE='cosmos-reason3',
        RTVI_VLM_MODEL_PATH='/opt/nvidia/rtvi/.rtvi/ngc_model_cache/nim_nvidia_cosmos3-nano-reasoner_bf16-final' if cached_models else 'ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final',
        RTVI_VLLM_GPU_MEMORY_UTILIZATION='0.30', RTVI_VLLM_MAX_NUM_SEQS='1', RTVI_VLM_MAX_MODEL_LEN='16384',
        RTVI_VLM_MAX_GENERATION_TOKENS='4096', RTVI_EMBED_BATCH_SIZE='2',
        RTVI_EMBED_KAFKA_ENABLED='true', RTVI_EMBED_KAFKA_TOPIC='mdx-embed',
        LVS_TAG='3.2.1-sbsa', VSS_AGENT_HOST='127.0.0.1', VSS_AGENT_BACKEND_HOST='127.0.0.1', VSS_UI_PORT='3001',
        COSMOS_EMBED_ENDPOINT='http://127.0.0.1:8017', ELASTIC_SEARCH_ENDPOINT='http://127.0.0.1:9200',
        NEXT_PUBLIC_APP_TITLE='LOCAL VIDEO INTELLIGENCE', NEXT_PUBLIC_APP_SUBTITLE='DGX SPARK',
        ALERT_ALWAYS_ON_ENABLED='false', GRAPH_DB_PASSWORD=password_path.read_text().strip(),
        NPM_CONFIG_REGISTRY=npm_registry,
        NGC_API_KEY='', NGC_CLI_API_KEY='', NVIDIA_API_KEY='', HF_TOKEN='', OPENAI_API_KEY='local',
    )
    template = (ROOT / 'deploy/docker/developer-profiles/dev-profile-thor-full/.env').read_text()
    for key, value in values.items():
        if any(c in value for c in "\n\r'"):
            raise RuntimeError(f'Unsupported character in {key}')
        line = f"{key}='{value}'"
        if re.search(r'^' + key + '=', template, re.M):
            template = re.sub(r'^' + key + '=.*$', lambda _: line, template, flags=re.M)
        else:
            template += '\n' + line + '\n'
    envpath = STATE / 'generated.env'
    private_write(envpath, template)
    # Do not inherit Thor shell variables or credentials into the rendered graph.
    clean_env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'XDG_RUNTIME_DIR')}
    result = run(['docker', 'compose', '--env-file', envpath, '-f', ROOT / 'deploy/docker/compose.yml',
                  '-f', ROOT / 'deploy/docker/thor-local/compose.yml', 'config', '--format', 'json'],
                 env=clean_env, capture_output=True, text=True)
    graph = json.loads(result.stdout)
    services = graph['services']
    services.pop('tegrastats-exporter', None)
    # Carry over shared application integration, replacing the Tegra codec layer.
    stream = services['streamprocessing-ms']
    stream.pop('build', None)
    stream['image'] = 'nvcr.io/nvidia/vss-core/vss-vios-streamprocessing:3.2.1'
    stream['entrypoint'] = ['/bin/bash', '-ec', '/home/vst/vst_release/tools/user_additional_install.sh; exec /home/vst/vst_release/launch_vst']
    stream['environment']['VST_INSTALL_ADDITIONAL_PACKAGES'] = 'true'
    # Sim's MediaMTX publisher accepts TCP only. Keep the inherited Thor
    # configuration intact and bind a generated Spark copy to each VST role.
    vst_config = json.loads((ROOT / 'deploy/docker/thor-local/vios/vst_config.json').read_text())
    vst_config['network']['rtsp_streaming_over_tcp'] = True
    vst_config_path = STATE / 'vst-config.json'
    private_write(vst_config_path, json.dumps(vst_config, indent=2) + '\n')
    for service in services.values():
        for mount in service.get('volumes', []):
            if mount.get('target') == '/home/vst/vst_release/configs/vst_config.json':
                mount['source'] = str(vst_config_path)
    services['sensor-ms']['environment'].pop('LD_LIBRARY_PATH', None)
    embed = services['rtvi-embed']['environment']
    embed.update(RTVI_OFFLINE='false', HF_HUB_OFFLINE='0', TRANSFORMERS_OFFLINE='0')
    vlm = services['rtvi-vlm']['environment']
    vlm.update(VLLM_KV_CACHE_MEMORY_BYTES='4294967296', VLLM_ENFORCE_EAGER='true', VLLM_MAX_NUM_SEQS='1',
               VLM_RECLAIM_MODEL_FILE_CACHE='true',
               VLM_FILE_CACHE_RECLAIM_ROOT='/opt/nvidia/rtvi/.rtvi/ngc_model_cache')
    # Credentials are supplied only while downloading models; never stored here.
    vlm['NGC_API_KEY'] = '${NGC_API_KEY:-}'
    llm_cache = {'type': 'volume', 'source': 'spark-nim-cache', 'target': '/opt/nim/.cache'}
    nim_image = 'nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant'
    # Docker creates an empty named volume as root. This NIM runs as nvs
    # (1000:1000), so prepare only its cache mount before downloading weights.
    services['spark-llm-cache-init'] = {
        'image': nim_image, 'user': '0:0', 'restart': 'no',
        'entrypoint': ['/bin/sh', '-ec', 'chown 1000:1000 /opt/nim/.cache; chmod 0770 /opt/nim/.cache'],
        'volumes': [llm_cache],
    }
    services['spark-llm'] = {
        'image': nim_image,
        'runtime': 'nvidia', 'ports': ['127.0.0.1:30081:8000'], 'shm_size': '16gb', 'restart': 'no',
        'environment': {'NGC_API_KEY': '${NGC_API_KEY:-}', 'NVIDIA_VISIBLE_DEVICES': '0',
                        'NIM_GPU_MEM_FRACTION': '0.11', 'NIM_MAX_BATCH_SIZE': '1', 'NIM_MAX_MODEL_LEN': '32768',
                        'HF_HOME': '/opt/nim/.cache/huggingface', 'VLLM_CACHE_ROOT': '/opt/nim/.cache/vllm'},
        'volumes': [llm_cache],
        'depends_on': {'spark-llm-cache-init': {'condition': 'service_completed_successfully'}},
        'healthcheck': {'test': ['CMD', 'curl', '-f', 'http://localhost:8000/v1/health/ready'],
                        'interval': '15s', 'timeout': '5s', 'retries': 120, 'start_period': '120s'},
    }
    if cached_models:
        for environment in (embed, vlm):
            environment.update(RTVI_OFFLINE='true', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', NGC_API_KEY='')
        services['spark-llm']['environment'].update(
            NGC_API_KEY='', NIM_DISABLE_MODEL_DOWNLOAD='1',
            NIM_MODEL_PATH='/opt/nim/.cache/ngc/hub/models--nim--nvidia--nemotron-nano-9b-v2/snapshots/hf-nvfp4-v1',
            HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    graph.setdefault('volumes', {})['spark-nim-cache'] = {'name': 'vss-spark-nim-cache'}
    va_config = '/vss-agent/deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/va_mcp_server_config.yml'
    services['vss-va-mcp']['command'] = ['mcp', 'serve', '--config_file', va_config, '--host', '127.0.0.1', '--port', '9901']
    agent = services['vss-agent']
    agent['command'] = ['serve', '--config_file', '/vss-agent/deploy/docker/spark/config.yml', '--host', '127.0.0.1', '--port', '8100']
    agent['environment'].update(
        VSS_AGENT_CONFIG_FILE='/vss-agent/deploy/docker/spark/config.yml',
        VSS_WAREHOUSE_RTVI_CV_URL='http://127.0.0.1:9000' if detector_enabled else '',
        VSS_TRAFFIC_RTVI_CV_URL='',
        VST_CLIP_FALLBACK_URL='http://127.0.0.1:8098',
        VST_CLIP_FALLBACK_MEDIA_URL=f'http://{host_ip}:7777/api/vision/evidence-media',
        EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY='true')
    if detector_enabled:
        # A single Spark worker uses the SBSA runtime and the model-only
        # warehouse pipeline. Do not select the inherited search profile:
        # it also stages a vision encoder and enables tracker ReID.
        services['spark-perception'] = {
            'image': 'nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1-sbsa',
            'container_name': 'vss-rtvi-cv', 'network_mode': 'host',
            'runtime': 'nvidia', 'restart': 'no',
            'working_dir': '/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app',
            'entrypoint': [], 'command': ['bash', '/opt/spark/detector-start.sh'],
            'mem_limit': '6g', 'memswap_limit': '6g', 'shm_size': '2g', 'cpus': 4,
            'environment': {
                'HARDWARE_PROFILE': 'DGX-SPARK', 'NVIDIA_VISIBLE_DEVICES': '0',
                'DS_MODEL_FAMILY': 'rtdetr-warehouse', 'DS_MODE_FLAG': '1',
                'DS_MESSAGE_RATE': '1', 'DS_TRACKER_REID': 'false',
                'DS_SHOW_SENSOR_ID': 'false', 'NUM_SENSORS': '1',
                'STREAM_TYPE': 'kafka', 'DEEPSTREAM_ENABLE_SENSOR_ID_EXTRACTION': '1',
                'GST_ENABLE_CUSTOM_PARSER_MODIFICATIONS': '1', 'OTEL_SDK_DISABLED': 'true',
            },
            'volumes': [
                {'type': 'bind', 'source': str(ROOT / 'deploy/docker/spark'), 'target': '/opt/spark', 'read_only': True},
                {'type': 'bind', 'source': str(ROOT / 'deploy/docker/industry-profiles/warehouse-operations/warehouse-2d-app/deepstream/configs'),
                 'target': '/opt/spark-detector-templates', 'read_only': True},
                {'type': 'bind', 'source': str(data / 'models/spark-detector'), 'target': '/opt/storage'},
            ],
            'healthcheck': {
                'test': ['CMD', 'curl', '--fail', '--silent', '--connect-timeout', '2', '--max-time', '4',
                         'http://127.0.0.1:9000/api/v1/health/get-dsready-state'],
                'interval': '15s', 'timeout': '5s', 'retries': 40, 'start_period': '120s',
            },
        }
        agent['environment']['VSS_WAREHOUSE_MAX_SOURCES'] = '1'
        services['vss-ui']['environment']['RTVI_CV_HEALTH_URL'] = 'http://127.0.0.1:9000/api/v1/health/get-dsready-state'
    services['alert-bridge']['environment']['ALERT_ALWAYS_ON_ENABLED'] = 'false'
    services['lvs-server']['environment'].update(LVS_LLM_BASE_URL='http://127.0.0.1:30081/v1', LVS_LLM_MODEL_NAME=LLM,
        VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME=VLM, VIA_VLM_ENDPOINT='http://127.0.0.1:8018/v1/', LVS_EMB_DIMENSIONS='768')
    # All startup is explicit during qualification. Never replay a live source at boot.
    for name, service in services.items():
        service.pop('profiles', None)
        service['restart'] = 'no'
        service.get('deploy', {}).pop('restart_policy', None)
        if service.get('build'):
            service['image'] = f'vss-spark-{name}:source'
        service.setdefault('group_add', []).append('1000')
        for mount in service.get('volumes', []):
            if mount.get('type') == 'bind' and mount.get('source', '').startswith(str(data) + '/'):
                mount.setdefault('bind', {})['create_host_path'] = False
        for dependency in list(service.get('depends_on', {})):
            if dependency not in services:
                del service['depends_on'][dependency]
    # The broker check also requires all application topics. An empty data root
    # must initialize them before the serial startup waits on that check.
    services['broker-health-check']['depends_on'] = {
        'kafka': {'condition': 'service_healthy'},
        'kafka-topic-init-container': {'condition': 'service_completed_successfully'},
    }
    # Source config mounts are inherited from the agent's repository deployment mount.
    agent.setdefault('volumes', []).append({'type': 'bind', 'source': str(ROOT / 'deploy/docker/spark'),
                                          'target': '/vss-agent/deploy/docker/spark', 'read_only': True})
    # Compose config already escapes shell dollars as $$; preserve those pairs.
    # Escape only new singleton dollars, except the deferred download credential.
    encoded = re.sub(r'(?<!\$)\$(?!\$)', lambda _: '$$', json.dumps(graph, indent=2))
    encoded = encoded.replace('$${NGC_API_KEY:-}', '${NGC_API_KEY:-}')
    private_write(STATE / 'compose.json', encoded + '\n')
    private_write(STATE / 'settings.json', json.dumps({'host_ip': host_ip, 'data_dir': str(data), 'gateway': gateway, 'npm_registry': npm_registry, 'reserve_gib': reserve, 'cached_models': cached_models, 'detector_enabled': detector_enabled}, indent=2))
    run(compose('config', '--quiet'), env=clean_env)
    print(f'Rendered {len(services)} services to {STATE}/compose.json (unqualified Spark candidate).')


def stage():
    doctor()
    if shutil.disk_usage(STATE).free < 200 * 1024**3:
        raise RuntimeError('Require 200 GiB free for initial image/model staging; do not prune a running model stack.')
    # Do not build against active inference on a unified-memory development host.
    active = run(compose('ps', '--status', 'running', '-q'), capture_output=True, text=True).stdout
    if active.strip():
        raise RuntimeError('Stop this candidate stack before staging/building.')
    run(['bash', ROOT / 'deploy/docker/thor-local/vios-mcp/stage-wheelhouse.sh'])
    pack = ROOT / 'deploy/docker/services/infra/elk/logstash/offline-packs/logstash-codec-protobuf-1.3.0-logstash-9.3.3.zip'
    run([sys.executable, pack.parent.parent / 'verify-protobuf-offline-pack.py', pack, str(pack) + '.sha256', str(pack) + '.expected.sha256'])
    key = os.environ.get('NGC_API_KEY')
    if not key:
        raise RuntimeError('Set NGC_API_KEY privately for registry/model downloads; see handoff.')
    run(['docker', 'login', 'nvcr.io', '--username', '$oauthtoken', '--password-stdin'], input=key, text=True)
    run(compose('pull', '--ignore-buildable'))
    run(compose('build', '--pull'), env={**os.environ, 'COMPOSE_PARALLEL_LIMIT': '1'})
    print('Images built. Model weights download on first staged startup. No runtime qualification yet.')


def provision():
    graph = json.loads((STATE / 'compose.json').read_text())
    data = Path(json.loads((STATE / 'settings.json').read_text())['data_dir'])
    paths = data_roots(graph, data)
    for path in sorted(paths):
        if not path.exists():
            uid = '65532' if path.name in ('vision-history', 'vision-rules', 'vision-investigations') else '1000'
            run(['sudo', '-n', 'install', '-d', '-m', '2770', '-o', uid, '-g', '1000', path])


def data_roots(graph, data):
    paths = set()
    for volume in graph.get('volumes', {}).values():
        device = Path(volume.get('driver_opts', {}).get('device', '/'))
        if data in device.parents:
            paths.add(device)
    for service in graph['services'].values():
        for mount in service.get('volumes', []):
            source = Path(mount.get('source', '/'))
            if mount.get('type') == 'bind' and data in source.parents:
                paths.add(source)
    return paths


def up():
    doctor()
    provision()
    run(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service'])
    graph = json.loads((STATE / 'compose.json').read_text())
    models = ['spark-llm', 'rtvi-embed', 'rtvi-vlm']
    detectors = ['spark-perception'] if 'spark-perception' in graph['services'] else []
    late = ['vss-agent', 'vss-ui', 'vss-haproxy-ingress', 'lvs-server', 'alert-bridge', 'vss-va-mcp']
    early = [s for s in graph['services'] if s not in models + detectors + late]
    order = startup_order(graph['services'], early, models + detectors, late)
    for service in order:
        if service in models:
            required = model_admission_gib(service)
            if available() < required:
                raise RuntimeError(f'Admission refused before {service}: {available():.1f} GiB available; need {required:g} ({memory_reserve():g} reserve + {MODEL_STARTUP_HEADROOM_GIB[service]:g} startup headroom).')
        if service in detectors:
            required = memory_reserve() + DETECTOR_STARTUP_HEADROOM_GIB
            if available() < required:
                raise RuntimeError(f'Admission refused before {service}: {available():.1f} GiB available; need {required:g} ({memory_reserve():g} reserve + {DETECTOR_STARTUP_HEADROOM_GIB:g} startup headroom).')
        run(compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', service))
        await_service(service, graph['services'][service].get('restart') == 'no' and service in ('broker-health-check', 'elasticsearch-init-container', 'kafka-topic-init-container', 'kibana-init-container-thor-full', 'sdr-streamprocessing-init', 'spark-llm-cache-init'))
        if service in models:
            reclaim_model_file_cache(service)
    verify()


def reclaim_model_file_cache(service):
    result = run(compose('exec', '-T', service, 'python3', '-c', CACHE_RECLAIM_SCRIPT,
                         *MODEL_CACHE_ROOTS[service]), capture_output=True, text=True, timeout=30)
    print(f'{service} candidate file-cache advice: {result.stdout.strip()}', flush=True)


def startup_order(services, early, models, late):
    ordered, visiting = [], set()
    def visit(name):
        if name in ordered:
            return
        if name in visiting:
            raise RuntimeError(f'Dependency cycle: {name}')
        visiting.add(name)
        for dependency in services[name].get('depends_on', {}):
            visit(dependency)
        visiting.remove(name)
        ordered.append(name)
    for name in early + models + late:
        visit(name)
    return ordered


def await_service(service, one_shot=False):
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        reserve = memory_reserve()
        if available() < reserve:
            run(compose('stop'), stdout=subprocess.DEVNULL)
            raise RuntimeError(f'{reserve:g} GiB reserve crossed; candidate stack stopped.')
        cid = run(compose('ps', '-a', '-q', service), capture_output=True, text=True).stdout.strip()
        if cid:
            state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', cid], capture_output=True, text=True).stdout)
            if state['Status'] == 'exited':
                if one_shot and state['ExitCode'] == 0:
                    return
                raise RuntimeError(f'{service} exited; inspect its Docker logs.')
            if not one_shot and state['Status'] == 'running' and state.get('Health', {}).get('Status', 'healthy') == 'healthy':
                return
        time.sleep(5)
    raise RuntimeError(f'{service} did not become ready in 1 hour; inspect logs.')


def install_guard():
    doctor()
    unit = Path.home() / '.config/systemd/user/vss-spark-guard.service'
    python = sys.executable
    if any(c in str(ROOT) + python for c in '\n"%'):
        raise RuntimeError('Unsupported systemd path characters')
    private_write(unit, f"""[Unit]
Description=Spark VSS configurable memory reserve guard
[Service]
ExecStart="{python}" "{ROOT}/tools/spark/guard.py"
Restart=on-failure
RestartSec=2
[Install]
WantedBy=default.target
""")
    run(['systemctl', '--user', 'daemon-reload'])
    run(['systemctl', '--user', 'enable', '--now', unit.name])


def verify():
    failures = []
    probes = {'llm': 'http://127.0.0.1:30081/v1/models', 'vlm': 'http://127.0.0.1:8018/v1/health/ready',
              'embed': 'http://127.0.0.1:8017/v1/ready', 'agent': 'http://127.0.0.1:8100/health',
              'vios': 'http://127.0.0.1:30888/vst/api/v1/sensor/list'}
    graph_path = STATE / 'compose.json'
    if graph_path.exists() and 'spark-perception' in json.loads(graph_path.read_text()).get('services', {}):
        probes['detector'] = 'http://127.0.0.1:9000/api/v1/health/get-dsready-state'
    for name, url in probes.items():
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                if response.status != 200:
                    failures.append(name)
        except Exception:
            failures.append(name)
    receipt = {'time': time.time(), 'commit': run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
               'available_gib': available(), 'reserve_gib': memory_reserve(), 'failed_probes': failures,
               'qualification': 'health only; browser and real clip/RTSP inference still required'}
    private_write(STATE / 'health-receipt.json', json.dumps(receipt, indent=2))
    if failures:
        raise RuntimeError('Failed health probes: ' + ', '.join(failures))
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['doctor', 'render', 'stage', 'up', 'verify', 'stop', 'install-guard'])
    parser.add_argument('--host-ip')
    parser.add_argument('--gateway', default='172.17.0.1')
    parser.add_argument('--data-dir', default=str(STATE / 'data'))
    parser.add_argument('--npm-registry', default='https://registry.npmjs.org', help='HTTPS package registry for the source UI build')
    parser.add_argument('--reserve-gib', type=float, help='Runtime memory reserve; render preserves the saved value when omitted')
    parser.add_argument('--cached-models', action=argparse.BooleanOptionalAction, default=None, help='Cache-only model startup without download credentials; render preserves the saved mode when omitted')
    parser.add_argument('--detector', action=argparse.BooleanOptionalAction, dest='detector_enabled', default=None, help='Enable the single-source Spark detection/tracking worker; render preserves the saved mode when omitted')
    args = parser.parse_args()
    if args.command == 'render':
        if not args.host_ip:
            parser.error('render requires --host-ip <Spark LAN IPv4>')
        render(args.host_ip, args.data_dir, args.gateway, args.npm_registry, args.reserve_gib, args.cached_models, args.detector_enabled)
    elif args.reserve_gib is not None or args.cached_models is not None or args.detector_enabled is not None:
        parser.error('--reserve-gib, --cached-models and --detector/--no-detector apply to render; restart the guard after changing its reserve')
    elif args.command == 'stop':
        run(compose('stop'))
    else:
        globals()[args.command.replace('-', '_')]()

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
