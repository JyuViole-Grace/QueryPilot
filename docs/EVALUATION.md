# QueryPilot evaluation

Full evaluation notes: datasets, benchmark status, failure analyses, the
ablation/resampling experiments with their pre-registered decision rules, and
how to reproduce every run. The summary lives in the [README](../README.md#results).

## Data editions

The sample database exists in two editions that share every number, key and
date; only four text columns differ (customer name, city, category name,
supplier country).

| Edition | Example values | Status |
| ------- | -------------- | ------ |
| Russian-language | `Львов`, `Ноутбуки`, `Польша` | Used for all development experiments in this document; reports in `reports/ru_edition/` |
| English (current) | `Lviv`, `Laptops`, `Poland` | Current database; all datasets migrated |

The translation was done through the seed script (`scripts/seed_data.py`):
the lists have the same lengths, so the random draws are unchanged. This was
verified, not assumed: a fresh seed reproduces the shipped database table by
table (`tests/test_sample_data.py`), and comparing the old and new databases
cell by cell shows differences only in those four columns, with a one-to-one
mapping of values and no Cyrillic left.

The question sets were migrated with `scripts/rebase_dataset.py` (translate the
literals, re-execute every reference query on the new database, regenerate the
expected results). Across all 190 questions: **175 are identical after
translation, 15 differ only in row order** (queries that sort by, or return in
the order of, a translated text column) and none differ in content. The
mechanical validations of `heldout_v4` (unique sort keys, discriminating wrong
answers, no unrequested columns) were re-run on the English edition and pass.

**Consequence.** Every result below was measured on the Russian-language
edition. The dataset fingerprints changed, so `--compare` and `--rescore`
refuse to mix reports across editions, and the old numbers are not directly
comparable with new runs. They remain valid as findings about that edition.
Results on the English edition are in the next section.

### English edition results

Same protocol as before (`qwen2.5:7b`, `--quality-repair --no-deterministic-repair`,
join hints on unless stated). Because `heldout_v4` was already run once on the
Russian edition, the English run of `heldout_v4` is a **re-measurement** with
the same questions, not a second clean run. Run on 5 Nov 2026 by the project
owner.

| Run | EX first | EX final | relaxed final | executed | Report |
| --- | -------- | -------- | ------------- | -------- | ------ |
| `heldout_v4`, hints on | 83/100 | **83/100** (74-89%) | 86/100 | 97/100 | `reports/en_v4_qwen7b.json` |
| `heldout_v3`, hints on, a | 17/30 | 17/30 (39-73%) | 22/30 | 29/30 | `reports/en_v3_hints_on_a.json` |
| `heldout_v3`, hints on, b | 17/30 | 17/30 | 22/30 | 29/30 | `reports/en_v3_hints_on_b.json` |
| `heldout_v3`, hints off, a | 15/30 | 16/30 (36-70%) | 23/30 | 29/30 | `reports/en_v3_hints_off_a.json` |
| `heldout_v3`, hints off, b | 15/30 | 16/30 | 23/30 | 29/30 | `reports/en_v3_hints_off_b.json` |

The two runs of each `heldout_v3` configuration are identical question by
question, so each pair is one sample, not two (the same happened with the
resampling pair on the Russian edition; the hints-on pair there did differ).

**`heldout_v4`, English vs Russian edition (same model, same questions).**
EX 83% vs 86%, relaxed 86% vs 88%, executed 97% vs 98%: well inside the
confidence intervals (74-89% vs 78-91%). Of the 14 questions that failed on the
Russian edition, 13 fail again; v4_050 now passes; four questions fail that
passed before (v4_044, 054, 061, 093). v4_054 and v4_061 are the two that the
repair stage had fixed after an execution error: this time the repair
produced a wrong answer. The model repeated its previous SQL after feedback
on 3 questions (1 before), and self-correction added nothing (83 to 83; 84 to
86 before). The failure families from the audit above persist.

**Join-hint ablation, decision rule applied to the English data.**

| Edition | EX final with hints | without | difference |
| ------- | ------------------- | ------- | ---------- |
| Russian | 18, 19 (mean 18.5) | 15, 16 (mean 15.5) | **+3.0** (rule met) |
| English | 17, 17 (mean 17.0) | 16, 16 (mean 16.0) | **+1.0** (rule not met) |

On the English data the pre-registered rule (at least +3 and more than the
noise) is not met: first-attempt EX differs by +2, final EX by +1, relaxed by
-1. Per question, the hints fix v3_25 and v3_28 (both are wrong-key joins) in
both editions and break v3_02 in this one; the other differences of the
Russian edition (v3_21, v3_17) did not repeat. So the supported statement is
narrow: **the hints help a few wrong-key join questions; an overall gain is
not demonstrated.**

The rule then says to prefer the simpler setting (hints off). The shipped
default stays **on** as a documented deviation: the published `heldout_v4`
figure was measured with the hints on, re-running it with them off would no
longer be a clean run, the line costs nothing, and the targeted effect was seen
twice. `QUERYPILOT_JOIN_HINTS=0` switches it off.

## The semantic critic: evaluated and removed (5 Nov 2026)

`scripts/semantic_critic.py` asked the same 7B model to judge whether a
query's result answered the question, and (in `--quality-repair`) fed an
`invalid` verdict back into the repair loop. The evidence collected on
`heldout_v3` and `heldout_v4` (below, in the failure audits) was:

-   it marked every wrong answer it reviewed as `valid` (6 of 6 on the first
    v3 run, 29 of 29 verdicts on the 14B run, 12 of 12 executed wrong answers
    on `heldout_v4`);
-   its only `invalid` verdicts on `heldout_v4` (3 events) were on one answer
    that was already correct and stayed correct, costing extra model calls;
-   it roughly doubled the number of model calls per question.

It was therefore removed together with the `--critic-observe` mode. Reports
made while it existed are kept in `reports/ru_edition/` as
history; re-scoring them still works (their critic fields are ignored).

**Consequence for the numbers in this document.** Every result below was
measured with the critic present in the quality loop. Its only observed
influence was the three wasted calls on v4_049, so the removal was expected
to be neutral. This was checked on the development set rather than on
`heldout_v4` (which is meant to be run once), with a criterion fixed in
advance: EX of 17-20/30 in two runs.

**Verification (5 Nov 2026):** two runs of `heldout_v3` without the critic
(`reports/ru_edition/v3_nocritic_a.json`, `v3_nocritic_b.json`; `qwen2.5:7b`,
`--quality-repair --no-deterministic-repair`, join hints on) gave EX 18/30
first attempt and 18/30 after repair, relaxed 24/30, in both runs. The
criterion is met. The two runs are identical question by question (30/30
same SQL), so they are one sample, not two. Against the earlier run with the
critic (`v3_hints_on_a.json`, EX 18/30) the first SQL differs on 12 of 30
questions and three questions change outcome (v3_05 worse, v3_28 better,
v3_30 now ends in an execution error), consistent with the run-to-run
nondeterminism described below. The English-edition run of `heldout_v4` (83%, see above) was made after the critic had been removed.

## Datasets and results

> Unless stated otherwise, the figures in this part were measured on the
> Russian-language edition of the sample data (see [Data editions](#data-editions)).

QueryPilot separates development validation from held-out model
evaluation.

### Datasets

| Dataset | Role | Usage |
| ------- | ---- | ----- |
| `golden_questions.json` | Development | Reference SQL checks and iterative development |
| `heldout_questions.json` | Historical, contaminated | Earlier experiments; not suitable as a fresh independent benchmark |
| `heldout_v3_questions.json` | Development (was held-out on its first run) | 30 questions; used for critic and grounding development after 31 Oct 2026 |
| `heldout_v4_questions.json` | Held-out | 100 validated questions (see "Experiment plan"); one clean run on the Russian edition, re-measured on the English edition |

The `heldout_v3` development dataset contains **30 English questions** and is
tied to a specific SQLite database snapshot through its recorded
database fingerprint. Its reference SQL was validated separately before
model evaluation.

**Benchmark hygiene matters:** an evaluation set is no longer a clean
held-out set if its questions or individual failures are used to write
or tune prompts, validators, deterministic repairs, or
candidate-selection logic. Earlier held-out results that were involved
in repair development are retained as development history, not presented
as independent generalization results.

### Benchmark status

The `heldout_v3` set was clean only for its first run
(`reports/ru_edition/heldout_v3_independent.json`, 31 Oct 2026). Afterwards the same
questions were re-run at least ten times while the semantic critic was being
developed (see `reports/ru_edition/archive/critic_observe_heldout_v3*.json` and
`heldout_v3_critic_*.json`). Prompt and dataset fingerprints are identical
across these runs, so the prompt itself was not changed, but validators and
the critic were tuned while looking at these questions. The set is therefore
treated as a **development set**. A genuinely independent score requires a
new, larger set that is run once and not tuned against (see Roadmap).

Two further caveats about the system itself:

-   `SYSTEM_PROMPT` contains rules whose examples mirror benchmark
    categories (for example carriers of returned orders, coupon discount
    totals, `suppliers.name` output naming), and `sql_quality.py` contains
    domain-specific checks (UAH thresholds on `payments.amount_cents` and
    `products.price_cents`). They help on this synthetic schema; they should
    not be expected to transfer to another database.
-   14/30 vs 13/30 is a difference of **one question** and is within noise.

### Failure analysis of heldout_v3 (manual review, 3 Nov 2026)

All 15 failures of the `qwen2.5:7b` run (`reports/ru_edition/archive/heldout_v3_critic_v6.json`)
were executed against the database and compared with the references by hand.
The review is by a single reviewer and on a set that was already used for
development, so it is a diagnosis, not a benchmark.

| Cause | Questions | Count |
| ----- | --------- | ----- |
| Metric too strict: SQL is right, but a float differs by rounding the question never specified, or the reference includes an unrequested ID column | v3_01, 09, 18, 20, 24, 25, 27 | 7 |
| Wrong join key (`customer_id = order_id`, `category_id = product_id`) | v3_10, 28 | 2 |
| Invented status filter | v3_15, 17 | 2 |
| Row fan-out (`COUNT` after a one-to-many join) | v3_21 | 1 |
| Column out of CTE scope (execution error, repair failed) | v3_29, 30 | 2 |
| Ambiguous: duplicate rows for an order with two failed payments | v3_13 | 1 |

Observations (small sample, treat as hypotheses):

-   The semantic critic marked **6 of 6** wrong answers it reviewed as
    `valid` (the other two failed to execute and were not reviewed). In this
    setup it detects nothing, and is kept only as an experiment.
-   11 of the 15 failures use a `WITH` clause, against 4 of the 15 passes.
-   The new `relaxed` metric (see `scoring.py`) was written *after* this
    review. Re-scoring both saved runs with it reproduces the manual
    classification exactly:

| Run | EX | lenient | relaxed |
| --- | -- | ------- | ------- |
| first run, after repair (31 Oct) | 14/30 | 16/30 | 22/30 (73%, CI 56-86%) |
| critic run v6, after repair (3 Nov) | 15/30 | 16/30 | 22/30 (73%, CI 56-86%) |

`relaxed` is a development metric defined with knowledge of these failures.
`execution_match` remains the headline metric until `relaxed` is confirmed on
a fresh set.

### Model comparison on heldout_v3 (3 Nov 2026, development set)

Same flags for both runs (`--quality-repair --no-deterministic-repair`),
current code (grounding v2, join-key guard). Reports:
`reports/ru_edition/heldout_v3_qwen7b_v2.json`, `reports/ru_edition/heldout_v3_qwen14b.json`.

| Run | EX first | EX final | relaxed final |
| --- | -------- | -------- | ------------- |
| qwen2.5:7b, code of 31 Oct | 13/30 | 14/30 | 22/30 |
| qwen2.5:7b, current code | 18/30 | 19/30 | 25/30 |
| qwen2.5:14b, current code | 18/30 | 18/30 | 25/30 |

7B vs 14B, question by question: 0 improved, 1 regressed, 29 unchanged
(sign test p = 1.0). Final SQL differs between the models on 29 of 30
questions, so equal scores are not copies of each other.

What the comparison does and does not show:

-   **No measurable gain from the larger model** on this set. The intervals
    (EX about 42-75% for both) overlap almost completely.
-   **The 7B improvement from 47% to 63% EX cannot be attributed to a single
    cause.** Four questions (v3_17, 21, 25, 28) flipped to correct on the
    first attempt, so the repair loop and the join guard did not cause it;
    the added join-condition grounding is the likely factor, but it was
    introduced after reviewing these same failures, and the effect has not
    been isolated (no ablation, single runs, temperature 0 is not strictly
    deterministic). Treat it as unconfirmed.
-   The semantic critic again found nothing in the 14B run (29/29 `valid`
    with 12 wrong answers by EX).

Remaining failures (manual review of both runs):

| Question | 7B | 14B | Diagnosis |
| -------- | -- | --- | --------- |
| v3_15 | fail | fail | Both write `s.status != 'delivered'` to express "never"; needs `NOT EXISTS`. A reasoning error shared by both sizes (51 rows vs 14) |
| v3_10 | fail | fail | 7B groups by customer first; 14B generates an ambiguous column and repeats the same SQL after feedback |
| v3_29 | fail | **correct** | 7B: column out of CTE scope. 14B returns the right 32 customers; the reference carries an unrequested `category_count`, so it is scored wrong |
| v3_30 | fail | correct | 7B: out-of-scope column, error not fixed |
| v3_05 | pass by coincidence | fail | All 12 suppliers have at least five in-stock products, so the question does not discriminate. 7B uses a `LEFT JOIN` that would be wrong on other data; 14B counts all products, not only in-stock ones |
| v3_13 | fail | fail | Ambiguous: one order has two failed payments of the same amount, so a plain join returns a duplicate row; the reference uses `DISTINCT` |

Dataset defects found: v3_05 does not discriminate, v3_13 is ambiguous, and
v3_29 (and, for strict EX, several others) include columns the question did
not ask for. `heldout_v3` is **not edited**, because that would change its
fingerprint and break comparability; these defects are to be avoided in the
next set.

A second pattern: when an execution error is fed back, the model often
returns **the same SQL** (`stuck_on_same_sql`: 7B on v3_29, 14B on v3_10), and
the loop stops. Feedback text alone is not enough for these models.

### Ablation, resampling and the clean run (4 Nov 2026)

All runs: `qwen2.5:7b`, `--quality-repair --no-deterministic-repair`. Reports
are in `reports/ru_edition/` (`v3_hints_on_a.json`, ...,
`heldout_v4_qwen7b.json`). Test suite on the same code: **185 passed**
(Python 3.14, sqlglot 30.26.0, fastapi 0.143.0, pytest 9.1.1).

**A. Join-condition grounding, `heldout_v3` (development set, n = 30)**

| Run | EX first | EX final | relaxed final |
| --- | -------- | -------- | ------------- |
| hints on, a | 18 | 18 | 24 |
| hints on, b | 18 | 19 | 25 |
| hints off, a | 14 | 15 | 21 |
| hints off, b | 15 | 16 | 23 |

**B. Resampling after a repeated SQL (hints on)**

| Run | EX first | EX final | relaxed final | extra requests |
| --- | -------- | -------- | ------------- | -------------- |
| resample, a | 17 | 18 | 23 | 3 |
| resample, b | 17 | 18 | 23 | 3 |

(Runs a and b are identical question by question: fixed seeds make the
resampling reproducible, so they are not two independent samples.)

**Decision rules (fixed before the runs) applied**

1.  *Run-to-run noise:* the two runs of the same configuration differ by 1
    question in EX (18/19 with hints, 15/16 without). Noise < 2.
2.  *Join hints:* mean EX 18.5 with vs 15.5 without = **+3.0**, which meets
    the "at least 3 and more than noise" rule exactly, and the two sets of
    runs do not overlap (18-19 vs 15-16). **Decision: keep the hints.**
    This is a borderline pass on a development set. Two questions (v3_21,
    v3_25) are wrong in both hints-off runs and right in both hints-on runs;
    two more (v3_17, v3_28) flip in one run. The effect is therefore about
    2-4 questions, concentrated in join-related ones, and the hints were
    written after reviewing exactly these failures.
3.  *Resampling:* it fixed **none** of the 11 questions that fail in both
    baseline runs (v3_01, 09, 10, 13, 15, 18, 20, 24, 27, 29, 30), so the
    "at least 2" condition is not met. **Decision: leave it off.** It did
    stop the model from returning the same SQL (the "repeated the same SQL"
    line disappeared), but the new answers were still wrong. The v3_02
    difference turned out to be run-to-run nondeterminism, not resampling:
    comparing `v3_hints_on_a.json` with `v3_resample_a.json`, the **first**
    SQL (which resampling cannot touch) differs on 9 of 30 questions (v3_02,
    05, 08, 10, 11, 23, 25, 28, 30) although both runs use temperature 0 and
    identical settings. The cause was not investigated (possibly Ollama/GPU
    nondeterminism or prompt-cache effects). Net scores differ by only 1-2
    questions because flips cancel out, so the "noise < 2" figure above
    understates per-question variability and a 30-question comparison needs
    several runs.
4.  Configuration fixed (hints on, resampling off); then run C.

**C. Clean run, `heldout_v4` (100 questions, run once, config as decided)**

| Metric | First attempt | After repair |
| ------ | ------------- | ------------ |
| strict (names + order) | 63/100 | 63/100 |
| EX | 84/100 (76-90%) | **86/100 (78-91%)** |
| relaxed | 86/100 | 88/100 (80-93%) |
| SQL executed | 96/100 | 98/100 |

By category (EX after repair): joins 14/14, filtering 9/9, sorting 4/4,
date aggregation 9/10, negation 9/10, aggregation 11/13, conditional
aggregation 5/6, subqueries 10/13, multi-table aggregation 13/17, ranking 2/4.
Failing questions: v4_010, 046, 048, 050, 051, 052, 058, 063, 074, 084, 089,
094, 095, 100.

#### Audit of the 14 failures (5 Nov 2026)

Checked against the database and the reports. **No wrong reference and no
ambiguous question was found.** One borderline metric case.

| Cause | Questions | Count |
| ----- | --------- | ----- |
| Wrong grouping granularity or row multiplication (grouped per customer but asked per city; extra join multiplies rows; grouped per product; average of per-order sums instead of per item row) | v4_051, 058, 089, 094, 100 | 5 |
| Wrong aggregate (`COUNT` instead of `SUM(quantity)`) | v4_052 | 1 |
| Wrong source of "delivered" (shipment status instead of order status) | v4_063 | 1 |
| Negation logic (`NOT IN` over the wrong set) | v4_084 | 1 |
| `LEFT JOIN` keeps customers without orders although the question says "who has placed orders" | v4_095 | 1 |
| SQLite dialect: `> ALL (...)` is not supported; not repaired | v4_048 | 1 |
| Unresolved column after three attempts | v4_050 | 1 |
| Ignored the instruction "rounded to two decimals" (relaxed forgives it; EX does not) | v4_010, 046 | 2 |
| Type mismatch: weekday returned as text `'0'` instead of integer `0` | v4_074 | 1 |

On `heldout_v4` the rounding is stated in the question, so **EX (86%) is the
right headline**; `relaxed` (88%) only forgives the two cases where the
model ignored the instruction. If v4_074 were accepted, EX would be 87%; the
original 86% stays the primary number.

Patterns (hypotheses; the sample is small and difficulty is a confounder):

-   Five of the 11 substantive errors are aggregation-granularity errors,
    the same family as v3_10 and v3_21.
-   `WITH` clauses are used in 11 of the 14 failures and in 47 of the 86
    passes (v3: 11 of 15 failures, 4 of 15 passes). Harder questions probably
    invite CTEs, so this does not show that CTEs cause errors.
-   **Critic:** it was never right on this run. All 12 wrong answers that
    executed received the verdict `valid` (the two that failed to execute
    were not reviewed). Its only `invalid` verdicts (3 events) were on
    v4_049, which was already correct and stayed correct, so they cost
    extra model calls without changing the outcome. Recall on wrong answers
    0/12, one false positive.
-   **Repair:** the two questions gained by repair (v4_054, v4_061) were
    fixed after an execution error, not by the quality validator or the critic.


How to read this:

-   **86% EX is a clean number for this question distribution, not a
    general accuracy.** The set was written by an AI assistant, with explicit
    statuses, units and output columns, and was built so that each question
    has one defensible answer. Real user questions are vaguer. The same
    model scores 60-63% on `heldout_v3`, whose questions are messier and
    include harder negation and aggregation patterns; both numbers are
    true, for different question styles.
-   The repair stage added 2 questions (84 to 86), the same order of
    magnitude as run-to-run noise.
-   The semantic critic did not catch any of the 12 wrong answers that
    executed (see the audit above).
-   Nothing was tuned on `heldout_v4`. Under the protocol the set is now
    used: do not change the prompt, grounding, validators or repair in
    response to its failures. Audit it for defects (a wrong reference or an
    ambiguous question) only by reporting results with and without the
    affected questions and keeping the original number as the primary one.

### Held-out v3 first-run result (31 Oct 2026)

Run configuration:

-   **Model:** `qwen2.5:7b`
-   **Dataset:** `heldout_v3` (30 questions)
-   **Repair mode:** quality self-correction
-   **Maximum correction retries:** 2
-   **Deterministic repairs:** disabled
-   **Reference-based repair candidate selection:** removed from the
    evaluation flow
-   **Intermediate checkpointing:** enabled

| Metric | First attempt | After quality repair |
| ------ | ------------- | -------------------- |
| Strict Match (column names and order) | 2/30 (7%) | 2/30 (7%) |
| Execution Match (EX) | **13/30 (43%)** | **14/30 (47%)** |
| Lenient Match | 15/30 (50%) | 16/30 (53%) |
| SQL executed without errors | 25/30 (83%) | 28/30 (93%) |

Additional observations from this run:

-   Average attempts per question: **1.20**
-   Average generation attempts: **1.23**
-   Same SQL repeated after feedback: **1**
-   Quality validator passed after repair: **30/30**

The quality-validator pass rate is not the same as answer correctness.
Execution Match is computed by comparing the final query result with the
reference result for evaluation; reference comparison is used for
scoring, not as feedback for selecting repair candidates in this run.

The repair stage improved Execution Match by one question on this
sample (within sampling noise). The result suggests that the current quality-repair loop has
limited impact on semantic correctness for this workload. The category
breakdown also indicates that multi-table aggregation and joins are
difficult areas for the current model and grounding strategy.

### Category breakdown

Execution Match by category, first attempt → after repair:

| Category | First attempt | After repair |
| -------- | ------------- | ------------ |
| Aggregation | 4/6 | 4/6 |
| Date aggregation | 2/2 | 2/2 |
| Filtering | 1/1 | 1/1 |
| Joins | 1/5 | 1/5 |
| Multi-table aggregation | 0/9 | 1/9 |
| Sorting | 0/1 | 0/1 |
| Subqueries | 5/6 | 5/6 |

The category counts are descriptive only. Several categories contain
very few questions, so they should not be interpreted as stable
estimates of category-level performance.

### Reproduce the held-out v3 evaluation

First validate the reference queries:

``` bash
python scripts/evaluate_sql.py --all-reference --dataset heldout_v3
```

Run the model with quality repair and deterministic repairs disabled:

``` bash
python scripts/evaluate_sql.py \
  --all-model \
  --dataset heldout_v3 \
  --model qwen2.5:7b \
  --retries 2 \
  --quality-repair \
  --no-deterministic-repair \
  --report-name heldout_v3_independent.json
```

The evaluator writes the final report to (note: re-running this on
`heldout_v3` no longer gives an independent measurement):

``` text
reports/heldout_v3_independent.json
```

It also checkpoints progress in `reports/scratch/` after each evaluated
question. A checkpoint is useful for recovering completed results after
an interrupted run; it should not be mistaken for a completed
full-dataset report.

### Other evaluation commands

Run the development benchmark:

``` bash
python scripts/evaluate_sql.py --all-reference --dataset golden
python scripts/evaluate_sql.py --all-model --dataset golden --model qwen2.5:7b
```

Compare two saved reports:

``` bash
python scripts/evaluate_sql.py --compare \
  reports/report_a.json \
  reports/report_b.json
```

For controlled comparisons, keep the model, dataset version, database
snapshot, prompt fingerprint, retry limit, and repair configuration
consistent. Record any changed setting alongside the result.

`--oracle-hints` enables reference-derived feedback and is an
**oracle-assisted upper-bound experiment**, not a production or
independent held-out metric. Do not combine oracle-assisted results with
ordinary model results when reporting system accuracy.

### Historical / contaminated results

All earlier runs, including the critic experiments, are kept in
`reports/ru_edition/archive/` as development history.


Earlier held-out experiments reached 100% after repair. Those results
are retained as development history because benchmark-specific
deterministic repairs and reference-informed candidate selection
affected the repair pipeline. They are **not** presented as independent
held-out performance and should not be compared directly with the
current v3 score.

The historical `heldout_questions.json` set was also used during
iterative prompt and repair development. It should not be described as a
fresh independent test set.

## Experiment plan: ablation, resampling, clean run

Three questions are open after the 7B/14B comparison. Each has an
experiment and, to avoid fitting the analysis to the outcome, a decision rule
that is fixed **before** the runs.

### New switches

| Switch | Default | Purpose |
| ------ | ------- | ------- |
| `QUERYPILOT_JOIN_HINTS=0` | hints on | Removes the "valid join conditions" line from the grounding context (`context_version` 1 instead of 2 in the report) |
| `--resample-on-repeat` | off | If a repair answer equals the previous SQL, ask again (temperature 0.7, fixed seeds, up to 2 extra requests); the number of extra requests is printed |
| `QUERYPILOT_RESAMPLE_TEMPERATURE` | 0.7 | Temperature used for that resampling |

### heldout_v4

100 questions across 10 categories (aggregation, conditional aggregation,
date aggregation, filtering, joins, multi-table aggregation, negation,
ranking, sorting, subqueries). `scripts/build_heldout_v4.py` refuses to
write the file unless every question passes these checks, which target the
defects found in `heldout_v3`:

-   the reference SQL runs under the read-only safety layer and returns
    1-60 rows;
-   no unrequested `*_id` columns; floats only with "rounded to two
    decimals" in the question and `ROUND` in the SQL;
-   when order matters, the sort key is unique, including at the top-N cut;
-   **96 of 100 questions carry a plausible wrong SQL** (fan-out join,
    `!=` instead of `NOT EXISTS`, wrong key, missing `DISTINCT`, off-by-one
    boundary, ...) that is proven to be **rejected** by both EX and `relaxed`,
    so each such question can actually tell right from wrong;
-   no question or SQL duplicates another dataset.

`tests/test_heldout_v4.py` re-checks all of this and that the stored file is
exactly what the builder produces. Rebuild with
`python scripts/build_heldout_v4.py`; verify with `--check`.

**Authorship caveat:** the set was written by an AI assistant (Claude)
*after* reviewing the failures of `heldout_v3`. It targets general pitfalls,
not the v3 questions, but it is not blind. It is also tied to the exact
database file (its SHA-256 is stored and tested). Its score is meaningful only
if nothing (prompt, grounding, validators, repair) is changed in response to
it; if that happens, retire the set and write a new one.

### Protocol (PowerShell)

Common flags: `--quality-repair --no-deterministic-repair`. The model is
`qwen2.5:7b` unless stated.

``` powershell
# A. Ablation of the join hints on heldout_v3 (development set), two runs each
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --quality-repair --no-deterministic-repair --report-name v3_hints_on_a.json
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --quality-repair --no-deterministic-repair --report-name v3_hints_on_b.json
$env:QUERYPILOT_JOIN_HINTS = "0"
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --quality-repair --no-deterministic-repair --report-name v3_hints_off_a.json
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --quality-repair --no-deterministic-repair --report-name v3_hints_off_b.json
Remove-Item Env:QUERYPILOT_JOIN_HINTS            # do not leave the switch on

# B. Resampling of repeated answers (hints on), two runs
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --quality-repair --no-deterministic-repair --resample-on-repeat --report-name v3_resample_a.json
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --quality-repair --no-deterministic-repair --resample-on-repeat --report-name v3_resample_b.json
```

`--compare` checks the dataset but not the context version or the flags, so
compare only runs you meant to.

**Decision rules, fixed in advance**

1.  *Run-to-run noise* = the difference in EX between the two runs of the
    same configuration (hints-on a vs b). If the two disagree by 2 or more
    questions, a difference of 2 questions between configurations means
    nothing.
2.  *Keep the join hints* only if the mean EX with hints exceeds the mean EX
    without by at least 3 questions **and** more than the observed
    run-to-run noise. Otherwise report the effect as not demonstrated and
    prefer the simpler setting (hints off).
3.  *Keep resampling* only if it fixes at least 2 questions that stay wrong
    without it in both baseline runs, and breaks none. Otherwise leave it
    off.
4.  Fix the chosen configuration, write it down, and only then run C.

``` powershell
# C. Clean run: once per model, no changes afterwards
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v4 --model qwen2.5:7b --quality-repair --no-deterministic-repair --report-name heldout_v4_qwen7b.json
# optional, only if the 7B result is worth a comparison:
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v4 --model qwen2.5:14b --quality-repair --no-deterministic-repair --report-name heldout_v4_qwen14b.json
```

Report EX and `relaxed` with their 95% intervals. For n = 100 a result of
60% has an interval of roughly 50-69%, so differences of a few points between
configurations are still within noise.

## Comparing models on a small GPU

An 8 GB GPU (e.g. RTX 3070) cannot hold a 14B model entirely; Ollama puts
the remaining layers in system RAM (16 GB or more recommended). Answers are
slow (seconds per token batch) but an evaluation run is offline, so this is
usable. Windows PowerShell:

``` powershell
ollama pull qwen2.5:14b
$env:QUERYPILOT_REQUEST_TIMEOUT = "900"   # default 120 s is too short when layers spill to CPU

# 1. 7B baseline with the CURRENT code (grounding v2, join guard); same flags as the 14B run
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --model qwen2.5:7b --quality-repair --no-deterministic-repair --report-name heldout_v3_qwen7b_v2.json

# 2. 14B
python .\scripts\evaluate_sql.py --all-model --dataset heldout_v3 --model qwen2.5:14b --quality-repair --no-deterministic-repair --report-name heldout_v3_qwen14b.json

# 3. question-by-question comparison
python .\scripts\evaluate_sql.py --compare reports\heldout_v3_qwen7b_v2.json reports\heldout_v3_qwen14b.json
```

Notes:

-   **Context length.** `SYSTEM_PROMPT` plus `schema.sql` is roughly 4-4.5k
    tokens (estimate), which can exceed Ollama's default context window; an
    over-long prompt is silently truncated. Check the Ollama server log for a
    truncation warning. `QUERYPILOT_NUM_CTX` sets `num_ctx` explicitly. When
    it is unset, behaviour is unchanged. If you set it, **re-run the 7B
    baseline with the same value** before comparing models; it may change the
    7B numbers by itself.
-   **Context grounding version.** The grounding text changed (version 2 adds
    the valid join conditions); reports record `context_version`. Runs with
    different context versions are not directly comparable.
-   **Flags.** `--no-deterministic-repair` only works together with
    `--quality-repair` (the evaluator refuses it otherwise). It disables the
    question-specific repairs, which were written while looking at benchmark
    failures. The first heldout_v3 run used exactly
    `--quality-repair --no-deterministic-repair`; the `critic_v6` run did not
    use quality repair at all (it used the removed `--critic-observe` mode), so the join guard (which lives inside quality
    validation) was inactive there. Compare runs with identical flags only.
-   **Why re-run the 7B baseline.** The old 7B reports used grounding
    version 1 and no join guard. Comparing a new 14B run with them mixes
    model and code changes.
-   (Historical) the semantic critic used to add a model call per question
    in `--quality-repair`; it has been removed.
-   Use the same dataset, retry limit and flags for both models, and say that
    `heldout_v3` is a development set.
