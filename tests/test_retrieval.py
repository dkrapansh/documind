from app.models.chunk import Chunk
from app.repositories.documents import create_document
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