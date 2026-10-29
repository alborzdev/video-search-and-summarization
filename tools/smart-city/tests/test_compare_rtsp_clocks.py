# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'compare_rtsp_clocks.py'
SPEC = importlib.util.spec_from_file_location('compare_rtsp_clocks', PATH)
clock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clock)


def avcc(*nals):
    return b''.join(len(nal).to_bytes(4, 'big') + nal for nal in nals)


def sei(native):
    payload = clock.NATIVE_UUID + json.dumps(native).encode()
    size = b'\xff' * (len(payload) // 255) + bytes([len(payload) % 255])
    return b'\x06\x05' + size + payload + b'\x80'


class CompareClocksTests(unittest.TestCase):
    def test_ignores_added_parameter_sets_and_other_sei_for_vcl_identity(self):
        base = clock.au_identity(avcc(b'\x65abc'))
        other = clock.au_identity(avcc(b'\x67params', b'\x68pps', b'\x06\x01\x01X\x80', b'\x65abc'))
        self.assertEqual(base['vclSha256'], other['vclSha256'])
        self.assertNotEqual(base['vclSha256'], clock.au_identity(avcc(b'\x65abd'))['vclSha256'])

    def test_native_sei_extended_length(self):
        native = {'timestamp': 1792991111000000000, 'frame_num': 12, 'publish_sim_time_ns': 123,
                  'timestamp_basis': 'wall-capture', 'padding': 'A' * 300}
        result = clock.au_identity(avcc(sei(native), b'\x65abc'))
        self.assertEqual(result['nativeSei'][0]['timestamp'], native['timestamp'])
        self.assertEqual(clock.native_key(result), (str(native['timestamp']), '12'))

    def test_emulation_prevention_only_in_defined_context(self):
        payloads = clock.sei_payloads(b'\x06\x05\x05\x00\x00\x03\x01\x03\x02\x80')
        self.assertEqual(payloads, [(5, b'\x00\x00\x01\x03\x02')])

    def test_truncated_input_rejected(self):
        for payload in [b'\x00\x00', b'\x00\x00\x00\x05x', b'\x00\x00\x00\x00']:
            with self.assertRaises(ValueError):
                clock.avcc_nals(payload)
        with self.assertRaises(ValueError):
            clock.sei_payloads(b'\x06\x05\x20abc')

    def test_reference_caps_are_explicit(self):
        self.assertEqual(clock.reference_unix({'reference': {'caps': 'timestamp/x-ntp', 'timestampNs': str(clock.NTP_UNIX_NS + 20)}}), 20)
        with self.assertRaises(ValueError):
            clock.reference_unix({'reference': {'caps': 'unknown', 'timestampNs': '20'}})

    def test_match_added_sei_and_keep_receive_clock_difference(self):
        native = {'timestamp': 100000000, 'frame_num': 4, 'publish_sim_time_ns': 5, 'timestamp_basis': 'wall-capture'}
        def row(index, whole, received, ref):
            return {'index': index, 'payloadSha256': whole, 'receivedUnixNs': str(received),
                    'referenceUnixNs': ref, **clock.au_identity(avcc(sei(native), b'\x65abc'))}
        a, b = row(0, 'original', 300000000, 100000000), row(0, 'modified', 410000000, 550000000)
        result = clock.compare({'camera': [a]}, {'camera': [b]})['camera']
        self.assertEqual(result['matchMethods'], {'native-SEI-plus-VCL-sha256': 1})
        self.assertEqual(result['proxyMinusOriginReceiveMs']['p50'], 110)
        self.assertEqual(result['proxyMinusOriginReferenceMs']['p50'], 450)

    def test_ambiguous_repeat_is_not_invented_match(self):
        row = {'index': 0, 'payloadSha256': 'repeated', 'vclSha256': 'repeated', 'nativeSei': [], 'referenceUnixNs': None}
        result = clock.compare({'camera': [row]}, {'camera': [row, {**row, 'index': 1}]})['camera']
        self.assertEqual(result['matchedSameVclAccessUnits'], 0)
        result = clock.compare({'camera': [row, {**row, 'index': 1}]}, {'camera': [row]})['camera']
        self.assertEqual(result['matchedSameVclAccessUnits'], 0)

    def test_common_render_frame_requires_both_exact_fields(self):
        row = {'nativeSei': [{'frame_num': 3, 'publish_sim_time_ns': 7, 'timestamp': 100000000}],
               'receivedUnixNs': '200000000', 'referenceUnixNs': 100000000}
        peer = {**row, 'nativeSei': [{**row['nativeSei'][0], 'timestamp': 101000000}]}
        result = clock.compare_same_render_frame({'a': [row], 'b': [peer]})
        self.assertEqual(result['matchedRenderTicks'], 1)
        self.assertEqual(result['secondMinusFirstNativeHandoffMs']['p50'], 1)
        peer = {**peer, 'nativeSei': [{**peer['nativeSei'][0], 'publish_sim_time_ns': 8}]}
        self.assertEqual(clock.compare_same_render_frame({'a': [row], 'b': [peer]})['matchedRenderTicks'], 0)


if __name__ == '__main__':
    unittest.main()
