# SPDX-License-Identifier: Apache-2.0
"""Exercise the isolated synthetic qualification without live-service access."""

import os
import subprocess
import urllib.request

import pytest

from apps.city.qualify_fixture_loops import qualify


def test_complete_repeated_rule_loops_are_isolated_and_durable(tmp_path, monkeypatch):
    protected_database = tmp_path / "must-not-open.sqlite3"
    protected_database.write_bytes(b"not a SQLite database: preserve this sentinel")
    protected_native = tmp_path / "must-not-write-native"
    protected_native.mkdir()
    native_sentinel = protected_native / "analytics.ini"
    native_sentinel.write_text("must remain unchanged\n")
    monkeypatch.setenv("CITY_STATE_DB", str(protected_database))
    monkeypatch.setenv("CITY_NATIVE_CONFIG_DIR", str(protected_native))
    monkeypatch.setenv("CITY_MEDIA_REGISTRY_JSON", "invalid ambient live registry")
    monkeypatch.setenv("CITY_SITE_FILE", "/not-a-real-live-site.json")

    def forbidden(*args, **kwargs):
        raise AssertionError("Qualification must never launch a process or network request")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = qualify(loops=2)
    assert result["result"] == "passed"
    assert result["eventCount"] == 22
    assert result["acceptedObservations"] == 404
    assert result["duplicateObservationsRejected"] == 8
    assert result["lateRetiredSessionObservationsRejected"] == 2
    assert len(result["ruleFamilies"]) == 7
    assert result["durableJsonAndCsvEventCounts"] == {
        "beforeReopen": 22,
        "afterReopen": 22,
        "csvRowsAfterReopen": 22,
    }
    assert result["historicalBeforeTriggerAtTriggerAtClearChecks"] == 66
    assert result["midIncidentResetProbe"]["activeEventsMadeUnknown"] == 6
    assert result["isolation"]["gpuUsed"] is False
    assert result["isolation"]["liveServicesMutated"] is False
    assert protected_database.read_bytes() == b"not a SQLite database: preserve this sentinel"
    assert native_sentinel.read_text() == "must remain unchanged\n"
    assert os.environ["CITY_STATE_DB"] == str(protected_database)
    assert os.environ["CITY_MEDIA_REGISTRY_JSON"] == "invalid ambient live registry"


@pytest.mark.parametrize("loops", [0, 31])
def test_qualification_loop_bound_is_explicit(loops):
    with pytest.raises(ValueError, match="1–30"):
        qualify(loops=loops)
