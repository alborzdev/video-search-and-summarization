"""The opt-in archive payload preserves provider bounds and typed incident results."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from handlers.direct_media.direct_media_handler import merge_vlm_result
from schemas.vlm_responses import VLMResponse
from vlm.vlm_client import _VLMClientBase
from web.schemas.alert_config_schemas import AlertConfigRequest

PRESET = Path(__file__).resolve().parents[2] / 'presets/archive-conveyor-binary.json'


@pytest.fixture
def preset():
    # Validate the actual operator payload using the same model as the API.
    return AlertConfigRequest.model_validate_json(PRESET.read_text())


def test_preset_is_valid_explicit_and_preserves_selected_model(preset):
    assert preset.alert_type == 'demo_archive_conveyor_binary'
    assert preset.system_prompt == 'You are a helpful assistant.'
    assert preset.prompt == (
        'Does any frame in this video show a cardboard box on the blue conveyor belt? '
        'Answer YES if at least one frame shows a box, otherwise NO. Return only YES or NO.'
    )
    assert preset.vlm_params.model is None
    assert preset.vlm_params.base_url is None
    assert preset.vlm_params.json_parser is None
    shipped = json.loads((PRESET.parent.parent / 'alert_type_config.json').read_text())
    assert preset.alert_type not in {item['alert_type'] for item in shipped['alerts']}


def test_cosmos_override_omits_provider_json_without_mutating_global_defaults(preset):
    global_config = {
        'model': 'nim_nvidia_cosmos3-nano-reasoner_bf16-final',
        'base_url': 'http://already-selected-vlm:8000/v1',
        'response_format': 'json',
        'json_parser': {'verdict_field': 'hazard', 'verdict_mapping': {'yes': 'NO'}},
        'use_vlm_media_defaults': False,
        'max_tokens': 512,
        'temperature': 0.4,
    }
    original = deepcopy(global_config)
    overrides = preset.vlm_params.model_dump(exclude_none=True)
    client = _VLMClientBase(global_config)  # Payload helpers create no HTTP client.
    extra = client._build_extra_body(video=True, config_overrides=overrides)
    kwargs = client._build_chat_kwargs(extra, config_overrides=overrides)
    assert kwargs == {
        'max_tokens': 64,
        'temperature': 0.0,
        'timeout': 30,
        'extra_body': {
            'media_io_kwargs': {'video': {'num_frames': 20}},
        },
    }
    assert 'mm_processor_kwargs' not in extra
    assert preset.vlm_params.do_resize is False
    assert 'response_format' not in kwargs
    assert 'json_parser' not in kwargs
    assert global_config == original
    assert client.model == original['model']
    assert client.base_url == original['base_url']
    # The same client keeps JSON behavior for calls that do not opt in.
    assert client._build_chat_kwargs({})['response_format'] == {'type': 'json_object'}
    # A stale global JSON mapping cannot reinterpret the binary verdict.
    parsed = VLMResponse.model_validate_text('YES', response_format=overrides['response_format'], json_config=global_config['json_parser'])
    assert parsed.model_dump()['verdict'] == 'confirmed'


@pytest.mark.parametrize(('raw', 'expected'), [('YES', 'confirmed'), ('NO', 'rejected')])
def test_binary_response_uses_normalized_incident_envelope(preset, raw, expected):
    message = {'id': 'fixture-event', 'sensorId': 'fixture-sensor', 'info': {
        'media_urls': ['http://archive.example/clip.mp4'], 'validationRun': 'fixture-run',
    }}
    merge_vlm_result(message, raw, model_name='nvidia/cosmos3-nano-reasoner',
                     use_verdict=True, media_type='video',
                     response_format=preset.vlm_params.response_format)
    assert message['id'] == 'fixture-event'
    assert message['sensorId'] == 'fixture-sensor'
    info = message['info']
    assert info['verdict'] == expected
    assert info['reasoning'] == ''
    assert info['verificationResponseCode'] == '200'
    assert info['verificationResponseStatus'] == 'OK'
    assert info['videoSource'] == 'http://archive.example/clip.mp4'
    assert info['validationRun'] == 'fixture-run'
    assert 'vlm_response' not in info
    assert 'errorSource' not in info


@pytest.mark.parametrize('raw', ['', '   ', 'YES or NO', 'There might be a box.'])
def test_empty_or_ambiguous_response_fails_closed(preset, raw):
    message = {'info': {'media_urls': ['http://archive.example/clip.mp4']}}
    merge_vlm_result(message, raw, model_name='nvidia/cosmos3-nano-reasoner',
                     use_verdict=True, media_type='video',
                     response_format=preset.vlm_params.response_format)
    info = message['info']
    assert info['verdict'] == 'verification-failed'
    assert info['verificationResponseCode'] == '500'
    assert info['errorSource'] == 'vlm_schema'
    assert 'reasoning' not in info
