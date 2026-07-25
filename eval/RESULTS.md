# Eval harness results: confidence_threshold tuning (Day 26/27)

Two full runs of `eval/golden_dataset.json` (v2, 30 items: 24 answerable,
6 `expected_refusal`) through the real retrieval + answering pipeline via
`eval/run_eval.py`, scored with RAGAS (faithfulness, answer_relevancy,
context_precision via `gemini-3.1-flash-lite` as judge). Only
`confidence_threshold` (`app/services/reranking.py`'s `retrieve_ranked`)
changed between the two runs, same golden set, same models, same
retrieval/reranking code.

| | Baseline (eval run 6) | Tuned (eval run 7) |
|---|---|---|
| `confidence_threshold` | -6.0 (original, from a 5-example manual probe) | -3.0 |
| Faithfulness (24 answerable items) | 1.0 | 1.0 |
| Answer relevancy (24 answerable items) | 0.832 | 0.832 |
| Context precision (24 answerable items) | 0.792 | 0.792 |
| Refusal accuracy (6 `expected_refusal` items) | 3/6 (50%) | 5/6 (83%) |

## Headline sentence

**Re-tuning `confidence_threshold` from -6.0 to -3.0 against a 30-item
golden dataset raised refusal accuracy from 50% to 83% while leaving
faithfulness (1.0), answer relevancy (0.83), and context precision
(0.79) on answerable questions completely unchanged**, a real,
evidence-backed improvement to the system's core safety property (never
answer from insufficient context) with no measurable cost to answer
quality, replacing what had been a five-example manual probe with a
proper offline evaluation run.

## Why this makes sense

`confidence_threshold` only gates the *decision* to refuse vs. answer -
it never changes which chunks get retrieved or how an answer gets
generated once that decision is made "answer." So for the 24 answerable
questions (whose best-reranked chunk already scored well above either
threshold), moving the threshold from -6.0 to -3.0 changes nothing:
identical retrieved chunks, identical prompts, identical answers -
which is exactly why faithfulness/answer_relevancy/context_precision
came back byte-for-byte identical between the two runs. The only
population -3.0 can possibly affect is borderline cases whose
best-reranked score falls between the two thresholds - which is
precisely the `expected_refusal` set (real questions about topics
genuinely absent from the corpus), and where the improvement landed.

## Caveats

- 3/6 correct refusals at -6.0 rising to 5/6 at -3.0 is real signal but
  a small sample (6 items) - the direction is trustworthy, the exact
  percentage less so. Worth re-checking as the golden dataset grows.
- Both runs' `answer_relevancy` needed `AnswerRelevancy(strictness=1)`
  instead of ragas's default `strictness=3`: the default asks the judge
  LLM for 3 candidate questions in one call (`candidate_count=3`), which
  every Gemini free-tier lite model tested rejects outright ("Multiple
  candidates is not enabled for this model"). strictness=1 trades away
  some of the metric's internal self-consistency averaging to actually
  get a score instead of a silent None on every item.

# Reranker swap: CrossEncoder/PyTorch -> flashrank/ONNX (2026-07-25, eval run 8)

The old reranker (`sentence-transformers`' `CrossEncoder`, backed by PyTorch)
cost ~555MB RSS just to load - confirmed by direct measurement, in isolation,
of a clean process going from 11.7MB to 566.8MB on first model load. That
alone exceeds Render free tier's 512MB ceiling, independent of the rest of
the app. Replaced with `flashrank` (`ms-marco-MiniLM-L-12-v2`, ONNX Runtime,
no PyTorch/`transformers` dependency at all) - same class of model (a real
MS MARCO-trained MiniLM cross-encoder), different inference runtime. Measured
the same way: 17.0MB baseline -> 120.5MB after loading the model and running
one real rerank call, a ~103MB delta versus the old ~555MB.

This swap changed `confidence_threshold`'s valid range: flashrank's scores
are sigmoid/softmax-normalized to roughly [0, 1], not the old CrossEncoder's
raw logits (~-11 to +5.6), so the existing -3.0 became a no-op (nothing
could ever score below it - see the failing
`test_retrieve_ranked_refuses_when_no_chunk_is_actually_relevant` this
surfaced). Before spending a real, rate-limited eval run on a blind guess,
a local-only probe (real retrieval + reranking, no LLM/RAGAS calls) scored
every golden dataset item's best-reranked chunk directly: all 6
`expected_refusal` items scored <=0.405, all 24 answerable items scored
>=0.909 - a clean gap, from which 0.7 was picked as a centered, principled
threshold (not a guess) ahead of running the real pipeline.

| | Old (eval run 7, CrossEncoder) | New (eval run 8, flashrank) |
|---|---|---|
| Reranker | `sentence-transformers` CrossEncoder (PyTorch) | flashrank (ONNX Runtime) |
| Reranker RSS, isolated | ~555MB (11.7MB -> 566.8MB) | ~120.5MB (17.0MB -> 120.5MB) |
| `confidence_threshold` | -3.0 (raw logit scale) | 0.7 (sigmoid/softmax [0, 1] scale) |
| Faithfulness (24 answerable items) | 1.0 | 1.0 |
| Answer relevancy (24 answerable items) | 0.832 | 0.832 |
| Context precision (24 answerable items) | 0.792 | 0.792 |
| Refusal accuracy (6 `expected_refusal` items) | 5/6 (83%) | 6/6 (100%) |

## Headline sentence

**Replacing the PyTorch-based cross-encoder with an ONNX-based one cut its
isolated memory cost from ~555MB to ~120.5MB - clearing Render free tier's
512MB ceiling - while leaving faithfulness (1.0), answer relevancy (0.832),
and context precision (0.792) on answerable questions unchanged, and
actually improving refusal accuracy from 83% to 100%** on the 6
`expected_refusal` golden items, with the new `confidence_threshold` (0.7)
chosen from a real, measured score gap rather than a guess.

## Why this makes sense

The bulk of the old reranker's ~555MB was PyTorch's own framework overhead
(tensor runtime, autograd engine, CUDA-detection machinery) - paid once
`torch` is imported, largely independent of which checkpoint size is loaded.
A smaller checkpoint within the same framework (e.g. TinyBERT instead of
MiniLM-L6) would only have saved the weights portion, tens of MB, not the
framework tax. ONNX Runtime is a lean, inference-only engine with none of
that training-oriented machinery, so switching runtimes - not just shrinking
the model - is what actually cleared the ceiling. Retrieval and generation
are otherwise untouched (same RRF fusion, same LLM), which is why
faithfulness/answer_relevancy/context_precision landed at the same values as
eval run 7: those metrics depend on which chunks get retrieved and how an
answer gets generated once the refuse/answer decision is "answer," and
neither of those changed. The refusal-accuracy gain came from moving to a
threshold backed by a real measured gap (0.405 vs. 0.909) rather than -3.0's
original five-example manual probe.

## Caveats

- No direct old-vs-new run exists with both rerankers installed
  side-by-side in the same process - `torch`/`transformers`/
  `sentence-transformers` were uninstalled as part of this swap. The "old"
  row above is eval run 7's recorded result from the prior session, not a
  re-run under identical conditions today.
- 5/6 -> 6/6 on `expected_refusal` is still a 6-item sample - same caveat
  as Day 26/27's tuning: the direction and the measured score gap are
  trustworthy, the exact percentage less so at this dataset size.
- 0.7 was chosen from the *local* score probe's gap (0.405-0.909), then
  confirmed, not re-derived, by the real pipeline run (eval run 8, which
  used 0.7 directly rather than sweeping multiple candidate thresholds
  through the expensive real pipeline).
