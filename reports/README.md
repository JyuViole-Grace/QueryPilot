# Evaluation reports

Generated locally by `scripts/evaluate_sql.py`.

- `ru_edition/` - every run made on the earlier **Russian-language edition** of
  the sample data: the first clean `heldout_v3` run, the 7B/14B comparison,
  the join-hint ablation, resampling, the `heldout_v4` run and the runs made
  with the removed semantic critic (`archive/`, `legacy/`). They are valid
  findings about that edition but cannot be compared or re-scored against
  the current datasets: the data changed, so the dataset fingerprints differ.
- `en_*.json` - runs on the current English edition (see the table in
  `docs/EVALUATION.md`, "English edition results"): `en_v4_qwen7b.json`,
  `en_v3_hints_on_a.json`, `en_v3_hints_on_b.json`, `en_v3_hints_off_a.json`,
  `en_v3_hints_off_b.json`.
- `scratch/` - per-question checkpoints of interrupted runs (git-ignored).

Compare reports only if model, dataset fingerprint, prompt fingerprint,
retry limit and repair configuration match.
