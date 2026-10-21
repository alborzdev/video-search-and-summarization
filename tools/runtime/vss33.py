"""Shared 3.3 source/runtime contracts for the measured Spark/Thor adapters.

Rendering is pure configuration. No downloads, container startup, model changes
or reserve changes are performed here.
"""
from pathlib import Path
import re
import shlex
import shutil

SOURCE_VERSION = '3.3.0-rc0'
LEGACY_VLM_VERSION = '3.2.1'
VLM33_SBSA_IMAGE = 'ghcr.io/nvidia-ai-blueprints/vss/vss-rt-vlm@sha256:23f844c9715e2d98ac01260b085fd1f9c7523d748dd594995c4ec952b7f4f65d'
# This tag is promoted only after encoded-file DASH qualification. The public
# 3.3 image lacks our FILE sensor-type repair and is not interchangeable.
VIOS33_NATIVE_IMAGE = 'vss-vios-streamprocessing:3.3-native'
PROFILE = ','.join((
    'bp_developer_thor_full_2d', 'alert-bridge', 'broker-health-check',
    'cadvisor', 'centralizedb', 'elasticsearch', 'elasticsearch-init-container',
    'grafana', 'kafka', 'kafka-topic-init-container', 'kibana', 'logstash',
    'lvs-server', 'node-exporter', 'phoenix', 'prometheus', 'redis',
    'rtvi-embed', 'rtvi-vlm', 'sensor-ms', 'streamprocessing-ms',
    'vss-agent', 'vss-haproxy-ingress', 'vss-search-analytics-2d-fusion',
    'vss-ui', 'vss-va-mcp', 'vst-ingress',
))
HOST_SERVICES = {
    'alert-bridge', 'broker-health-check', 'centralizedb', 'elasticsearch',
    'elasticsearch-init-container', 'graph-db', 'kafka',
    'kafka-topic-init-container', 'kibana', 'kibana-init-container-thor-full',
    'logstash', 'lvs-server', 'phoenix', 'redis', 'sensor-ms', 'streamprocessing-ms',
    'vios-mcp', 'vss-agent', 'vss-behavior-analytics-thor-candidates',
    'vss-haproxy-ingress', 'vss-search-analytics-2d-fusion', 'vss-ui',
    'vss-va-mcp', 'vss-video-analytics-api-fusion', 'vst-ingress',
}


def runtime_options(saved, adaptive_evs=None, rtvi_vlm_image=None, demo_profile=None,
                    vios_streamprocessing_image=None, hardware=None):
    """Preserve saved choices; never imply old engine supports EVS++ sessions."""
    enabled = saved.get('adaptive_evs', False) if adaptive_evs is None else adaptive_evs
    image = saved.get('rtvi_vlm_image', '') if rtvi_vlm_image is None else rtvi_vlm_image
    profile = saved.get('demo_profile', 'all') if demo_profile is None else demo_profile
    vios_image = (saved.get('vios_streamprocessing_image', '') if vios_streamprocessing_image is None
                  else vios_streamprocessing_image)
    if not isinstance(vios_image, str) or vios_image not in ('', VIOS33_NATIVE_IMAGE):
        raise RuntimeError('VIOS streamprocessing requires the reviewed source-fixed image '
                           f'{VIOS33_NATIVE_IMAGE}, or an empty string to restore the cached 3.2.1 runtime; '
                           'the public unpatched 3.3 image is not qualified for encoded DASH.')
    if vios_image and hardware is not None and hardware != 'DGX-SPARK':
        raise RuntimeError('The native 3.3 VIOS streamprocessing image is qualified for Spark only; '
                           'Thor must retain its cached runtime until separately qualified.')
    if not isinstance(enabled, bool) or not isinstance(image, str):
        raise RuntimeError('adaptive_evs must be a boolean and rtvi_vlm_image an image reference.')
    if image and (any(char.isspace() for char in image) or not re.fullmatch(r'[A-Za-z0-9./_:@+-]+', image)):
        raise RuntimeError('Use an explicit container image reference without shell syntax.')
    # A pinned 3.3 SBSA/Thor image or a locally built 3.3 image is required.
    # Runtime imports/inference must still be qualified on the target device.
    if enabled and image != VLM33_SBSA_IMAGE and not re.search(r'(?:^|[/:_-])3[.]3(?:[.\-_:]|$)', image):
        raise RuntimeError('Adaptive EVS needs an explicitly selected compatible 3.3 RT-VLM image; the cached 3.2.1 engine does not support it.')
    if profile not in ('all', 'clips'):
        raise RuntimeError('demo_profile must be all or clips.')
    return dict(adaptive_evs=enabled, rtvi_vlm_image=image, demo_profile=profile,
                vios_streamprocessing_image=vios_image)


def runtime_version(image):
    if not image:
        return LEGACY_VLM_VERSION
    if image == VLM33_SBSA_IMAGE:
        return '3.3'
    match = re.search(r'(?:^|[/:_-])(3[.]\d+(?:[.]\d+)?)(?:[.\-_:]|$)', image)
    return match.group(1) if match else 'unverified'


def prepare_literal_build_contexts(services, root, state, names):
    """Copy named public files before BuildKit evaluates wildcard COPY inputs.

    Private database directories can be unreadable, and some Docker context
    walkers still visit them when expanding wildcard inputs. A literal source
    snapshot also guarantees deleted files cannot survive the previous build.
    This helper intentionally rejects directory and symlink COPY inputs.
    """
    root, state = Path(root), Path(state)
    for name in names:
        build = services[name]['build']
        dockerfile = Path(build['dockerfile'])
        context = state / 'build-contexts' / name
        if context.is_symlink():
            raise RuntimeError('Build context cannot be a symlink')
        if context.exists():
            shutil.rmtree(context)
        context.mkdir(parents=True)
        for line in (root / dockerfile).read_text().splitlines():
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
                matches = list(root.glob(pattern))
                if not matches:
                    raise RuntimeError(f'Missing build source {pattern}')
                for source in matches:
                    if not source.is_file() or source.is_symlink() or source.resolve() != source:
                        raise RuntimeError(f'Build source must be a regular file: {source}')
                    target = context / source.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        target = context / dockerfile
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / dockerfile, target)
        ignore = root / (str(dockerfile) + '.dockerignore')
        if ignore.exists():
            shutil.copyfile(ignore, context / ignore.relative_to(root))
        build['context'] = str(context)


def reconcile(graph, root, hardware, options, detector_enabled=None):
    """Adapt 3.3 bridge defaults to the existing loopback appliance contracts."""
    # Revalidate direct callers too. This is reference validation only: image
    # staging/provenance and database rollback review belong to the operator.
    options = runtime_options(options, hardware=hardware)
    selected_image = options['rtvi_vlm_image']
    if hardware != 'DGX-SPARK' and (selected_image == VLM33_SBSA_IMAGE or 'sbsa' in selected_image.lower()):
        raise RuntimeError('Thor requires its own reviewed non-SBSA RT-VLM image; a Spark image cannot be reused on Thor.')
    root = Path(root)
    services = graph['services']
    # Source updates must not migrate an existing appliance's persisted stores
    # or monitoring databases as a side effect. Those versions have their own
    # upgrade/rollback procedure and are unrelated to VSS feature work.
    preserved_images = {
        'centralizedb': 'postgres:17.9-alpine',
        'redis': 'redis:8.6.2-alpine',
        'kibana': 'docker.elastic.co/kibana/kibana:9.3.3',
        'phoenix': 'arizephoenix/phoenix:14.15.0',
        'prometheus': 'quay.io/prometheus/prometheus:v3.11.3',
        'grafana': 'grafana/grafana:13.0.1-ubuntu',
        'node-exporter': 'quay.io/prometheus/node-exporter:v1.11.1',
        'cadvisor': 'ghcr.io/google/cadvisor:0.56.2',
        'vss-haproxy-ingress': 'haproxy:3.0-alpine',
    }
    for name, image in preserved_images.items():
        if name in services:
            services[name]['image'] = image
    # This cached image is the existing ES 9.3.3 derivative. In particular do
    # not rebuild it using the upstream 9.4.4 Dockerfile against old index data.
    services['elasticsearch'].pop('build', None)
    services['elasticsearch']['image'] = 'vss-spark-elasticsearch:source' if hardware == 'DGX-SPARK' else 'vss-thor-elasticsearch:source'
    prefix = 'vss-spark' if hardware == 'DGX-SPARK' else 'vss-thor'
    # Keep the existing small shell-tool runtimes, mounting the updated source
    # scripts rather than downloading a new broker distribution to run a job.
    for name in ('broker-health-check', 'elasticsearch-init-container'):
        services[name].pop('build', None)
        services[name]['image'] = f'{prefix}-{name}:source'
    services['broker-health-check'].setdefault('volumes', []).append(dict(
        type='bind', source=str(root / 'deploy/docker/services/infra/broker-health-check/scripts/check-kafka-health.sh'),
        target='/scripts/check-kafka-health.sh', read_only=True))
    # Source mounts retain Git's non-executable mode. Run them through Bash
    # rather than relying on the chmod baked into the cached tool image.
    services['broker-health-check']['entrypoint'] = ['bash', '/scripts/check-kafka-health.sh']
    services['elasticsearch-init-container'].setdefault('volumes', []).append(dict(
        type='bind', source=str(root / 'deploy/docker/services/infra/elk/elasticsearch/init-scripts'),
        target='/opt/mdx/init-scripts', read_only=True))
    services['elasticsearch-init-container']['command'] = ['bash', '-ec', ' && '.join(
        'bash /opt/mdx/init-scripts/' + script for script in (
            'elasticsearch-ilm-policy-creation.sh', 'elasticsearch-template-creation.sh',
            'elasticsearch-ingest-pipeline-creation.sh'))]
    services['kafka-topic-init-container'].pop('build', None)
    services['kafka-topic-init-container']['image'] = 'confluentinc/cp-kafka:8.2.0'
    # The unused benchmark volume still encodes its pre-relocation host path
    # in Docker. Retire its runtime attachment, preserving both the existing
    # volume and its data; normal demo startup must never ask to recreate it.
    for service in services.values():
        service['volumes'] = [mount for mount in service.get('volumes', [])
                              if mount.get('target') != '/vss-agent/agent_eval']
    graph.get('volumes', {}).pop('agent-eval', None)
    for name, target, published in (('prometheus', 9090, 9090), ('grafana', 3000, 14000),
                                     ('node-exporter', 9100, 19100), ('cadvisor', 8080, 18080)):
        if name in services:
            services[name]['ports'] = [dict(mode='ingress', host_ip='127.0.0.1', target=target,
                                           published=str(published), protocol='tcp')]
    # The device builds contain their codecs already. An upstream best-effort
    # apt cache job adds startup work and can touch the network unnecessarily.
    services.pop('vios-apt-cache-init', None)
    for name in HOST_SERVICES & services.keys():
        service = services[name]
        service['network_mode'] = 'host'
        service.pop('networks', None)
        service.pop('ports', None)
        hosts = service.setdefault('extra_hosts', {})
        if isinstance(hosts, list):
            hosts = dict(item.split('=' if '=' in item else ':', 1) for item in hosts)
            service['extra_hosts'] = hosts
        # Upstream JSON/YAML configuration names the bridge services. These
        # exact aliases preserve those configurations on the host-local lane.
        hosts.update(kafka='127.0.0.1', elasticsearch='127.0.0.1', redis='127.0.0.1',
                     **{'vss-va-mcp': '127.0.0.1', 'vss-vios-sensor': '127.0.0.1',
                        'vss-vios-streamprocessing': '127.0.0.1', 'vst-ingress': '127.0.0.1',
                        'lvs-server': '127.0.0.1', 'vss-rtvi-cv': '127.0.0.1'})
    for service in services.values():
        service.get('depends_on', {}).pop('vios-apt-cache-init', None)
    pythonpath = '/vss-agent/edge-agent-src:/vss-agent/edge-core-src:/vss-agent/edge-cli-src'
    mounts = (
        ('services/agent/packages/vss_agents/src', '/vss-agent/edge-agent-src'),
        ('libs/vss/core/src', '/vss-agent/edge-core-src'),
        ('libs/vss/cli/src', '/vss-agent/edge-cli-src'),
    )
    for name in ('vss-agent', 'vss-va-mcp'):
        if name not in services:
            continue
        service = services[name]
        service['image'] = 'vss-edge-agent:3.3-source'
        service['build'] = dict(context=str(root), dockerfile='deploy/docker/thor-local/Dockerfile.agent33',
                               network='none')
        service.setdefault('environment', {})['PYTHONPATH'] = pythonpath
        volumes = service.setdefault('volumes', [])
        volumes[:] = [m for m in volumes if m.get('target') != '/vss-agent/thor-local-src']
        for source, target in mounts:
            volumes.append(dict(type='bind', source=str(root / source), target=target, read_only=True))
    # CPU services move together with the source API contracts. Do not copy a
    # few 3.3 modules over an incompatible 3.2 image dependency environment.
    services['alert-bridge']['build'] = dict(context=str(root), dockerfile='deploy/docker/thor-local/Dockerfile.alert33', network='none')
    services['vss-video-analytics-api-fusion']['image'] = f'{prefix}-video-analytics-api:source'
    services['vss-video-analytics-api-fusion']['build'] = dict(
        context=str(root), dockerfile='deploy/docker/thor-local/Dockerfile.video-analytics-api33', network='none')
    for name in ('vss-search-analytics-2d-fusion', 'vss-behavior-analytics-thor-candidates'):
        if name in services:
            services[name]['build'] = dict(context=str(root), dockerfile='deploy/docker/thor-local/Dockerfile.behavior-analytics33', network='none')
    # Persistent services keep their measured runtime versions by default.
    # A VIOS image change below requires a separate explicit selection; source
    # updates must not silently upgrade formats on an existing demo appliance.
    services['kafka']['image'] = 'confluentinc/cp-kafka:8.2.0'
    services['kafka']['environment'].update(
        KAFKA_ADVERTISED_LISTENERS='INTERNAL://127.0.0.1:29092,EXTERNAL://' +
        services['kafka']['environment']['KAFKA_ADVERTISED_LISTENERS'].split('EXTERNAL://')[-1])
    for name in ('kafka-topic-init-container', 'broker-health-check'):
        services[name].setdefault('environment', {}).update(BOOTSTRAP_HOST='127.0.0.1', KAFKA_PORT='9092')
    services['kibana'].setdefault('environment', {})['ELASTICSEARCH_HOSTS'] = '["http://127.0.0.1:9200"]'
    services['sensor-ms']['image'] = 'nvcr.io/nvidia/vss-core/vss-vios-sensor:3.2.1'
    if options['vios_streamprocessing_image']:
        stream = services['streamprocessing-ms']
        stream['image'] = options['vios_streamprocessing_image']
        stream.pop('build', None)
        # Match the isolated software-codec archive qualification envelope.
        # The old hardware runtime remains unchanged unless explicitly selected.
        stream.update(runtime='runc', mem_limit='2g', memswap_limit='2g', cpus=2)
        # The source-fixed 3.3 image already contains its reviewed codec bytes;
        # it does not contain the old derivative's offline-entrypoint script.
        stream['entrypoint'] = ['/home/vst/vst_release/launch_vst']
        stream.setdefault('environment', {}).update(
            VST_INSTALL_ADDITIONAL_PACKAGES='false', NVIDIA_VISIBLE_DEVICES='void')
    # The UI talks through this same host-local edge; Compose DNS names are not
    # resolvable from host-network services.
    ingress = services['vss-haproxy-ingress'].setdefault('environment', {})
    for key in ('ELASTICSEARCH_SERVICE_HOST', 'VSS_UI_SERVICE_HOST', 'VSS_AGENT_SERVICE_HOST',
                'VST_INGRESS_SERVICE_HOST', 'VST_STREAMPROCESSING_SERVICE_HOST',
                'BEHAVIOR_ANALYTICS_SERVICE_HOST', 'VSS_VA_MCP_SERVICE_HOST',
                'VIDEO_ANALYTICS_API_SERVICE_HOST', 'ALERT_BRIDGE_SERVICE_HOST',
                'KIBANA_SERVICE_HOST', 'PHOENIX_SERVICE_HOST', 'LVS_SERVICE_HOST',
                'RTVI_CV_SERVICE_HOST', 'PERCEPTION_SDR_SERVICE_HOST'):
        ingress[key] = '127.0.0.1'
    ingress.update(RTVI_EMBED_SERVICE_HOST='127.0.0.1', RTVI_EMBED_SERVICE_PORT='8017',
                   RTVI_VLM_SERVICE_HOST='127.0.0.1', RTVI_VLM_SERVICE_PORT='8018',
                   LLM_SERVICE_HOST='127.0.0.1', LLM_SERVICE_PORT='30081')
    ui = services['vss-ui'].setdefault('environment', {})
    ui.update(VSS_PROXY_BASE_URL='http://127.0.0.1:7777',
              VSS_SOURCE_VERSION=SOURCE_VERSION,
              VSS_RTVI_RUNTIME_VERSION=runtime_version(options['rtvi_vlm_image']),
              VSS_DEMO_PROFILE=options['demo_profile'],
              VSS_ADAPTIVE_EVS_ENABLED=str(options['adaptive_evs']).lower(),
              VSS_DASH_PLAYBACK_ENABLED=str(bool(options['vios_streamprocessing_image'])).lower())
    if detector_enabled is not None:
        ui['VSS_DETECTOR_ENABLED'] = str(detector_enabled).lower()
    # Restrict host-published chat URLs to the existing ingress.
    for key in ('NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL', 'NEXT_PUBLIC_SIDEBAR_CHAT_HTTP_CHAT_COMPLETION_URL'):
        ui[key] = 'http://127.0.0.1:7777/chat/stream'
    services['rtvi-vlm'].setdefault('environment', {}).pop('RTVI_VLLM_NATIVE_CONV3D', None)
    if options['rtvi_vlm_image']:
        vlm = services['rtvi-vlm']
        vlm['image'] = options['rtvi_vlm_image']
        # Never overlay new Python on an older vLLM dependency stack.
        vlm.pop('build', None)
        vlm.setdefault('environment', {}).update(
            VIA_EVS_SESSION=str(options['adaptive_evs']).lower(),
            VLM_VIDEO_PRUNING_RATE='0.5' if options['adaptive_evs'] else '',
            VIA_EVS_TOKEN_BUDGET='1', VIA_EVS_MAX_SESSIONS='1',
            VLLM_EVS_SIMILARITY_THRESHOLD='0.4', VLLM_NUM_PREPROCESS_WORKERS='2')
        if hardware == 'DGX-SPARK' and runtime_version(options['rtvi_vlm_image']).split('.')[:2] == ['3', '3']:
            # The reviewed GB10 3.3 stack uses vLLM's native Conv3d path;
            # cuDNN's Conv3d kernel fails even for a tiny BF16/FP16 input.
            vlm['environment']['RTVI_VLLM_NATIVE_CONV3D'] = 'true'
    else:
        # Source upgrades do not upgrade the cached inference engine. Keep the
        # measured engine explicit until a 3.3 image is staged and qualified.
        services['rtvi-vlm'].pop('build', None)
        services['rtvi-vlm']['image'] = 'vss-spark-rtvi-vlm:source' if hardware == 'DGX-SPARK' else 'vss-thor-rtvi-vlm:source'
    # Local embedding continues using the pinned model/dimension and cache.
    services['rtvi-embed'].pop('build', None)
    services['rtvi-embed']['image'] = 'vss-spark-rtvi-embed:source' if hardware == 'DGX-SPARK' else 'vss-thor-rtvi-embed:source'
    # Cached 3.2.1 Embed reads KAFKA_TOPIC, while 3.3 uses MESSAGE_BUS_TOPIC.
    # Keep both contracts explicit so completed ingestion reaches search rather
    # than silently publishing vectors to the default caption topic.
    services['rtvi-embed'].setdefault('environment', {}).update(
        MESSAGE_BUS='kafka', MESSAGE_BUS_TOPIC='mdx-embed',
        KAFKA_TOPIC='mdx-embed', KAFKA_ENABLED='true')
    broker = services['kafka']['environment']['KAFKA_ADVERTISED_LISTENERS'].split('EXTERNAL://')[-1]
    for name in ('rtvi-embed', 'rtvi-vlm'):
        services[name].setdefault('environment', {})['KAFKA_BOOTSTRAP_SERVERS'] = broker
    if options['demo_profile'] == 'clips':
        # Search analytics also relays mdx-embed to mdx-embed-filtered, which is
        # the Logstash input for recorded-video search. It remains required
        # without live CV; only the live alert candidate consumer is optional.
        services.pop('vss-behavior-analytics-thor-candidates', None)
    return graph
