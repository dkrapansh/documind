# Eval run: v3 dataset (2026-07-27, eval run 9)

The 41-item v3 dataset (see the dataset-hardening section below) run once against the real
pipeline via `eval/run_eval.py`, same models and `confidence_threshold` (0.7) as v2's tuned
run 8, so the two rows below are a direct comparison.

| | v2 (24 answerable, 6 refusal - run 8) | v3 (33 answerable, 8 refusal - run 9) |
|---|---|---|
| Faithfulness | 1.0 | 0.995 |
| Answer relevancy | 0.832 | 0.784 |
| Context precision | 0.792 | 0.727 |
| Refusal accuracy | 6/6 (100%) | 6/8 (75%) |

## Headline sentence

**The harder v3 items did exactly what they were built to do: refusal accuracy dropped from
100% to 75%, and both misses are the two deliberately near-miss items (gd-038, gd-039) - but in
both cases the model's actual generated answer was still correct and non-hallucinatory ("the
documents don't specify that"), it just doesn't literally match the `REFUSAL_ANSWER` string this
metric checks against. The failure is in the confidence gate's determinism on near-miss lexical
overlap, not in the system's user-facing correctness.**

## What actually happened on the two refusal misses

Reproduced directly against the eval-harness tenant (`retrieve_ranked` + `answer_question`,
the same deterministic dense/BM25/RRF/rerank funnel plus `temperature=0` generation the real
run used, so this matches run 9's own behavior):

- **gd-038** ("data breach *suspected but not confirmed*"): best-reranked confidence 0.999 -
  the near-miss overlap with the real "confirmed data breach, 72 hours" chunk reads as clearly
  relevant, so the 0.7 gate never fires. The LLM then correctly answers that the documents only
  cover the **confirmed**-breach case, not the suspected one.
- **gd-039** (referral credit reversed on a later refund): best-reranked confidence 0.875, same
  shape. The LLM answers that the context says nothing about credit reversal on a refund.

Both are the exact failure mode predicted when these items were designed: near-miss lexical
overlap beats the retrieval-confidence gate. What's new here is that the system prompt's "say so
explicitly instead of guessing" instruction caught both cases anyway at generation time - the
system never gave a wrong or fabricated answer, it just paid for an unnecessary LLM call, and the
harness's exact-string refusal check can't distinguish that from a real failure. All six original,
topically-unrelated refusal items still refuse cleanly, unchanged from v2.

## Faithfulness and context_precision under the harder categories

Faithfulness barely moved (1.0 -> 0.995): only one item, `multi_hop` gd-040, scored below 1.0
(0.833), and every other new category - `numeric_derived`, `negation_distractor`,
`cross_doc_conflict`, and the other `multi_hop` item - scored a clean 1.0. The model rarely bolts
on unsupported claims even under arithmetic and cross-document reasoning, a real result rather
than the near-tautological one v2's near-verbatim ground truths produced.

`context_precision` (0.792 -> 0.727) looks worse, but pulling run 8's own per-item scores shows
the identical pattern already existed in v2: `single_chunk_lookup` items score ~1.0 across the
board, but several `multi_chunk_synthesis` items (gd-010, gd-024 through gd-027) already scored
exactly 0.0. v3's new multi-document categories (`cross_doc_conflict`, `multi_hop`) land in that
same 0.0 bucket, so v3 mostly added more items to a pre-existing pattern rather than surfacing a
new one. Most likely mechanism, not confirmed against RAGAS's source: `context_precision` judges
each retrieved chunk's standalone relevance and weights by rank, so a genuinely-needed supporting
chunk ranked below an unrelated one within the top 4 tanks the score even though generation still
sees and correctly uses every chunk regardless of rank - consistent with faithfulness staying at
1.0 on the very same items. Worth a closer look before trusting this metric's absolute number.

`answer_relevancy` (0.832 -> 0.784) dropped moderately, dragged down by two exact-0.0 scores
(gd-037 `cross_doc_conflict`, gd-041 `multi_hop`) alongside otherwise-normal 0.7-0.9 scores
elsewhere - plausibly `AnswerRelevancy(strictness=1)`'s known self-consistency tradeoff (see the
Day 26/27 entry below) landing badly on two comparative answers, not independently confirmed.

## Caveats

- One run, not repeated - Gemini free-tier quota and the ~13-minute RAGAS scoring pass (heavy
  429 backoff throughout) make repeating this expensive. The directional findings (near-miss
  refusal-gate failure, faithfulness holding under harder categories) are trustworthy; exact
  percentages on an 8-item refusal set are not.
- The refusal-miss reproduction above re-ran gd-038/039 outside the original eval run, since the
  eval harness calls retrieval/answering directly and doesn't write to `query_logs` (only the
  real `POST /query` path does). Retrieval is deterministic and generation runs at
  `temperature=0`, so this is expected to match run 9 exactly, but it's technically a separate
  execution, not a read of run 9's own stored output.

# Golden dataset hardened to v2 -> v3 (2026-07-26)

Runs 6-8 below all score faithfulness at a flat 1.0 on the 24 `single_chunk_lookup` /
`multi_chunk_synthesis` answerable items. That number is real but weaker evidence than
it looks: every `single_chunk_lookup` item's `ground_truth` is a near-verbatim copy of
one source sentence, and every `multi_chunk_synthesis` item is two verbatim sentences
concatenated, not actual synthesis. Generation runs at `temperature=0` and mostly echoes
the retrieved chunk back, so RAGAS faithfulness (does the answer's claims entail from
`retrieved_contexts`?) is close to trivially satisfied - it says the model doesn't bolt
on extra claims on an easy extractive lookup, not that it stays faithful under harder
conditions. Refusal accuracy (6/6 in run 8) has the same shape: all six original
`expected_refusal` items are on topics completely absent from the corpus (SSO, uptime
SLA, crypto payment, free trial, nonprofit discount, white-label), so both retrieval legs
return weak candidates and the 0.7 gate fires easily. Nothing in the v2 set exercises the
threshold's boundary region (no golden item scores between the measured 0.405/0.909 gap -
see eval run 8 below), so 0.7 is well-chosen for these 30 items but untested against a
genuine near-miss.

`golden_dataset.json` v3 adds 11 items (gd-031..gd-041) across four new categories,
built from the same 10-document corpus (no new source documents, so no re-ingestion
changes needed beyond content-hash dedup already handling it):

- **`numeric_derived`** (gd-031/032/033): the answer requires arithmetic the corpus
  never states outright (e.g. 15 extra seats x $5/month = $75/month), so an unfaithful
  answer has to invent or miscalculate a number rather than just echo a sentence.
- **`negation_distractor`** (gd-034/035): the question shares vocabulary with a real
  sentence but asks about the case that sentence explicitly excludes (e.g. asking about
  a prorated refund on a *monthly* plan, when the corpus's "prorated" sentence is
  specifically about *annual* plans) - tests whether retrieval + generation discriminate
  the exception, not just pattern-match on shared terms.
- **`cross_doc_conflict`** (gd-036/037): requires comparing two documents' numbers
  against each other (which window is longer, which deadline is stricter), not just
  reporting both facts side by side the way the original `multi_chunk_synthesis` items do.
- **`multi_hop`** (gd-040/041): requires an elimination/selection step across three
  chunks (which plan satisfies two constraints at once, and which doesn't) rather than
  concatenating two independently-retrievable sentences.
- Two new **`expected_refusal`** items (gd-038/039) are deliberately near-miss: topically
  adjacent to a real chunk (data-breach notification timing, referral-credit/refund
  interaction) with heavy lexical overlap, but the specific fact asked for isn't in the
  corpus. These are a harder test of the refusal gate than the original six's
  completely-unrelated topics.

This section documented the dataset change itself, ahead of spending the real, rate-limited
Gemini quota a v3 run costs. That run has since happened - see "Eval run: v3 dataset
(2026-07-27, eval run 9)" above for the actual faithfulness/relevancy/precision/refusal numbers.

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

## Confidence threshold removed (2026-08-28)

The reranker score is no longer an absolute gate on whether to answer. It
still orders candidates; the refusal decision moved to the model.

**Why.** The threshold was tuned twice against this golden dataset (-6.0 to
-3.0 on the old CrossEncoder logit scale, then 0.70 after the flashrank swap
moved scores into [0, 1]) and looked cleanly separated: every answerable item
scored >= 0.909, every expected_refusal item <= 0.405.

That separation did not survive contact with a real document. The golden
questions were written from the corpus and share its phrasing; real questions
do not. Scored against an uploaded job description with the real reranker:

| Question | Score | Old verdict | Present in the document? |
| --- | --- | --- | --- |
| What skills does apple want for this role? | 0.981 | answer | yes |
| What are the key qualifications for this role? | 0.787 | answer | yes |
| what skills do they want | 0.124 | refuse | yes |
| what do i need for this job | 0.133 | refuse | yes |
| How many years of experience are required? | 0.041 | refuse | yes, "5+ years" |
| Does this role require Kubernetes? | 0.013 | refuse | yes, "Deep experience with Kubernetes" |
| What programming languages are required? | 0.001 | refuse | yes, "Python, Go, or Java" |
| what is the salary | 0.000 | refuse | no |
| who is the hiring manager | 0.000 | refuse | no |

Answerable questions span 0.001 to 0.981; genuinely unanswerable ones sit at
0.000. There is no cut point between them, so retuning the number could not
fix this. Splitting the document into its natural sections was also tried and
did not fix it: "Does this role require Kubernetes?" only moved from 0.013 to
0.041 against the section that contains the word Kubernetes.

The lesson worth keeping: a threshold validated only against a dataset whose
questions were authored from the corpus is validated against its own
assumptions. The 0.909/0.405 gap was measuring phrasing overlap, not
relevance.

**What replaced it.** services/answering.py instructs the model to reply with
the exact REFUSAL_ANSWER sentence when the context does not answer the
question. The wording is pinned so refusals stay machine-detectable, which
this harness depends on. An empty retrieval result still refuses without a
model call, but that now only happens when the tenant has no documents.

**Measured effect**, real reranker and real Gemini, same nine questions:
4/9 correct before, 9/9 after. All six false refusals answer correctly; all
three genuine refusals still refuse.

**Costs, stated honestly.** A question that ends in a refusal now pays for a
model call the gate used to avoid. Refusal is no longer deterministic: it
depends on the model following an instruction rather than on an arithmetic
comparison. `settings.confidence_threshold` is retained, defaulting to None,
so this harness can still sweep values and reproduce the old behavior for
comparison.

**Measured against the golden dataset: eval run 10, dataset v3, 41 items,
confidence_threshold None.**

| Metric | run 9 (gate at 0.70) | run 10 (gate removed) |
| --- | --- | --- |
| Faithfulness | 0.995 | 0.996 |
| Answer relevancy | 0.784 | 0.820 |
| Context precision | 0.727 | 0.727 |
| Refusal accuracy | 6/8 (75%) | 8/8 (100%) |

Scored 33/33 answerable items, none timed out.

Refusal accuracy went up, not down. That is the result worth understanding,
because removing a refusal gate sounds like it should do the opposite.

The two misses in run 9 were gd-038 and gd-039, the deliberate near-miss
items. They were not caught by the gate: their lexical overlap with real
content scored 0.999 and 0.875, well above 0.70, so the gate passed them
through and the model answered. The gate was making the wrong call in both
directions at once, refusing questions the corpus answered (measured
separately against a real job description, 0.001 to 0.13 for questions
answered outright) while admitting questions it did not. Removing it left
the decision with the only component that reads the text, and both items now
refuse correctly.

Answer relevancy improved 0.784 to 0.820, consistent with the same cause:
questions that previously received a canned refusal now get a real answer
scored on its merits. Faithfulness and context precision are unchanged,
which is expected, since neither depends on the refuse/answer decision.

The costs stated above still stand and are not measured by these numbers: a
refusal now pays for a model call, and refusal depends on instruction
adherence rather than arithmetic. Run 10 shows that adherence held on 8 of 8
refusal items and 33 of 33 answerable ones, which is evidence, not a
guarantee.
