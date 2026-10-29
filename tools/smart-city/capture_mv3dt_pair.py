#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded two-camera H264 copy capture; timestamps are evidence, not sync proof.

Example: --source CAMERA_A=rtsp://host/a --source CAMERA_B=rtsp://host/b
         --seconds 30 --name mv3dt-pair-example
No source registration, decoding, inference, rendering or service changes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / '.spark/city/media'
SAFE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
NONE = (1 << 64) - 1


def sources(values):
    result = []
    for value in values:
        source_id, separator, uri = value.partition('=')
        parsed = urlsplit(uri)
        if not separator or not SAFE.fullmatch(source_id) or parsed.scheme not in {'rtsp', 'rtsps'} or not parsed.hostname:
            raise ValueError('Use safe CAMERA_ID=rtsp[s]://host/path source arguments.')
        result.append((source_id, uri))
    if len(result) != 2 or len({item[0] for item in result}) != 2 or len({item[1] for item in result}) != 2:
        raise ValueError('Exactly two distinct fixed camera IDs and endpoints are required.')
    return result


def output_directory(name, media=MEDIA):
    if not SAFE.fullmatch(name):
        raise ValueError('Capture name must be a safe single directory name.')
    media.mkdir(parents=True, exist_ok=True)
    path = media.resolve() / name
    path.mkdir()  # Never overwrite a prior capture, including failed output.
    return path


def ns(value):
    return None if value is None or int(value) == NONE else str(int(value))


def timing(buffer, caps, index, segment=None):
    reference = buffer.get_reference_timestamp_meta(None)
    size = buffer.get_size()
    if size > 16 * 1024 * 1024:
        raise ValueError('Encoded access unit exceeds the 16 MiB copy bound.')
    return {'kind': 'access-unit', 'index': index, 'receivedUnixNs': str(time.time_ns()),
            'ptsNs': ns(buffer.pts), 'dtsNs': ns(buffer.dts), 'durationNs': ns(buffer.duration),
            'bufferFlags': int(buffer.get_flags()), 'bytes': size, 'caps': caps,
            'payloadSha256': hashlib.sha256(buffer.extract_dup(0, size)).hexdigest(),
            'segment': segment, 'reference': None if reference is None else {
                'caps': reference.reference.to_string(), 'timestampNs': ns(reference.timestamp),
                'durationNs': ns(reference.duration)}}


def summarize(state, row):
    state['accessUnits'] += 1
    for key, value in [('PtsNs', row['ptsNs']), ('ReferenceNs', (row['reference'] or {}).get('timestampNs'))]:
        if value is None:
            continue
        if state.get('first' + key) is None:
            state['first' + key] = value
        previous = state.get('last' + key)
        if previous is not None and int(value) < int(previous):
            state['regressions' + key] = state.get('regressions' + key, 0) + 1
        state['last' + key] = value
    if row['reference']:
        state['referenceAccessUnits'] += 1
        value = row['reference']['caps']
        if value not in state['referenceCaps']:
            state['referenceCaps'].append(value)


def file_timestamps(path):
    """Read container packet clocks without decoding, bounded even for bad output."""
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_packets', '-show_streams', '-show_entries',
            'packet=pts,dts:stream=time_base,codec_name,width,height', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=5, check=True)
        value = json.loads(result.stdout)
        packets = value.get('packets', [])
        stream = next(iter(value.get('streams', [])), {})
        return {'status': 'read' if packets else 'no-packets', 'packetCount': len(packets),
                'stream': stream, 'firstPacket': packets[0] if packets else None,
                'lastPacket': packets[-1] if packets else None,
                'clockNote': 'Container time-base ticks, not source NTP. Compare with access-unit sidecar before replay.'}
    except (OSError, subprocess.SubprocessError, ValueError):
        runtime = ROOT / '.spark/city/export-env/bin/python'
        try:
            result = subprocess.run([str(runtime), str(Path(__file__).with_name('verify_mv3dt_pair.py')), '--inspect-file', str(path)],
                capture_output=True, text=True, timeout=5, check=True)
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            return {'status': 'unavailable', 'clockNote': 'Container packet clock could not be inspected; capture alignment remains unqualified.'}


def capture(pair, seconds, directory):
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    Gst.init(None)
    pipeline = Gst.Pipeline.new('paired-encoded-capture')
    loop = GLib.MainLoop()
    started = time.monotonic()
    receipt = {'schemaVersion': 'city.encoded-pair.v1', 'status': 'recording',
               'captureId': directory.name, 'commonHostStartUnixNs': str(time.time_ns()),
               'commonHostStartMonotonicNs': str(time.monotonic_ns()), 'requestedSeconds': seconds,
               'gstreamer': Gst.version_string(), 'transport': 'tcp', 'codec': 'h264',
               'parser': 'h264parse', 'timingProbe': 'parsed-access-unit-before-mux',
               'copyOnly': True, 'replayAlignmentQualified': False,
               'clockNote': 'Host start is provenance only. Reference caps/timestamps require validation and replay mapping; independent file zero points are not synchronized capture clocks.',
               'sources': [], 'errors': [], 'eosFinalized': False}
    handles, previous_signals, timers = [], {}, []
    stopping = False

    def write_receipt():
        (directory / 'capture.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def fail(message):
        nonlocal stopping
        message = str(message)
        for _, uri in pair:
            message = message.replace(uri, '[camera endpoint]')
        receipt['errors'].append(message)
        stop()
        return False

    def stop():
        nonlocal stopping
        if stopping:
            return False
        stopping = True
        if not pipeline.send_event(Gst.Event.new_eos()):
            receipt['errors'].append('Pipeline rejected EOS; preserved files may be incomplete.')
            loop.quit()
        else:
            timers.append(GLib.timeout_add_seconds(5, lambda: fail_finalization()))
        return False

    def fail_finalization():
        receipt['errors'].append('EOS finalization exceeded 5 seconds; preserved files may be incomplete.')
        loop.quit()
        return False

    def message(_bus, item):
        if item.type == Gst.MessageType.ERROR:
            error, _debug = item.parse_error()
            fail(f'{item.src.get_name()}: {error.message}')
        elif item.type == Gst.MessageType.EOS:
            if not stopping:
                receipt['errors'].append('Stream ended before the requested capture duration.')
            receipt['eosFinalized'] = True
            loop.quit()

    def make(factory, name):
        element = Gst.ElementFactory.make(factory, name)
        if element is None:
            raise RuntimeError(f'Required GStreamer factory unavailable: {factory}')
        pipeline.add(element)
        return element

    try:
        write_receipt()
        if Gst.ElementFactory.find('h264parse') is None:
            raise RuntimeError('h264parse is required. Use the existing CPU-only DeepStream runtime; no host ABI plugin mixing.')
        for index, (source_id, uri) in enumerate(pair):
            state = {'sourceId': source_id, 'file': f'{source_id}.mkv', 'timingFile': f'{source_id}.timing.ndjson',
                     'accessUnits': 0, 'referenceAccessUnits': 0, 'referenceCaps': [], 'segments': 0,
                     'firstPtsNs': None, 'lastPtsNs': None, 'firstReferenceNs': None, 'lastReferenceNs': None}
            receipt['sources'].append(state)
            output = (directory / state['timingFile']).open('x', buffering=65536)
            handles.append(output)
            output.write(json.dumps({'kind': 'header', 'sourceId': source_id, 'captureId': directory.name,
                                     'commonHostStartUnixNs': receipt['commonHostStartUnixNs'],
                                     'referenceEpoch': 'defined-by-reference-caps-not-host-start',
                                     'replayAlignmentQualified': False}) + '\n')
            source = make('rtspsrc', f'camera-{index}')
            for key, value in [('location', uri), ('protocols', 4), ('latency', 200), ('drop-on-latency', False),
                               ('add-reference-timestamp-meta', True), ('tcp-timeout', 5_000_000), ('teardown-timeout', 1_000_000_000)]:
                source.set_property(key, value)
            depay = make('rtph264depay', f'depay-{index}')
            depay.set_property('wait-for-keyframe', True)
            parser = make('h264parse', f'parser-{index}')
            codec = make('capsfilter', f'avc-{index}')
            codec.set_property('caps', Gst.Caps.from_string('video/x-h264,stream-format=avc,alignment=au'))
            mux = make('matroskamux', f'mux-{index}')
            mux.set_property('offset-to-zero', False)
            sink = make('filesink', f'file-{index}')
            sink.set_property('location', str(directory / state['file']))
            sink.set_property('sync', False)
            sink.set_property('async', False)
            # Parsing supplies muxer codec_data but performs no decoding/encoding.
            # Probe after parsing so the sidecar hash matches the stored packet.
            if not (depay.link(parser) and parser.link(codec) and codec.link(mux) and mux.link(sink)):
                raise RuntimeError(f'{source_id}: encoded capture elements could not link')
            def linked(_source, pad, target=depay, sid=source_id):
                caps = pad.get_current_caps() or pad.query_caps(None)
                structure = caps.get_structure(0)
                if structure.get_string('media') != 'video':
                    return
                if structure.get_string('encoding-name') != 'H264':
                    GLib.idle_add(fail, f'{sid}: source is not H264')
                elif pad.link(target.get_static_pad('sink')) != Gst.PadLinkReturn.OK:
                    GLib.idle_add(fail, f'{sid}: RTP video pad could not link')
            source.connect('pad-added', linked)
            def probe(pad, info, saved=state, stream=output):
                try:
                    if info.type & Gst.PadProbeType.EVENT_DOWNSTREAM:
                        event = info.get_event()
                        if event.type == Gst.EventType.SEGMENT:
                            segment = event.parse_segment()
                            saved['segments'] += 1
                            saved['segment'] = {key: ns(getattr(segment, key)) for key in ['start', 'stop', 'time', 'base', 'offset']}
                            saved['segment'].update(format=Gst.Format.get_name(segment.format), rate=segment.rate, appliedRate=segment.applied_rate)
                            stream.write(json.dumps({'kind': 'segment', 'index': saved['segments'], **saved['segment']}) + '\n')
                        return Gst.PadProbeReturn.OK
                    buffer = info.get_buffer()
                    caps = pad.get_current_caps()
                    row = timing(buffer, caps.to_string() if caps else None, saved['accessUnits'], saved.get('segment'))
                    row['discontinuity'] = bool(buffer.has_flags(Gst.BufferFlags.DISCONT))
                    summarize(saved, row)
                    stream.write(json.dumps(row, separators=(',', ':')) + '\n')
                    saved['lastCaps'] = row['caps']
                except Exception as exc:
                    GLib.idle_add(fail, f'{saved["sourceId"]}: timing sidecar failed: {exc}')
                    return Gst.PadProbeReturn.DROP
                return Gst.PadProbeReturn.OK
            codec.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER | Gst.PadProbeType.EVENT_DOWNSTREAM, probe)
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', message)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_signals[signum] = signal.signal(signum, lambda sig, _frame: GLib.idle_add(fail, f'Capture interrupted by signal {sig}.'))
        timers.append(GLib.timeout_add_seconds(seconds, stop))
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Pipeline could not enter PLAYING.')
        loop.run()
    except Exception as exc:
        receipt['errors'].append(str(exc))
    finally:
        pipeline.set_state(Gst.State.NULL)
        for timer in timers:
            if GLib.MainContext.default().find_source_by_id(timer):
                GLib.source_remove(timer)
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)
        for handle in handles:
            handle.close()
        for state in receipt['sources']:
            path = directory / state['file']
            state['fileBytes'] = path.stat().st_size if path.is_file() else 0
            sidecar = directory / state['timingFile']
            state['timingBytes'] = sidecar.stat().st_size if sidecar.is_file() else 0
            state['referenceMetadataComplete'] = state['accessUnits'] > 0 and state['referenceAccessUnits'] == state['accessUnits']
            state['muxedFileTiming'] = file_timestamps(path) if state['fileBytes'] else {'status': 'no-file'}
            if not state['fileBytes'] or not state['accessUnits']:
                receipt['errors'].append(f'{state["sourceId"]}: no complete encoded access units/file.')
        receipt['elapsedSeconds'] = round(time.monotonic() - started, 3)
        receipt['endedUnixNs'] = str(time.time_ns())
        receipt['status'] = 'complete' if receipt['eosFinalized'] and len(receipt['sources']) == 2 and not receipt['errors'] else 'failed'
        write_receipt()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', required=True, metavar='CAMERA_ID=RTSP_URL')
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--name', default=f'mv3dt-pair-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}-{uuid.uuid4().hex[:6]}')
    args = parser.parse_args()
    if not 30 <= args.seconds <= 180:
        parser.error('--seconds must be between 30 and 180.')
    try:
        pair = sources(args.source)
        directory = output_directory(args.name)
    except ValueError as exc:
        parser.error(str(exc))
    receipt = capture(pair, args.seconds, directory)
    print(json.dumps({'status': receipt['status'], 'receipt': str(directory / 'capture.json'), 'replayAlignmentQualified': False}))
    return 0 if receipt['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
