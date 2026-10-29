# SPDX-License-Identifier: Apache-2.0
"""CPU regressions for durable event selection and bounded frame history."""
import pytest

from apps.city.store import CityStore


@pytest.fixture
def store():
    result = CityStore(max_events=2000)
    yield result
    result.close()


def event(number, **values):
    return {
        "id": str(number),
        "triggeredAtNs": str(number),
        "updatedAtNs": str(number),
        "siteId": "site",
        "sourceId": "wanted-source",
        "ruleId": "wanted-rule",
        "state": "closed",
        **values,
    }


@pytest.mark.parametrize(
    ("filters", "nonmatching"),
    [
        ({"source_id": "wanted-source"}, {"sourceId": "other-source"}),
        ({"rule_id": "wanted-rule"}, {"ruleId": "other-rule"}),
        ({"state": "closed"}, {"state": "active"}),
        (
            {"source_id": "wanted-source", "rule_id": "wanted-rule", "state": "closed"},
            {"sourceId": "other-source", "ruleId": "other-rule", "state": "active"},
        ),
    ],
)
def test_filtered_events_find_retained_matches_before_limit(store, filters, nonmatching):
    store.save_event(event(0))
    for number in range(1, 1002):
        store.save_event(event(number, **nonmatching))
    # A later event in another site must never displace the requested site's match.
    store.save_event(event(1002, siteId="other-site"))

    assert [record["id"] for record in store.events(1, site_id="site", **filters)] == ["0"]
    assert store.events(1, site_id="site")[0]["id"] == "1001"


def test_event_filters_require_all_requested_values_and_preserve_order(store):
    store.save_event(event(1))
    store.save_event(event(2, state="active"))
    store.save_event(event(3))
    store.save_event(event(4, ruleId="other-rule"))
    store.save_event(event(5, sourceId="other-source"))

    matches = store.events(2, site_id="site", source_id="wanted-source", rule_id="wanted-rule", state="closed")
    assert [record["id"] for record in matches] == ["3", "1"]


def test_round_robin_history_prunes_all_sources_across_sessions():
    store = CityStore(max_history_frames=2, max_history_bytes=1_000_000)
    try:
        for number in range(64):
            store.save_history("A" if number % 2 == 0 else "B", f"session-{number // 16}", {"mediaTimeSeconds": number})

        assert store.connection.execute("SELECT source,COUNT(*) FROM history GROUP BY source").fetchall() == [("A", 2), ("B", 2)]
        assert store.nearest_history("A", 62)["mediaTimeSeconds"] == 62
        assert store.nearest_history("B", 63)["mediaTimeSeconds"] == 63
        assert store._history_bytes == store.connection.execute("SELECT SUM(bytes) FROM history").fetchone()[0]
    finally:
        store.close()


def test_history_byte_quota_stays_bounded_with_interleaved_sources():
    store = CityStore(max_history_frames=100, max_history_bytes=1000)
    try:
        for number in range(65):
            store.save_history(str(number % 3), "session", {"mediaTimeSeconds": number, "payload": "x" * 100})
            actual_bytes = store.connection.execute("SELECT COALESCE(SUM(bytes),0) FROM history").fetchone()[0]
            assert actual_bytes == store._history_bytes
            assert actual_bytes <= store.max_history_bytes
    finally:
        store.close()


def test_latest_session_lookup_uses_source_index_without_sort(store):
    store.save_history("camera", "old-session", {"mediaTimeSeconds": 100})
    store.save_history("camera", "new-session", {"mediaTimeSeconds": 1})
    store.save_history("other-camera", "unrelated-session", {"mediaTimeSeconds": 101})

    assert store.nearest_history("camera", 100)["mediaTimeSeconds"] == 1
    assert store.nearest_history("camera", 100, "old-session")["mediaTimeSeconds"] == 100
    plan = store.connection.execute(
        "EXPLAIN QUERY PLAN SELECT session FROM history WHERE source=? ORDER BY id DESC LIMIT 1",
        ("camera",),
    ).fetchall()
    assert any("history_source_id" in row[3] for row in plan)
    assert all("TEMP B-TREE" not in row[3] for row in plan)


def test_existing_store_adds_site_and_history_indexes_without_losing_data(tmp_path):
    path = str(tmp_path / "city.sqlite3")
    original = CityStore(path)
    original.save_event(event(1))
    original.save_history("camera", "session", {"mediaTimeSeconds": 1})
    original.connection.execute("DROP INDEX events_site_updated")
    original.connection.execute("DROP INDEX history_source_id")
    original.close()

    reopened = CityStore(path)
    try:
        assert reopened.events(1, site_id="site")[0]["id"] == "1"
        assert reopened.nearest_history("camera", 1)["mediaTimeSeconds"] == 1
        plan = reopened.connection.execute(
            "EXPLAIN QUERY PLAN SELECT value FROM events WHERE json_extract(value,'$.siteId')=? ORDER BY updated_at DESC LIMIT ?",
            ("site", 1),
        ).fetchall()
        assert any("events_site_updated" in row[3] for row in plan)
        assert "history_source_id" in {row[1] for row in reopened.connection.execute("PRAGMA index_list(history)")}
    finally:
        reopened.close()
