from app.models.chunk import Chunk
from app.repositories.documents import create_document
from app.services.reranking import retrieve_ranked
from app.services.retrieval import retrieve

def _make_embedding(dominant_index: int) -> list[float]:
    """A 1536-dim vector pointing strongly in one direction. Two
    vectors with the same dominant_index are close (near-zero cosine
    distance); different indices are far apart, makes the expected
    ordering easy to reason about without real embeddings."""

    vector = [0.0] * 1536
    vector[dominant_index] = 1.0
    return vector

def test_retrieve_returns_closest_chunk_first(client, db_session, monkeypatch):
    issue_response = client.post("/auth/keys", json={"tenant_name": "acme"})
    tenant_id = issue_response.json()["tenant_id"]

    document = create_document(db_session, tenant_id, "test.txt", "hash123")

    close_chunk = Chunk(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=0,
        text="closest chunk",
        embedding=_make_embedding(0),
        token_count=2,
    )

    far_chunk = Chunk(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=1,
        text="far chunk",
        embedding=_make_embedding(500),
        token_count=2,
    )
    db_session.add_all([close_chunk, far_chunk])
    db_session.commit()

    monkeypatch.setattr("app.services.retrieval.embed_text", lambda q: _make_embedding(0))

    results = retrieve(db_session, tenant_id, "irrelevant question text", top_k=2)

    assert results[0].text == "closest chunk"
    assert results[0].distance < results[1].distance

def test_hybrid_pipeline_surfaces_keyword_match_that_dense_alone_misses(client, db_session, monkeypatch):
    """Five distractor chunks all embed identically to the query (dense
    loves them); the one chunk that actually answers the question embeds
    far away (dense would never surface it in a top_k=4 cut) but shares
    exact keywords with the question. Dense-only retrieve() should miss
    it; the full hybrid+rerank funnel (BM25 + RRF + cross-encoder) should
    recover it - proving why Days 17-19 exist, not just that they run."""
    issue_response = client.post("/auth/keys", json={"tenant_name": "acme"})
    tenant_id = issue_response.json()["tenant_id"]

    document = create_document(db_session, tenant_id, "test.txt", "hash123")

    distractor_texts = [
        "The office is closed on public holidays.",
        "Our support team responds within 24 hours.",
        "The mobile app is available on iOS and Android.",
        "Employees receive an annual performance review.",
        "The company was founded in 2015.",
    ]
    distractors = [
        Chunk(
            document_id=document.id,
            tenant_id=tenant_id,
            chunk_index=index,
            text=text,
            embedding=_make_embedding(0),
            token_count=8,
        )
        for index, text in enumerate(distractor_texts)
    ]
    keyword_match = Chunk(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=len(distractor_texts),
        text="Product code XR-4471 ships within 2 business days.",
        embedding=_make_embedding(500),
        token_count=8,
    )
    db_session.add_all([*distractors, keyword_match])
    db_session.commit()

    monkeypatch.setattr("app.services.retrieval.embed_text", lambda q: _make_embedding(0))

    question = "What is the shipping time for product code XR-4471?"

    dense_only_results = retrieve(db_session, tenant_id, question, top_k=4)
    assert keyword_match.text not in [chunk.text for chunk in dense_only_results]

    hybrid_results = retrieve_ranked(db_session, tenant_id, question)
    assert keyword_match.text in [chunk.text for chunk in hybrid_results]

def test_retrieve_never_returns_another_tenants_chunks(client, db_session, monkeypatch):
    """The core multi-tenancy invariant (CLAUDE.md: "every query filters on
    tenant_id inside the SQL itself"), exercised directly: tenant B's chunk
    embeds identically to tenant A's query and would be the closest match by
    distance alone - the only thing that can keep it out of tenant A's
    results is the tenant_id filter in repositories/chunks.py, not luck."""
    tenant_a_id = client.post("/auth/keys", json={"tenant_name": "acme"}).json()["tenant_id"]
    tenant_b_id = client.post("/auth/keys", json={"tenant_name": "globex"}).json()["tenant_id"]

    document_a = create_document(db_session, tenant_a_id, "a.txt", "hash-a")
    document_b = create_document(db_session, tenant_b_id, "b.txt", "hash-b")

    chunk_a = Chunk(
        document_id=document_a.id,
        tenant_id=tenant_a_id,
        chunk_index=0,
        text="tenant A's own chunk",
        embedding=_make_embedding(0),
        token_count=4,
    )
    # Same embedding as the query below - would win on distance alone if
    # the tenant filter weren't applied.
    chunk_b = Chunk(
        document_id=document_b.id,
        tenant_id=tenant_b_id,
        chunk_index=0,
        text="tenant B's secret chunk",
        embedding=_make_embedding(0),
        token_count=4,
    )
    db_session.add_all([chunk_a, chunk_b])
    db_session.commit()

    monkeypatch.setattr("app.services.retrieval.embed_text", lambda q: _make_embedding(0))

    results = retrieve(db_session, tenant_a_id, "irrelevant question text", top_k=5)

    assert [chunk.text for chunk in results] == ["tenant A's own chunk"]

def test_retrieve_ranked_refuses_when_no_chunk_is_actually_relevant(client, db_session, monkeypatch):
    issue_response = client.post("/auth/keys", json={"tenant_name": "acme"})
    tenant_id = issue_response.json()["tenant_id"]

    document = create_document(db_session, tenant_id, "test.txt", "hash123")

    unrelated_chunk = Chunk(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=0,
        text="The office is closed on public holidays.",
        embedding=_make_embedding(0),
        token_count=8,
    )
    db_session.add(unrelated_chunk)
    db_session.commit()

    monkeypatch.setattr("app.services.retrieval.embed_text", lambda q: _make_embedding(0))

    results = retrieve_ranked(
        db_session, tenant_id, "What is the refund policy for defective electronics?"
    )

    assert results == []