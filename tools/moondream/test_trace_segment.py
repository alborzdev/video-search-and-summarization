"""CPU-only checks of the real Photon SVG decoder and observational hooks."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from tokenizers import Tokenizer

from kestrel.models.moondream.config import TokenizerConfig
from kestrel.models.moondream.skills.segment import SegmentSkill
from kestrel.runtime.tokens import CoordToken, SizeToken, TextToken
from kestrel.scheduler.scheduler import GenerationScheduler
from kestrel.scheduler.pipeline import DecodeLaunch, LaunchHandle
from kestrel.scheduler.types import GenerationRequest
from kestrel.skills.base import DecodeStep
from trace_segment import install_trace


class SegmentTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        pointer = root / ".spark/moondream-photon/tokenizer-path.txt"
        if not pointer.exists():
            raise unittest.SkipTest("Requires the existing local Starmie tokenizer; never downloads")
        tokenizer = Tokenizer.from_file(pointer.read_text().strip())
        cfg = TokenizerConfig()
        cls.runtime = SimpleNamespace(
            tokenizer=tokenizer, prompt_template=cfg,
            config=SimpleNamespace(tokenizer=cfg), eos_token_ids=(0,),
            seg_refiner=None, model_name="cpu-decoder-fixture")

    def make_request(self, request_id=1):
        skill = SegmentSkill()
        built = skill.build_request(b"fixture-image-not-decoded", {"object": "square"}, None)
        tokens = skill.build_prompt_tokens(self.runtime, built.request_context)
        request = GenerationRequest(
            request_id=request_id, prompt="square", prompt_tokens=tokens,
            max_new_tokens=built.max_new_tokens, skill=skill,
            request_context=built.request_context)
        state = skill.create_state(self.runtime, request, built.request_context)
        return request, state

    def consume(self, state, tokens):
        for position, token in enumerate(tokens):
            state.consume_step(self.runtime, DecodeStep(token, position))

    def test_real_finalize_valid_svg_and_empty_model_eos(self):
        """A valid path survives the actual skill; an EOS-only path stays empty."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            handle = install_trace(path)
            try:
                _, state = self.make_request()
                svg_ids = self.runtime.tokenizer.encode("M 0 0 L 960 0 L 960 960 Z").ids
                self.consume(state, [CoordToken(.5), CoordToken(.5), SizeToken(1., 1.),
                                     *[TextToken(t) for t in svg_ids], TextToken(0)])
                result = state.finalize(self.runtime, reason="stop")
                segment = result.output["segments"][0]
                self.assertEqual(segment["svg_path"], "M 0 0 L 1 0 L 1 1 Z")
                self.assertNotIn("parse_error", segment)
                self.assertEqual(segment["bbox"],
                                 {"x_min": 0., "x_max": 1., "y_min": 0., "y_max": 1.})
                _, empty = self.make_request(2)
                self.consume(empty, [CoordToken(.5), CoordToken(.5), SizeToken(1., 1.), TextToken(0)])
                self.assertEqual(empty.finalize(self.runtime, reason="stop").output["segments"][0]["svg_path"], "")
            finally:
                handle.close()
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertNotIn("trace_error", [event["event"] for event in events])
            self.assertEqual(len([event for event in events if event["event"] == "finalize"]), 2)
            self.assertTrue(any(event["event"] == "prompt" and event["text_token_ids"][-1] == 3
                                for event in events))

    def test_sampler_observation_preserves_logits_output_and_stop_reason(self):
        request, state = self.make_request()
        self.consume(state, [CoordToken(.5), CoordToken(.5), SizeToken(1., 1.)])
        seq = SimpleNamespace(request=request, skill_state=state, last_token=SizeToken(1., 1.),
                              total_length=40, state=SimpleNamespace(max_length=4096))
        scheduler = object.__new__(GenerationScheduler)
        scheduler.runtime = self.runtime
        scheduler._eos_token_ids = frozenset({0})
        scheduler._hooks = SimpleNamespace(process_logits=None, sample_greedy=None)
        scheduler._build_mask_spec = lambda sequences: ([None], [None], False, [], True, False)
        reasons = []
        scheduler._finalize_sequence = lambda sequence, reason: reasons.append(reason)
        logits = torch.full((1, 51200), -20., dtype=torch.float32)
        logits[0, 0], logits[0, 65] = 20., 5.
        original_logits = logits.clone()
        baseline = scheduler._sample_batch(logits, [seq], torch.empty(1, dtype=torch.long))[0].clone()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            original_method = GenerationScheduler._sample_batch
            handle = install_trace(path)
            try:
                output = torch.empty(1, dtype=torch.long)
                result = scheduler._sample_batch(logits, [seq], output)
                torch.testing.assert_close(result[0], baseline, rtol=0, atol=0)
                torch.testing.assert_close(logits, original_logits, rtol=0, atol=0)
                self.assertEqual(result[0].data_ptr(), output.data_ptr())
                state.consume_step(self.runtime, DecodeStep(TextToken(0), 3))
                seq.last_token = TextToken(0)
                self.assertTrue(scheduler._mark_finished_if_needed(seq))
                self.assertEqual(reasons, ["stop"])
            finally:
                handle.close()
            self.assertIs(GenerationScheduler._sample_batch, original_method)
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertNotIn("trace_error", [event["event"] for event in events])
            sample = next(event for event in events if event["event"] == "sample")
            self.assertEqual(sample["sampled_id"], 0)
            self.assertEqual(sample["top_token_ids"][:2], [0, 65])
            stop = next(event for event in events if event["event"] == "stop_check")
            self.assertTrue(stop["model_eos_hit"])
            self.assertFalse(stop["max_new_hit"] or stop["max_context_hit"] or stop["skill_stop_hit"])

    def test_finalize_sampling_captures_fused_tail_without_duplicate_generic_event(self):
        """Exercise the actual scheduler fast-path branch with a CPU kernel stand-in."""
        request, state = self.make_request()
        self.consume(state, [CoordToken(.5), CoordToken(.5), SizeToken(1., 1.)])
        seq = SimpleNamespace(request=request, skill_state=state, packed_pending_ready=False)
        scheduler = object.__new__(GenerationScheduler)
        scheduler.runtime = self.runtime
        scheduler._eos_token_ids = frozenset({0})
        scheduler._hooks = SimpleNamespace(process_logits=None, sample_greedy=None, post_sample=None)
        scheduler._pending_token_ids = torch.zeros(1, dtype=torch.long)
        scheduler._greedy_tail_workspaces = (object(),)
        slot = SimpleNamespace(
            logits=torch.full((1, 51200), -20.), sampled_ids=torch.empty(1, dtype=torch.long),
            sampled_logprobs=torch.empty(1),
            meta=SimpleNamespace(batch_idx=SimpleNamespace(gpu=torch.zeros(1, dtype=torch.long))),
            step_done_event=SimpleNamespace(record=lambda: None),
            commit_done_event=SimpleNamespace(record=lambda: None),
            render=SimpleNamespace(transfer=lambda ids, **kwargs: ids.clone()))
        slot.logits[0, 0] = 20.
        original_logits = slot.logits.clone()
        self.runtime.decode_slots = [slot]
        launch = LaunchHandle(kind="decode", sequences=[seq], payload=DecodeLaunch(slot_id=0))
        plan = SimpleNamespace(all_greedy=True, any_return_logprobs=False,
                               disallow=None, event=None, suppress_rows=[])

        def cpu_greedy(logits, batch_idx, pending, workspace, *, out, **kwargs):
            torch.argmax(logits, dim=-1, out=out)
            pending.index_copy_(0, batch_idx, out)
            return out

        with tempfile.TemporaryDirectory() as directory:
            for fused in (True, False):
                with self.subTest(fused=fused):
                    scheduler._greedy_tail_hooks_eligible = fused
                    path = Path(directory) / f"trace-{fused}.jsonl"
                    trace = install_trace(path)
                    try:
                        with patch("kestrel.scheduler.scheduler.greedy_tail_from_logits",
                                   side_effect=cpu_greedy) as kernel:
                            pending = scheduler._finalize_sampling_on_stream(launch, plan)
                            self.assertEqual(kernel.call_count, int(fused))
                            self.assertEqual(pending.kind, "decode")
                            self.assertEqual(pending.transfer.tolist(), [0])
                            torch.testing.assert_close(slot.logits, original_logits, rtol=0, atol=0)
                    finally:
                        trace.close()
                    events = [json.loads(line) for line in path.read_text().splitlines()]
                    self.assertNotIn("trace_error", [event["event"] for event in events])
                    samples = [event for event in events if event["event"] == "sample"]
                    self.assertEqual(len(samples), 1)
                    self.assertEqual(samples[0]["sampled_id"], 0)
                    self.assertEqual(samples[0]["sampler_path"],
                                     "fused_greedy_tail" if fused else "generic")


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()
