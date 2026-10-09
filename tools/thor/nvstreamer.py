#!/usr/bin/env python3
"""Guarded, optional NVStreamer sidecar for the current Thor candidate."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import time
import urllib.parse
import urllib.request

import bootstrap as thor

BASE_IMAGE = ('nvcr.io/nvidia/vss-core/vss-vios-nvstreamer@sha256:'
              '0e7d2ac43abfa1e238b0af33aa96e2dc8637838cdf114c4f546ea1de768a80da')
IMAGE = 'vss-thor-nvstreamer:source'
GRAPH = thor.STATE / 'nvstreamer-compose.json'
BASE_URL = 'http://127.0.0.1:31000/vst/api/v1'


def api(path):
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.load(response)


def compose(*args):
    return ['docker', 'compose', '--project-name', thor.PROJECT, '-f', GRAPH, *args]


def stage():
    thor.require_guard()
    if thor.shared.available() < 90:
        raise RuntimeError('NVStreamer image staging needs 90 GiB available with AI stopped')
    if shutil.disk_usage(thor.STATE).free < 200 * 1024**3:
        raise RuntimeError('Image staging requires 200 GiB free disk')
    active = thor.run(thor.compose('ps', '--status', 'running', '-q',
        'thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception'),
        capture_output=True, text=True).stdout.strip()
    if active:
        raise RuntimeError('Stop AI workloads before staging NVStreamer')
    with (thor.STATE / 'image-stage.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        thor.run(['python3', thor.ROOT / 'tools/thor/restore_codecs.py'])
        thor.run(['docker', 'pull', BASE_IMAGE])
        thor.run(['docker', 'build', '--network=none', '--build-arg',
            'VST_NVSTREAMER_BASE_IMAGE=' + BASE_IMAGE,
            '--build-arg', 'CODEC_LOCK_PATH=deploy/docker/thor-current/codecs.lock.json',
            '--build-arg', 'CODEC_BUNDLE_PATH=deploy/docker/thor-current/vios-codecs/bundle',
            '-f', thor.ROOT / 'deploy/docker/thor-local/Dockerfile.vios-nvstreamer',
            '-t', IMAGE, thor.ROOT])


def render():
    settings = thor.settings()
    data = Path(settings['data_dir']) / 'nvstreamer'
    for name in ('videos', 'data'):
        (data / name).mkdir(parents=True, exist_ok=True)
        (data / name).chmod(0o2770)
    config = json.loads((thor.ROOT / 'deploy/docker/developer-profiles/dev-profile-lvs/'
        'nvstreamer/configs/vst-config.json').read_text())
    config['network'].update(server_domain_name=settings['host_ip'],
        stunurl_list=[], webrtc_port_range={'min': 32001, 'max': 32100})
    config_path = thor.STATE / 'nvstreamer-config.json'
    thor.shared.private_write(config_path, json.dumps(config, indent=2))
    config_path.chmod(0o640)
    image = json.loads(thor.run(['docker', 'image', 'inspect', IMAGE],
                               capture_output=True, text=True).stdout)[0]
    if image['Architecture'] != 'arm64':
        raise RuntimeError('NVStreamer image must be native ARM64')
    graph = {'services': {'nvstreamer': {
        'image': image['Id'], 'container_name': 'vss-vios-nvstreamer',
        'runtime': 'nvidia', 'network_mode': 'host', 'user': f'0:{os.getgid()}', 'restart': 'no',
        'environment': {'ADAPTOR': 'streamer', 'HTTP_PORT': '31000',
            'NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES': 'false',
            'NVIDIA_VISIBLE_DEVICES': 'all', 'NVIDIA_DRIVER_CAPABILITIES': 'compute,utility,video'},
        'volumes': [f'{config_path}:/home/vst/vst_release/configs/vst_config.json:ro',
            str(thor.ROOT / 'deploy/docker/developer-profiles/dev-profile-lvs/nvstreamer/configs/vst-storage.json')
            + ':/home/vst/vst_release/configs/vst_storage.json:ro',
            f'{data / "videos"}:/home/vst/vst_release/streamer_videos',
            f'{data / "data"}:/home/vst/vst_release/vst_data'],
        'mem_limit': '4g', 'memswap_limit': '4g', 'cpus': 4, 'pids_limit': 1024,
        'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL'],
        'healthcheck': {'test': ['CMD', 'python3', '-c',
            "import json,urllib.request; assert json.load(urllib.request.urlopen("
            "'http://127.0.0.1:31000/vst/api/v1/sensor/version',timeout=3))['type']=='streamer'"],
            'interval': '10s', 'timeout': '5s', 'retries': 3, 'start_period': '60s'}
    }}}
    thor.shared.private_write(GRAPH, json.dumps(graph, indent=2))


def start():
    thor.require_guard()
    # Its full 4 GiB limit must fit above the diagnostic reserve, even though
    # a single pass-through source normally consumes much less.
    if thor.shared.available() < thor.memory_reserve() + 4:
        raise RuntimeError(f'NVStreamer startup requires the {thor.memory_reserve():g} GiB reserve plus 4 GiB')
    render()
    thor.run(compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'nvstreamer'))
    for _ in range(60):
        thor.require_guard()
        state = json.loads(thor.run(['docker', 'inspect', '--format', '{{json .State}}',
            'vss-vios-nvstreamer'], capture_output=True, text=True).stdout)
        if state['Status'] in ('exited', 'dead'):
            raise RuntimeError(f'NVStreamer exited with code {state["ExitCode"]}; inspect container logs')
        try:
            version = api('/sensor/version')
            if version.get('type') == 'streamer':
                print(json.dumps(version, indent=2))
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('NVStreamer readiness deadline exceeded; inspect container logs')


def upload(path):
    thor.require_guard()
    if api('/sensor/version').get('type') != 'streamer':
        raise RuntimeError('Wrong service at NVStreamer endpoint')
    path = path.resolve(strict=True)
    if any(char.isspace() for char in path.name) or path.suffix.lower() not in ('.mp4', '.mkv'):
        raise RuntimeError('Use an H.264/H.265 MP4/MKV filename without spaces')
    url = BASE_URL + '/storage/file/' + urllib.parse.quote(path.name)
    result = thor.run(['curl', '--fail-with-body', '--silent', '--show-error',
        '--max-time', '300', '-H', 'Content-Type: application/octet-stream',
        '--upload-file', path, url], capture_output=True, text=True)
    record = json.loads(result.stdout)
    print(json.dumps(record, indent=2))
    sid = record['sensorId']
    for _ in range(30):
        streams = api('/sensor/' + urllib.parse.quote(sid, safe='') + '/streams')
        if streams and streams[0].get('url', '').startswith('rtsp://'):
            print(json.dumps(streams, indent=2))
            return
        time.sleep(1)
    raise RuntimeError('Uploaded file has not exposed an RTSP URL yet')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'start', 'stop', 'status', 'list', 'upload'))
    parser.add_argument('file', nargs='?', type=Path)
    args = parser.parse_args()
    if args.action == 'stage':
        stage()
    elif args.action == 'start':
        start()
    elif args.action == 'stop':
        thor.run(compose('stop', 'nvstreamer'))
    elif args.action == 'upload':
        if not args.file:
            parser.error('upload requires a local MP4/MKV path')
        upload(args.file)
    else:
        print(json.dumps(api('/sensor/version' if args.action == 'status' else '/sensor/streams'), indent=2))


if __name__ == '__main__':
    main()
