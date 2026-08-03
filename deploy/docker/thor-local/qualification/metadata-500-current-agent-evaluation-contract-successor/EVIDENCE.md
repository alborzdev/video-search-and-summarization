# Repository authority

- Upstream commit: `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`
- Dev-base config: `deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml`
- Config raw SHA-256: `e89664e421bac7b8869b9dfa1e4149930e11b935bf6dc01351392a6557bb4c79`
- Report evaluator selection: `eval.evaluators.report_evaluator.metric_configs.llm_judge.llm_name: eval_llm_judge`
- Selected profile: `llms.eval_llm_judge`
- Profile values: `max_tokens: 4096`, `temperature: 0.0`
- Report evaluator source: `services/agent/src/vss_agents/evaluators/report_evaluator/evaluate.py`
- Evaluator raw SHA-256: `e36fccd2f36e9ea0eceacc49c623eb868b41c68215eac9293e2d6ac15fb4d684`

The exact `ReportEvaluatorConfig` class section contains no `max_tokens`
field. Therefore these values are repository profile configuration, not
evaluator-class defaults. No runtime execution or Warehouse data is involved.
