import json
import logging
import os
import time
from pathlib import Path

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.models.eval import EvalRun
from app.repositories.document_contents import upsert_content
from app.repositories.documents import claim_next_pending, create_document, get_by_content_hash
from app.repositories.eval_runs import create_eval_result, create_eval_run, get_eval_run
from app.repositories.tenants import create_tenant, get_by_name
from app.services.answering import REFUSAL_ANSWER, answer_question
from app.services.file_storage import compute_content_hash
from app.services.ingestion import process_document
from app.services.reranking import retrieve_ranked
from app.services.text_extraction import extract_text

logger = logging.getLogger(__name__)

EVAL_TENANT_NAME = "eval-harness"

_EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "eval"
GOLDEN_DATASET_PATH = _EVAL_DIR / "golden_dataset.json"
GOLDEN_CORPUS_DIR = _EVAL_DIR / "golden_corpus"

# Free tier caps generate_content at 15 requests/minute. Reactive
# retry-after-429 works but wastes backoff budget on congestion that's
# avoidable, so this paces one call per item, comfortably under the
# 4s/request ceiling 15 RPM implies, instead of only recovering after
# the fact.
_ITEM_PACING_SECONDS = 5


def evaluate(**kwargs):
    """Thin lazy wrapper around ragas.evaluate(). Importing ragas at
    module level drags in langchain/langgraph/datasets/pyarrow and was
    part of what OOM-killed the free-tier deploy on every boot, even
    for a plain /query request. Kept as a named function, not inlined,
    so tests can still monkeypatch this directly.
    """
    from ragas import evaluate as _ragas_evaluate
    return _ragas_evaluate(**kwargs)


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
    against. Doesn't use create_tenant() directly since that always
    inserts a new row (a known bug), and this needs the SAME tenant_id
    across runs so content-hash dedup skips re-ingesting the golden
    corpus every time.
    """
    tenant = get_by_name(db, EVAL_TENANT_NAME)
    if tenant is not None:
        return tenant.id
    return create_tenant(db, name=EVAL_TENANT_NAME).id


def _ensure_golden_corpus_ingested(db: Session, tenant_id: int) -> None:
    """Ingest every eval/golden_corpus/*.txt file through the real ingestion
    pipeline, not a shortcut, so eval measures the exact path production
    uploads go through. Content-hash dedup makes reruns a no-op.

    Mirrors the upload route: extract, store the text, create the document,
    then run the job. It calls process_document directly rather than waiting
    on the background worker because the eval harness is a synchronous script
    that needs the corpus ready before it can score anything.
    """
    for path in sorted(GOLDEN_CORPUS_DIR.glob("*.txt")):
        file_bytes = path.read_bytes()
        content_hash = compute_content_hash(file_bytes)

        if get_by_content_hash(db, tenant_id, content_hash) is not None:
            continue

        extracted_text = extract_text(file_bytes, path.name)
        document = create_document(db, tenant_id, path.name, content_hash)
        upsert_content(db, document.id, extracted_text)
        db.commit()

        # Claim it the same way the worker would, so attempt_count and the
        # lease are set consistently rather than left in a state no real
        # ingestion would produce.
        claimed_id = claim_next_pending(
            db,
            lease_seconds=settings.ingestion_lease_seconds,
            max_attempts=settings.ingestion_max_attempts,
        )
        if claimed_id is not None:
            process_document(claimed_id)


def load_golden_dataset() -> dict:
    """Public - both run_evaluation() and eval/run_eval.py's console
    summary need the same golden_dataset.json, and the summary script
    needs each question's category (not stored on EvalResult - see the
    refusal-accuracy note in run_evaluation) to report refusal accuracy."""
    return json.loads(GOLDEN_DATASET_PATH.read_text(encoding="utf-8"))


def _build_ragas_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    from ragas.llms import LangchainLLMWrapper

    return LangchainLLMWrapper(ChatGoogleGenerativeAI(
        model=settings.gemini_llm_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.0,
    ))


def _build_ragas_embeddings():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    return LangchainEmbeddingsWrapper(GoogleGenerativeAIEmbeddings(
        model=f"models/{settings.gemini_embedding_model}",
        google_api_key=settings.gemini_api_key,
    ))


def start_eval_run(
    db: Session,
    requesting_tenant_id: int,
    confidence_threshold_override: float | None = None,
) -> EvalRun:
    """The fast half of an eval run: creates the EvalRun row so the
    caller gets an id back immediately, before execute_eval_run's real
    retrieval, generation, and RAGAS scoring (minutes on Gemini's free
    tier) does any work.
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
    """Runs every golden_dataset.json item through the real retrieval
    and answering pipeline (retrieve_ranked + answer_question, the same
    functions POST /query calls), scores non-refusal items with RAGAS,
    and persists one EvalResult per question.

    Always runs against a dedicated eval-harness tenant, never
    eval_run.tenant_id's own documents: scoring a fixed golden corpus
    against an arbitrary caller's uploads would make the scores
    meaningless. eval_run.tenant_id is recorded only as an audit trail.

    expected_refusal items still run through the real pipeline (proving
    refusal fires) but aren't scored: faithfulness/relevancy/precision
    are undefined with no supporting context, so those rows store None
    instead of a misleading number.
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
        from ragas import EvaluationDataset
        from ragas.metrics import AnswerRelevancy, context_precision, faithfulness
        from ragas.run_config import RunConfig

        # Ragas's default AnswerRelevancy(strictness=3) needs multi-candidate
        # support Gemini free-tier models reject outright ("Multiple
        # candidates is not enabled for this model"), silently turning
        # every score into None. strictness=1 asks one question per call
        # instead, at some cost to the metric's self-consistency averaging.
        answer_relevancy_metric = AnswerRelevancy(strictness=1)

        # Gemini free-tier rate limits are tight enough that concurrent
        # workers compound pressure instead of avoiding it (a 2-worker
        # probe still hit timeouts). Serial (max_workers=1), a max_wait
        # just past the 60s window, and a generous per-job timeout trade
        # speed for actually finishing a 30-item run.
        run_config = RunConfig(max_workers=1, max_wait=65, max_retries=6, timeout=400)

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
            metrics=[faithfulness, answer_relevancy_metric, context_precision],
            llm=_build_ragas_llm(),
            embeddings=_build_ragas_embeddings(),
            run_config=run_config,
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
    """Synchronous entry point for eval/run_eval.py: create and execute
    the run in one blocking call, since a CLI script you're watching
    finish doesn't need the return-immediately pattern the HTTP endpoint
    does (see run_eval_in_background).
    """
    eval_run = start_eval_run(db, requesting_tenant_id, confidence_threshold_override)
    execute_eval_run(db, eval_run, confidence_threshold_override)
    return eval_run


def run_eval_in_background(eval_run_id: int, confidence_threshold_override: float | None) -> None:
    """Entry point for FastAPI BackgroundTasks. Runs in its own DB
    session, same as ingestion.py's process_document: BackgroundTasks
    runs after the response is sent, so the request's own session is
    already closed by then.
    """
    db = SessionLocal()
    try:
        eval_run = get_eval_run(db, eval_run_id)
        execute_eval_run(db, eval_run, confidence_threshold_override)
    finally:
        db.close()
