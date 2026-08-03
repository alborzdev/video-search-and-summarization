# Agent evaluation contract metadata successor

This immutable successor corrects the `evaluation.agent.report` planning
contract without claiming runtime qualification. The old `judge_defaults`
claim incorrectly treated `2048` as a `ReportEvaluatorConfig` default. The
corrected `judge_profile_config` instead binds the exact
`llms.eval_llm_judge` profile selected by
`report_evaluator.metric_configs.llm_judge` in the VSS dev-base configuration
at upstream commit `7732edf8`, where `max_tokens` is `4096` and `temperature`
is `0.0`.

The compiler changes exactly one capability and one oracle in both the 289-row
root and selected 500-row plane, updates only the matching Wave 2 enrichment,
and preserves the 211-row candidate suffix as exact JSON values. It does not use
or create an Agent-evaluation runtime package and does not add evidence.

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-agent-evaluation-contract-successor/compiler.py
```

Use `--write` only to regenerate reviewed package artifacts. Use
`--install-canonical` separately for fail-closed, atomic publication.
