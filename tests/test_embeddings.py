from app.clients.embeddings import embed_text
def test_embed_text_returns_1536_dim_vector():
    vector = embed_text("The quick brown fox jumps over the lazy dog")

    assert isinstance(vector, list)
    assert len(vector) == 1536
    assert all(isinstance(x, float) for x in vector)