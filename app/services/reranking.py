from sqlalchemy.orm import Session

from app.clients.reranker import rerank_chunks
from app.config import settings
from app.schemas.query import RetrievedChunk
from app.services.hybrid_retrieval import hybrid_retrieve

CANDIDATE_K = 10
FINAL_TOP_K = 4

def retrieve_ranked(
    db: Session,
    tenant_id: int,
    question: str,
    confidence_threshold: float | None = None,
) -> list[RetrievedChunk]:
    """The full hybrid retrieval funnel POST /query actually calls:
    RRF-fused candidates from dense + BM25 (hybrid_retrieval.py), cross-
    encoder reranked (clients/reranker.py), cut to the final top_k.

    The reranker orders candidates. It no longer decides whether to answer.

    It used to: any question whose best-reranked chunk scored below
    settings.confidence_threshold got an automatic refusal, before the LLM
    was ever called. That was deterministic and cheap, and it was measurably
    wrong on real questions. Measured against a real uploaded job
    description, with the threshold at 0.70:

        "What skills does apple want for this role?"   0.981  answered
        "What programming languages are required?"     0.001  refused
        "Does this role require Kubernetes?"           0.013  refused
        "what is the salary" (genuinely absent)        0.000  refused

    The middle two are answered explicitly by the document ("Python, Go, or
    Java", "Deep experience with Kubernetes"). The problem is not that 0.70
    was too high: questions the document answers scored 0.001 to 0.13 while
    questions it genuinely cannot answer scored 0.000, so no threshold
    separates them. Re-chunking the document did not fix it either.

    The threshold looked well-calibrated because it was tuned against
    eval/golden_dataset.json, whose questions were written *from* the corpus
    and so share its phrasing, scoring 0.909 and above. Real users do not
    phrase questions that way. The number was fitted to a sample that was not
    representative of the traffic it gates.

    So the refusal decision moved to the one component that reads the actual
    text rather than scoring a similarity: the model. services/answering.py
    instructs it to reply with the exact refusal sentence when the context
    does not answer the question. That costs a model call on questions that
    end in a refusal, which the old gate avoided, and it gives up
    determinism, which is a real loss. It buys correctness on the queries
    users actually type.

    An empty list still means refuse without calling the model, but now only
    when retrieval genuinely found nothing, which happens when the tenant has
    no documents at all.

    confidence_threshold is retained as an optional hard floor, off by
    default. The eval harness uses it to sweep thresholds and reproduce the
    old behavior for comparison; nothing in the request path sets it.
    """
    if confidence_threshold is None:
        confidence_threshold = settings.confidence_threshold

    candidates = hybrid_retrieve(db, tenant_id, question, top_k=CANDIDATE_K)
    if not candidates:
        return []

    ranked = rerank_chunks(question, candidates)
    top_ranked = ranked[:FINAL_TOP_K]
    if not top_ranked:
        # Defensive: candidates was non-empty, but if the reranker ever
        # comes back empty anyway (e.g. an unexpected flashrank result),
        # treat it the same as "no candidates" rather than crashing on
        # an unguarded index into an empty list.
        return []

    if confidence_threshold is not None:
        best_score = top_ranked[0][1]
        if best_score < confidence_threshold:
            return []

    return [
        RetrievedChunk(
            id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            confidence=float(score),
        )
        for chunk, score in top_ranked
    ]
