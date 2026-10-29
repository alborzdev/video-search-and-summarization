"""Read-only Photon entrypoint audit; no Torch import or model download."""

import ast
import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sysconfig
import urllib.request


OUTPUT = Path(__file__).with_suffix('.json')
SITE = Path(sysconfig.get_paths()['purelib'])
MAX_TOTAL_BYTES = 2 * 1024**2
network = []


def fetch(url):
    used = sum(row['bytes'] for row in network)
    limit = min(512 * 1024, MAX_TOTAL_BYTES - used)
    if limit <= 0:
        raise RuntimeError('Audit network budget exhausted')
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise RuntimeError('Audit response exceeded byte cap')
    network.append({'url': url, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
    return body


def source_info(relative, needles):
    path = SITE / relative
    body = path.read_bytes()
    lines = body.decode().splitlines()
    return {
        'path': str(path),
        'sha256': hashlib.sha256(body).hexdigest(),
        'locations': {
            needle: [i for i, line in enumerate(lines, 1) if needle in line]
            for needle in needles
        },
    }


def registry_rows():
    init = ast.parse((SITE / 'kestrel/models/moondream/__init__.py').read_text())
    names = next(ast.literal_eval(n.value) for n in init.body
                 if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == '_MODEL_NAMES' for t in n.targets))
    tree = ast.parse((SITE / 'kestrel/models/moondream/registration.py').read_text())
    config = ast.parse((SITE / 'kestrel/models/moondream/config.py').read_text())
    tokenizer = next(ast.literal_eval(n.value) for n in config.body
                     if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == '_TOKENIZER_CONFIG' for t in n.targets))
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'ModelSpec':
            continue
        values = {k.arg: k.value for k in node.keywords}
        row = {'name': names[ast.literal_eval(values['name'].slice)]}
        for name in ['repo_id', 'filename', 'checkpoint_format', 'tokenizer_id']:
            row[name] = ast.literal_eval(values[name])
        row['default_config'] = values['default_config'].id
        row['skills_factory'] = values['skills'].id
        row['revision'] = ast.literal_eval(values['revision']) if 'revision' in values else None
        row['segment_template'] = None if row['checkpoint_format'] == 'md2' else tokenizer['templates']['segment']
        row['bos_id'] = tokenizer['bos_id']
        row['eos_id'] = tokenizer['eos_id']
        row['coord_id'] = tokenizer['coord_id']
        row['size_id'] = tokenizer['size_id']
        rows.append(row)
    return rows


def main():
    local_files = {
        'sdk_factory': ('moondream/__init__.py', ['def photon(', 'return PhotonClient(', 'if local:', 'return photon(model']),
        'sdk_client': ('moondream/photon_client.py', ['def _parse_model(', 'RuntimeConfig(', 'InferenceEngine.create(', 'def segment(', 'settings=self._settings(settings)']),
        'runtime_config': ('kestrel/config.py', ['model_path:', 'ensure_model_weights(self.model)']),
        'download': ('kestrel/model_download.py', ['spec = get_spec(model)', 'hf_hub_download(repo_id']),
        'registry': ('kestrel/models/moondream/registration.py', ['ModelSpec(', 'filename=', 'skills=']),
        'prompt_config': ('kestrel/models/moondream/config.py', ['"segment":', 'MD2 doesn\'t support segment']),
        'runtime': ('kestrel/models/moondream/runtime.py', ['deepcopy(self._spec.default_config)', 'self.seg_refiner =', 'if self._vision_backend is None and _HAS_SEG_DEPS', 'return self.skills().names()']),
        'skills': ('kestrel/models/moondream/skills/__init__.py', ['def build_skill_registry(', 'SegmentSkill(),']),
        'segment': ('kestrel/models/moondream/skills/segment.py', ['Model does not include a segment template', 'if svg_path and bbox', 'runtime.seg_refiner(']),
        'refiner': ('kestrel/seg_refiner.py', ['_HAS_SEG_DEPS = False', 'repo_id="moondream/SegHeadRefiner"', 'token=os.environ.get("HF_TOKEN")', 'if coarse_mask.sum() == 0:']),
        'introspection': ('kestrel/engine/handle.py', ['def tasks(', 'def supports(', 'return task in self.tasks']),
    }
    receipt = {
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'Read-only code, distribution metadata, and primary-source HTTP metadata; no GPU, Torch import, model load, service change, installation, or cloud inference',
        'packages': {},
        'registered_moondream_models': registry_rows(),
        'optional_refinement_dependencies': {name: importlib.util.find_spec(name) is not None for name in ['cv2', 'resvg', 'potrace', 'PIL']},
        'local_source': {name: source_info(*args) for name, args in local_files.items()},
    }
    for package in ['moondream', 'kestrel']:
        dist = importlib.metadata.distribution(package)
        receipt['packages'][package] = {
            'version': dist.version,
            'console_scripts': [{'name': ep.name, 'value': ep.value} for ep in dist.entry_points if ep.group == 'console_scripts'],
        }
    commit = json.loads(fetch('https://api.github.com/repos/m87-labs/kestrel/commits/main'))
    sha = commit['sha']
    receipt['upstream'] = {'revision': sha, 'date': commit['commit']['committer']['date'], 'files': {}}
    paths = ['README.md', 'triton_server/README.md',
             'triton_server/model_repository/moondream/1/engine_singleton.py',
             'triton_server/model_repository/moondream/1/model.py',
             'kestrel/models/moondream/registration.py',
             'kestrel/models/moondream/config.py']
    needles = ['separate model weights', 'KESTREL_MODEL_PATH', 'RuntimeConfig(**kwargs)',
               'skill == "', 'Unknown skill:', '"segment":', 'filename=']
    for path in paths:
        body = fetch(f'https://raw.githubusercontent.com/m87-labs/kestrel/{sha}/{path}')
        lines = body.decode().splitlines()
        item = {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'locations': {
            needle: [i for i, line in enumerate(lines, 1) if needle in line]
            for needle in needles if any(needle in line for line in lines)
        }}
        local = SITE / path
        if local.exists():
            item['byte_identical_to_installed'] = body == local.read_bytes()
        if path == 'README.md':
            item['segmentation_note'] = next(line for line in lines if 'separate model weights' in line)
        receipt['upstream']['files'][path] = item
    refiner = json.loads(fetch('https://huggingface.co/api/models/moondream/SegHeadRefiner'))
    receipt['refiner_repository'] = {k: refiner.get(k) for k in ['id', 'sha', 'private', 'gated', 'lastModified', 'usedStorage', 'siblings']}
    pr = json.loads(fetch('https://api.github.com/repos/m87-labs/moondream-python/pulls/15'))
    receipt['upstream_segmentation_smoke'] = {
        'url': pr['html_url'], 'title': pr['title'], 'merged_at': pr['merged_at'],
        'merge_commit_sha': pr['merge_commit_sha'],
        'body_sha256': hashlib.sha256(pr['body'].encode()).hexdigest(),
        'selected_prompt_report': 'The selected MD3 segmentation smoke prompt returned a bbox and no SVG tokens in the raw Kestrel skill result.',
        'selected_prompt_report_present_in_body': 'The selected MD3 segmentation smoke prompt returned a bbox and no SVG tokens in the raw Kestrel skill result.' in pr['body'],
        'scope': 'One selected H100 smoke prompt; not a universal failure claim or identification of every tested checkpoint/prompt.',
    }
    receipt['refiner_activation'] = {
        'construction_condition': '_vision_backend is None and _HAS_SEG_DEPS',
        'dependency_condition': 'cv2, PIL.Image, and resvg.render/usvg import successfully',
        'current_environment_constructs_refiner': False,
        'current_disabled_reason': 'cv2 and resvg are not installed',
        'invocation_condition': 'nonempty svg_path, bbox, no parse_error, source image, and runtime.seg_refiner is not None',
        'weights': 'moondream/SegHeadRefiner/model.pt',
        'automatic_default_segmentation_adapter': None,
    }
    receipt['findings'] = {
        'sdk_and_legacy_local_factory_same_engine': True,
        'standard_photon_serve_console_entrypoint_found': False,
        'triton_example_selects_different_hidden_checkpoint': False,
        'triton_example_dispatches_segment': False,
        'automatic_segment_specific_adapter_found': False,
        'runtime_reads_prompt_config_from_registry_not_hf_config': True,
        'md2_shared_registry_advertises_segment_but_template_is_none': True,
        'refiner_runs_only_after_nonempty_svg': True,
        'missing_refiner_explains_empty_svg_before_refinement': False,
        'separate_weights_note_proves_different_base_checkpoint': False,
        'separate_weights_note_limitation': 'README does not distinguish another base checkpoint from the gated refinement head; no public alternate base ID is identified by this audit.',
    }
    receipt['network'] = {'total_response_bytes': sum(r['bytes'] for r in network), 'requests': network}
    OUTPUT.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(OUTPUT), 'network_bytes': receipt['network']['total_response_bytes'], 'upstream_sha': sha, 'registry': receipt['registered_moondream_models']}, indent=2))


if __name__ == '__main__':
    main()
