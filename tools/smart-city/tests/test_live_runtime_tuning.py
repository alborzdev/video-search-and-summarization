import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('city_manage_tuning', Path(__file__).parents[1] / 'manage.py')
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


def tuning(tmp_path, monkeypatch, value):
    path = tmp_path / '.spark/city/state/runtime-tuning.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    monkeypatch.setattr(manage, 'ROOT', tmp_path)
    return manage.live_runtime_tuning('spark')


def test_extra_decode_surfaces_are_explicit_bounded_and_hardware_only(tmp_path, monkeypatch):
    assert tuning(tmp_path, monkeypatch, {'decoder': 'hardware', 'decoderExtraSurfaces': 4}) == {
        'decoder': 'hardware', 'decoderExtraSurfaces': 4}


@pytest.mark.parametrize('value', [-1, 9, True, 1.5, '4'])
def test_bad_surface_counts_rejected(tmp_path, monkeypatch, value):
    with pytest.raises(ValueError, match='decoderExtraSurfaces'):
        tuning(tmp_path, monkeypatch, {'decoder': 'hardware', 'decoderExtraSurfaces': value})


def test_surfaces_cannot_silently_select_hardware_or_enable_ineffective_interval(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='explicit hardware'):
        tuning(tmp_path, monkeypatch, {'decoderExtraSurfaces': 4})
    path = tmp_path / '.spark/city/state/runtime-tuning.json'
    path.write_text(json.dumps({'inferenceInterval': 1}))
    with pytest.raises(ValueError, match='unsupported'):
        manage.live_runtime_tuning('spark')


@pytest.mark.parametrize('value', [1, 'true', None])
def test_low_latency_requires_strict_boolean(tmp_path, monkeypatch, value):
    with pytest.raises(ValueError, match='boolean'):
        tuning(tmp_path, monkeypatch, {'decoder': 'hardware', 'decoderLowLatency': value})


def test_low_latency_is_explicit_hardware_selection(tmp_path, monkeypatch):
    assert tuning(tmp_path, monkeypatch, {'decoder': 'hardware', 'decoderLowLatency': True})['decoderLowLatency'] is True
    with pytest.raises(ValueError, match='hardware decoding'):
        tuning(tmp_path, monkeypatch, {'decoder': 'cpu', 'decoderLowLatency': True})
