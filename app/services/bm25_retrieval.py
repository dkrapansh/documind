import re

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from app.repositories.chunks import list_by_tenant
from app.schemas.query import BM25Chunk

DEFAULT_TOP_K = 4

_WORD_RE = re.compile(r"\w+")

def _tokenize(text: str) -> list[str]:
    # Strip punctuation so "policy?" and "policy" count as the same term -
    # a plain .split() would treat them as different tokens and silently
    # tank every score that should have matched.
    return _WORD_RE.findall(text.lower())

def bm25_retrieve(
    db: Session, tenant_id: int, question: str, top_k: int = DEFAULT_TOP_K
) -> list[BM25Chunk]:
    """Sparse keyword retrieval (BM25): the second leg of hybrid search.

    Dense retrieval (retrieval.py) finds chunks that are semantically
    similar, which can miss exact-term matches (product codes, names,
    rare words) that don't embed distinctively. BM25 scores every chunk
    for this tenant purely on keyword/term overlap with the question,
    independent of the dense leg.

    A BM25Chunk carries `score` (higher = more relevant), not `distance`
    (lower = more similar) — the two retrievers use opposite similarity
    directions, so reusing RetrievedChunk here would silently mislead
    any code that assumes "smaller is better".

    No fusion yet (Reciprocal Rank Fusion arrives on Day 18) and not
    wired into /query yet — this is the narrowest working slice of the
    BM25 leg, verified in isolation before merging with dense results.
    """
    chunks = list_by_tenant(db, tenant_id)
    if not chunks:
        return []

    tokenized_corpus = [_tokenize(chunk.text) for chunk in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(question))

    ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)

    return [
        BM25Chunk(
            id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            score=score,
        )
        for chunk, score in ranked[:top_k]
    ]
