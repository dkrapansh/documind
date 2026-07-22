import json
import logging
import os
import time
from pathlib import Path

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from ragas import EvaluationDataset, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import AnswerRelevancy, context_precision, faithfulness
from ragas.run_config import RunConfig
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.models.eval import EvalRun
from app.repositories.documents import create_document, get_by_content_hash
from app.repositories.eval_runs import create_eval_result, create_eval_run, get_eval_run
from app.repositories.tenants import create_tenant, get_by_name
from app.services.answering import REFUSAL_ANSWER, answer_question
from app.services.file_storage import compute_content_hash, save_file
from app.services.ingestion import process_document
from app.services.reranking import retrieve_ranked

logger = logging.getLogger(__name__)

EVAL_TENANT_NAME = "eval-harness"

_EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "eval"
GOLDEN_DATASET_PATH = _EVAL_DIR / "golden_dataset.json"
GOLDEN_CORPUS_DIR = _EVAL_DIR / "golden_corpus"

# Free-tier Gemini rate limits are tight (~10 RPM for flash-tier models).
# A live 2-item probe at max_workers=2 still hit 2 job timeouts and took
# 9 minutes - concurrent workers compound rate-limit pressure instead of
# avoiding it. Fully serial (max_workers=1) plus a max_wait just past the
# 60s free-tier window, and a per-job timeout generous enough to survive
# several such waits, trades speed for actually finishing a 30-item run.
_RUN_CONFIG = RunConfig(max_workers=1, max_wait=65, max_retries=6, timeout=400)

# Ragas's default AnswerRelevancy asks the judge LLM for 3 candidate
# questions in a single call (strictness=3), which needs the API's
# multi-candidate (candidate_count>1) support. A live baseline run showed
# gemini-3.5-flash-lite hard-rejects that ("Multiple candidates is not
# enabled for this model", 400 INVALID_ARGUMENT) on every single item -
# not a rate limit, a real capability gap - silently turning every
# answer_relevancy score into None. strictness=1 asks one question per
# call instead, at the cost of some of the metric's self-consistency
# averaging.
answer_relevancy = AnswerRelevancy(strictness=1)

# Free-tier generate_content is capped at 15 requests/minute for
# gemini-3.5-flash-lite. Waiting until a 429 happens and then retrying
# (clients/llm.py) works but wastes most of its backoff budget on a
# congestion that a little upfront pacing avoids: one production
# generate_answer call per golden item, spaced comfortably under the
# 4s/request ceiling 15 RPM implies, keeps this loop from ever tripping
# the limit in the first place instead of only recovering after the fact.
_ITEM_PACING_SECONDS = 5


def _clean_score(value: float | None) -> float | None:
    """RAGAS reports an unrecoverable per-item failure (e.g. every retry
    timed out) as NaN, not an exception - storing NaN in a nullable
    Postgres float column would silently poison any later average, so
    it's normalized to None (a real, honest "no score") here instead."""
    if value is None:
        return None
    return None if value != value else value  # NaN != NaN is the float check


def _ensure_eval_tenant(db: Session) -> int:
    """Get-or-create the one stable tenant the eval harness always runs
    against. Deliberately does not rely on the shared create_tenant()
    repository function's own semantics for this - that function always
    inserts a new row (see CLAUDE.md's flagged "no get-or-create" bug) -
    because the eval harness specifically needs the SAME tenant_id across
    runs so content-hash document dedup (documents.py) keeps the golden
    corpus from being re-ingested and re-embedded every run.
    """
    tenant = get_by_name(db, EVAL_TENANT_NAME)
    if tenant is not None:
        return tenant.id
    return create_tenant(db, name=EVAL_TENANT_NAME).id


def _ensure_golden_corpus_ingested(db: Session, tenant_id: int) -> None:
    """Ingest every eval/golden_corpus/*.txt file through the REAL upload
    pipeline (save_file -> create_document -> process_document) rather
    than a shortcut, so eval measures the exact chunking/embedding path
    production uploads go through. Content-hash dedup makes every run
    after the first a no-op here.
    """
    for path in sorted(GOLDEN_CORPUS_DIR.glob("*.txt")):
        file_bytes = path.read_bytes()
        content_hash = compute_content_hash(file_bytes)

        if get_by_content_hash(db, tenant_id, content_hash) is not None:
            continue

        save_file(content_hash, path.name, file_bytes)
        document = create_document(db, tenant_id, path.name, content_hash)
        process_document(document.id)


def load_golden_dataset() -> dict:
    """Public - both run_evaluation() and eval/run_eval.py's console
    summary need the same golden_dataset.json, and the summary script
    needs each question's category (not stored on EvalResult - see the
    refusal-accuracy note in run_evaluation) to report refusal accuracy."""
    return json.loads(GOLDEN_DATASET_PATH.read_text(encoding="utf-8"))


def _build_ragas_llm() -> LangchainLLMWrapper:
    return LangchainLLMWrapper(ChatGoogleGenerativeAI(
        model=settings.gemini_llm_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.0,
    ))


def _build_ragas_embeddings() -> LangchainEmbeddingsWrapper:
    return LangchainEmbeddingsWrapper(GoogleGenerativeAIEmbeddings(
        model=f"models/{settings.gemini_embedding_model}",
        google_api_key=settings.gemini_api_key,
    ))


def start_eval_run(
    db: Session,
    requesting_tenant_id: int,
    confidence_threshold_override: float | None = None,
) -> EvalRun:
    """The fast, synchronous half of an eval run: just creates the EvalRun
    row so a caller (routers/eval.py's POST handler) gets an id back
    immediately, before the slow part (execute_eval_run - real retrieval,
    real generation, real RAGAS scoring, likely minutes to tens of
    minutes on Gemini's free tier) has done any work.
    """
    dataset = load_golden_dataset()
    config = {
        "gemini_llm_model": settings.gemini_llm_model,
        "gemini_embedding_model": settings.gemini_embedding_model,
        "confidence_threshold": (
            confidence_threshold_override
            if confidence_threshold_override is not None
            else settings.confidence_threshold
        ),
    }
    return create_eval_run(
        db,
        tenant_id=requesting_tenant_id,
        dataset_version=dataset["version"],
        config=config,
    )


def execute_eval_run(
    db: Session,
    eval_run: EvalRun,
    confidence_threshold_override: float | None = None,
) -> None:
    """Run every eval/golden_dataset.json item through the REAL retrieval +
    answering pipeline (retrieve_ranked + answer_question - the exact
    functions POST /query calls, not a reimplementation), score each
    non-refusal item with RAGAS (faithfulness, answer_relevancy,
    context_precision), and persist one EvalResult per question against
    the given, already-created eval_run.

    Always runs against a dedicated eval-harness tenant (see
    _ensure_eval_tenant), never against eval_run.tenant_id's own
    documents: the golden dataset is a fixed, hand-verified corpus, and
    scoring it against whatever documents an arbitrary caller happens to
    have uploaded would make the scores meaningless. eval_run.tenant_id
    is recorded purely as an audit trail of who triggered the run.

    expected_refusal items are still run through the real pipeline (that
    IS the test - proving refusal fires) but are not scored by RAGAS:
    faithfulness/answer_relevancy/context_precision are undefined for an
    answer with no supporting context, so their EvalResult rows store
    None for all three metrics rather than a misleading number.
    """
    eval_tenant_id = _ensure_eval_tenant(db)
    _ensure_golden_corpus_ingested(db, eval_tenant_id)

    dataset = load_golden_dataset()
    items = dataset["items"]

    samples = []
    for i, item in enumerate(items):
        if i > 0:
            time.sleep(_ITEM_PACING_SECONDS)

        chunks = retrieve_ranked(
            db,
            eval_tenant_id,
            item["question"],
            confidence_threshold=confidence_threshold_override,
        )
        if chunks:
            response = answer_question(item["question"], chunks)
            answer_text = response.answer
            retrieved_contexts = [chunk.text for chunk in chunks]
        else:
            answer_text = REFUSAL_ANSWER
            retrieved_contexts = []

        samples.append({
            "question": item["question"],
            "ground_truth": item["ground_truth"],
            "category": item["category"],
            "answer": answer_text,
            "retrieved_contexts": retrieved_contexts,
        })

    scorable_indices = [i for i, s in enumerate(samples) if s["category"] != "expected_refusal"]
    scores_by_index: dict[int, dict] = {}

    if scorable_indices:
        ragas_dataset = EvaluationDataset.from_list([
            {
                "user_input": samples[i]["question"],
                "response": samples[i]["answer"],
                "retrieved_contexts": samples[i]["retrieved_contexts"],
                "reference": samples[i]["ground_truth"],
            }
            for i in scorable_indices
        ])
        result = evaluate(
            dataset=ragas_dataset,
            metrics=[faithfulness, answer_relevancy, context_precision],
            llm=_build_ragas_llm(),
            embeddings=_build_ragas_embeddings(),
            run_config=_RUN_CONFIG,
        )
        for position, sample_index in enumerate(scorable_indices):
            scores_by_index[sample_index] = result.scores[position]

    for i, sample in enumerate(samples):
        scores = scores_by_index.get(i, {})
        create_eval_result(
            db,
            eval_run_id=eval_run.id,
            question=sample["question"],
            faithfulness=_clean_score(scores.get("faithfulness")),
            answer_relevancy=_clean_score(scores.get("answer_relevancy")),
            context_precision=_clean_score(scores.get("context_precision")),
        )

    refusal_samples = [s for s in samples if s["category"] == "expected_refusal"]
    if refusal_samples:
        correctly_refused = sum(1 for s in refusal_samples if s["answer"] == REFUSAL_ANSWER)
        logger.info(
            "eval run %s: refused %d/%d expected_refusal questions correctly",
            eval_run.id, correctly_refused, len(refusal_samples),
        )


def run_evaluation(
    db: Session,
    requesting_tenant_id: int,
    confidence_threshold_override: float | None = None,
) -> EvalRun:
    """Synchronous entry point for eval/run_eval.py (the CLI script):
    create the run and execute it in one blocking call, which is exactly
    what you want from a command you're sitting and watching finish -
    unlike routers/eval.py's HTTP endpoint, which must return immediately
    and let a BackgroundTask fill in results (see run_eval_in_background).
    """
    eval_run = start_eval_run(db, requesting_tenant_id, confidence_threshold_override)
    execute_eval_run(db, eval_run, confidence_threshold_override)
    return eval_run


def run_eval_in_background(eval_run_id: int, confidence_threshold_override: float | None) -> None:
    """Entry point for FastAPI BackgroundTasks (routers/eval.py). Runs in
    its OWN database session, same reasoning as services/ingestion.py's
    process_document: BackgroundTasks executes after the HTTP response
    has already been sent, so the request's own session (from
    Depends(get_db)) is already closed by then.
    """
    db = SessionLocal()
    try:
        eval_run = get_eval_run(db, eval_run_id)
        execute_eval_run(db, eval_run, confidence_threshold_override)
    finally:
        db.close()
