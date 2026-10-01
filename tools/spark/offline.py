#!/usr/bin/env python3
"""Local-only checks and address preparation for the Spark desktop launcher."""

import ipaddress
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

import bootstrap as b
import ui


# Run the packaged installer in a fresh CPU-only, network-isolated agent image.
# Import and round-trip decode also catch missing shared libraries and ABI
# mismatches that a file-exists check would miss.
CODEC_CHECK = r'''
import os, sys, tempfile
sys.path.insert(0, '/vss-agent')
import install_proprietary_codecs
target = install_proprietary_codecs.install()
if not target:
    raise RuntimeError('The cached video codec could not be installed.')
sys.path.insert(0, target)
import cv2, numpy as np
if cv2.__version__ != '4.13.0':
    raise RuntimeError('Unexpected OpenCV version: ' + cv2.__version__)
with tempfile.TemporaryDirectory() as folder:
    path = folder + '/decode-check.mp4'
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 1, (32, 32))
    if not writer.isOpened():
        raise RuntimeError('The cached MP4 video encoder is unavailable.')
    writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
    writer.release()
    video = cv2.VideoCapture(path)
    ok, frame = video.read()
    video.release()
    if not ok or frame is None or frame.shape != (32, 32, 3):
        raise RuntimeError('The cached MP4 video decoder is unavailable.')
print('Fresh agent codec installation and video decoding passed with networking disabled.')
'''


CACHE_CHECK = r'''
import hashlib, json, struct, subprocess
from pathlib import Path
parser = Path('/offline-tools/jq')
if not parser.is_file() or hashlib.sha256(parser.read_bytes()).hexdigest() != '4dd2d8a0661df0b22f1bb9a1f9830f06b6f3b8f7d91211a1ef5d7c4f06a8b4a5':
    raise RuntimeError('The pinned offline Kafka jq tool is missing or changed.')
if subprocess.check_output([str(parser), '--version'], text=True, timeout=5).strip() != 'jq-1.7.1':
    raise RuntimeError('Unexpected offline Kafka jq version.')
def required(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError('Missing cached file: ' + str(path))
def model(root, files):
    root = Path(root)
    for name in files + ['config.json', 'model.safetensors.index.json']:
        required(root / name)
    index = json.loads((root / 'model.safetensors.index.json').read_text())
    shards = set(index.get('weight_map', {}).values())
    if not shards:
        raise RuntimeError('Empty model weight map: ' + str(root))
    for name in shards:
        path = (root / name).resolve()
        required(path)
        with path.open('rb') as f:
            header = f.read(8)
            if len(header) != 8:
                raise RuntimeError('Incomplete safetensors file: ' + str(path))
            length = struct.unpack('<Q', header)[0]
            if length > 16777216 or length + 8 > path.stat().st_size:
                raise RuntimeError('Incomplete safetensors file: ' + str(path))
            tensors = json.loads(f.read(length))
        ends = [item['data_offsets'][1] for name, item in tensors.items() if name != '__metadata__']
        if ends and max(ends) + length + 8 > path.stat().st_size:
            raise RuntimeError('Truncated tensor data: ' + str(path))
model('/nim/ngc/hub/models--nim--nvidia--nemotron-nano-9b-v2/snapshots/hf-nvfp4-v1',
      ['hf_quant_config.json', 'tokenizer.json', 'tokenizer_config.json'])
model('/rtvi/Cosmos-Embed1-448p-anomaly-detection', ['tokenizer.json', 'vocab.txt'])
model('/rtvi/nim_nvidia_cosmos3-nano-reasoner_bf16-final',
      ['tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json', 'video_preprocessor_config.json'])
for name in ['video_embeddings/1/cosmos_embed1_video_NVIDIA_GB10_2_fp16.engine',
             'text_embeddings/1/cosmos_embed1_text_NVIDIA_GB10_2_fp16.engine']:
    required(Path('/triton/cosmos-embed1-448p-anomaly-detection') / name)
for name in ['rtdetr_warehouse_v1.0.2.fp16.onnx', 'rtdetr_warehouse_v1.0.2.fp16.onnx_b1_gpu0_fp16.engine']:
    required(Path('/detector') / name)
print('All pinned model files and GB10 engines are cached.')
'''


def load():
    return json.loads((b.STATE / 'settings.json').read_text()), json.loads((b.STATE / 'compose.json').read_text())


def local_gateway(settings):
    result = b.run(['docker', 'network', 'inspect', 'bridge', '--format', '{{json .IPAM.Config}}'],
                   capture_output=True, text=True, timeout=15)
    gateways = {item.get('Gateway') for item in json.loads(result.stdout)}
    gateway = settings['gateway']
    if gateway not in gateways or not ipaddress.ip_address(gateway).is_private:
        raise RuntimeError('The saved Docker gateway has changed. Ask the technical lead to rerender the Spark configuration.')
    return gateway


def validate_graph(settings, graph):
    if not settings.get('cached_models') or not settings.get('detector_enabled'):
        raise RuntimeError('This desktop setup requires cached models and the warehouse detector enabled.')
    for name in ('spark-llm', 'rtvi-embed', 'rtvi-vlm'):
        env = graph['services'][name]['environment']
        if str(env.get('HF_HUB_OFFLINE')) != '1' or str(env.get('TRANSFORMERS_OFFLINE')) != '1' or env.get('NGC_API_KEY'):
            raise RuntimeError(f'{name} is not configured for credential-free offline startup.')
        key, value = ('NIM_DISABLE_MODEL_DOWNLOAD', '1') if name == 'spark-llm' else ('RTVI_OFFLINE', 'true')
        if str(env.get(key)).lower() != value:
            raise RuntimeError(f'{name} may attempt a model download; offline startup refused.')
    stream = graph['services']['streamprocessing-ms']
    if ('user_additional_install.sh' in ' '.join(stream.get('entrypoint', [])) or
            str(stream.get('environment', {}).get('VST_INSTALL_ADDITIONAL_PACKAGES')).lower() != 'false'):
        raise RuntimeError('The video service still invokes an online package installer.')
    topics = graph['services'].get('kafka-topic-init-container')
    if topics and str(topics.get('environment', {}).get('KAFKA_INIT_OFFLINE')).lower() != 'true':
        raise RuntimeError('Kafka topic initialization is not configured for offline startup.')
    agent = graph['services'].get('vss-agent')
    if not agent:
        raise RuntimeError('The offline video agent is missing from the service graph.')
    env = agent.get('environment', {})
    mount = next((item for item in agent.get('volumes', []) if isinstance(item, dict)
                  and item.get('target') == b.CODEC_WHEEL_TARGET), {})
    if (str(env.get('INSTALL_PROPRIETARY_CODECS')).lower() != 'true'
            or env.get('VSS_PROPRIETARY_CODECS_WHEEL') != b.CODEC_WHEEL_TARGET
            or str(env.get('VSS_PROPRIETARY_CODECS_MAX_RETRY_SECONDS')) != '0'
            or mount.get('source') != str(b.STATE / 'offline-tools' / b.CODEC_WHEEL_NAME)
            or mount.get('type') != 'bind' or not mount.get('read_only')
            or mount.get('bind', {}).get('create_host_path') is not False):
        raise RuntimeError('The video agent is not configured to use its pinned offline codec wheel.')


def verify_codec_cache():
    path = b.STATE / 'offline-tools' / b.CODEC_WHEEL_NAME
    if not path.is_file():
        raise RuntimeError('The pinned offline video decoder is missing or changed. Restore its local wheel cache before startup.')
    with path.open('rb') as wheel:
        if hashlib.file_digest(wheel, 'sha256').hexdigest() != b.CODEC_WHEEL_SHA256:
            raise RuntimeError('The pinned offline video decoder is missing or changed. Restore its local wheel cache before startup.')
    return path


def cache_mount(graph, service, target, destination):
    mount = next(item for item in graph['services'][service]['volumes'] if item['target'] == target)
    if mount['type'] == 'volume':
        source = graph['volumes'][mount['source']].get('name', 'vss-spark_' + mount['source'])
        b.run(['docker', 'volume', 'inspect', source], stdout=subprocess.DEVNULL, timeout=15)
    else:
        source = mount['source']
        if not Path(source).is_dir():
            raise RuntimeError('A required model cache directory is missing.')
    return ['-v', f'{source}:{destination}:ro']


def preflight(progress):
    settings, graph = load()
    # Normalize older cached graphs before validation, without starting services
    # or changing models, budgets, source identity, or local addresses.
    before = json.dumps(graph, sort_keys=True)
    b.booth_runtime_safety(graph)
    validate_graph(settings, graph)
    codec = verify_codec_cache()
    if json.dumps(graph, sort_keys=True) != before:
        b.private_write(b.STATE / 'compose.json', json.dumps(graph, indent=2) + '\n')
    local_gateway(settings)
    progress('Checking local images and cached model files…')
    images = sorted({service['image'] for service in graph['services'].values()})
    b.run(['docker', 'image', 'inspect', *images], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    ui.validate_dependencies()  # Never run npm install from a desktop shortcut.
    missing = [str(path) for path in b.data_roots(graph, Path(settings['data_dir'])) if not path.is_dir()]
    if missing:
        raise RuntimeError('Required data folders are missing. Technical setup is required; no sudo prompts are used by this launcher.')
    mounts = []
    parser = b.STATE / 'offline-tools/jq'
    if not parser.is_file():
        raise RuntimeError('The offline Kafka parser is missing. Restore its local cache before startup.')
    mounts += ['-v', f'{parser}:/offline-tools/jq:ro']
    for service, target, destination in [
        ('spark-llm', '/opt/nim/.cache', '/nim'),
        ('rtvi-embed', '/opt/nvidia/rtvi/.rtvi/ngc_model_cache', '/rtvi'),
        ('rtvi-embed', '/tmp/triton_model_repo', '/triton'),
        ('spark-perception', '/opt/storage', '/detector'),
    ]:
        mounts += cache_mount(graph, service, target, destination)
    # This check has no network, GPU allocation, dependency installer or image pull.
    b.run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--runtime', 'runc',
           '--memory', '256m', '--memory-swap', '256m', '--cpus', '1', '--user', '0:0',
           *mounts, '--entrypoint', 'python3', graph['services']['rtvi-embed']['image'], '-c', CACHE_CHECK], timeout=45)
    progress('Checking the video decoder with networking disabled…')
    b.run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--runtime', 'runc',
           '--memory', '512m', '--memory-swap', '512m', '--cpus', '1',
           '-v', f'{codec}:{b.CODEC_WHEEL_TARGET}:ro',
           '-e', f'VSS_PROPRIETARY_CODECS_WHEEL={b.CODEC_WHEEL_TARGET}',
           '-e', 'VSS_PROPRIETARY_CODECS_DIR=/tmp/vss-offline-codecs',
           '-e', 'VSS_PROPRIETARY_CODECS_MAX_RETRY_SECONDS=0',
           '--entrypoint', '/vss-agent/.venv/bin/python', graph['services']['vss-agent']['image'],
           '-c', CODEC_CHECK], timeout=45)
    return settings, graph


def sql(statement):
    return b.run(['docker', 'exec', '-i', 'vss-vios-postgres', 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                  '-U', 'vst', '-d', 'nvcentralizedb', '-tA'], input=statement, text=True,
                 capture_output=True, timeout=30).stdout.strip()


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def migrate_sim_urls(original_host, gateway):
    """Only the same-host Sim URL changes; identities and recording tables stay intact."""
    rows = json.loads(sql("SELECT COALESCE(json_agg(row_to_json(r)), '[]') FROM "
                          "(SELECT sensor_id,stream_id,stream_live_url,stream_proxy_url,stream_replay_url "
                          "FROM public.sensor_streams) r;"))
    selected = []
    for row in rows:
        url = urlsplit(row['stream_live_url'])
        if (url.scheme == 'rtsp' and url.hostname in (original_host, '127.0.0.1')
                and url.port == 8554 and url.path == '/digital-twin' and not url.username):
            selected.append(row)
    if len(selected) != 1:
        raise RuntimeError('Expected one registered local digital-twin source. Source setup needs a technical review; no recordings were changed.')
    row = selected[0]
    sid = row['sensor_id']
    if row['stream_id'] != sid:
        raise RuntimeError('Unexpected Sim stream identity; source migration refused.')
    sensor = json.loads(sql(f'SELECT row_to_json(r) FROM (SELECT sensor_id,device_id,type,ipaddress,url '
                            f'FROM public.sensor_details WHERE sensor_id={literal(sid)}) r;'))
    if sensor['type'] != 'sensor_rtsp' or sensor['ipaddress'] not in (original_host, '127.0.0.1'):
        raise RuntimeError('Unexpected Sim source type/address; source migration refused.')
    backup = b.STATE / 'desktop-source-before.json'
    if not backup.exists():
        b.private_write(backup, json.dumps({'sensor': sensor, 'stream': row}, indent=2))
    live = 'rtsp://127.0.0.1:8554/digital-twin'
    proxy = f'rtsp://{gateway}:30554/live/{sid}'
    replay = f'rtsp://{gateway}:30564/vod/{sid}'
    statement = f'''BEGIN;
DO $$ DECLARE changed integer; BEGIN
UPDATE public.sensor_details SET ipaddress='127.0.0.1'
WHERE sensor_id={literal(sid)} AND device_id={literal(sensor['device_id'])}
AND type='sensor_rtsp' AND ipaddress={literal(sensor['ipaddress'])};
GET DIAGNOSTICS changed = ROW_COUNT;
IF changed <> 1 THEN RAISE EXCEPTION 'Sim sensor precondition changed'; END IF;
UPDATE public.sensor_streams SET stream_live_url={literal(live)},
stream_proxy_url={literal(proxy)},stream_replay_url={literal(replay)}
WHERE sensor_id={literal(sid)} AND stream_id={literal(sid)}
AND stream_live_url={literal(row['stream_live_url'])}
AND stream_proxy_url={literal(row['stream_proxy_url'])}
AND stream_replay_url={literal(row['stream_replay_url'])};
GET DIAGNOSTICS changed = ROW_COUNT;
IF changed <> 1 THEN RAISE EXCEPTION 'Sim stream precondition changed'; END IF;
END $$;
COMMIT;'''
    sql(statement)
    return sid


def prepare(settings, progress, execute):
    gateway = local_gateway(settings)
    graph_path = b.STATE / 'compose.json'
    graph = json.loads(graph_path.read_text())
    before = json.dumps(graph, sort_keys=True)
    b.booth_runtime_safety(graph)
    if json.dumps(graph, sort_keys=True) != before:
        b.private_write(graph_path, json.dumps(graph, indent=2) + '\n')
        progress('Updated local Kafka reader and bounded service logging configuration.')
    marker = b.STATE / 'desktop-offline.json'
    if marker.exists() and json.loads(marker.read_text()).get('gateway') == gateway and settings['host_ip'] == gateway:
        return json.loads(marker.read_text())
    origin = b.STATE / 'desktop-network-before.json'
    if not origin.exists():
        b.private_write(origin, json.dumps(settings, indent=2))
    original = json.loads(origin.read_text())
    progress('Preparing stable local addresses. Stopping VSS for configuration…')
    execute(b.compose('stop', '-t', '10'), 'Stopping VSS for local configuration')
    b.render(gateway, settings['data_dir'], gateway, settings['npm_registry'],
             reserve_gib=settings['reserve_gib'], cached_models=True, detector_enabled=True)
    graph = json.loads(graph_path.read_text())
    ingress = graph['services']['vss-haproxy-ingress']['environment']
    # HAProxy appends :port. Bind both host-local addresses, without exposing
    # a new listener on venue network interfaces.
    ingress['HAPROXY_BIND_ADDR'] = f"127.0.0.1:{ingress['HAPROXY_PORT']},{gateway}"
    b.private_write(graph_path, json.dumps(graph, indent=2) + '\n')
    config_path = b.STATE / 'vst-config.json'
    config = json.loads(config_path.read_text())
    config['network']['server_domain_name'] = gateway
    b.private_write(config_path, json.dumps(config, indent=2) + '\n')
    execute(b.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'centralizedb'), 'Preparing the existing video database')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            sql('SELECT 1;')
            break
        except subprocess.CalledProcessError:
            time.sleep(1)
    else:
        raise RuntimeError('Video database did not become ready for local setup.')
    sid = migrate_sim_urls(original['host_ip'], gateway)
    prepared = {'gateway': gateway, 'sensor_id': sid, 'app_url': 'http://127.0.0.1:7777/?workspace=guided'}
    b.private_write(marker, json.dumps(prepared, indent=2))
    progress('Local addressing prepared. Saved recordings and source identity preserved.')
    return prepared
