# Changelog

## [1.0.0] - 2026-11-05

First public release.

### Features
- Local-first Text-to-SQL agent for SQLite (Ollama, default `qwen2.5:7b`):
  schema and value grounding, join-condition grounding, bounded
  self-correction, FastAPI service and a small browser UI.
- Guarded execution: read-only connection, SQLite authorizer allow-list,
  deny-lists for `sqlite_*` tables and memory-bomb functions, timeout, row and
  string limits.
- Schema-derived join-key guard (`scripts/join_check.py`).
- Evaluation tooling: strict / EX / lenient / relaxed metrics, confidence
  intervals, dataset and prompt fingerprints, re-scoring of saved reports,
  paired comparison of runs.
- Datasets: golden (development), `heldout_v3` (development), `heldout_v4`
  (100 mechanically validated questions, meant to be run once).
- HTTP API status codes, model allow-list, Docker image (non-root,
  healthcheck), CI on Python 3.11 and 3.12.

### Sample data
- English-language sample data: customer names, cities, categories and supplier
  countries were translated through `seed_data.py` (same random draws, so all
  numbers, keys and dates are unchanged). The question sets were migrated with
  `scripts/rebase_dataset.py`: of 190 questions, 175 are identical after
  translation and 15 differ only in row order. `tests/test_sample_data.py`
  checks that a fresh seed reproduces the shipped database and that every
  dataset records its fingerprint.

### Interface
- New browser UI: result table (numeric alignment, NULL handling, sticky
  header), syntax-highlighted SQL with a copy button, example questions,
  loading state, Ctrl+Enter, readable error messages. Results are rendered as
  text only; the page uses no external resources. Logic tested in Node
  (`tests/ui_logic.js`, run by `tests/test_ui.py`).

### Findings (see `docs/EVALUATION.md`)
- `heldout_v4`: 83% Execution Match (95% CI 74-89%) on the English data; an
  earlier clean run on the Russian-language edition gave 86% (same questions).
- `heldout_v3` (development): 57% with join-condition grounding, 53% without
  (English data); 60-63% and 50-53% on the Russian edition. The grounding gain
  is small and not robust (+3 and +1 EX of 30).
- A 14B model, an LLM critic and resampling of repeated answers gave no
  measurable gain.

### Removed
- The LLM semantic critic and its `--critic-observe` mode, after it missed
  every wrong answer it reviewed. Reports made with it are kept as history and
  can still be re-scored.

### Known limitations
- Scores come from one synthetic database and small samples; `heldout_v4`
  was written by an AI assistant after the development failures were known.
- The 86% on the Russian-language edition was measured with the critic in the
  loop; the 83% on the English edition was measured after its removal.
  `heldout_v3` gave EX 18/30 in two runs both before and after the removal.
- The HTTP API has no authentication and is meant for localhost use.
