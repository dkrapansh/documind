from app.models.chunk import Chunk
from app.repositories.documents import create_document
from app.services.bm25_retrieval import bm25_retrieve

def _dummy_embedding() -> list[float]:
    # BM25 never reads this column; only present because it's NOT NULL.
    return [0.0] * 1536

def test_bm25_retrieve_ranks_keyword_overlap_first(client, db_session):
    issue_response = client.post("/auth/keys", json={"tenant_name": "acme"})
    tenant_id = issue_response.json()["tenant_id"]

    document = create_document(db_session, tenant_id, "test.txt", "hash123")

    matching_chunk = Chunk(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=0,
        text="Our return policy allows refunds within 30 days of purchase.",
        embedding=_dummy_embedding(),
        token_count=10,
    )
    unrelated_chunk = Chunk(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=1,
        text="The quarterly report shows steady revenue growth in Q3.",
        embedding=_dummy_embedding(),
        token_count=10,
    )
    another_unrelated_chunk = Chunk(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=2,
        text="Support hours are Monday through Friday, 9am to 5pm.",
        embedding=_dummy_embedding(),
        token_count=10,
    )
    # BM25's IDF is log((N - df + 0.5) / (df + 0.5)); with only 2 documents,
    # a term appearing in exactly 1 of them scores idf = log(1) = 0, which
    # would mask the ranking this test wants to prove. A third, unrelated
    # document breaks that symmetry.
    db_session.add_all([matching_chunk, unrelated_chunk, another_unrelated_chunk])
    db_session.commit()

    results = bm25_retrieve(db_session, tenant_id, "What is the return policy for refunds?", top_k=2)

    assert results[0].text == matching_chunk.text
    assert results[0].score > results[1].score

def test_bm25_retrieve_returns_empty_list_when_tenant_has_no_chunks(client, db_session):
    issue_response = client.post("/auth/keys", json={"tenant_name": "acme"})
    tenant_id = issue_response.json()["tenant_id"]

    results = bm25_retrieve(db_session, tenant_id, "any question", top_k=4)

    assert results == []
