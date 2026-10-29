# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
from contextlib import suppress
from unittest.mock import Mock

import pytest
from starlette.requests import Request
from starlette.datastructures import Headers

from apps.city.tests.test_preview import BASE, headers, observation, setup  # noqa: F401
from apps.city.preview import FrameIdentity, PreviewError
from apps.city.video import MAX_SESSIONS, VIDEO_HISTORY


def publish(setup, sequence=0, rtp=1234, **kwargs):
    engine, _, app, client = setup
    sample = observation(sequence, ns=BASE + sequence * 100_000_000, **kwargs)
    engine.ingest(sample)
    response = client.post('/api/v1/city/video/frame', headers={**headers(sample), 'Content-Type': 'application/json'}, json={
        'schemaVersion': 'city.video-rtp.v1', 'rtpTimestamp': rtp, 'clockRate': 90000, 'encoder': 'nvenc-h264'})
    assert response.status_code == 201, response.text
    session = engine.sources[sample.sourceId]['sessionId']
    return sample, session, app.state.video.read(sample.sourceId, session)[-1]


def test_video_carries_exact_identity_with_immutable_cached_geometry(setup):
    first, session, row = publish(setup)
    manifest, frame = json.loads(row[2]), json.loads(row[3])
    assert frame['transport']['rtpTimestamp'] == 1234
    assert frame['sequence'] == first.sequence and frame['sourceTimeNs'] == first.sourceTimeNs
    assert frame['sessionId'] == session and frame['sourceSessionId'] == first.sourceSessionId
    assert frame['provenance']['correlation'] == 'source-session-sequence-time-rtp'
    assert 'rules' not in frame['snapshot'] and manifest['snapshot']['rules'][0]['id'] == 'zone'
    assert 'width' not in frame['snapshot']['sources'][0] and manifest['snapshot']['sources'][0]['width'] == 100
    assert 'inputUri' not in row[2].decode() and 'secret' not in row[2].decode()
    assert 'private' not in row[3].decode()
    _, _, next_row = publish(setup, 1, 5678, x=50)
    assert next_row[1] == row[1]  # Static geometry is unchanged by motion.
    assert json.loads(next_row[3])['snapshot']['tracks'][0]['bboxPx'][0] == 45
    assert json.loads(row[3])['snapshot']['tracks'][0]['bboxPx'][0] == 25


def test_metadata_pending_bounds_session_expiry_and_no_jpeg_storage(setup):
    engine, clock, app, client = setup
    sample, session, _ = publish(setup)
    for sequence in range(1, VIDEO_HISTORY + 5):
        publish(setup, sequence, 1234 + sequence * 9000)
    assert len(app.state.video.read('cam', session, 1)) == VIDEO_HISTORY
    assert app.state.video.health()['retainedBytes'] > 0
    with pytest.raises(PreviewError):
        app.state.video.read('cam', 'obsolete')
    clock.value += 2.01
    with pytest.raises(PreviewError):
        app.state.video.read('cam', session)
    assert app.state.video.health()['retainedBytes'] == 0
    assert client.post('/api/v1/city/video/frame', headers={**headers(sample), 'Content-Type': 'application/json'}, json={
        'schemaVersion': 'city.video-rtp.v1', 'rtpTimestamp': -1, 'clockRate': 90000, 'encoder': 'nvenc-h264'}).status_code == 422


def test_session_or_rule_change_retires_all_old_frame_metadata(setup):
    engine, _, app, _ = setup
    _, session, _ = publish(setup)
    engine.ingest(observation(0, session='new-session', ns=BASE + 1))
    with pytest.raises(PreviewError):
        app.state.video.read('cam', session)


def test_sse_sends_manifest_then_exact_frame_through_the_actual_route(setup):
    _, _, app, _ = setup
    _, session, row = publish(setup)
    endpoint = next(route.endpoint for route in app.routes if route.path == '/api/v1/city/video/metadata/{source_id}')

    async def read():
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []}, receive)
        response = await endpoint('cam', request, session)
        iterator = response.body_iterator
        parts = [await anext(iterator) for _ in range(3)]
        await iterator.aclose()
        return parts
    parts = asyncio.run(read())
    assert parts[0] == 'retry: 1000\n\n'
    assert parts[1] == b'event: manifest\ndata: ' + row[2] + b'\n\n'
    assert parts[2] == b'event: frame\ndata: ' + row[3] + b'\n\n'


def test_whep_is_session_bound_capacity_limited_and_explicitly_released(setup):
    _, _, app, client = setup
    sample, session, _ = publish(setup)
    broker = app.state.video_sessions
    response = Mock()
    response.status = 201
    response.headers = {'Location': '/city/cam/' + sample.sourceSessionId + '/whep/relay-session'}
    response.read.return_value = b'v=0\r\n'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    broker.http.open = Mock(return_value=response)
    tokens = []
    for _ in range(MAX_SESSIONS):
        result = client.post('/api/v1/city/video/whep/cam?sessionId=' + session, content=b'v=0\r\n', headers={'Content-Type': 'application/sdp'})
        assert result.status_code == 201, result.text
        tokens.append(result.headers['x-city-video-session'])
    assert client.post('/api/v1/city/video/whep/cam?sessionId=' + session, content=b'v=0\r\n', headers={'Content-Type': 'application/sdp'}).status_code == 503
    assert client.put('/api/v1/city/video/sessions/cam/' + tokens[0]).status_code == 204
    assert client.delete('/api/v1/city/video/sessions/other/' + tokens[0]).status_code == 404
    assert client.delete('/api/v1/city/video/sessions/cam/' + tokens[0]).status_code == 204
    assert len(broker.sessions) == MAX_SESSIONS - 1
    assert broker.http.open.call_args.args[0].method == 'DELETE'


def test_whep_does_not_follow_untrusted_relay_locations(setup):
    _, _, app, client = setup
    _, session, _ = publish(setup)
    response = Mock(status=201, headers={'Location': 'http://untrusted.invalid/private'})
    response.read.return_value = b'v=0\r\n'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    app.state.video_sessions.http.open = Mock(return_value=response)
    result = client.post('/api/v1/city/video/whep/cam?sessionId=' + session, content=b'v=0\r\n', headers={'Content-Type': 'application/sdp'})
    assert result.status_code == 502
    assert app.state.video_sessions.sessions == {}


def test_shared_stream_multiplexes_health_manifest_and_exact_frames_and_resets_expired_source(setup):
    _, clock, app, _ = setup
    _, _, row = publish(setup)
    endpoint = next(route.endpoint for route in app.routes if route.path == '/api/v1/city/stream')

    class Viewer:
        async def is_disconnected(self):
            return False

    async def read():
        response = await endpoint(Viewer(), video=True)
        iterator = response.body_iterator
        manifest = await anext(iterator)
        frame = await anext(iterator)
        health = await anext(iterator)
        assert 'event: snapshot\n' in health
        assert manifest == b'event: video-manifest:cam\ndata: ' + row[2] + b'\n\n'
        assert frame == b'event: video-frame:cam\ndata: ' + row[3] + b'\n\n'
        clock.value += 2.01
        app.state.video.changed.set()
        # A reset must invalidate the camera overlay without a new SSE socket.
        reset = await anext(iterator)
        if 'snapshot' in str(reset):
            reset = await anext(iterator)
        assert reset == 'event: video-reset:cam\ndata: {}\n\n'
        await iterator.aclose()
    asyncio.run(read())


def test_slow_health_serialization_cannot_delay_new_video_metadata(setup, monkeypatch):
    from threading import Event
    engine, _, app, _ = setup
    publish(setup)
    entered, release = Event(), Event()
    original = engine.snapshot

    def slow_snapshot():
        entered.set()
        assert release.wait(2)
        return original()

    monkeypatch.setattr(engine, 'snapshot', slow_snapshot)
    endpoint = next(route.endpoint for route in app.routes if route.path == '/api/v1/city/stream')
    class Viewer:
        async def is_disconnected(self): return False

    async def run():
        response = await endpoint(Viewer(), video=True)
        iterator = response.body_iterator
        await anext(iterator)  # manifest
        await anext(iterator)  # first frame
        pending = asyncio.create_task(anext(iterator))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            sample = observation(1, ns=BASE + 100_000_000)
            engine.ingest(sample)
            app.state.video.accept_rtp(FrameIdentity.headers(Headers(headers(sample))), {
                'schemaVersion': 'city.video-rtp.v1', 'rtpTimestamp': 5678,
                'clockRate': 90000, 'encoder': 'nvenc-h264'})
            previous, app.state.video.changed = app.state.video.changed, asyncio.Event()
            previous.set()
            frame = await asyncio.wait_for(pending, .5)
            assert frame.startswith(b'event: video-frame:cam\n')
            assert b'"rtpTimestamp":5678' in frame
            assert not release.is_set()  # It arrived while health was still blocked.
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
            await iterator.aclose()
    asyncio.run(run())


def test_retired_inflight_viewer_releases_validated_relay_session(setup):
    _, _, app, _ = setup
    sample, session, _ = publish(setup)
    broker = app.state.video_sessions
    response = Mock(status=201, headers={'Location': '/city/cam/' + sample.sourceSessionId + '/whep/relay-session'})
    response.read.return_value = b'v=0\r\n'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)

    def cancelled(request, **kwargs):
        if request.get_method() == 'POST':
            broker.sessions.clear()  # Reaper/shutdown during the blocking SDP request.
        return response
    broker.http.open = Mock(side_effect=cancelled)
    with pytest.raises(PreviewError, match='video-viewer-retired-during-negotiation'):
        broker.create('cam', session, b'v=0\r\n')
    assert broker.http.open.call_args.args[0].method == 'DELETE'
    assert broker.http.open.call_args.args[0].full_url.endswith('/whep/relay-session')


def test_status_snapshot_serialization_is_shared_across_viewers_and_invalidated_by_configuration(setup, monkeypatch):
    engine, _, app, _ = setup
    original = engine.snapshot
    calls = []
    def counted():
        calls.append(True)
        return original()
    monkeypatch.setattr(engine,'snapshot',counted)
    endpoint = next(route.endpoint for route in app.routes if route.path == '/api/v1/city/stream')
    class Viewer:
        async def is_disconnected(self): return False
    async def first():
        response = await endpoint(Viewer())
        value = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return value
    async def run():
        first_value = await first()
        assert await first() == first_value
        assert len(calls) == 1
        engine.site.revision += 1
        assert await first() != first_value
        assert len(calls) == 2
    asyncio.run(run())
