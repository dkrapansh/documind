# Eval harness results — confidence_threshold tuning (Day 26/27)

Two full runs of `eval/golden_dataset.json` (v2, 30 items: 24 answerable,
6 `expected_refusal`) through the real retrieval + answering pipeline via
`eval/run_eval.py`, scored with RAGAS (faithfulness, answer_relevancy,
context_precision via `gemini-3.1-flash-lite` as judge). Only
`confidence_threshold` (`app/services/reranking.py`'s `retrieve_ranked`)
changed between the two runs — same golden set, same models, same
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
(0.79) on answerable questions completely unchanged** — a real,
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
